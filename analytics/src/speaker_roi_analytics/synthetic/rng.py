"""Deterministic, *independent* random streams for the synthetic factory.

Why not just pass one ``Generator`` around
------------------------------------------
plan.md §11 requires that "one seed reproduces the entire dataset bit-for-bit".
A single shared generator satisfies that only until the first code change: add
one HCP and every subsequent draw in every domain shifts, so an unrelated diff
in ``hcps.py`` silently rewrites every event, every invitation and every Rx row.
Bisecting a regression against that is impossible.

So each domain gets its own stream, derived by
``numpy.random.SeedSequence(seed).spawn(...)`` on a **fixed, ordered name list**.
Spawned children are statistically independent by construction (the SeedSequence
entropy-mixing algorithm is designed for exactly this), so a change in one
domain's consumption pattern cannot perturb another's.

The name list is append-only. Inserting a name in the middle renumbers every
stream after it and invalidates every stored checksum; that is a
generator-version bump (``config.GENERATOR_VERSION``), not a refactor.
"""

from __future__ import annotations

from typing import Final

import numpy as np

__all__ = ["STREAM_NAMES", "RngBook"]

#: Ordered, **append-only** list of stream names. Position is the spawn key, so
#: the order is part of the reproducibility contract.
STREAM_NAMES: Final[tuple[str, ...]] = (
    "taxonomy",  # tenants, brands, products, reference vocabularies
    "hcps",  # HCP master + latent attributes
    "events",  # campaigns, events, per-event truth draws
    "invitations",  # who gets invited to what
    "attendance",  # the selection model and its realisation
    "outcomes",  # the Rx panel counts
    "context",  # market factors and marketing activity
    "costs",  # event cost lines and finance assumptions
    "imperfections",  # gaps, dupes, suppression, unmatched IDs
    "calibration",  # the t0 pre-pass; kept separate so calibration
    # cost does not perturb the real attendance draws
    "source_files",  # vendor file shaping (header dialects, ID mangling)
)


class RngBook:
    """A named collection of independent :class:`numpy.random.Generator` streams.

    Usage is deliberately blunt::

        book = RngBook(20260819)
        rng = book.stream("hcps")

    ``stream`` returns the *same* object on every call for a given name, so a
    module that draws in two phases keeps a single consistent sequence. Asking
    for an unregistered name raises immediately rather than silently minting an
    unreproducible stream.

    Never use ``numpy.random.<func>`` module-level helpers anywhere in this
    package: they read a hidden global ``RandomState`` that no seed here
    controls.
    """

    __slots__ = ("_generators", "_seed", "_seed_sequence")

    def __init__(self, seed: int) -> None:
        if seed < 0:
            raise ValueError(f"seed must be non-negative, got {seed}")
        self._seed = int(seed)
        self._seed_sequence = np.random.SeedSequence(self._seed)
        children = self._seed_sequence.spawn(len(STREAM_NAMES))
        self._generators: dict[str, np.random.Generator] = {
            name: np.random.default_rng(child)
            for name, child in zip(STREAM_NAMES, children, strict=True)
        }

    @property
    def seed(self) -> int:
        """The integer seed this book was constructed from."""
        return self._seed

    def stream(self, name: str) -> np.random.Generator:
        """Return the generator registered under ``name``."""
        try:
            return self._generators[name]
        except KeyError:
            known = ", ".join(STREAM_NAMES)
            raise KeyError(f"unknown RNG stream {name!r}; registered streams: {known}") from None

    def substream(self, name: str, key: int) -> np.random.Generator:
        """A fresh, independent generator derived from ``name`` and ``key``.

        Used where work is chunked (the Rx panel is generated per tenant-brand to
        bound peak memory, plan.md §11 "generation must be chunked"). A substream
        keyed by the chunk index makes each chunk's draws independent of how many
        chunks came before it, so re-ordering or parallelising chunks cannot
        change the output.
        """
        base = self._generators.get(name)
        if base is None:
            known = ", ".join(STREAM_NAMES)
            raise KeyError(f"unknown RNG stream {name!r}; registered streams: {known}")
        index = STREAM_NAMES.index(name)
        # Entropy is (seed, stream index, chunk key): distinct for every triple,
        # and derived from the root seed alone, so it stays reproducible.
        return np.random.default_rng(np.random.SeedSequence([self._seed, index, int(key)]))


def negative_binomial_counts(
    rng: np.random.Generator,
    mean: np.ndarray,
    dispersion: float,
) -> np.ndarray:
    """Draw NB2-parameterised over-dispersed counts.

    numpy exposes the *textbook* negative binomial ``NB(n, p)`` - the number of
    failures before the ``n``-th success - whose mean is ``n(1-p)/p`` and
    variance ``n(1-p)/p**2``. Epidemiology and prescribing data are instead
    described in the NB2 parameterisation: a mean ``mu`` and a dispersion
    ``phi`` with

        Var(Y) = mu + mu**2 / phi

    Matching the two gives

        n = phi
        p = phi / (phi + mu)

    which is what this function does, elementwise over ``mean``. Larger ``phi``
    means *less* over-dispersion; ``phi -> inf`` recovers the Poisson.

    Rx counts are over-dispersed in reality (a handful of high-volume months in
    an otherwise quiet series), and plan.md §12.2 requires the estimator to be
    honest about that. A Poisson DGP would make an incorrect variance assumption
    look harmless, which is the opposite of what a validation dataset is for.
    """
    if dispersion <= 0.0:
        raise ValueError(f"dispersion must be positive, got {dispersion}")
    mu = np.asarray(mean, dtype=np.float64)
    p = dispersion / (dispersion + mu)
    # numpy rejects p == 1.0 (mu == 0) and p == 0.0; clip into the open interval.
    p = np.clip(p, 1e-12, 1.0 - 1e-12)
    return rng.negative_binomial(dispersion, p).astype(np.int64)


def gumbel_top_k(
    rng: np.random.Generator,
    log_weights: np.ndarray,
    k: int,
) -> np.ndarray:
    """Weighted sampling **without replacement**, vectorised.

    The Gumbel-top-k trick: adding i.i.d. Gumbel(0,1) noise to log-weights and
    taking the ``k`` largest is exactly equivalent to ``k`` sequential draws from
    the weighted distribution without replacement (Vieira 2014). It costs one
    ``argpartition`` instead of ``k`` renormalisations, which is what makes
    5,400 invitation draws over a 5,200-HCP universe finish in seconds rather
    than minutes.
    """
    n = log_weights.shape[0]
    if k >= n:
        return np.arange(n, dtype=np.int64)
    if k <= 0:
        return np.empty(0, dtype=np.int64)
    perturbed = log_weights + rng.gumbel(size=n)
    top = np.argpartition(-perturbed, k - 1)[:k]
    # Sort for determinism: argpartition does not promise a stable ordering.
    return np.sort(top).astype(np.int64)
