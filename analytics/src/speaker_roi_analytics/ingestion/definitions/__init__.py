"""The twelve dataset contracts of plan.md §10.1, one module each.

Each module exports a single ``CONTRACT`` and reads as documentation: the
docstring explains what the dataset is *for* and why its rules exist, and the
field descriptions are the same text the uploader sees in the generated template
and data dictionary.  That is deliberate — there is exactly one place to change
a rule and its explanation, so the two cannot drift apart.

:data:`ALL_CONTRACTS` is consumed by
:func:`speaker_roi_analytics.ingestion.contracts.contract_registry`, which
asserts at import time that every member of
:class:`speaker_roi_core.enums.DatasetType` has at least one contract.  Adding a
dataset type without a contract is therefore an immediate, loud failure rather
than an empty dropdown discovered in production.

**Versioning.**  Contracts are versioned with semver and a new version is added
alongside the old one rather than replacing it: files produced against v1.0.0
must keep validating after v1.1.0 ships, because a supplier's export job is not
redeployed on our schedule.  Add the new module, append it to
:data:`ALL_CONTRACTS`, and the registry sorts versions and treats the highest as
current.
"""

from __future__ import annotations

from speaker_roi_analytics.ingestion.contracts import DatasetContract
from speaker_roi_analytics.ingestion.definitions import (
    attendance,
    brand_product_master,
    campaign_event_master,
    candidate_programs,
    event_cost,
    finance_assumptions,
    hcp_crosswalk,
    hcp_master,
    invitations,
    market_factors,
    marketing_activity,
    rx_monthly,
)

__all__ = ["ALL_CONTRACTS"]

#: Every published contract, in load order: reference data first, then the
#: transactional datasets that depend on it. The registry re-sorts by dataset
#: type and version, so this order is documentation rather than mechanism - but
#: it is the order the upload wizard recommends, and it is the order in which a
#: fresh tenant must be populated for the reference checks to pass.
ALL_CONTRACTS: tuple[DatasetContract, ...] = (
    brand_product_master.CONTRACT,
    campaign_event_master.CONTRACT,
    hcp_master.CONTRACT,
    hcp_crosswalk.CONTRACT,
    invitations.CONTRACT,
    attendance.CONTRACT,
    rx_monthly.CONTRACT,
    marketing_activity.CONTRACT,
    event_cost.CONTRACT,
    market_factors.CONTRACT,
    finance_assumptions.CONTRACT,
    candidate_programs.CONTRACT,
)
