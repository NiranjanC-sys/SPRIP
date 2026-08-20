"""One seed in, the same bytes out - every time (plan.md §11).

Determinism is not a nicety here. The causal estimates this platform ships are
validated against a known truth, and a validation run that cannot be reproduced
proves nothing: a reviewer who re-runs the generator and gets different numbers
cannot tell a regression from noise. So the contract is deliberately strict -
**the full content of every frame**, not a row count, not a summary statistic.

The tests below cover the three ways determinism actually breaks in practice:

1. a stage reaches for global ``np.random`` and picks up interpreter state;
2. a stage's draws are order-dependent, so adding a stage shifts every stage
   after it (guarded by the per-domain ``SeedSequence.spawn`` streams);
3. something reads the wall clock and leaks it into the output.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from speaker_roi_analytics.synthetic import GOLD_FRAMES, TRUTH_FRAMES, generate
from speaker_roi_analytics.synthetic.generator import GeneratedDataset
from speaker_roi_analytics.synthetic.rng import RngBook

pytestmark = pytest.mark.unit

SEED = 20240501
STAMP = datetime(2026, 1, 1, tzinfo=UTC)


def _digest(frame: pd.DataFrame) -> str:
    """Content hash that ignores row order but nothing else.

    Row order is an artefact of how stages concatenate; the *values* are the
    contract. Sorting on every column normalises the former without hiding a
    single changed cell.
    """
    ordered = frame.sort_values(list(frame.columns), kind="stable").reset_index(drop=True)
    digest = hashlib.sha256()
    for column in ordered.columns:
        digest.update(str(column).encode())
        digest.update(str(ordered[column].dtype).encode())
    digest.update(pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes())
    return digest.hexdigest()


def _all_digests(dataset: GeneratedDataset) -> dict[str, str]:
    return {
        **{name: _digest(dataset.frames[name]) for name in GOLD_FRAMES},
        **{f"ground_truth/{name}": _digest(dataset.truth[name]) for name in TRUTH_FRAMES},
    }


@pytest.fixture(scope="module")
def twice() -> tuple[GeneratedDataset, GeneratedDataset]:
    """Two independent in-memory runs of the same seed.

    ``write=False``: writing them would measure parquet, not the DGP, and would
    make the test twenty times slower for no additional guarantee.
    """
    first = generate("smoke", SEED, Path("unused"), STAMP, write=False)
    second = generate("smoke", SEED, Path("unused"), STAMP, write=False)
    return first, second


def test_every_frame_is_bit_for_bit_reproducible(
    twice: tuple[GeneratedDataset, GeneratedDataset],
) -> None:
    """The headline contract: same seed, same content, frame by frame."""
    first, second = twice
    left, right = _all_digests(first), _all_digests(second)

    assert set(left) == set(right)
    differing = sorted(name for name in left if left[name] != right[name])
    assert not differing, (
        f"{len(differing)} frame(s) differ between two runs of seed {SEED}: "
        f"{differing}. Something in those stages is drawing from global state, "
        "reading the clock, or depending on dict/set iteration order."
    )
    # Guard against the degenerate pass where every frame is empty.
    assert sum(first.frames[name].shape[0] for name in GOLD_FRAMES) > 50_000


def test_row_counts_match_exactly(twice: tuple[GeneratedDataset, GeneratedDataset]) -> None:
    """A cheaper signal than the digest, and a much clearer failure message."""
    first, second = twice
    left = {name: first.frames[name].shape for name in GOLD_FRAMES}
    right = {name: second.frames[name].shape for name in GOLD_FRAMES}
    assert left == right


def test_manifest_checksums_are_stable(twice: tuple[GeneratedDataset, GeneratedDataset]) -> None:
    """The manifest is the artefact reviewers diff, so it must be reproducible."""
    first, second = twice
    assert first.manifest["checksums"] == second.manifest["checksums"]
    assert first.manifest["row_counts"] == second.manifest["row_counts"]
    assert first.manifest["assertions"] == second.manifest["assertions"]
    assert set(first.manifest["checksums"]) == set(GOLD_FRAMES)


def test_manifest_checksums_match_independently_computed_digests(
    twice: tuple[GeneratedDataset, GeneratedDataset],
) -> None:
    """The manifest must hash what it claims to hash.

    Computed here from scratch rather than by calling the generator's own
    helper: a checksum verified with the same function that produced it would
    pass even if that function hashed a constant.
    """
    first, _ = twice
    recomputed = {name: _digest(first.frames[name]) for name in GOLD_FRAMES}
    assert first.manifest["checksums"] == recomputed


def test_generated_at_is_the_value_passed_in(
    twice: tuple[GeneratedDataset, GeneratedDataset],
) -> None:
    """The generator must never read the clock (plan.md §11 determinism note)."""
    first, _ = twice
    assert first.manifest["generated_at"] == STAMP.isoformat()


def test_a_different_seed_changes_the_data() -> None:
    """Determinism must not have been achieved by ignoring the seed.

    Taxonomy frames are excluded on purpose: tenants, brands and products are
    fixed business configuration, so they are *supposed* to be seed-invariant.
    Everything stochastic must move.
    """
    baseline = generate("smoke", SEED, Path("unused"), STAMP, write=False)
    other = generate("smoke", SEED + 1, Path("unused"), STAMP, write=False)

    stochastic = ("hcps", "events", "invitations", "attendance", "rx_monthly", "market_factors")
    for name in stochastic:
        assert _digest(baseline.frames[name]) != _digest(other.frames[name]), (
            f"{name!r} is identical under two different seeds - it is either "
            "hard-coded or drawing from a stream that ignores the seed."
        )


class TestRngBook:
    """The mechanism that makes stage-order changes safe."""

    def test_named_streams_are_reproducible(self) -> None:
        left = RngBook(7).stream("outcomes").normal(size=64)
        right = RngBook(7).stream("outcomes").normal(size=64)
        np.testing.assert_array_equal(left, right)

    def test_named_streams_are_independent_of_each_other(self) -> None:
        """Two domains must not accidentally share a sequence."""
        book = RngBook(7)
        outcomes = book.stream("outcomes").normal(size=256)
        events = book.stream("events").normal(size=256)
        assert not np.allclose(outcomes, events)
        # Independence, not merely inequality: a shared-but-offset stream would
        # pass the check above and still couple the two domains.
        assert abs(float(np.corrcoef(outcomes, events)[0, 1])) < 0.2

    def test_the_same_stream_returns_the_same_generator(self) -> None:
        """Callers hold on to a stream across stages; it must not reset."""
        book = RngBook(7)
        first = book.stream("hcps")
        assert book.stream("hcps") is first

    def test_stream_values_do_not_depend_on_request_order(self) -> None:
        """Adding a new stage must not shift the numbers an old stage produces."""
        forwards = RngBook(11)
        forwards.stream("hcps").normal(size=8)
        expected = forwards.stream("costs").normal(size=8)

        backwards = RngBook(11)
        backwards.stream("costs").normal(size=8)  # requested first this time
        # Re-derive from a clean book to compare like with like.
        assert not np.allclose(expected, RngBook(11).stream("hcps").normal(size=8))
        np.testing.assert_array_equal(expected, RngBook(11).stream("costs").normal(size=8))

    def test_a_different_seed_yields_a_different_stream(self) -> None:
        assert not np.allclose(
            RngBook(7).stream("outcomes").normal(size=64),
            RngBook(8).stream("outcomes").normal(size=64),
        )


def test_library_modules_never_touch_global_numpy_random() -> None:
    """A single ``np.random.normal`` call would silently destroy determinism.

    Global-state draws are invisible in review and produce a test failure far
    from their cause, so they are banned outright rather than audited. Only
    ``np.random.Generator`` / ``default_rng`` / ``SeedSequence`` (the explicit,
    seeded API) are allowed.
    """
    package = Path(__file__).resolve().parents[2] / "analytics/src/speaker_roi_analytics/synthetic"
    banned = re.compile(r"np\.random\.(?!Generator\b|default_rng\b|SeedSequence\b|BitGenerator\b)")
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if banned.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "global numpy random state used in the DGP:\n" + "\n".join(offenders)


def test_writing_twice_without_force_refuses(tmp_path: Path) -> None:
    """Two runs must never be mixed in one output tree.

    Overwriting selectively would leave a manifest describing frames that are no
    longer on disk, which is worse than either outcome on its own.
    """
    generate("smoke", SEED, tmp_path, STAMP)
    with pytest.raises(FileExistsError):
        generate("smoke", SEED, tmp_path, STAMP)
    generate("smoke", SEED, tmp_path, STAMP, force=True)  # explicit is fine
