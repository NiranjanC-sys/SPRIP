"""Object storage: private buckets, derived keys, and content that has been looked at.

plan.md §15 asks for four things from this layer - private buckets with short-lived
authorized download URLs, rejection of macros and executables, neutralised CSV formula
injection, and no file contents in logs. Each is implemented here rather than in the upload
endpoint, because an endpoint is one of several call sites and this is one.

Four decisions worth stating, since each has a plausible-looking alternative:

**Object keys are derived, never supplied.** The key is
``{tenant_id}/{bucket_role}/{sha256}{ext}``, computed from the tenant in the request context
and the bytes themselves. A client-supplied key - even a "sanitised" one - puts the caller in
control of which prefix they write to, and prefix is the only thing separating tenants inside
a bucket. Path traversal in an object key is not a filesystem escape, but
``../other-tenant/file.xlsx`` is a perfectly valid S3 key, and it lands exactly where its
author intended.

**Content type comes from the bytes, not the request.** The browser-supplied ``Content-Type``
is a hint from the least trustworthy party, and the file extension is a hint from a user who
renamed something to get past a previous check. So :func:`sniff` reads the leading bytes, and
for the zip-container formats - every modern Office file is a zip - it looks *inside*, because
``.xlsx`` and ``.xlsm`` are byte-identical for the first four bytes and differ only in whether
the archive contains ``vbaProject.bin``.

**Formula neutralisation happens on export, not import.** A cell beginning ``=``, ``+``, ``-``,
``@`` or a control character is inert in our database and dangerous only when a recipient opens
our generated CSV in Excel, where it executes with their privileges. So the escaping belongs on
the way out. Doing it on the way in would corrupt legitimate data - a speaker note reading
"-40% vs Q3" is not an attack - while leaving the actual vulnerability open, because the
dangerous file is the one *we* write.

**Integrity is content-addressed.** The SHA-256 of the bytes is the key, so re-uploading the
same file is a no-op rather than a duplicate, a corrupted transfer cannot silently overwrite a
good object, and the ingestion audit trail can cite a digest that is verifiable later. It also
makes retry-after-timeout safe, which matters because a 200 MB upload over a hotel connection
times out reasonably often.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Final, Literal

from speaker_roi_core.config import Settings, StorageSettings, get_settings
from speaker_roi_core.context import current_tenant_id
from speaker_roi_core.errors import (
    DependencyUnavailableError,
    IngestionRejectedError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from speaker_roi_core.logging import get_logger

log = get_logger(__name__)

#: Which logical bucket an object belongs to. Not free-form: it becomes part of the key and
#: selects the bucket, and a typo in a string literal would silently create a new prefix that
#: no retention policy or lifecycle rule covers.
BucketRole = Literal["uploads", "exports", "artifacts"]

#: File shapes the ingestion pipeline can actually read. An allowlist rather than a denylist
#: of dangerous types: the set of formats we can parse is small, known and slow-changing,
#: while the set of formats that can carry executable content is neither.
ALLOWED_UPLOAD_TYPES: Final[frozenset[str]] = frozenset(
    {
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-excel",  # legacy .xls
    }
)

#: Extensions matching the above, used only to give the stored object a sensible suffix. The
#: extension is never trusted as evidence of type.
_EXTENSION_FOR_TYPE: Final[dict[str, str]] = {
    "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/json": ".json",
    "application/pdf": ".pdf",
    "application/octet-stream": "",
}

#: Leading-byte signatures. Ordered longest-first so a prefix cannot shadow a longer match.
_MAGIC: Final[tuple[tuple[bytes, str], ...]] = (
    (b"PK\x03\x04", "application/zip"),  # refined by _inspect_zip
    (b"PK\x05\x06", "application/zip"),  # empty archive
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/x-ole-storage"),  # refined below
    (b"%PDF-", "application/pdf"),
    (b"\x7fELF", "application/x-executable"),
    (b"MZ", "application/x-msdownload"),
    (b"\xca\xfe\xba\xbe", "application/x-executable"),  # Mach-O fat / Java class
    (b"\xfe\xed\xfa\xce", "application/x-executable"),
    (b"\xfe\xed\xfa\xcf", "application/x-executable"),
    (b"#!", "text/x-script"),
    (b"\x1f\x8b", "application/gzip"),
    (b"BZh", "application/x-bzip2"),
    (b"Rar!\x1a\x07", "application/x-rar-compressed"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
)

#: Entries whose presence in an Office archive means the file carries code. Checked by
#: substring against every archive member name, so a macro stored under an unexpected path
#: is still caught.
_MACRO_MEMBERS: Final[tuple[str, ...]] = (
    "vbaproject.bin",
    "vbaproject.bin.rels",
    "xlmacrosheet",
    "macrosheet",
    "vbadata.xml",
)

#: Members that make an archive an Office document at all. Their absence in something that
#: claims to be a spreadsheet means it is a zip file with a misleading name.
_OOXML_MARKERS: Final[tuple[str, ...]] = ("[content_types].xml", "_rels/.rels")

#: Characters that make Excel, LibreOffice and Google Sheets treat a cell as a formula.
#: ``\t`` and ``\r`` are included because they let a payload straddle a cell boundary.
_FORMULA_LEADERS: Final[str] = "=+-@\t\r"

#: A hard ceiling on how much of an archive we will expand while inspecting it. A zip bomb
#: is a few kilobytes on disk and a few terabytes decompressed, and the inspection below is
#: the first thing in the system to touch it.
_MAX_INSPECT_MEMBERS: Final = 2_000
_MAX_INSPECT_EXPANDED_BYTES: Final = 256 * 1024 * 1024

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Content inspection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Inspection:
    """What was actually found in the bytes, as opposed to what was claimed about them."""

    #: The type inferred from content. May disagree with the declared type, which is the
    #: interesting case.
    detected_type: str
    #: True when the payload carries executable content: a VBA project, a shell script, a
    #: PE/ELF/Mach-O image. Rejected regardless of type.
    carries_code: bool
    #: Human-readable reason, safe to return to the caller. Never contains file content.
    detail: str
    size_bytes: int
    sha256: str

    @property
    def is_allowed_upload(self) -> bool:
        return self.detected_type in ALLOWED_UPLOAD_TYPES and not self.carries_code


def sniff(
    payload: bytes, *, declared_type: str | None = None, filename: str | None = None
) -> Inspection:
    """Determine what a payload is from its bytes.

    ``declared_type`` and ``filename`` are accepted for one purpose only: distinguishing CSV
    from other plain text, where there is genuinely no signature to read and the alternative
    is rejecting every CSV. They never *widen* the result - a payload with an executable
    signature stays executable whatever it is called.
    """
    digest = hashlib.sha256(payload).hexdigest()
    size = len(payload)

    for signature, kind in _MAGIC:
        if payload.startswith(signature):
            if kind == "application/zip":
                return _inspect_zip(payload, digest=digest, size=size)
            if kind == "application/x-ole-storage":
                return _inspect_ole(payload, digest=digest, size=size)
            return Inspection(
                detected_type=kind,
                carries_code=kind
                in {"application/x-executable", "application/x-msdownload", "text/x-script"},
                detail=f"content identifies as {kind}",
                size_bytes=size,
                sha256=digest,
            )

    # No signature. Either text or something we do not recognise; decide by decoding, not by
    # the extension, because a renamed binary is precisely the case this must not wave
    # through.
    if _looks_like_text(payload):
        looks_csv = (filename or "").lower().endswith(".csv") or (declared_type == "text/csv")
        detected = "text/csv" if looks_csv else "text/plain"
        return Inspection(
            detected_type=detected,
            carries_code=False,
            detail="content decodes as text",
            size_bytes=size,
            sha256=digest,
        )

    return Inspection(
        detected_type="application/octet-stream",
        carries_code=False,
        detail="content matches no recognised format and is not decodable text",
        size_bytes=size,
        sha256=digest,
    )


def _looks_like_text(payload: bytes) -> bool:
    """Whether the payload is plausibly a text document.

    Two conditions, and the NUL check is the load-bearing one: UTF-16 text and most binary
    formats both decode partially under a permissive codec, but a NUL byte in the first
    kilobyte is essentially diagnostic of binary content and is what a renamed executable
    trips on.
    """
    head = payload[:8192]
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            # A truncated multi-byte sequence at the 8 kB boundary is not evidence of binary.
            head[: max(0, len(head) - 4)].decode("utf-8")
        except UnicodeDecodeError:
            return False
    return True


def _inspect_zip(payload: bytes, *, digest: str, size: int) -> Inspection:
    """Look inside a zip container to tell xlsx from xlsm from an arbitrary archive.

    The first four bytes of every OOXML file are the same, so a caller who renames
    ``budget.xlsm`` to ``budget.xlsx`` defeats any check that stops at the signature - and
    that rename is the whole attack, because the macro runs on open.

    Reading the *central directory* rather than extracting is what keeps this cheap: member
    names and declared sizes come from the index, so a zip bomb is rejected on its claimed
    expanded size without a byte of it being decompressed.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_INSPECT_MEMBERS:
                return Inspection(
                    detected_type="application/zip",
                    carries_code=False,
                    detail=(
                        f"archive contains {len(infos)} members, above the "
                        f"{_MAX_INSPECT_MEMBERS} inspected; refusing to inspect further"
                    ),
                    size_bytes=size,
                    sha256=digest,
                )
            expanded = sum(info.file_size for info in infos)
            names = [info.filename.lower() for info in infos]
    except zipfile.BadZipFile:
        return Inspection(
            detected_type="application/zip",
            carries_code=False,
            detail="content begins with a zip signature but the archive is not readable",
            size_bytes=size,
            sha256=digest,
        )

    if expanded > _MAX_INSPECT_EXPANDED_BYTES:
        ratio = expanded / max(size, 1)
        return Inspection(
            detected_type="application/zip",
            carries_code=False,
            detail=(
                f"archive expands to {expanded} bytes from {size} "
                f"({ratio:.0f}x), above the permitted limit"
            ),
            size_bytes=size,
            sha256=digest,
        )

    if any(marker in name for name in names for marker in _MACRO_MEMBERS):
        return Inspection(
            detected_type="application/vnd.ms-excel.sheet.macroEnabled.12",
            carries_code=True,
            detail="the workbook contains a macro project (vbaProject.bin or a macro sheet)",
            size_bytes=size,
            sha256=digest,
        )

    if not any(marker in name for name in names for marker in _OOXML_MARKERS):
        return Inspection(
            detected_type="application/zip",
            carries_code=False,
            detail="archive is not an Office document (no OOXML relationship parts)",
            size_bytes=size,
            sha256=digest,
        )

    if any("xl/workbook.xml" in name for name in names):
        detected = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif any("word/document.xml" in name for name in names):
        detected = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        detected = "application/zip"

    return Inspection(
        detected_type=detected,
        carries_code=False,
        detail=f"OOXML container identified as {detected}",
        size_bytes=size,
        sha256=digest,
    )


def _inspect_ole(payload: bytes, *, digest: str, size: int) -> Inspection:
    """Legacy OLE compound files: ``.xls``, and also ``.doc`` and macro-bearing variants.

    Parsing the OLE directory properly would need a dependency. Instead the raw bytes are
    searched for the UTF-16LE stream names a VBA project uses, which is what an OLE macro
    container necessarily contains regardless of how the directory is laid out. It over-flags
    rather than under-flags, and for an input format that exists only for backward
    compatibility that is the correct direction to be wrong in.
    """
    haystack = payload[: 4 * 1024 * 1024]
    for stream in ("VBA", "Macros", "_VBA_PROJECT"):
        if stream.encode("utf-16-le") in haystack:
            return Inspection(
                detected_type="application/vnd.ms-excel",
                carries_code=True,
                detail=f"legacy workbook contains an OLE {stream} stream",
                size_bytes=size,
                sha256=digest,
            )
    return Inspection(
        detected_type="application/vnd.ms-excel",
        carries_code=False,
        detail="legacy OLE workbook with no macro streams found",
        size_bytes=size,
        sha256=digest,
    )


def assert_upload_acceptable(
    payload: bytes,
    *,
    declared_type: str | None = None,
    filename: str | None = None,
    settings: Settings | None = None,
) -> Inspection:
    """Inspect a payload and raise the appropriate refusal if it must not be stored.

    Raises before anything is written, so a rejected upload leaves no object behind to be
    cleaned up - and no object that a later bug could serve.
    """
    cfg = (settings or get_settings()).storage
    inspection = sniff(payload, declared_type=declared_type, filename=filename)

    if inspection.size_bytes == 0:
        raise IngestionRejectedError(
            "The uploaded file is empty.",
            internal_detail="zero-byte payload",
        )
    if inspection.size_bytes > cfg.max_upload_bytes:
        raise PayloadTooLargeError(limit_bytes=cfg.max_upload_bytes)

    if inspection.carries_code:
        # Logged at warning: a macro-bearing workbook reaching the endpoint is worth seeing
        # in aggregate, because a spike is either a compromised vendor or a new template
        # someone is circulating internally.
        log.warning(
            "storage.upload_rejected_code",
            detected_type=inspection.detected_type,
            sha256=inspection.sha256,
            size_bytes=inspection.size_bytes,
        )
        raise IngestionRejectedError(
            "Files containing macros or executable content are not accepted. "
            "Save the workbook as .xlsx or export it as CSV and upload again.",
            internal_detail=f"{inspection.detail}; sha256={inspection.sha256}",
        )

    if inspection.detected_type not in ALLOWED_UPLOAD_TYPES:
        raise UnsupportedMediaTypeError(
            detected=inspection.detected_type,
            allowed=sorted(ALLOWED_UPLOAD_TYPES),
            internal_detail=f"{inspection.detail}; declared={declared_type!r}",
        )

    if declared_type and declared_type != inspection.detected_type:
        # Not a refusal on its own - browsers get this wrong routinely, and a .csv from
        # Windows Excel often arrives as application/vnd.ms-excel. Worth a log line, because
        # a *deliberate* mismatch is reconnaissance and looks identical to the innocent kind
        # until you count them.
        log.info(
            "storage.declared_type_mismatch",
            declared=declared_type,
            detected=inspection.detected_type,
            sha256=inspection.sha256,
        )

    return inspection


# ---------------------------------------------------------------------------
# CSV export hardening
# ---------------------------------------------------------------------------


def neutralise_csv_cell(value: object) -> str:
    """Make one cell safe to open in a spreadsheet application.

    A leading ``=``, ``+``, ``-``, ``@``, tab or carriage return makes Excel evaluate the
    cell, and ``=cmd|' /c calc'!A1`` in a downloaded report executes with the privileges of
    whoever opened it. The fix is a leading apostrophe, which every major spreadsheet reads
    as "the rest is literal text" and strips on display.

    Prefixing rather than stripping is deliberate: ``-40%`` and ``+12 pts`` are legitimate
    values a report should contain, and deleting the sign silently changes the number a
    reader acts on. That is a worse outcome than a stray apostrophe in the rare case a
    consumer reads the raw file.
    """
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_LEADERS:
        return "'" + text
    return text


def neutralise_csv_row(row: Iterable[object]) -> list[str]:
    return [neutralise_csv_cell(cell) for cell in row]


def neutralise_csv_rows(rows: Iterable[Iterable[object]]) -> Iterator[list[str]]:
    """Lazy, because an export is streamed - the whole point is not holding it in memory."""
    for row in rows:
        yield neutralise_csv_row(row)


# ---------------------------------------------------------------------------
# Object keys
# ---------------------------------------------------------------------------


def build_object_key(
    *,
    role: BucketRole,
    sha256: str,
    tenant_id: uuid.UUID | None = None,
    content_type: str | None = None,
    suffix: str | None = None,
) -> str:
    """Compose the key an object will be stored under.

    The tenant prefix is the isolation boundary inside a shared bucket, so it comes from the
    request context rather than a parameter unless one is passed explicitly - and the digest
    is validated, because it is the one component that arrives from a caller in the resume
    and re-upload paths.
    """
    if not _SHA256_RE.match(sha256):
        raise ValueError(f"sha256 must be 64 lowercase hex characters, got {len(sha256)} chars")
    tenant = tenant_id or current_tenant_id()
    extension = suffix if suffix is not None else _EXTENSION_FOR_TYPE.get(content_type or "", "")
    # Two hex characters of the digest as an intermediate prefix. S3 no longer needs it for
    # partition throughput, but it keeps a MinIO directory listing and a lifecycle audit
    # navigable once a tenant has a few hundred thousand objects.
    return f"{tenant}/{role}/{sha256[:2]}/{sha256}{extension}"


def tenant_owns_key(key: str, tenant_id: uuid.UUID | None = None) -> bool:
    """Whether a key sits under the tenant's prefix.

    Checked before any presign, and checked on a *parsed* boundary rather than with
    ``startswith``: without the trailing slash, tenant ``…7ab`` would match a key belonging
    to ``…7abc``. That is a narrow case and an entirely real one, because these are hex
    strings and prefix collisions are not rare among them.
    """
    tenant = tenant_id or current_tenant_id()
    return key.startswith(f"{tenant}/")


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


class ObjectStore:
    """A narrow, tenant-aware wrapper over an S3-compatible API.

    Narrow on purpose. It exposes put, get, presign, delete and exists, and nothing else -
    no bucket creation from application code, no ACL manipulation, no listing across
    prefixes. Every method that names an object goes through the ownership check, so
    "did this call verify the tenant" is answerable by reading this class rather than by
    auditing its callers.

    boto3 is synchronous, and its calls are run through :func:`asyncio.to_thread` rather
    than through an async S3 client. That trades a thread per in-flight object operation for
    one fewer dependency and for botocore's retry, checksum and signing behaviour, which is
    considerably better tested than any of the async reimplementations.
    """

    __slots__ = ("_client", "_settings")

    def __init__(self, settings: StorageSettings | None = None, *, client: Any = None) -> None:
        self._settings = settings or get_settings().storage
        self._client = client

    # -- wiring -----------------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> Any:
        import boto3
        from botocore.config import Config

        cfg = self._settings
        return boto3.client(
            "s3",
            endpoint_url=cfg.endpoint_url or None,
            aws_access_key_id=cfg.access_key.get_secret_value() or None,
            aws_secret_access_key=cfg.secret_key.get_secret_value() or None,
            region_name=cfg.region,
            config=Config(
                # Path style for MinIO, which does not do virtual-host addressing without
                # wildcard DNS - and wildcard DNS in a developer's compose stack is not
                # something to require.
                s3={"addressing_style": "path" if cfg.use_path_style else "auto"},
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    def bucket_for(self, role: BucketRole) -> str:
        cfg = self._settings
        return {
            "uploads": cfg.upload_bucket,
            "exports": cfg.export_bucket,
            "artifacts": cfg.artifact_bucket,
        }[role]

    # -- operations -------------------------------------------------------

    async def put(
        self,
        *,
        role: BucketRole,
        payload: bytes,
        content_type: str,
        sha256: str | None = None,
        tenant_id: uuid.UUID | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Store bytes and return the key. Idempotent for identical content.

        ``ChecksumSHA256`` is supplied so the server verifies the digest independently. Two
        parties computing the same hash over the same bytes is what makes the key
        content-addressed in fact rather than by convention: without it, a truncated upload
        stores short content under the full file's digest and every later integrity check
        passes.
        """
        digest = sha256 or hashlib.sha256(payload).hexdigest()
        key = build_object_key(
            role=role, sha256=digest, tenant_id=tenant_id, content_type=content_type
        )
        import base64

        extra = {
            "Bucket": self.bucket_for(role),
            "Key": key,
            "Body": payload,
            "ContentType": content_type,
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(digest)).decode(),
            "ServerSideEncryption": "AES256",
            "Metadata": {
                # Metadata is small, non-sensitive and travels with the object, which makes
                # it the right place for the facts a later forensic question needs.
                "sha256": digest,
                "tenant-id": str(tenant_id or current_tenant_id()),
                **(metadata or {}),
            },
        }
        try:
            await asyncio.to_thread(lambda: self.client.put_object(**extra))
        except Exception as exc:
            raise self._translate(exc, operation="put", key=key) from exc

        log.info(
            "storage.put",
            role=role,
            key=key,
            size_bytes=len(payload),
            content_type=content_type,
            sha256=digest,
        )
        return key

    async def get(self, *, role: BucketRole, key: str, tenant_id: uuid.UUID | None = None) -> bytes:
        """Fetch an object's bytes, refusing keys outside the tenant's prefix.

        The refusal is a 404 rather than a 403, because confirming that a key exists in
        another tenant is itself a disclosure - and the digest is in the key, so a caller who
        learned one would be learning that a specific file was uploaded by a specific
        competitor.
        """
        self._assert_owned(key, tenant_id, role=role)
        try:
            response = await asyncio.to_thread(
                lambda: self.client.get_object(Bucket=self.bucket_for(role), Key=key)
            )
            return await asyncio.to_thread(response["Body"].read)
        except Exception as exc:
            raise self._translate(exc, operation="get", key=key) from exc

    async def exists(
        self, *, role: BucketRole, key: str, tenant_id: uuid.UUID | None = None
    ) -> bool:
        """Whether the object is present. Used to make re-upload a no-op."""
        self._assert_owned(key, tenant_id, role=role)
        try:
            await asyncio.to_thread(
                lambda: self.client.head_object(Bucket=self.bucket_for(role), Key=key)
            )
            return True
        except Exception as exc:
            translated = self._translate(exc, operation="head", key=key)
            if isinstance(translated, NotFoundError):
                return False
            raise translated from exc

    async def presign_download(
        self,
        *,
        role: BucketRole,
        key: str,
        filename: str,
        tenant_id: uuid.UUID | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """A short-lived URL granting exactly one object.

        plan.md §15 wants private buckets and short-lived authorized download URLs, and the
        authorization is the point: the check happens *here*, before the URL is minted,
        because once minted the URL is a bearer credential that S3 will honour from anywhere
        with no further reference to our session.

        ``ResponseContentDisposition`` forces a download with a chosen filename rather than
        inline rendering. Without it a stored HTML file - which our allowlist rejects, but
        the artifacts bucket also holds machine-generated content - would render in the
        browser under the storage origin, which is a stored-XSS primitive.
        """
        self._assert_owned(key, tenant_id, role=role)
        ttl = ttl_seconds or self._settings.presign_ttl_seconds
        safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)[:120] or "download"
        try:
            url = await asyncio.to_thread(
                lambda: self.client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": self.bucket_for(role),
                        "Key": key,
                        "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
                    },
                    ExpiresIn=ttl,
                )
            )
        except Exception as exc:
            raise self._translate(exc, operation="presign", key=key) from exc

        # The URL contains a signature; it is a credential and is never logged. The key is,
        # because it is the thing an audit question is asked about.
        log.info("storage.presigned", role=role, key=key, ttl_seconds=ttl)
        return url

    async def delete(
        self, *, role: BucketRole, key: str, tenant_id: uuid.UUID | None = None
    ) -> None:
        self._assert_owned(key, tenant_id, role=role)
        try:
            await asyncio.to_thread(
                lambda: self.client.delete_object(Bucket=self.bucket_for(role), Key=key)
            )
        except Exception as exc:
            raise self._translate(exc, operation="delete", key=key) from exc
        log.info("storage.deleted", role=role, key=key)

    async def health(self) -> tuple[bool, str]:
        """Whether the store is reachable and the buckets exist. For ``/health/ready``."""
        try:
            for role in ("uploads", "exports", "artifacts"):
                bucket = self.bucket_for(role)  # type: ignore[arg-type]
                await asyncio.to_thread(lambda b=bucket: self.client.head_bucket(Bucket=b))
        except Exception as exc:
            return False, type(exc).__name__
        return True, "ok"

    # -- internals --------------------------------------------------------

    def _assert_owned(self, key: str, tenant_id: uuid.UUID | None, *, role: BucketRole) -> None:
        if tenant_owns_key(key, tenant_id):
            return
        # Deliberately identical to a genuine miss from the caller's point of view. The log
        # line is where the difference lives, and this one is a warning rather than info:
        # a key from another tenant's prefix does not arrive by accident.
        log.warning(
            "storage.cross_tenant_key_refused",
            role=role,
            key_prefix=key.split("/", 1)[0],
            tenant_id=str(tenant_id or ""),
        )
        raise NotFoundError(
            "file",
            internal_detail=f"key {key!r} is outside the caller's tenant prefix",
        )

    def _translate(self, exc: Exception, *, operation: str, key: str) -> Exception:
        """Map a botocore error onto the application taxonomy.

        Only the codes with an unambiguous meaning. Anything else is wrapped as a dependency
        failure rather than guessed at, so an unfamiliar S3 error surfaces as "storage is
        unhealthy" - which is actionable - instead of as a 404, which would send someone
        looking for a missing row.
        """
        code = ""
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            code = str(response.get("Error", {}).get("Code", ""))
        status = 0
        if isinstance(response, dict):
            status = int(response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)

        if code in {"NoSuchKey", "404", "NotFound"} or status == 404:
            return NotFoundError("file", internal_detail=f"{operation} missing key {key!r}")
        if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
            log.error("storage.access_denied", operation=operation, code=code)
            return DependencyUnavailableError(
                "object storage",
                internal_detail=(
                    f"credentials rejected on {operation} ({code}); the service account's "
                    "keys are wrong or its policy does not grant this bucket"
                ),
            )
        if code in {"BadDigest", "InvalidDigest", "XAmzContentSHA256Mismatch"}:
            return IngestionRejectedError(
                "The upload was corrupted in transit. Please try again.",
                internal_detail=f"checksum mismatch on {operation} of {key!r}",
            )
        log.error("storage.unexpected_error", operation=operation, code=code or type(exc).__name__)
        return DependencyUnavailableError(
            "object storage",
            internal_detail=f"{type(exc).__name__} on {operation}: {code or 'no error code'}",
        )


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    """The process-wide store. Cached, because building a boto3 client is not free."""
    global _store
    if _store is None:
        _store = ObjectStore()
    return _store


def set_object_store_for_tests(store: ObjectStore | None) -> None:
    global _store
    _store = store


__all__ = [
    "ALLOWED_UPLOAD_TYPES",
    "BucketRole",
    "Inspection",
    "ObjectStore",
    "assert_upload_acceptable",
    "build_object_key",
    "get_object_store",
    "neutralise_csv_cell",
    "neutralise_csv_row",
    "neutralise_csv_rows",
    "set_object_store_for_tests",
    "sniff",
    "tenant_owns_key",
]
