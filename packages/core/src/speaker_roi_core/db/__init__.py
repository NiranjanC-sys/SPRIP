"""Declarative base, shared column types and the tenant-isolation primitives.

The runtime pieces - engine, sessionmaker, tenant binding - are re-exported here so that
service code imports from one place. :mod:`speaker_roi_core.db.ddl` is deliberately *not*
re-exported: it generates DDL and is imported by migrations and by the security tests, and
keeping it off this surface means a service module cannot accidentally reach for a policy
builder when it wanted a session.
"""

from __future__ import annotations

from speaker_roi_core.db.base import (
    NAMING_CONVENTION,
    SCHEMAS,
    ActorMixin,
    Base,
    CurrencyCode,
    EffectiveDatedMixin,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    effective_range_check,
    metadata_obj,
    tenant_code_unique,
    tenant_lookup_index,
    uuid_pk,
)
from speaker_roi_core.db.session import (
    HealthState,
    assert_rls_enforced,
    bind_platform_scope,
    bind_tenant,
    build_engine,
    check_connectivity,
    current_bound_tenant,
    dispose_engine,
    get_engine,
    get_read_only_session,
    get_session,
    get_sessionmaker,
    health,
    platform_session_scope,
    probe_rls,
    session_scope,
    set_engine_for_tests,
)
from speaker_roi_core.db.types import (
    ENUM_SCHEMA,
    JSONB,
    Currency,
    Fraction,
    Measure,
    Money,
    Quantity,
    Sha256,
    pg_enum,
)

__all__ = [
    "ENUM_SCHEMA",
    "JSONB",
    "NAMING_CONVENTION",
    "SCHEMAS",
    "ActorMixin",
    "Base",
    "Currency",
    "CurrencyCode",
    "EffectiveDatedMixin",
    "Fraction",
    "HealthState",
    "Measure",
    "Money",
    "Quantity",
    "Sha256",
    "TenantMixin",
    "TimestampMixin",
    "VersionMixin",
    "assert_rls_enforced",
    "bind_platform_scope",
    "bind_tenant",
    "build_engine",
    "check_connectivity",
    "current_bound_tenant",
    "dispose_engine",
    "effective_range_check",
    "get_engine",
    "get_read_only_session",
    "get_session",
    "get_sessionmaker",
    "health",
    "metadata_obj",
    "pg_enum",
    "platform_session_scope",
    "probe_rls",
    "session_scope",
    "set_engine_for_tests",
    "tenant_code_unique",
    "tenant_lookup_index",
    "uuid_pk",
]
