"""Distributed rate limiting, keyed by what is actually being protected.

A single global limit is close to useless here, because the endpoints have wildly different
costs and wildly different abuse profiles. Three tiers instead:

* **Authentication** is limited per identifier *and* per IP, tightly. This is the credential
  stuffing surface, and per-account lockout alone is insufficient - an attacker spraying one
  password across ten thousand accounts never trips a per-account counter.
* **Analysis and optimizer runs** are limited per tenant, because one run occupies a worker for
  several minutes and a burst of them starves every other tenant. This is a fairness control
  more than a security one.
* **Everything else** gets a generous per-principal limit that exists only to stop a runaway
  client, and which a normal user will never see.

The algorithm is a sliding window over a Redis sorted set, not a fixed window counter. A fixed
window lets a caller send the whole quota in the last second of one window and the whole quota
in the first second of the next - double the intended rate, at the worst possible moment. The
sorted set costs one extra round trip and removes the problem.

**Redis being down does not lock everyone out.** The limiter fails *open*, logs loudly, and
increments a metric. That is the right trade for a rate limiter and the wrong one for
authentication: a cache outage should not be an outage, but it must be visible, because an
attacker who can take Redis down would otherwise silently uncap the login endpoint. The login
path's other defences - per-account lockout, which lives in PostgreSQL - are unaffected.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from redis.asyncio import Redis

from speaker_roi_core.config import get_settings
from speaker_roi_core.errors import RateLimitedError
from speaker_roi_core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

log = get_logger(__name__)

_KEY_PREFIX: Final = "rl:v1"


@dataclass(frozen=True, slots=True)
class Limit:
    """A quota: ``count`` requests per ``window_seconds``."""

    count: int
    window_seconds: int

    @property
    def label(self) -> str:
        return f"{self.count}/{self.window_seconds}s"


#: Per identifier (email) on the login endpoint. Ten attempts in five minutes is far more than
#: a human needs and far less than a dictionary needs.
LOGIN_PER_IDENTIFIER = Limit(10, 300)

#: Per source address on the login endpoint. Higher than the per-identifier limit because a
#: hospital NATs its whole staff behind one address, and lower than any useful spray rate.
LOGIN_PER_IP = Limit(40, 300)

#: Password reset requests. Each one sends an email to an address the requester names, so an
#: unlimited endpoint is a mail-bombing tool that spends our sender reputation.
RESET_PER_IP = Limit(5, 900)

#: MFA verification. Six digits is a million-wide space; ten guesses per five minutes makes an
#: online attack take years, without inconveniencing a user whose clock has drifted.
MFA_PER_SESSION = Limit(10, 300)

#: Analysis and optimizer submissions per tenant. A full sensitivity suite is nine to eleven
#: pipeline runs at seven or eight minutes each, so this is a day's worth of legitimate work.
ANALYSIS_PER_TENANT = Limit(30, 3600)

#: Assistant queries per principal. Each one costs a model call.
AI_PER_PRINCIPAL = Limit(60, 3600)

#: The catch-all. Deliberately loose - it is a runaway-client guard, not a security control.
DEFAULT_PER_PRINCIPAL = Limit(600, 60)


class RateLimiter:
    """Sliding-window limiter over Redis, with a local fallback and fail-open semantics."""

    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis
        #: Used only when Redis was never configured, which is the single-process development
        #: case. Explicitly not a production path: it is per-process, so two workers would
        #: allow twice the quota, and it is unbounded in the number of keys it retains for a
        #: window. Adequate for a laptop, and the startup log says so.
        self._local: dict[str, list[float]] = {}

    async def check(self, bucket: str, key: str, limit: Limit) -> None:
        """Consume one unit of quota, or raise :class:`RateLimitedError`.

        ``bucket`` names the tier (``login``, ``analysis``) and ``key`` identifies the subject
        within it. They are separate arguments rather than one pre-joined string so a caller
        cannot accidentally collide two tiers by formatting the key differently.
        """
        now = time.time()
        full_key = f"{_KEY_PREFIX}:{bucket}:{key}"
        try:
            used = await self._consume(full_key, limit, now)
        # Bare ``Exception`` on purpose: a connection error, a timeout, a protocol error
        # and a bug in this module must all fail open rather than refuse the request.
        except Exception as exc:
            log.error(
                "ratelimit.backend_unavailable",
                bucket=bucket,
                error=type(exc).__name__,
                consequence="requests are not being limited",
            )
            return

        if used > limit.count:
            retry_after = limit.window_seconds
            log.warning("ratelimit.exceeded", bucket=bucket, limit=limit.label)
            raise RateLimitedError(
                "too many requests; please wait before trying again",
                retry_after_seconds=retry_after,
                context={"limit": limit.label},
            )

    async def _consume(self, full_key: str, limit: Limit, now: float) -> int:
        if self._redis is None:
            return self._consume_local(full_key, limit, now)

        cutoff = now - limit.window_seconds
        pipe = self._redis.pipeline(transaction=True)
        # Prune, then record, then count, then re-arm the expiry - in that order and in one
        # round trip. Counting before recording would let two concurrent requests each see
        # the pre-increment count and both be admitted at the boundary.
        pipe.zremrangebyscore(full_key, 0, cutoff)
        # A random member, not a timestamp: two requests in the same microsecond - in one
        # process or across four workers - would write the same member, and the second zadd
        # would update the existing score instead of adding a row. That silently undercounts
        # exactly at the burst the limiter exists to catch.
        pipe.zadd(full_key, {secrets.token_hex(8).encode("ascii"): now})
        pipe.zcard(full_key)
        # Expiry on every write, not just the first: a key whose TTL was set once and then
        # kept receiving writes would expire mid-window and reset the quota.
        pipe.expire(full_key, limit.window_seconds + 1)
        results = await pipe.execute()
        return int(results[2])

    def _consume_local(self, full_key: str, limit: Limit, now: float) -> int:
        cutoff = now - limit.window_seconds
        hits = [t for t in self._local.get(full_key, ()) if t > cutoff]
        hits.append(now)
        self._local[full_key] = hits
        return len(hits)

    async def aclose(self) -> None:
        """Release the Redis connection.

        Public rather than reached into from the shutdown hook: a module-level helper poking
        at ``limiter._redis`` breaks the moment the backend gains a second connection or a
        pool, and nothing would fail loudly when it does.
        """
        redis, self._redis = self._redis, None
        self._local.clear()
        if redis is not None:
            await redis.aclose()

    async def reset(self, bucket: str, key: str) -> None:
        """Clear a subject's quota. Called after a *successful* login.

        Without this, a user who mistyped their password four times and then got it right
        still carries four strikes for the rest of the window - so a second legitimate login
        from a different device can be refused. Only the identifier bucket is cleared, never
        the IP bucket: a successful login from one account behind a NAT must not reset the
        spray counter for everything else behind it.
        """
        full_key = f"{_KEY_PREFIX}:{bucket}:{key}"
        self._local.pop(full_key, None)
        if self._redis is not None:
            try:
                await self._redis.delete(full_key)
            except Exception as exc:  # best effort: a failed reset is a stale counter
                log.warning("ratelimit.reset_failed", error=type(exc).__name__)


_limiter: RateLimiter | None = None


def build_redis() -> Redis | None:
    """Connect to Redis for rate limiting, or return ``None`` if it is not configured.

    ``decode_responses=False``: this module only ever reads integers back out of the
    pipeline, and asking Redis to decode every member of a sorted set to a Python string on
    the hot path is work for nothing.
    """
    settings = get_settings()
    if not settings.redis.enabled:
        return None
    return Redis.from_url(
        settings.redis.cache_url,
        decode_responses=False,
        socket_connect_timeout=1.0,
        # A short timeout is essential given the fail-open policy: a Redis that is slow rather
        # than dead would otherwise add its latency to every request while still limiting
        # nothing useful.
        socket_timeout=1.0,
        health_check_interval=30,
    )


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        redis = build_redis()
        if redis is None:
            log.warning(
                "ratelimit.in_process_only",
                detail="no Redis configured; limits are per-process and not shared between "
                "workers. Acceptable for local development only.",
            )
        _limiter = RateLimiter(redis)
    return _limiter


def set_limiter_for_tests(limiter: RateLimiter | None) -> None:
    global _limiter
    _limiter = limiter


async def close_limiter() -> None:
    """Release the Redis connection at shutdown."""
    global _limiter
    if _limiter is not None:
        await _limiter.aclose()
    _limiter = None


def limit(bucket: str, key: str, quota: Limit) -> Awaitable[None]:
    """Convenience wrapper so a route reads ``await limit("login", email, LOGIN_PER_IDENTIFIER)``."""
    return get_limiter().check(bucket, key, quota)


__all__ = [
    "AI_PER_PRINCIPAL",
    "ANALYSIS_PER_TENANT",
    "DEFAULT_PER_PRINCIPAL",
    "LOGIN_PER_IDENTIFIER",
    "LOGIN_PER_IP",
    "MFA_PER_SESSION",
    "RESET_PER_IP",
    "Limit",
    "RateLimiter",
    "build_redis",
    "close_limiter",
    "get_limiter",
    "limit",
    "set_limiter_for_tests",
]
