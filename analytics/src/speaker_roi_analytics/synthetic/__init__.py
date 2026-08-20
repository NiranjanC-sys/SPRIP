"""Deterministic synthetic data factory (plan.md §11, §12; PLAN_REVIEW F-2).

**This package writes ground truth.** ``ground_truth/event_effects.parquet``
holds the per-event causal effect the platform is asked to recover, and
``ground_truth/hcp_latent.parquet`` holds the confounders that generated it.
Nothing in ``apps/api``, ``apps/worker`` or the feature layer may import this
package; ``tests/model_validation/test_synthetic_dgp.py`` fails the build if the
API source tree so much as mentions it.

What this exists for
--------------------
Every causal claim the platform makes is unverifiable on real data - the
counterfactual is not observed. So the estimator is validated here instead,
against a world whose true effects are known by construction, and which is
deliberately built to *punish* a naive analyst:

* attendance is **selected on the outcome's own drivers**, so a
  before-and-after comparison overstates the effect by design;
* effects **decay** and a sixth of them are zero or negative, so an estimator
  that assumes a constant positive lift fails visibly;
* the data arrives **broken** in the specific ways real vendor feeds break.

Public surface
--------------
``generate`` is the whole API. Everything else is an implementation detail of
the DGP and may change between generator versions - which is why the version is
stamped into the manifest alongside the seed.
"""

from __future__ import annotations

from .config import GENERATOR_VERSION, PROFILES, ProfileName, SyntheticProfile, get_profile
from .generator import (
    GOLD_FRAMES,
    TRUTH_FRAMES,
    GeneratedDataset,
    SyntheticMinimumNotMet,
    generate,
)

__all__ = [
    "GENERATOR_VERSION",
    "GOLD_FRAMES",
    "PROFILES",
    "TRUTH_FRAMES",
    "GeneratedDataset",
    "ProfileName",
    "SyntheticMinimumNotMet",
    "SyntheticProfile",
    "generate",
    "get_profile",
]
