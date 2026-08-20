"""Vendor-shaped delivery files - the input to real ingestion (plan.md §10).

The gold parquet frames are what the platform looks like *after* ingestion.
Handing those back as "source data" would let the whole intake layer - column
mapping, type coercion, date parsing, encoding detection, quarantine - go
untested, and plan.md §10.3 builds a mapping wizard specifically because no
vendor ever sends the canonical contract.

So the source tree is deliberately hostile in the ways real deliveries are:

* **Column headers are vendor vocabulary**: ``Event Code``, ``HCP ID``,
  ``Rx Month``. Never the gold column name.
* **Date formats differ per feed**: ``%d/%m/%Y`` from the invitation system,
  ``%d-%b-%Y`` from the event vendor, ``%m/%d/%Y`` from finance. Two of those
  are ambiguous for the first twelve days of every month, which is exactly why
  the mapping step has to capture the format rather than guess it.
* **Identifiers are source identifiers**, resolved through the crosswalk, not
  master UUIDs. Rows whose crosswalk entry was degraded to UNMATCHED still
  appear in the files - that is what an unresolvable delivery looks like.
* **One feed is .xlsx**, one carries a **UTF-8 BOM**, one renders money with
  thousands separators.
* **Files are partitioned by quarter** for the time-series feeds, because
  vendors deliver on a cadence and the platform has to accept a partial
  window without treating the missing months as zeros.

Nothing here changes the data. It is a re-rendering of the same rows, so a
correct ingestion of ``source/`` must reproduce ``gold/`` up to the documented
imperfections.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from speaker_roi_core.enums import DatasetType, EventStatus

from .config import SourceFileParams, SyntheticProfile
from .taxonomy import Taxonomies

__all__ = ["SourceFileRecord", "write_source_files"]


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    """One emitted file, for the manifest."""

    tenant_code: str
    dataset_type: str
    relative_path: str
    row_count: int
    encoding: str
    file_format: str


#: Gold column -> vendor header, per dataset type. Anything not listed is
#: dropped from the delivery: vendors send what their system holds, not the
#: platform's full schema, and the missing columns must be derivable or
#: optional. Order here is the column order in the file.
_VENDOR_COLUMNS: dict[str, dict[str, str]] = {
    DatasetType.BRAND_PRODUCT_MASTER.value: {
        "brand_code": "Brand Cd",
        "brand_name": "Brand",
        "product_code": "Product Cd",
        "product_name": "Product",
        "dosage_form": "Form",
        "therapeutic_area": "TA",
        "is_flagship": "Flagship Flag",
    },
    DatasetType.CAMPAIGN_EVENT_MASTER.value: {
        "campaign_code": "Campaign Cd",
        "campaign_name": "Campaign",
        "event_code": "Event Code",
        "brand_code": "Brand Cd",
        "topic_code": "Topic",
        "event_format": "Format",
        "region_code": "Region",
        "venue_city": "City",
        "speaker_tier": "Speaker Tier",
        "status": "Event Status",
        "event_date": "Event Dt",
        "planned_attendees": "Planned Attendees",
    },
    DatasetType.HCP_MASTER.value: {
        "source_hcp_id": "HCP ID",
        "national_id": "NPI",
        "first_name": "First Name",
        "last_name": "Last Name",
        "specialty_code": "Specialty",
        "practice_type_code": "Practice Type",
        "segment_code": "Segment",
        "region_code": "Region",
        "state_code": "State",
        "decile": "Decile",
        "years_in_practice": "Yrs In Practice",
    },
    DatasetType.HCP_CROSSWALK.value: {
        "source_system": "Source System",
        "source_hcp_id": "Source HCP ID",
        "national_id": "NPI",
        "hcp_code": "Master HCP Cd",
    },
    DatasetType.INVITATIONS.value: {
        "event_code": "Event Code",
        "source_hcp_id": "HCP ID",
        "invitation_channel": "Channel",
        "invited_on": "Invite Dt",
        "is_target_specialty": "Target Flag",
    },
    DatasetType.ATTENDANCE.value: {
        "event_code": "Event Code",
        "source_hcp_id": "HCP ID",
        "attendance_status": "Status",
        "verification_source": "Verification",
        "is_verified": "Verified",
        "attended_on": "Attended Dt",
        "duration_minutes": "Minutes",
    },
    DatasetType.RX_MONTHLY.value: {
        "source_hcp_id": "HCP ID",
        "product_code": "Product Cd",
        "month": "Rx Month",
        "nrx": "NRx",
        "trx": "TRx",
        "competitor_trx": "Comp TRx",
        "suppression_flag": "Suppressed",
    },
    DatasetType.MARKETING_ACTIVITY.value: {
        "source_hcp_id": "HCP ID",
        "month": "Activity Month",
        "rep_calls": "Calls",
        "emails_delivered": "Emails",
        "samples_dropped": "Samples",
        "other_promotional_exposures": "Other Promo",
    },
    DatasetType.EVENT_COST.value: {
        "event_code": "Event Code",
        "cost_category": "Cost Category",
        "amount": "Amount",
        "currency_code": "Ccy",
        "invoice_date": "Invoice Dt",
    },
    DatasetType.MARKET_FACTORS.value: {
        "brand_code": "Brand Cd",
        "region_code": "Region",
        "month": "Factor Month",
        "access_index": "Access Idx",
        "competitor_index": "Competitor Idx",
    },
    DatasetType.FINANCE_ASSUMPTIONS.value: {
        "brand_code": "Brand Cd",
        "scenario": "Scenario",
        "effective_from": "Effective From",
        "net_contribution_per_nrx": "Net Contribution Per NRx",
        "currency_code": "Ccy",
    },
    DatasetType.CANDIDATE_PROGRAMS.value: {
        "event_code": "Program Ref",
        "brand_code": "Brand Cd",
        "topic_code": "Topic",
        "event_format": "Format",
        "region_code": "Region",
        "speaker_tier": "Speaker Tier",
        "event_date": "Planned Dt",
        "planned_attendees": "Planned Attendees",
    },
}

#: Which gold frame feeds each dataset type.
_SOURCE_FRAME: dict[str, str] = {
    DatasetType.BRAND_PRODUCT_MASTER.value: "products",
    DatasetType.CAMPAIGN_EVENT_MASTER.value: "events",
    DatasetType.HCP_MASTER.value: "hcps",
    DatasetType.HCP_CROSSWALK.value: "hcp_crosswalk",
    DatasetType.INVITATIONS.value: "invitations",
    DatasetType.ATTENDANCE.value: "attendance",
    DatasetType.RX_MONTHLY.value: "rx_monthly",
    DatasetType.MARKETING_ACTIVITY.value: "marketing_activity",
    DatasetType.EVENT_COST.value: "event_costs",
    DatasetType.MARKET_FACTORS.value: "market_factors",
    DatasetType.FINANCE_ASSUMPTIONS.value: "finance_assumptions",
    DatasetType.CANDIDATE_PROGRAMS.value: "candidate_programs",
}

#: Which column carries the delivery date used to split files into quarters.
_QUARTER_COLUMN: dict[str, str] = {
    DatasetType.INVITATIONS.value: "invited_on",
    DatasetType.ATTENDANCE.value: "attended_on",
    DatasetType.RX_MONTHLY.value: "month",
    DatasetType.MARKETING_ACTIVITY.value: "month",
    DatasetType.EVENT_COST.value: "invoice_date",
    DatasetType.MARKET_FACTORS.value: "month",
}


def write_source_files(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    frames: dict[str, pd.DataFrame],
    out_dir: Path,
    generator: np.random.Generator,
) -> list[SourceFileRecord]:
    """Emit ``source/{tenant_code}/{DATASET_TYPE}/*`` for every tenant.

    Returns one record per file for the manifest, so a reviewer can see exactly
    what a tenant was sent without opening the tree.
    """
    params = profile.source_files
    lookups = _build_lookups(taxonomies, frames)
    records: list[SourceFileRecord] = []

    for spec in taxonomies.specs:
        for dataset_type, frame_name in _SOURCE_FRAME.items():
            gold = frames.get(frame_name)
            if gold is None or gold.empty:
                continue
            shaped = _shape(dataset_type, gold, spec.tenant_id, lookups, params)
            if shaped is None or shaped.empty:
                continue
            records.extend(
                _emit(dataset_type, shaped, spec.tenant_code, out_dir, params, generator)
            )
    return records


def _build_lookups(taxonomies: Taxonomies, frames: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    """id -> business-code maps, so files carry codes rather than UUIDs.

    A vendor has never heard of the platform's surrogate keys. Delivering them
    would make the join trivial and the resolution step untested.
    """
    crosswalk = frames["hcp_crosswalk"]
    # The delivery uses each system's own identifier. Where the crosswalk was
    # degraded to UNMATCHED the hcp_id is null, so those source ids simply have
    # no master - which is the state ingestion has to quarantine.
    rx_ids = crosswalk.loc[crosswalk["source_system"] == "RXVENDOR"]
    event_ids = crosswalk.loc[crosswalk["source_system"] == "EVENTVENDOR"]
    return {
        "brand_code": taxonomies.brands.set_index("brand_id")["brand_code"],
        "brand_name": taxonomies.brands.set_index("brand_id")["brand_name"],
        "therapeutic_area": taxonomies.brands.set_index("brand_id")["therapeutic_area"],
        "product_code": taxonomies.products.set_index("product_id")["product_code"],
        "brand_of_product": taxonomies.products.set_index("product_id")["brand_id"],
        "event_code": frames["events"].set_index("event_id")["event_code"],
        "brand_of_event": frames["events"].set_index("event_id")["brand_id"],
        "campaign_code": frames["campaigns"].set_index("campaign_id")["campaign_code"],
        "campaign_name": frames["campaigns"].set_index("campaign_id")["campaign_name"],
        "hcp_code": frames["hcps"].set_index("hcp_id")["hcp_code"],
        "national_id": frames["hcps"].set_index("hcp_id")["national_id"],
        "rx_source_id": _first_by_hcp(rx_ids),
        "event_source_id": _first_by_hcp(event_ids),
    }


def _first_by_hcp(crosswalk: pd.DataFrame) -> pd.Series:
    """hcp_id -> that system's source identifier, dropping unresolved rows."""
    resolved = crosswalk.loc[crosswalk["hcp_id"].notna()]
    return resolved.drop_duplicates(subset=["hcp_id"]).set_index("hcp_id")["source_hcp_id"]


def _shape(
    dataset_type: str,
    gold: pd.DataFrame,
    tenant_id: str,
    lookups: dict[str, pd.Series],
    params: SourceFileParams,
) -> pd.DataFrame | None:
    """Restrict to one tenant and add the vendor-side derived columns."""
    frame = gold.loc[gold["tenant_id"] == tenant_id].copy()
    if frame.empty:
        return None

    if dataset_type == DatasetType.CAMPAIGN_EVENT_MASTER.value:
        frame = frame.loc[frame["status"] != EventStatus.PROPOSED.value].copy()
        frame["campaign_code"] = frame["campaign_id"].map(lookups["campaign_code"])
        frame["campaign_name"] = frame["campaign_id"].map(lookups["campaign_name"])
        frame["brand_code"] = frame["brand_id"].map(lookups["brand_code"])
    elif dataset_type == DatasetType.CANDIDATE_PROGRAMS.value:
        # Already restricted to PROPOSED upstream, and deliberately carries no
        # ``status`` column: a candidate program that could be filtered on
        # status would let a forecaster learn from programs that later ran.
        frame["brand_code"] = frame["brand_id"].map(lookups["brand_code"])
    elif dataset_type == DatasetType.HCP_MASTER.value:
        frame["source_hcp_id"] = frame["hcp_id"].map(lookups["rx_source_id"])
    elif dataset_type == DatasetType.HCP_CROSSWALK.value:
        frame["hcp_code"] = frame["hcp_id"].map(lookups["hcp_code"])
        frame["national_id"] = frame["hcp_id"].map(lookups["national_id"])
    elif dataset_type == DatasetType.BRAND_PRODUCT_MASTER.value:
        frame["brand_code"] = frame["brand_id"].map(lookups["brand_code"])
        frame["brand_name"] = frame["brand_id"].map(lookups["brand_name"])
        frame["therapeutic_area"] = frame["brand_id"].map(lookups["therapeutic_area"])
    elif dataset_type == DatasetType.RX_MONTHLY.value:
        frame["product_code"] = frame["product_id"].map(lookups["product_code"])
        frame["source_hcp_id"] = frame["hcp_id"].map(lookups["rx_source_id"])
    elif dataset_type == DatasetType.MARKETING_ACTIVITY.value:
        frame["source_hcp_id"] = frame["hcp_id"].map(lookups["rx_source_id"])
    elif dataset_type in {DatasetType.INVITATIONS.value, DatasetType.ATTENDANCE.value}:
        frame["event_code"] = frame["event_id"].map(lookups["event_code"])
        frame["source_hcp_id"] = frame["hcp_id"].map(lookups["event_source_id"])
    elif dataset_type == DatasetType.EVENT_COST.value:
        frame["event_code"] = frame["event_id"].map(lookups["event_code"])
    elif dataset_type in {
        DatasetType.MARKET_FACTORS.value,
        DatasetType.FINANCE_ASSUMPTIONS.value,
    }:
        frame["brand_code"] = frame["brand_id"].map(lookups["brand_code"])
    return frame


def _emit(
    dataset_type: str,
    shaped: pd.DataFrame,
    tenant_code: str,
    out_dir: Path,
    params: SourceFileParams,
    generator: np.random.Generator,
) -> list[SourceFileRecord]:
    """Render and write one dataset type for one tenant, split by quarter."""
    mapping = _VENDOR_COLUMNS[dataset_type]
    available = {gold: header for gold, header in mapping.items() if gold in shaped.columns}
    rendered = _render(dataset_type, shaped, available, params)

    directory = out_dir / "source" / tenant_code / dataset_type
    directory.mkdir(parents=True, exist_ok=True)

    quarter_column = _QUARTER_COLUMN.get(dataset_type)
    partitions: list[tuple[str, pd.DataFrame]] = []
    if quarter_column is not None and quarter_column in shaped.columns:
        stamps = pd.to_datetime(shaped[quarter_column])
        labels = stamps.dt.year.astype(str) + "Q" + stamps.dt.quarter.astype(str)
        for label in sorted(labels.dropna().unique()):
            partitions.append((str(label), rendered.loc[(labels == label).to_numpy()]))
    else:
        partitions.append(("full", rendered))

    records: list[SourceFileRecord] = []
    for label, part in partitions:
        if part.empty:
            continue
        stem = f"{tenant_code.lower()}_{dataset_type.lower()}_{label}"
        records.append(_write_one(dataset_type, part, directory, stem, out_dir, params, generator))
    return records


def _write_one(
    dataset_type: str,
    part: pd.DataFrame,
    directory: Path,
    stem: str,
    out_dir: Path,
    params: SourceFileParams,
    generator: np.random.Generator,
) -> SourceFileRecord:
    """Write a single delivery file in whichever hostile shape it deserves."""
    if dataset_type == params.xlsx_dataset:
        path = directory / f"{stem}.xlsx"
        # openpyxl is the only writer guaranteed present; the sheet name is
        # deliberately not "Sheet1" so the reader cannot assume a default.
        part.to_excel(path, index=False, sheet_name="Attendance Export")
        encoding, file_format = "binary", "XLSX"
    else:
        path = directory / f"{stem}.csv"
        encoding = "utf-8-sig" if dataset_type == params.bom_dataset else "utf-8"
        part.to_csv(path, index=False, encoding=encoding, lineterminator="\r\n")
        file_format = "CSV"
    del generator  # deliberately unused: file shape is a function of the data
    return SourceFileRecord(
        tenant_code=directory.parent.name,
        dataset_type=dataset_type,
        relative_path=path.relative_to(out_dir).as_posix(),
        row_count=int(part.shape[0]),
        encoding=encoding,
        file_format=file_format,
    )


def _render(
    dataset_type: str,
    shaped: pd.DataFrame,
    available: dict[str, str],
    params: SourceFileParams,
) -> pd.DataFrame:
    """Gold columns -> vendor headers, with vendor-shaped value rendering."""
    date_format = params.date_formats.get(dataset_type)
    columns: dict[str, pd.Series] = {}
    for gold, header in available.items():
        values = shaped[gold]
        if pd.api.types.is_datetime64_any_dtype(values) and date_format:
            columns[header] = values.dt.strftime(date_format)
        elif pd.api.types.is_bool_dtype(values):
            # Vendors send Y/N, not True/False. Coercion has to handle it.
            columns[header] = np.where(values.to_numpy(), "Y", "N")
        elif gold == "amount" and dataset_type == params.thousands_separator_dataset:
            columns[header] = values.map(lambda v: f"{v:,.2f}")
        else:
            columns[header] = values
    return pd.DataFrame(columns, index=shaped.index)
