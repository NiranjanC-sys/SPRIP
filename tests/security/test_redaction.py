"""Regression lock on the log redaction pipeline.

plan.md §15 forbids logging file contents, access tokens or sensitive free text, and forbids
ingesting patient names, phone numbers, addresses or ABHA identifiers at all. The pipeline in
:mod:`speaker_roi_core.logging` is what actually delivers that; this file is what keeps it
delivered.

Every case here is present because it is a way the pipeline can fail, and two of them are
here because the pipeline *did* fail that way. Neither was visible from reading the code:

* **UUIDs were being mangled.** A UUID's final group is twelve hex characters, so about one
  in sixteen is all digits - and the "long digit run" rule rewrote
  ``...-000000000007`` to ``...-***REDACTED***``. That silently destroys the ``tenant_id``
  and ``correlation_id`` fields the log is searched by, for a *fraction* of identifiers, so
  every example anyone spot-checks looks fine.
* **Spaced phone numbers leaked.** The first pattern matched only ten bare digits, while a
  number pasted out of a spreadsheet arrives as ``+91 98765 43210``. The single most common
  real-world spelling of the thing the rule exists to catch went straight through.

The pair of them is why this file asserts in both directions. A redactor tested only on
things it must catch drifts toward matching everything, which is its own outage: an analytics
log with the prescription counts redacted out of it is not a log.
"""

from __future__ import annotations

import io
import json
import logging
import uuid

import pytest
import structlog

from speaker_roi_core.context import Principal, RequestContext, request_context
from speaker_roi_core.errors import InvalidCredentialsError, tenant_scoped_missing
from speaker_roi_core.logging import (
    MAX_ITEMS,
    MAX_VALUE_CHARS,
    REDACTED,
    LogTimer,
    _redact,
    _scrub_string,
    configure_logging,
    redact_processor,
)

pytestmark = pytest.mark.security


# ---------------------------------------------------------------------------
# Values that must be redacted.
# ---------------------------------------------------------------------------

MUST_REDACT: tuple[tuple[str, str], ...] = (
    # (input, the substring that must NOT survive)
    ("contact +91 98765 43210 for details", "98765"),
    ("phone 98765-43210 on file", "98765"),
    ("mobile 9876543210", "9876543210"),
    ("call +919876543210 now", "9876543210"),
    ("98765.43210", "98765"),
    # 3-3-4 grouping, the other common spelling.
    ("987 654 3210", "3210"),
    # ABHA, 14 digits in 2-4-4-4.
    ("abha 12-3456-7890-1234 verified", "3456"),
    ("id 12345678901234", "12345678901234"),
    # Free-text email out of a validation message quoting the offending cell.
    ("row 4: 'dr.mehta@hospital.example' is not a valid speaker code", "dr.mehta"),
    # Credentials.
    ("Authorization: Bearer abcdefghijklmnop1234", "abcdefghijklmnop"),
    ("token sk_live_abcdefghijklmnopqrstuv", "abcdefghijklmnopqrstuv"),
    (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQabcd",
        "eyJhbGciOiJIUzI1NiJ9",
    ),
    ("could not connect to postgresql://app:hunter2@db:5432/roi", "hunter2"),
)


@pytest.mark.parametrize(("raw", "forbidden"), MUST_REDACT, ids=[c[1] for c in MUST_REDACT])
def test_sensitive_values_never_survive_scrubbing(raw: str, forbidden: str) -> None:
    scrubbed = _scrub_string(raw)
    assert forbidden not in scrubbed, f"{forbidden!r} leaked through: {scrubbed!r}"
    assert REDACTED in scrubbed


def test_email_redaction_preserves_the_domain() -> None:
    """The domain is operationally useful and is not, alone, a personal identifier.

    Knowing a failed login came from ``@ourcompany.example`` versus a customer domain is
    the difference between an internal misconfiguration and a real intrusion attempt, and
    it costs nothing in disclosure.
    """
    scrubbed = _scrub_string("login failed for dr.mehta@hospital.example")
    assert "dr.mehta" not in scrubbed
    assert "@hospital.example" in scrubbed


def test_url_credentials_keep_the_scheme_and_host() -> None:
    """A connection error with the password removed is still a diagnosable error."""
    scrubbed = _scrub_string("FATAL: postgresql://app_rw:s3cret@db.internal:5432/roi")
    assert "s3cret" not in scrubbed
    assert "postgresql://app_rw:" in scrubbed
    assert "@db.internal:5432/roi" in scrubbed


# ---------------------------------------------------------------------------
# Values that must NOT be touched. This half is the one that decays quietly.
# ---------------------------------------------------------------------------

MUST_PRESERVE: tuple[str, ...] = (
    # The regression that motivated _HEXISH. All-digit final group.
    "00000000-0000-0000-0000-000000000007",
    "3f2504e0-4f89-11d3-9a0c-000000000000",
    # A content hash. 64 hex characters, and a long digit run if you squint.
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    # Ordinary analytical output. A row of monthly prescription counts is ten smallish
    # integers separated by spaces, which is exactly what a permissive phone pattern eats.
    "7 8 9 1 2 3 4 5 6 7 events",
    "trx 61 72 83 94 105",
    "monthly volumes: 9 8 7 6 5 4 3 2 1 9",
    # Money, rates and timestamps.
    "total 1234567 INR",
    "rate 0.6789 and 8.7654321",
    "2026-08-19T09:37:02.721621Z",
    "connect localhost:5432",
    "in 2026 we had 4 events",
    # A plausible identifier that is short enough to be meaningless on its own.
    "event 4821 completed",
)


@pytest.mark.parametrize("raw", MUST_PRESERVE)
def test_ordinary_values_pass_through_untouched(raw: str) -> None:
    assert _scrub_string(raw) == raw, "redaction fired on a value it must leave alone"


def test_a_uuid_survives_every_position_of_an_all_digit_group() -> None:
    """The original bug only bit some identifiers, so sample the space rather than one case.

    A single hand-picked UUID is precisely what let the bug ship: the developer's example
    had a letter in the last group.
    """
    for i in range(64):
        ident = f"{i:08d}-0000-0000-0000-{i:012d}"
        assert _scrub_string(ident) == ident, f"mangled {ident}"


# ---------------------------------------------------------------------------
# Key-based redaction.
# ---------------------------------------------------------------------------


def test_sensitive_keys_are_dropped_regardless_of_value() -> None:
    out = _redact(
        {
            "db_password": "anything",
            "Authorization": "whatever",
            "x-api-key": "k",
            "session_cookie": "abc",
            "patient_name": "A. Patient",
            "totp": "123456",
            "raw_row": "col1,col2,col3",
        }
    )
    assert set(out.values()) == {REDACTED}, out


def test_safe_lookalike_keys_are_kept() -> None:
    """``token_count`` is a metric; losing it makes the AI cost dashboard unbuildable."""
    out = _redact(
        {"token_count": 512, "has_password": True, "phone_column_present": False, "count": 3}
    )
    assert out == {
        "token_count": 512,
        "has_password": True,
        "phone_column_present": False,
        "count": 3,
    }


def test_nested_structures_are_redacted_at_depth() -> None:
    out = _redact({"outer": {"inner": {"api_key": "x", "rows": 12}}})
    assert out["outer"]["inner"]["api_key"] == REDACTED
    assert out["outer"]["inner"]["rows"] == 12


def test_bytes_are_reduced_to_a_length() -> None:
    """The realistic way a spreadsheet reaches a log is a bytes payload in an error context."""
    out = _redact({"upload": b"col_a,col_b\n1,2\n"})
    assert out["upload"] == "<16 bytes>"


def test_secret_str_is_masked_even_under_an_innocuous_key() -> None:
    pydantic = pytest.importorskip("pydantic")
    out = _redact({"value": pydantic.SecretStr("hunter2")})
    assert "hunter2" not in json.dumps(out)


def test_long_values_are_truncated_and_report_their_real_length() -> None:
    """Knowing a value was 400 kB is diagnostic. The bytes are not."""
    out = _scrub_string("x" * 5_000)
    assert len(out) < MAX_VALUE_CHARS + 60
    assert "5000 chars" in out


def test_large_collections_are_summarised_rather_than_walked() -> None:
    out = _redact({"rows": list(range(MAX_ITEMS + 20))})
    assert len(out["rows"]) == MAX_ITEMS + 1
    assert "20 more" in out["rows"][-1]


def test_recursive_structures_terminate() -> None:
    """A self-referential context object must not turn a log call into an infinite walk."""
    node: dict[str, object] = {"name": "a"}
    node["self"] = node
    rendered = json.dumps(_redact(node))
    assert "max depth" in rendered


def test_an_object_whose_repr_leaks_is_still_scrubbed() -> None:
    """This is the case no key-based rule can catch.

    An ORM object's ``repr`` is exactly where a password hash or an email address turns up
    in a log without anyone choosing to put it there.
    """

    class Leaky:
        def __repr__(self) -> str:
            return "<User email=dr.mehta@hospital.example password_hash=$argon2id$abcdefgh>"

    out = _redact({"user": Leaky()})
    assert "dr.mehta" not in out["user"]


# ---------------------------------------------------------------------------
# The processor itself, including its failure behaviour.
# ---------------------------------------------------------------------------


def test_redaction_is_fail_closed() -> None:
    """If the redactor raises, the event is replaced - never passed through.

    A lost log line is an inconvenience. An emitted one is permanent, and this is the exact
    situation in which the emitted one contains something interesting.
    """

    class Exploding:
        def __repr__(self) -> str:
            raise ValueError("boom")

    out = redact_processor(None, "info", {"event": "upload.failed", "payload": Exploding()})
    assert out["event"] == "log_redaction_failed"
    assert out["redaction_error"] == "ValueError"
    assert "payload" not in out


def test_the_processor_redacts_by_key_at_the_top_level() -> None:
    out = redact_processor(None, "info", {"event": "login", "password": "hunter2"})
    assert out["password"] == REDACTED
    assert out["event"] == "login"


# ---------------------------------------------------------------------------
# End to end, through the real configured pipeline.
# ---------------------------------------------------------------------------


@pytest.fixture
def captured():
    """Configure the real pipeline and return a reader over what it emitted.

    Reads the installed handler's own stream rather than pytest's stdout capture. The
    alternative depends on how pytest's capture and logging plugins interleave with a
    handler installed mid-test, which is not the thing under test - and when it goes wrong
    it goes wrong as an empty capture, which reads identically to "nothing was logged" and
    would make these assertions vacuous rather than failing.

    ``cache_logger_on_first_use`` means structlog memoises bound loggers against the active
    configuration, so the teardown resets defaults and clears the contextvars that
    ``configure_logging`` binds process-wide. Without that, a later test inherits this
    test's ``environment=test`` binding and the ordering of the file changes its results.
    """
    configure_logging(level="DEBUG", fmt="json", environment="test")
    root = logging.getLogger()
    handler = next(h for h in root.handlers if isinstance(h, logging.StreamHandler))
    stream = io.StringIO()
    handler.setStream(stream)
    try:
        yield stream
    finally:
        structlog.contextvars.clear_contextvars()
        structlog.reset_defaults()
        root.handlers.clear()


def _lines(stream: io.StringIO) -> list[dict]:
    return [
        json.loads(line) for line in stream.getvalue().splitlines() if line.strip().startswith("{")
    ]


def test_a_real_log_call_carries_context_and_leaks_nothing(captured) -> None:
    tenant = uuid.UUID("00000000-0000-0000-0000-000000000007")
    principal = Principal(user_id=uuid.uuid4(), email="ops@ourcompany.example")
    ctx = RequestContext(
        correlation_id="c" * 32,
        tenant_id=tenant,
        principal=principal,
        route="/api/v1/events/{event_id}",
        method="POST",
    )
    log = structlog.stdlib.get_logger("test")
    with request_context(ctx):
        log.info(
            "ingestion.row_rejected",
            reason="invalid phone",
            offending_cell="+91 98765 43210",
            db_password="hunter2",
            row_index=41,
        )

    (line,) = _lines(captured)
    blob = json.dumps(line)
    # The context is present and, critically, intact.
    assert line["tenant_id"] == str(tenant), "the tenant id was mangled by redaction"
    assert line["correlation_id"] == "c" * 32
    assert line["route"] == "/api/v1/events/{event_id}"
    assert line["row_index"] == 41
    # The email became a domain; the phone and the password did not survive at all.
    assert line["user_domain"] == "ourcompany.example"
    assert "ops@" not in blob
    assert "98765" not in blob
    assert "hunter2" not in blob


def test_stdlib_loggers_are_redacted_too(captured) -> None:
    """SQLAlchemy and botocore log through stdlib, and they are the likeliest offenders.

    Routing stdlib logging *through* structlog rather than configuring it alongside is what
    makes this hold; without it these lines bypass the redactor entirely.
    """
    logging.getLogger("some.library").warning(
        "connection failed: postgresql://app:hunter2@db:5432/roi"
    )
    (line,) = _lines(captured)
    assert "hunter2" not in json.dumps(line)


def test_an_exception_traceback_is_scrubbed(captured) -> None:
    """Redaction runs after the exception formatter, so captured values are covered."""
    log = structlog.stdlib.get_logger("test")
    try:
        raise ValueError("bad token sk_live_abcdefghijklmnopqrstuv")
    except ValueError:
        log.exception("job.failed")

    (line,) = _lines(captured)
    assert "abcdefghijklmnopqrstuv" not in json.dumps(line)


def test_log_timer_reports_duration_on_both_paths(captured) -> None:
    log = structlog.stdlib.get_logger("test")
    with LogTimer("stage.match", logger=log, stage="matching") as timer:
        timer.add(matched_pairs=120)
    with pytest.raises(RuntimeError), LogTimer("stage.estimate", logger=log):
        raise RuntimeError("no")

    ok, failed = _lines(captured)
    assert ok["event"] == "stage.match.completed"
    assert ok["matched_pairs"] == 120
    assert isinstance(ok["duration_ms"], float | int)
    assert failed["event"] == "stage.estimate.failed"
    assert failed["error_type"] == "RuntimeError"
    assert failed["level"] == "error"


# ---------------------------------------------------------------------------
# The response side of the same rule: an error envelope discloses nothing extra.
# ---------------------------------------------------------------------------


def test_a_cross_tenant_miss_reveals_nothing_in_the_response() -> None:
    """Answering "not in your tenant" with a 403 confirms the row exists.

    That turns a sequential id scan into an existence oracle across tenants, which is a
    disclosure even though no field of the row is ever returned.
    """
    other = uuid.uuid4()
    exc = tenant_scoped_missing("event", other, exists_elsewhere=True)
    body = json.dumps(exc.to_envelope())
    assert exc.status_code == 404
    assert "elsewhere" not in body
    assert "tenant" not in body.lower()
    # The distinction is preserved where it belongs - the log line.
    assert "outside the caller's tenant scope" in exc.log_fields()["internal_detail"]


def test_invalid_credentials_cannot_be_made_more_helpful() -> None:
    """The message is fixed at class level so no raise site can turn it into an oracle.

    "No account with that email" versus "wrong password" is a user-enumeration primitive,
    and it gets added by someone improving an error message, not by someone attacking.
    """
    message = InvalidCredentialsError().to_envelope()["error"]["message"].lower()
    # The message may name both factors - "the email address or password is incorrect" is
    # ambiguous and therefore fine. What it must not do is resolve which one, so the test
    # looks for the disjunction and for the absence of any phrasing that singles one out.
    assert " or " in message
    for oracle in (
        "no account",
        "not found",
        "does not exist",
        "unknown",
        "unregistered",
        "wrong password",
        "incorrect password",
        "password is wrong",
    ):
        assert oracle not in message, f"the message discloses which factor failed: {oracle!r}"
    # And the raise site cannot override it, which is the property that actually holds the
    # line - the message is a class-level constant, not a parameter.
    assert (
        InvalidCredentialsError(internal_detail="user 41 has no password set")
        .to_envelope()["error"]["message"]
        .lower()
        == message
    )
