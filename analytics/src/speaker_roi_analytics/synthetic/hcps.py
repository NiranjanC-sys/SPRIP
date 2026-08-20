"""The prescriber universe and its four latent attributes.

Two frames come out of here and they must never be confused:

* ``hcps`` - the master record the platform legitimately holds (plan.md §9.3).
* ``latent`` - ``latent_opportunity``, ``latent_affinity``,
  ``latent_access_sensitivity`` and ``prior_engagement_count``.

**The latent frame is ground truth.** It is written under ``ground_truth/`` and
must never be imported, joined, or featurised by ``speaker_roi_api``,
``speaker_roi_worker``, or any model in ``analytics``. Three of the four fields
are, by construction, confounders that drive both attendance and prescribing; a
model that saw them would produce an unbiased estimate for a reason that will
never exist in production, and the entire validation exercise would be
circular. ``tests/model_validation/test_synthetic_dgp.py`` greps the API source
tree to enforce this.

``prior_engagement_count`` is the deliberate exception: it is *observable* in
production (it is the HCP's own attendance history before the window opens), so
it is copied into the ``hcps`` frame as well. It is the proxy the propensity
model is supposed to lean on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import SyntheticProfile
from .taxonomy import SPECIALTIES, Taxonomies, TenantSpec, stable_uuid

__all__ = ["HcpUniverse", "build_crosswalk", "build_hcps", "latent_truth_frame"]

#: Small, fixed name pools. Real enough to make fuzzy matching non-trivial in
#: the source files, small enough that collisions occur - which is exactly the
#: condition that produces AMBIGUOUS crosswalk rows.
_FIRST_NAMES: tuple[str, ...] = (
    "Alice",
    "Brian",
    "Carmen",
    "David",
    "Elena",
    "Farid",
    "Grace",
    "Hassan",
    "Ingrid",
    "James",
    "Kavita",
    "Luis",
    "Maria",
    "Nadia",
    "Omar",
    "Priya",
    "Quentin",
    "Rosa",
    "Samuel",
    "Tomas",
    "Ursula",
    "Victor",
    "Wei",
    "Yolanda",
)
_LAST_NAMES: tuple[str, ...] = (
    "Alvarez",
    "Bennett",
    "Chen",
    "Duarte",
    "Eriksen",
    "Fontaine",
    "Gupta",
    "Haddad",
    "Ibrahim",
    "Jansen",
    "Kowalski",
    "Lindqvist",
    "Moreau",
    "Nakamura",
    "OConnor",
    "Petrov",
    "Quintana",
    "Rossi",
    "Silva",
    "Tanaka",
    "Ueda",
    "Vasquez",
    "Weber",
    "Xu",
    "Yildiz",
    "Zhang",
)
_STATES_BY_REGION: dict[str, tuple[str, ...]] = {
    "NE": ("MA", "NY", "NJ", "CT", "PA"),
    "SE": ("FL", "GA", "NC", "TN", "SC"),
    "MW": ("IL", "OH", "MI", "MN", "WI"),
    "SW": ("TX", "AZ", "NM", "OK"),
    "WEST": ("CA", "WA", "OR", "NV"),
    "MTN": ("CO", "UT", "MT", "ID", "WY"),
}


class HcpUniverse:
    """The HCP master, the latent truth, and the numpy views the DGP needs.

    Kept as a class rather than a bare DataFrame because every downstream module
    wants the *same* columns as contiguous numpy arrays; re-extracting them from
    pandas on each access is the difference between a two-minute run and a
    twenty-minute one at 10,400 HCPs.
    """

    __slots__ = (
        "access_sensitivity",
        "affinity",
        "frame",
        "latent",
        "log_opportunity",
        "opportunity",
        "prior_engagement",
        "region_code",
        "region_index",
        "remoteness",
        "specialty_code",
        "tenant_id",
        "tenant_offsets",
    )

    def __init__(self, frame: pd.DataFrame, latent: pd.DataFrame, taxonomies: Taxonomies) -> None:
        self.frame = frame
        self.latent = latent
        self.tenant_id = frame["tenant_id"].to_numpy()
        self.region_code = frame["region_code"].to_numpy()
        self.specialty_code = frame["specialty_code"].to_numpy()
        self.opportunity = latent["latent_opportunity"].to_numpy(dtype=np.float64)
        self.log_opportunity = np.log(self.opportunity)
        self.affinity = latent["latent_affinity"].to_numpy(dtype=np.float64)
        self.access_sensitivity = latent["latent_access_sensitivity"].to_numpy(dtype=np.float64)
        self.prior_engagement = latent["prior_engagement_count"].to_numpy(dtype=np.float64)
        codes = taxonomies.region_codes
        lookup = {code: i for i, code in enumerate(codes)}
        self.region_index = np.array([lookup[c] for c in self.region_code], dtype=np.int64)
        self.remoteness = np.array(
            [taxonomies.region_remoteness[c] for c in self.region_code], dtype=np.float64
        )
        # Row-slice bounds per tenant. HCPs are emitted tenant-contiguously, so a
        # tenant's block is a slice rather than a boolean mask.
        self.tenant_offsets: dict[str, tuple[int, int]] = {}
        start = 0
        for tenant, size in frame.groupby("tenant_id", sort=False).size().items():
            self.tenant_offsets[str(tenant)] = (start, start + int(size))
            start += int(size)

    def __len__(self) -> int:
        return int(self.frame.shape[0])


def _draw_regions(
    generator: np.random.Generator, n: int, n_regions: int, concentration: float
) -> np.ndarray:
    """Regions drawn from a skewed Dirichlet, not uniform.

    Speaker-program target lists concentrate where the patients (and the reps)
    are. A uniform region draw would make the region fixed effects in the
    outcome model estimable from an unrealistically balanced design.
    """
    weights = generator.dirichlet(np.full(n_regions, concentration))
    return generator.choice(n_regions, size=n, p=weights)


def build_hcps(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    generator: np.random.Generator,
) -> HcpUniverse:
    """Draw the prescriber universe for every tenant."""
    population = profile.population
    latent_params = profile.latent

    frames: list[pd.DataFrame] = []
    latents: list[pd.DataFrame] = []

    for spec in taxonomies.specs:
        n = spec.n_hcps
        specialty_codes = taxonomies.specialty_codes_by_tenant[spec.tenant_id]
        specialty_weights = np.array(
            [next(s.weight for s in SPECIALTIES if s.code == code) for code in specialty_codes],
            dtype=np.float64,
        )
        specialty_weights /= specialty_weights.sum()

        # --- latent attributes (plan.md §11) -------------------------------
        opportunity = generator.lognormal(
            latent_params.opportunity_log_mu, latent_params.opportunity_log_sigma, size=n
        )
        affinity = generator.beta(latent_params.affinity_beta_a, latent_params.affinity_beta_b, n)
        access_sensitivity = generator.normal(
            latent_params.access_sensitivity_mu, latent_params.access_sensitivity_sigma, n
        )
        prior_engagement = generator.poisson(latent_params.prior_engagement_lambda, n)

        # --- observables ---------------------------------------------------
        specialty_idx = generator.choice(len(specialty_codes), size=n, p=specialty_weights)
        specialty = np.asarray(specialty_codes, dtype=object)[specialty_idx]
        region_idx = _draw_regions(
            generator, n, len(taxonomies.region_codes), population.region_concentration
        )
        region = np.asarray(taxonomies.region_codes, dtype=object)[region_idx]

        practice_codes = list(population.practice_type_weights)
        practice_probs = np.array(list(population.practice_type_weights.values()))
        practice_probs /= practice_probs.sum()
        practice = np.asarray(practice_codes, dtype=object)[
            generator.choice(len(practice_codes), size=n, p=practice_probs)
        ]

        # Segment is a *deterministic* function of the opportunity percentile:
        # commercial segmentation is a volume exercise, and this makes segment an
        # honest observable proxy for the latent confounder rather than noise.
        percentile = opportunity.argsort().argsort() / max(n - 1, 1)
        segment_idx = np.searchsorted(
            np.asarray(population.segment_decile_cuts), percentile, side="right"
        )
        segment = np.asarray(population.segment_labels, dtype=object)[segment_idx]
        decile = np.clip((percentile * 10).astype(np.int64) + 1, 1, 10)

        years = np.minimum(
            generator.gamma(
                population.years_in_practice_shape, population.years_in_practice_scale, n
            ),
            population.years_in_practice_max,
        )

        first = np.asarray(_FIRST_NAMES, dtype=object)[generator.integers(0, len(_FIRST_NAMES), n)]
        last = np.asarray(_LAST_NAMES, dtype=object)[generator.integers(0, len(_LAST_NAMES), n)]
        state = np.array(
            [
                _STATES_BY_REGION[code][int(generator.integers(0, len(_STATES_BY_REGION[code])))]
                for code in region
            ],
            dtype=object,
        )
        has_national_id = generator.random(n) < population.has_national_id_rate
        national_id = np.where(
            has_national_id,
            np.char.add("1", (generator.integers(10**8, 10**9, n)).astype(str)),
            None,
        )

        seq = np.arange(n)
        hcp_code = np.array([f"{spec.tenant_code[:2]}H{i:06d}" for i in seq], dtype=object)
        hcp_id = np.array(
            [stable_uuid("hcp", spec.tenant_code, code) for code in hcp_code], dtype=object
        )

        frames.append(
            pd.DataFrame(
                {
                    "tenant_id": spec.tenant_id,
                    "hcp_id": hcp_id,
                    "hcp_code": hcp_code,
                    "national_id": national_id,
                    "first_name": first,
                    "last_name": last,
                    "specialty_code": specialty,
                    "practice_type_code": practice,
                    "segment_code": segment,
                    "region_code": region,
                    "state_code": state,
                    "decile": decile,
                    "years_in_practice": np.round(years, 1),
                    "prior_engagement_count": prior_engagement.astype(np.int64),
                    "is_active": True,
                }
            )
        )
        latents.append(
            pd.DataFrame(
                {
                    "tenant_id": spec.tenant_id,
                    "hcp_id": hcp_id,
                    "latent_opportunity": opportunity,
                    "latent_affinity": affinity,
                    "latent_access_sensitivity": access_sensitivity,
                    "prior_engagement_count": prior_engagement.astype(np.int64),
                }
            )
        )

    frame = pd.concat(frames, ignore_index=True)
    latent = pd.concat(latents, ignore_index=True)
    return HcpUniverse(frame, latent, taxonomies)


def build_crosswalk(
    universe: HcpUniverse,
    specs: tuple[TenantSpec, ...],
) -> pd.DataFrame:
    """The clean source-identifier crosswalk, before imperfections are injected.

    plan.md §10.4: source systems never agree on an identifier, so the platform
    resolves ``(source_system, source_hcp_id)`` to a master ``hcp_id`` and
    records *how*. Here every row starts MATCHED by EXACT_SOURCE_ID;
    ``imperfections.py`` then degrades a documented share into UNMATCHED and
    AMBIGUOUS, which is what the steward queue exists to handle.
    """
    from speaker_roi_core.enums import IdentityMatchStatus, MatchMethod

    parts: list[pd.DataFrame] = []
    frame = universe.frame
    for spec in specs:
        block = frame.loc[frame["tenant_id"] == spec.tenant_id, ["hcp_id", "hcp_code"]]
        ordinal = np.arange(block.shape[0])
        for system, template in spec.source_id_templates.items():
            parts.append(
                pd.DataFrame(
                    {
                        "tenant_id": spec.tenant_id,
                        "source_system": system,
                        "source_hcp_id": [template.format(i) for i in ordinal],
                        "hcp_id": block["hcp_id"].to_numpy(),
                        "match_status": IdentityMatchStatus.MATCHED.value,
                        "match_method": MatchMethod.EXACT_SOURCE_ID.value,
                        "match_confidence": 1.0,
                    }
                )
            )
    return pd.concat(parts, ignore_index=True)


def latent_truth_frame(universe: HcpUniverse) -> pd.DataFrame:
    """The ground-truth latent attributes, keyed for offline validation only.

    **Never delivered to the platform.** Written to
    ``ground_truth/hcp_latent.parquet`` so a validation notebook can ask "how
    much of the naive lift is explained by ``latent_opportunity``?" without
    re-running the generator. ``hcp_code`` is carried alongside ``hcp_id``
    purely so a human reading the parquet can identify a prescriber; it is not
    a join key the platform is ever given.

    Three of these columns (opportunity, affinity, access sensitivity) are the
    confounders the causal engine must neutralise using observables alone.
    ``prior_engagement_count`` is duplicated from the master frame on purpose -
    it is the one latent quantity that is genuinely observable in production,
    and having both here makes it obvious in review which is which.
    """
    codes = universe.frame[["hcp_id", "hcp_code", "segment_code", "decile"]]
    return universe.latent.merge(codes, on="hcp_id", how="left", validate="one_to_one")[
        [
            "tenant_id",
            "hcp_id",
            "hcp_code",
            "segment_code",
            "decile",
            "latent_opportunity",
            "latent_affinity",
            "latent_access_sensitivity",
            "prior_engagement_count",
        ]
    ]
