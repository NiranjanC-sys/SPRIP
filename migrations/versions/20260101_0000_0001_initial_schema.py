"""Initial schema.

Creates the six schemas, the native enum types, all tables and indexes, the range
partitions, and the row-level-security policies and grants that make the
application role tenant-scoped.

This revision is generated from ``Base.metadata`` by
``scripts/devtools/gen_initial_migration.py`` and then frozen. Do not "refresh"
it - later schema changes belong in later revisions, or a database built from
scratch will silently disagree with one built incrementally.

Revision ID: 0001_initial_schema
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_SQL: tuple[str, ...] = (
    # --- Schemas --------------------------------------------------------
    "CREATE SCHEMA IF NOT EXISTS auth;",
    "CREATE SCHEMA IF NOT EXISTS core;",
    "CREATE SCHEMA IF NOT EXISTS ingestion;",
    "CREATE SCHEMA IF NOT EXISTS analytics;",
    "CREATE SCHEMA IF NOT EXISTS ml;",
    "CREATE SCHEMA IF NOT EXISTS audit;",
    # --- Extensions (all trusted; no superuser required) ----------------
    "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
    "CREATE EXTENSION IF NOT EXISTS btree_gist;",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
    # --- Roles ----------------------------------------------------------
    """\
DO $$ BEGIN
    IF to_regrole('app_migrator') IS NULL THEN
        EXECUTE 'CREATE ROLE app_migrator NOLOGIN';
    END IF;
END $$;
    """,
    """\
DO $$ BEGIN
    IF to_regrole('app_rw') IS NULL THEN
        EXECUTE 'CREATE ROLE app_rw NOLOGIN';
    END IF;
END $$;
    """,
    """\
DO $$ BEGIN
    IF to_regrole('app_ro') IS NULL THEN
        EXECUTE 'CREATE ROLE app_ro NOLOGIN';
    END IF;
END $$;
    """,
    # --- Controlled vocabularies as native enum types -------------------
    """\
CREATE TYPE core.tenant_status AS ENUM (
    'PENDING_ONBOARDING',
    'ACTIVE',
    'SUSPENDED',
    'ARCHIVED'
);
    """,
    """\
CREATE TYPE core.role AS ENUM (
    'PLATFORM_ADMIN',
    'PHARMA_ADMIN',
    'VENDOR_CONTRIBUTOR',
    'DATA_STEWARD',
    'ANALYTICS_LEAD',
    'FINANCE_REVIEWER',
    'COMPLIANCE_REVIEWER',
    'BRAND_MANAGER',
    'EXECUTIVE_VIEWER'
);
    """,
    """\
CREATE TYPE core.membership_status AS ENUM (
    'ACTIVE',
    'SUSPENDED',
    'EXPIRED'
);
    """,
    """\
CREATE TYPE core.user_status AS ENUM (
    'INVITED',
    'ACTIVE',
    'DISABLED',
    'LOCKED'
);
    """,
    """\
CREATE TYPE core.invitation_status AS ENUM (
    'PENDING',
    'ACCEPTED',
    'EXPIRED',
    'REVOKED'
);
    """,
    """\
CREATE TYPE core.auth_provider_kind AS ENUM (
    'LOCAL',
    'OIDC'
);
    """,
    """\
CREATE TYPE core.vendor_status AS ENUM (
    'ACTIVE',
    'SUSPENDED',
    'TERMINATED'
);
    """,
    """\
CREATE TYPE core.dataset_access AS ENUM (
    'WRITE',
    'READ',
    'READ_WRITE'
);
    """,
    """\
CREATE TYPE core.event_status AS ENUM (
    'PROPOSED',
    'SCHEDULED',
    'COMPLETED',
    'CANCELLED'
);
    """,
    """\
CREATE TYPE core.event_format AS ENUM (
    'IN_PERSON',
    'VIRTUAL',
    'HYBRID',
    'ROUNDTABLE',
    'ON_DEMAND'
);
    """,
    """\
CREATE TYPE core.campaign_status AS ENUM (
    'DRAFT',
    'ACTIVE',
    'COMPLETED',
    'CANCELLED'
);
    """,
    """\
CREATE TYPE core.taxonomy_kind AS ENUM (
    'REGION',
    'TOPIC',
    'SPECIALTY',
    'PRACTICE_TYPE',
    'HCP_SEGMENT',
    'COST_CATEGORY',
    'MARKETING_CHANNEL',
    'THERAPEUTIC_AREA'
);
    """,
    """\
CREATE TYPE core.invitation_channel AS ENUM (
    'EMAIL',
    'REP',
    'PORTAL',
    'PHONE',
    'OTHER'
);
    """,
    """\
CREATE TYPE core.attendance_status AS ENUM (
    'NOT_REGISTERED',
    'REGISTERED',
    'WAITLISTED',
    'CANCELLED',
    'NO_SHOW',
    'ATTENDED'
);
    """,
    """\
CREATE TYPE core.attendance_verification_source AS ENUM (
    'BADGE_SCAN',
    'SIGN_IN_SHEET',
    'WEBINAR_PLATFORM_LOG',
    'VENDOR_ATTESTATION',
    'UNVERIFIED'
);
    """,
    """\
CREATE TYPE core.identity_match_status AS ENUM (
    'MATCHED',
    'MANUALLY_MATCHED',
    'AMBIGUOUS',
    'UNMATCHED',
    'REJECTED'
);
    """,
    """\
CREATE TYPE core.match_method AS ENUM (
    'EXACT_SOURCE_ID',
    'DETERMINISTIC_RULE',
    'PROBABILISTIC',
    'STEWARD_DECISION'
);
    """,
    """\
CREATE TYPE core.approval_status AS ENUM (
    'DRAFT',
    'SUBMITTED',
    'APPROVED',
    'REJECTED'
);
    """,
    """\
CREATE TYPE core.finance_scenario AS ENUM (
    'CONSERVATIVE',
    'BASE',
    'OPTIMISTIC'
);
    """,
    """\
CREATE TYPE core.dataset_type AS ENUM (
    'BRAND_PRODUCT_MASTER',
    'CAMPAIGN_EVENT_MASTER',
    'HCP_MASTER',
    'HCP_CROSSWALK',
    'INVITATIONS',
    'ATTENDANCE',
    'RX_MONTHLY',
    'MARKETING_ACTIVITY',
    'EVENT_COST',
    'MARKET_FACTORS',
    'FINANCE_ASSUMPTIONS',
    'CANDIDATE_PROGRAMS'
);
    """,
    """\
CREATE TYPE core.upload_status AS ENUM (
    'CREATED',
    'UPLOADED',
    'SCANNING',
    'VALIDATING',
    'CONFORMING',
    'ACCEPTED',
    'PARTIALLY_ACCEPTED',
    'REJECTED',
    'QUARANTINED',
    'ABANDONED',
    'FAILED'
);
    """,
    """\
CREATE TYPE core.issue_severity AS ENUM (
    'ERROR',
    'QUARANTINE',
    'WARNING',
    'INFO'
);
    """,
    """\
CREATE TYPE core.data_version_status AS ENUM (
    'DRAFT',
    'PUBLISHED',
    'SUPERSEDED'
);
    """,
    """\
CREATE TYPE core.file_format AS ENUM (
    'CSV',
    'XLSX',
    'JSONL'
);
    """,
    """\
CREATE TYPE core.event_workflow_status AS ENUM (
    'DRAFT',
    'DATA_PENDING',
    'VALIDATING',
    'DATA_ISSUES',
    'READY_FOR_ANALYSIS',
    'ANALYSIS_RUNNING',
    'ANALYSIS_COMPLETE',
    'UNDER_REVIEW',
    'APPROVED',
    'PUBLISHED'
);
    """,
    """\
CREATE TYPE core.publication_state AS ENUM (
    'DRAFT',
    'UNDER_REVIEW',
    'APPROVED',
    'PUBLISHED',
    'SUPERSEDED'
);
    """,
    """\
CREATE TYPE core.review_decision AS ENUM (
    'APPROVED',
    'REJECTED',
    'CHANGES_REQUESTED'
);
    """,
    """\
CREATE TYPE core.review_gate AS ENUM (
    'ANALYTICS',
    'FINANCE',
    'COMPLIANCE'
);
    """,
    """\
CREATE TYPE core.outcome_metric AS ENUM (
    'NRX',
    'TRX'
);
    """,
    """\
CREATE TYPE core.analysis_grain AS ENUM (
    'HCP',
    'ACCOUNT',
    'TERRITORY'
);
    """,
    """\
CREATE TYPE core.aggregation_level AS ENUM (
    'EVENT',
    'CAMPAIGN',
    'BRAND',
    'TOPIC',
    'REGION',
    'FORMAT',
    'PORTFOLIO'
);
    """,
    """\
CREATE TYPE core.control_strategy AS ENUM (
    'INVITED_NON_ATTENDEE',
    'TARGET_UNIVERSE',
    'SYNTHETIC_CONTROL_POOL'
);
    """,
    """\
CREATE TYPE core.estimator_kind AS ENUM (
    'COHORT_TIME_ATT',
    'TWFE_DID'
);
    """,
    """\
CREATE TYPE core.exclusion_reason AS ENUM (
    'NOT_INVITED',
    'INELIGIBLE_SPECIALTY',
    'IDENTITY_UNRESOLVED',
    'IDENTITY_AMBIGUOUS',
    'INSUFFICIENT_PRE_HISTORY',
    'INSUFFICIENT_POST_COVERAGE',
    'OUTCOME_SUPPRESSED',
    'EVENT_CANCELLED',
    'OVERLAPPING_EXPOSURE',
    'NOT_FIRST_ELIGIBLE_EVENT',
    'UNVERIFIED_ATTENDANCE',
    'UNSUPPORTED_MARKET_PERIOD',
    'OUTSIDE_COMMON_SUPPORT',
    'NO_MATCH_WITHIN_CALIPER'
);
    """,
    """\
CREATE TYPE core.cohort_arm AS ENUM (
    'TREATMENT',
    'CONTROL',
    'EXCLUDED'
);
    """,
    """\
CREATE TYPE core.evidence_status AS ENUM (
    'ESTIMATED',
    'NOT_RELIABLY_ESTIMABLE'
);
    """,
    """\
CREATE TYPE core.evidence_grade AS ENUM (
    'STRONG',
    'MODERATE',
    'DIRECTIONAL',
    'NOT_ESTIMABLE'
);
    """,
    """\
CREATE TYPE core.evidence_gate AS ENUM (
    'MIN_TREATED_SAMPLE',
    'MIN_CONTROL_SAMPLE',
    'OUTCOME_COVERAGE',
    'COVARIATE_BALANCE',
    'PROPENSITY_OVERLAP',
    'MATCHED_RETENTION',
    'PARALLEL_PRE_TREND',
    'PLACEBO_NULL',
    'SENSITIVITY_STABILITY',
    'CONTAMINATION'
);
    """,
    """\
CREATE TYPE core.sensitivity_test AS ENUM (
    'PLACEBO_PRE_PERIOD',
    'ALTERNATE_CALIPER',
    'ALTERNATE_CONTROL_RATIO',
    'ALTERNATE_POST_WINDOW',
    'ALTERNATE_CONTROL_DEFINITION',
    'TWFE_CROSSCHECK',
    'LEAVE_ONE_MONTH_OUT',
    'UNMEASURED_CONFOUNDER_BOUND'
);
    """,
    """\
CREATE TYPE core.model_kind AS ENUM (
    'PROPENSITY',
    'FUTURE_IMPACT',
    'ATTENDANCE_FORECAST'
);
    """,
    """\
CREATE TYPE core.model_lifecycle_state AS ENUM (
    'DRAFT',
    'TRAINING',
    'VALIDATING',
    'CHALLENGER',
    'PENDING_APPROVAL',
    'ACTIVE',
    'REJECTED',
    'RETIRED'
);
    """,
    """\
CREATE TYPE core.run_status AS ENUM (
    'QUEUED',
    'RUNNING',
    'SUCCEEDED',
    'FAILED',
    'CANCELLED',
    'DEAD_LETTER'
);
    """,
    """\
CREATE TYPE core.run_kind AS ENUM (
    'FILE_VALIDATION',
    'CONFORMANCE',
    'DATA_VERSION_PUBLISH',
    'COHORT_BUILD',
    'PROPENSITY_TRAIN',
    'PROPENSITY_SCORE',
    'MATCHING',
    'CAUSAL_ESTIMATE',
    'SENSITIVITY_SUITE',
    'ROI_CALCULATION',
    'FORECAST_TRAIN',
    'FORECAST_SCORE',
    'BUDGET_OPTIMIZE',
    'AI_SUMMARY_PRECOMPUTE',
    'SYNTHETIC_GENERATE'
);
    """,
    """\
CREATE TYPE core.failure_category AS ENUM (
    'INPUT_DATA',
    'INSUFFICIENT_EVIDENCE',
    'DEPENDENCY_UNAVAILABLE',
    'TIMEOUT',
    'CONFIGURATION',
    'INTERNAL'
);
    """,
    """\
CREATE TYPE core.forecast_mode AS ENUM (
    'MODEL',
    'POOLED',
    'OUT_OF_SUPPORT'
);
    """,
    """\
CREATE TYPE core.scenario_status AS ENUM (
    'DRAFT',
    'SAVED',
    'ARCHIVED'
);
    """,
    """\
CREATE TYPE core.optimizer_status AS ENUM (
    'OPTIMAL',
    'FEASIBLE_SUBOPTIMAL',
    'INFEASIBLE',
    'UNBOUNDED',
    'TIME_LIMIT',
    'FAILED'
);
    """,
    """\
CREATE TYPE core.constraint_kind AS ENUM (
    'TOTAL_BUDGET',
    'REGION_MIN',
    'REGION_MAX',
    'TOPIC_MIN',
    'TOPIC_MAX',
    'FORMAT_MIN',
    'FORMAT_MAX',
    'BRAND_MIN',
    'BRAND_MAX',
    'MAX_PROGRAMS',
    'OPERATIONAL_CAPACITY',
    'MAX_CONCENTRATION',
    'EXPLORATION_BUDGET'
);
    """,
    """\
CREATE TYPE core.ai_intent AS ENUM (
    'EXPLAIN_EVENT_EVIDENCE',
    'COMPARE_EVENT_CATEGORIES',
    'SUMMARIZE_STRONG_EVIDENCE',
    'EXPLAIN_DATA_HEALTH_WARNING',
    'NARRATE_BUDGET_TRADEOFFS',
    'EXPLAIN_PORTFOLIO_SUMMARY',
    'EXPLAIN_SIMULATION'
);
    """,
    """\
CREATE TYPE core.ai_refusal_reason AS ENUM (
    'OUT_OF_SCOPE',
    'HCP_TARGETING',
    'PATIENT_LEVEL_REQUEST',
    'CROSS_TENANT_REQUEST',
    'NO_AUTHORIZED_EVIDENCE',
    'PROMPT_INJECTION_SUSPECTED',
    'RATE_LIMITED'
);
    """,
    """\
CREATE TYPE core.ai_answer_mode AS ENUM (
    'LLM',
    'DETERMINISTIC_FALLBACK',
    'REFUSED'
);
    """,
    """\
CREATE TYPE core.audit_action AS ENUM (
    'LOGIN_SUCCEEDED',
    'LOGIN_FAILED',
    'LOGOUT',
    'SESSION_EXPIRED',
    'REAUTH_REQUIRED',
    'PERMISSION_DENIED',
    'TENANT_CREATED',
    'TENANT_STATUS_CHANGED',
    'TENANT_CONFIG_CHANGED',
    'USER_INVITED',
    'INVITATION_ACCEPTED',
    'INVITATION_REVOKED',
    'MEMBERSHIP_CHANGED',
    'VENDOR_GRANT_GRANTED',
    'VENDOR_GRANT_REVOKED',
    'RECORD_CREATED',
    'RECORD_UPDATED',
    'RECORD_DEACTIVATED',
    'UPLOAD_CREATED',
    'UPLOAD_COMPLETED',
    'UPLOAD_REJECTED',
    'MAPPING_DECIDED',
    'DATA_VERSION_PUBLISHED',
    'ANALYSIS_RUN_STARTED',
    'ANALYSIS_RUN_COMPLETED',
    'RESULT_SUBMITTED_FOR_REVIEW',
    'REVIEW_DECISION_RECORDED',
    'RESULT_PUBLISHED',
    'MODEL_SUBMITTED',
    'MODEL_ACTIVATED',
    'MODEL_ROLLED_BACK',
    'FINANCE_ASSUMPTION_APPROVED',
    'SCENARIO_SAVED',
    'EXPORT_GENERATED',
    'OBJECT_DOWNLOAD_AUTHORIZED',
    'AI_QUERY_ANSWERED',
    'AI_QUERY_REFUSED',
    'RETENTION_DELETION_EXECUTED'
);
    """,
    """\
CREATE TYPE core.audit_outcome AS ENUM (
    'SUCCESS',
    'FAILURE',
    'DENIED'
);
    """,
    # --- Tables ---------------------------------------------------------
    """\
CREATE TABLE audit.audit_events (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id UUID,
	action core.audit_action NOT NULL,
	outcome core.audit_outcome DEFAULT 'SUCCESS' NOT NULL,
	actor_user_id UUID,
	actor_label VARCHAR(200),
	actor_role VARCHAR(40),
	impersonated_by_user_id UUID,
	actor_kind VARCHAR(20),
	resource_type VARCHAR(60),
	resource_id UUID,
	resource_label VARCHAR(300),
	before_state JSONB,
	after_state JSONB,
	changed_fields JSONB,
	reason VARCHAR(200),
	correlation_id VARCHAR(64),
	request_id VARCHAR(64),
	session_id UUID,
	ip_hash VARCHAR(64),
	user_agent_hash VARCHAR(64),
	http_method VARCHAR(10),
	route VARCHAR(200),
	status_code INTEGER,
	duration_ms INTEGER,
	CONSTRAINT pk_audit_events PRIMARY KEY (id, created_at),
	CONSTRAINT ck_audit_events_denied_event_states_reason CHECK (outcome <> 'DENIED' OR reason IS NOT NULL)
)
 PARTITION BY RANGE (created_at);
    """,
    """\
CREATE TABLE audit.erasure_requests (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID,
	request_kind VARCHAR(40) DEFAULT 'ERASURE' NOT NULL,
	subject_kind VARCHAR(20) NOT NULL,
	subject_user_id UUID,
	subject_hcp_id UUID,
	subject_reference_hash VARCHAR(64),
	status VARCHAR(30) DEFAULT 'RECEIVED' NOT NULL,
	received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	due_by DATE,
	completed_at TIMESTAMP WITH TIME ZONE,
	requested_by UUID,
	handled_by UUID,
	approved_by UUID,
	actions_taken JSONB,
	identifiers_shredded INTEGER,
	rows_tombstoned INTEGER,
	retained_categories JSONB,
	legal_basis TEXT,
	rejection_reason TEXT,
	note TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_erasure_requests PRIMARY KEY (id),
	CONSTRAINT ck_erasure_requests_completed_request_has_timestamp CHECK (status <> 'COMPLETED' OR completed_at IS NOT NULL),
	CONSTRAINT ck_erasure_requests_rejected_request_states_reason CHECK (status <> 'REJECTED' OR rejection_reason IS NOT NULL)
);
    """,
    """\
CREATE TABLE audit.export_log (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID,
	user_id UUID,
	export_kind VARCHAR(40) NOT NULL,
	source VARCHAR(120),
	filters JSONB,
	source_run_ids JSONB,
	object_key VARCHAR(500),
	checksum_sha256 VARCHAR(64),
	row_count INTEGER,
	byte_size INTEGER,
	url_issued BOOLEAN DEFAULT false NOT NULL,
	url_expires_at TIMESTAMP WITH TIME ZONE,
	downloaded_at TIMESTAMP WITH TIME ZONE,
	ip_hash VARCHAR(64),
	denied_reason VARCHAR(200),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_export_log PRIMARY KEY (id),
	CONSTRAINT ck_export_log_row_count_non_negative CHECK (row_count IS NULL OR row_count >= 0)
);
    """,
    """\
CREATE TABLE audit.retention_policy_runs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID,
	policy VARCHAR(40) NOT NULL,
	retention_days INTEGER,
	cutoff_date DATE,
	objects_examined INTEGER DEFAULT 0 NOT NULL,
	objects_deleted INTEGER DEFAULT 0 NOT NULL,
	objects_skipped_legal_hold INTEGER DEFAULT 0 NOT NULL,
	partitions_dropped JSONB,
	executed BOOLEAN DEFAULT true NOT NULL,
	error TEXT,
	duration_ms INTEGER,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_retention_policy_runs PRIMARY KEY (id)
);
    """,
    """\
CREATE TABLE auth.login_attempts (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	identifier_hash VARCHAR(64) NOT NULL,
	user_id UUID,
	tenant_id UUID,
	succeeded BOOLEAN NOT NULL,
	failure_reason VARCHAR(40),
	ip_hash VARCHAR(64),
	user_agent_hash VARCHAR(64),
	correlation_id VARCHAR(64),
	attempted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_login_attempts PRIMARY KEY (id)
);
    """,
    """\
CREATE TABLE auth.users (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	email VARCHAR(320) NOT NULL,
	display_name VARCHAR(200) NOT NULL,
	status core.user_status DEFAULT 'INVITED' NOT NULL,
	auth_provider_kind core.auth_provider_kind DEFAULT 'LOCAL' NOT NULL,
	password_hash VARCHAR(255),
	password_updated_at TIMESTAMP WITH TIME ZONE,
	must_change_password BOOLEAN DEFAULT false NOT NULL,
	mfa_secret_encrypted BYTEA,
	mfa_pending_secret_encrypted BYTEA,
	mfa_enrolled_at TIMESTAMP WITH TIME ZONE,
	mfa_required BOOLEAN DEFAULT false NOT NULL,
	mfa_recovery_codes JSONB,
	external_subject VARCHAR(255),
	external_issuer VARCHAR(500),
	failed_login_count INTEGER DEFAULT 0 NOT NULL,
	locked_until TIMESTAMP WITH TIME ZONE,
	last_login_at TIMESTAMP WITH TIME ZONE,
	last_password_login_at TIMESTAMP WITH TIME ZONE,
	is_platform_admin BOOLEAN DEFAULT false NOT NULL,
	tombstoned_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_users PRIMARY KEY (id),
	CONSTRAINT ck_users_local_user_has_credential CHECK (auth_provider_kind <> 'LOCAL' OR password_hash IS NOT NULL OR status IN ('INVITED', 'DISABLED')),
	CONSTRAINT ck_users_failed_login_count_non_negative CHECK (failed_login_count >= 0)
);
    """,
    """\
CREATE TABLE core.currencies (
	code VARCHAR(3) NOT NULL,
	name VARCHAR(80) NOT NULL,
	minor_units SMALLINT DEFAULT 2 NOT NULL,
	symbol VARCHAR(8),
	is_active BOOLEAN DEFAULT true NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_currencies PRIMARY KEY (code)
);
    """,
    """\
CREATE TABLE core.fx_rates (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	base_currency VARCHAR(3) NOT NULL,
	quote_currency VARCHAR(3) NOT NULL,
	rate_date DATE NOT NULL,
	rate NUMERIC(18, 6) NOT NULL,
	source VARCHAR(60) DEFAULT 'MANUAL' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_fx_rates PRIMARY KEY (id),
	CONSTRAINT uq_fx_rates_pair_date UNIQUE (base_currency, quote_currency, rate_date),
	CONSTRAINT ck_fx_rates_rate_positive CHECK (rate > 0),
	CONSTRAINT ck_fx_rates_rate_pair_distinct CHECK (base_currency <> quote_currency)
);
    """,
    """\
CREATE TABLE core.tenants (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(40) NOT NULL,
	name VARCHAR(200) NOT NULL,
	status core.tenant_status DEFAULT 'ACTIVE' NOT NULL,
	country VARCHAR(2) DEFAULT 'IN' NOT NULL,
	reporting_currency VARCHAR(3) DEFAULT 'INR' NOT NULL,
	locale VARCHAR(10) DEFAULT 'en-IN' NOT NULL,
	timezone VARCHAR(60) DEFAULT 'Asia/Kolkata' NOT NULL,
	fiscal_year_start_month SMALLINT DEFAULT 4 NOT NULL,
	synthetic_mode BOOLEAN DEFAULT false NOT NULL,
	data_retention_days INTEGER DEFAULT 2555 NOT NULL,
	settings JSONB DEFAULT '{}'::jsonb NOT NULL,
	suspended_at TIMESTAMP WITH TIME ZONE,
	suspended_reason VARCHAR(500),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_tenants PRIMARY KEY (id),
	CONSTRAINT uq_tenants_code UNIQUE (code)
);
    """,
    """\
CREATE TABLE ingestion.dataset_contracts (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	dataset_type core.dataset_type NOT NULL,
	version VARCHAR(20) NOT NULL,
	title VARCHAR(200) NOT NULL,
	description TEXT,
	schema_json JSONB NOT NULL,
	checksum VARCHAR(64) NOT NULL,
	is_active BOOLEAN DEFAULT true NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	template_object_keys JSONB,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_dataset_contracts PRIMARY KEY (id),
	CONSTRAINT uq_dataset_contracts_type_version UNIQUE (dataset_type, version)
);
    """,
    """\
CREATE TABLE analytics.ai_interactions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID,
	session_id UUID,
	intent core.ai_intent,
	answer_mode core.ai_answer_mode NOT NULL,
	refusal_reason core.ai_refusal_reason,
	question_redacted VARCHAR(2000),
	resolved_filters JSONB,
	fact_payload_hash VARCHAR(64),
	source_run_ids JSONB,
	model_name VARCHAR(120),
	latency_ms INTEGER,
	tokens_in INTEGER,
	tokens_out INTEGER,
	used_offline_fallback BOOLEAN DEFAULT false NOT NULL,
	user_feedback VARCHAR(20),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_ai_interactions PRIMARY KEY (id),
	CONSTRAINT fk_ai_interactions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.analysis_runs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_kind core.run_kind NOT NULL,
	status core.run_status DEFAULT 'QUEUED' NOT NULL,
	requested_by UUID,
	parameters JSONB DEFAULT '{}'::jsonb NOT NULL,
	input_data_versions JSONB DEFAULT '{}'::jsonb NOT NULL,
	estimator_spec_id UUID,
	finance_version_id UUID,
	model_version_id UUID,
	random_seed INTEGER,
	code_version VARCHAR(60),
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	duration_ms INTEGER,
	progress_percent SMALLINT DEFAULT 0 NOT NULL,
	progress_note VARCHAR(200),
	failure_category core.failure_category,
	failure_message VARCHAR(2000),
	events_considered INTEGER,
	events_measured INTEGER,
	events_not_estimable INTEGER,
	idempotency_key VARCHAR(120),
	correlation_id VARCHAR(64),
	task_id VARCHAR(120),
	fingerprint VARCHAR(64),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_analysis_runs PRIMARY KEY (id),
	CONSTRAINT uq_analysis_runs_tenant_idempotency UNIQUE (tenant_id, idempotency_key),
	CONSTRAINT ck_analysis_runs_failed_run_states_category CHECK (status <> 'FAILED' OR failure_category IS NOT NULL),
	CONSTRAINT fk_analysis_runs_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.data_health_snapshots (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	dataset_type core.dataset_type NOT NULL,
	computed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	run_id UUID,
	brand_id UUID,
	coverage_pct NUMERIC(9, 6),
	freshness_days INTEGER,
	latest_period DATE,
	unmatched_pct NUMERIC(9, 6),
	ambiguous_count INTEGER,
	missing_month_pct NUMERIC(9, 6),
	quarantine_count INTEGER,
	duplicate_count INTEGER,
	readiness_score SMALLINT,
	blocking_issues JSONB,
	definition_change_flag BOOLEAN DEFAULT false NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_data_health_snapshots PRIMARY KEY (id),
	CONSTRAINT uq_data_health_snapshots_grain UNIQUE (tenant_id, dataset_type, computed_at),
	CONSTRAINT fk_data_health_snapshots_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.estimator_specs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	version VARCHAR(20) NOT NULL,
	label VARCHAR(200) NOT NULL,
	primary_estimator core.estimator_kind DEFAULT 'COHORT_TIME_ATT' NOT NULL,
	control_strategy core.control_strategy DEFAULT 'INVITED_NON_ATTENDEE' NOT NULL,
	outcome_metric core.outcome_metric DEFAULT 'NRX' NOT NULL,
	pre_periods SMALLINT DEFAULT 6 NOT NULL,
	post_periods SMALLINT DEFAULT 3 NOT NULL,
	washout_periods SMALLINT DEFAULT 0 NOT NULL,
	caliper NUMERIC(18, 6) DEFAULT 0.05 NOT NULL,
	control_ratio SMALLINT DEFAULT 2 NOT NULL,
	enforce_common_support BOOLEAN DEFAULT true NOT NULL,
	matching_covariates JSONB DEFAULT '[]'::jsonb NOT NULL,
	gate_thresholds JSONB DEFAULT '{}'::jsonb NOT NULL,
	bootstrap_replicates INTEGER DEFAULT 1000 NOT NULL,
	confidence_level NUMERIC(9, 6) DEFAULT 0.95 NOT NULL,
	is_active BOOLEAN DEFAULT false NOT NULL,
	note TEXT,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_estimator_specs PRIMARY KEY (id),
	CONSTRAINT ck_estimator_specs_pre_periods_supports_trend_test CHECK (pre_periods >= 2),
	CONSTRAINT ck_estimator_specs_post_periods_positive CHECK (post_periods >= 1),
	CONSTRAINT ck_estimator_specs_caliper_positive CHECK (caliper > 0),
	CONSTRAINT ck_estimator_specs_control_ratio_at_least_one CHECK (control_ratio >= 1),
	CONSTRAINT fk_estimator_specs_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.scenarios (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(200) NOT NULL,
	brand_id UUID,
	status core.scenario_status DEFAULT 'DRAFT' NOT NULL,
	horizon_start DATE NOT NULL,
	horizon_end DATE NOT NULL,
	budget_total NUMERIC(18, 2) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	exploration_budget_share NUMERIC(9, 6) DEFAULT 0.1 NOT NULL,
	finance_version_id UUID,
	note TEXT,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_scenarios PRIMARY KEY (id),
	CONSTRAINT ck_scenarios_budget_non_negative CHECK (budget_total >= 0),
	CONSTRAINT ck_scenarios_horizon_ordered CHECK (horizon_end >= horizon_start),
	CONSTRAINT fk_scenarios_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE auth.api_keys (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	name VARCHAR(120) NOT NULL,
	key_prefix VARCHAR(12) NOT NULL,
	key_hash VARCHAR(64) NOT NULL,
	role core.role NOT NULL,
	scope JSONB DEFAULT '{}'::jsonb NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE,
	revoked_at TIMESTAMP WITH TIME ZONE,
	last_used_at TIMESTAMP WITH TIME ZONE,
	allowed_cidrs JSONB,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_api_keys PRIMARY KEY (id),
	CONSTRAINT uq_api_keys_key_hash UNIQUE (key_hash),
	CONSTRAINT fk_api_keys_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE auth.delegated_access_grants (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	grantee_user_id UUID NOT NULL,
	role core.role NOT NULL,
	reason VARCHAR(500) NOT NULL,
	approved_by UUID NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	effective_from DATE NOT NULL,
	effective_to DATE,
	CONSTRAINT pk_delegated_access_grants PRIMARY KEY (id),
	CONSTRAINT ck_delegated_access_grants_effective_range_valid CHECK (effective_to IS NULL OR effective_to > effective_from),
	CONSTRAINT ck_delegated_access_grants_grant_is_time_boxed CHECK (effective_to IS NOT NULL),
	CONSTRAINT fk_delegated_access_grants_grantee_user_id_users FOREIGN KEY(grantee_user_id) REFERENCES auth.users (id) ON DELETE CASCADE,
	CONSTRAINT fk_delegated_access_grants_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE auth.identity_providers (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID,
	kind core.auth_provider_kind NOT NULL,
	display_name VARCHAR(120) NOT NULL,
	issuer VARCHAR(500) NOT NULL,
	client_id VARCHAR(255) NOT NULL,
	client_secret_ref VARCHAR(255) NOT NULL,
	scopes VARCHAR(500) DEFAULT 'openid email profile' NOT NULL,
	discovery_cache JSONB,
	discovery_fetched_at TIMESTAMP WITH TIME ZONE,
	role_claim_mapping JSONB,
	auto_provision BOOLEAN DEFAULT false NOT NULL,
	enabled BOOLEAN DEFAULT true NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_identity_providers PRIMARY KEY (id),
	CONSTRAINT fk_identity_providers_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE CASCADE
);
    """,
    """\
CREATE TABLE auth.invitations (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	email VARCHAR(320) NOT NULL,
	display_name VARCHAR(200),
	role core.role NOT NULL,
	status core.invitation_status DEFAULT 'PENDING' NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	scope JSONB DEFAULT '{}'::jsonb NOT NULL,
	accepted_at TIMESTAMP WITH TIME ZONE,
	accepted_user_id UUID,
	revoked_at TIMESTAMP WITH TIME ZONE,
	resent_count INTEGER DEFAULT 0 NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_invitations PRIMARY KEY (id),
	CONSTRAINT uq_invitations_token_hash UNIQUE (token_hash),
	CONSTRAINT ck_invitations_invitation_expiry_after_creation CHECK (expires_at > created_at),
	CONSTRAINT fk_invitations_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE auth.memberships (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID NOT NULL,
	role core.role NOT NULL,
	status core.membership_status DEFAULT 'ACTIVE' NOT NULL,
	granted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	revoked_reason VARCHAR(500),
	all_brands BOOLEAN DEFAULT true NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_memberships PRIMARY KEY (id),
	CONSTRAINT uq_memberships_tenant_user_role UNIQUE (tenant_id, user_id, role),
	CONSTRAINT fk_memberships_user_id_users FOREIGN KEY(user_id) REFERENCES auth.users (id) ON DELETE CASCADE,
	CONSTRAINT fk_memberships_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE auth.password_reset_tokens (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	consumed_at TIMESTAMP WITH TIME ZONE,
	requested_ip_hash VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_password_reset_tokens PRIMARY KEY (id),
	CONSTRAINT uq_password_reset_tokens_token_hash UNIQUE (token_hash),
	CONSTRAINT fk_password_reset_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES auth.users (id) ON DELETE CASCADE
);
    """,
    """\
CREATE TABLE auth.sessions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	active_tenant_id UUID,
	issued_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	idle_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	absolute_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	revoked_reason VARCHAR(200),
	mfa_satisfied_at TIMESTAMP WITH TIME ZONE,
	reauthenticated_at TIMESTAMP WITH TIME ZONE,
	rotated_from_id UUID,
	ip_hash VARCHAR(64),
	user_agent_hash VARCHAR(64),
	refresh_token_hash VARCHAR(64),
	refresh_expires_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_sessions PRIMARY KEY (id),
	CONSTRAINT uq_sessions_token_hash UNIQUE (token_hash),
	CONSTRAINT ck_sessions_absolute_expiry_after_issue CHECK (absolute_expires_at > issued_at),
	CONSTRAINT fk_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES auth.users (id) ON DELETE CASCADE,
	CONSTRAINT fk_sessions_active_tenant_id_tenants FOREIGN KEY(active_tenant_id) REFERENCES core.tenants (id) ON DELETE CASCADE
);
    """,
    """\
CREATE TABLE core.brands (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(200) NOT NULL,
	therapeutic_area_code VARCHAR(60),
	molecule VARCHAR(200),
	is_active BOOLEAN DEFAULT true NOT NULL,
	launch_date DATE,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_brands PRIMARY KEY (id),
	CONSTRAINT fk_brands_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.feature_flags (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	key VARCHAR(80) NOT NULL,
	enabled BOOLEAN DEFAULT false NOT NULL,
	value JSONB,
	note VARCHAR(500),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_feature_flags PRIMARY KEY (id),
	CONSTRAINT uq_feature_flags_tenant_key UNIQUE (tenant_id, key),
	CONSTRAINT fk_feature_flags_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.finance_versions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	label VARCHAR(200) NOT NULL,
	is_active BOOLEAN DEFAULT false NOT NULL,
	frozen_at TIMESTAMP WITH TIME ZONE,
	note TEXT,
	assumptions_checksum VARCHAR(64),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_finance_versions PRIMARY KEY (id),
	CONSTRAINT fk_finance_versions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.hcp_rx_monthly (
	tenant_id UUID NOT NULL,
	hcp_id UUID NOT NULL,
	product_id UUID NOT NULL,
	month DATE NOT NULL,
	brand_id UUID NOT NULL,
	nrx NUMERIC(18, 6),
	trx NUMERIC(18, 6),
	competitor_trx NUMERIC(18, 6),
	market_trx NUMERIC(18, 6),
	is_observed BOOLEAN DEFAULT true NOT NULL,
	coverage_factor NUMERIC(9, 6),
	suppression_flag BOOLEAN DEFAULT false NOT NULL,
	supplier_definition_version VARCHAR(60),
	data_version_id UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_hcp_rx_monthly PRIMARY KEY (tenant_id, hcp_id, product_id, month),
	CONSTRAINT ck_hcp_rx_monthly_nrx_non_negative CHECK (nrx IS NULL OR nrx >= 0),
	CONSTRAINT ck_hcp_rx_monthly_trx_non_negative CHECK (trx IS NULL OR trx >= 0),
	CONSTRAINT ck_hcp_rx_monthly_coverage_factor_is_share CHECK (coverage_factor IS NULL OR (coverage_factor > 0 AND coverage_factor <= 1)),
	CONSTRAINT ck_hcp_rx_monthly_zero_outcome_must_be_observed CHECK (NOT (nrx = 0 AND NOT is_observed)),
	CONSTRAINT ck_hcp_rx_monthly_observed_unsuppressed_has_value CHECK (suppression_flag OR NOT is_observed OR nrx IS NOT NULL),
	CONSTRAINT ck_hcp_rx_monthly_month_is_first_of_month CHECK (date_trunc('month', month) = month),
	CONSTRAINT fk_hcp_rx_monthly_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
)
 PARTITION BY RANGE (month);
    """,
    """\
CREATE TABLE core.hcps (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	master_hcp_id VARCHAR(80) NOT NULL,
	specialty_code VARCHAR(60),
	region_code VARCHAR(60),
	practice_type VARCHAR(60),
	segment VARCHAR(60),
	city_code VARCHAR(60),
	is_active BOOLEAN DEFAULT true NOT NULL,
	first_seen_on DATE,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_hcps PRIMARY KEY (id),
	CONSTRAINT fk_hcps_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.marketing_activity (
	tenant_id UUID NOT NULL,
	hcp_id UUID NOT NULL,
	brand_id UUID DEFAULT '00000000-0000-0000-0000-000000000000'::uuid NOT NULL,
	month DATE NOT NULL,
	rep_calls INTEGER,
	emails_delivered INTEGER,
	emails_opened INTEGER,
	samples_dropped INTEGER,
	other_event_exposures INTEGER,
	digital_impressions INTEGER,
	data_version_id UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_marketing_activity PRIMARY KEY (tenant_id, hcp_id, brand_id, month),
	CONSTRAINT ck_marketing_activity_rep_calls_non_negative CHECK (rep_calls IS NULL OR rep_calls >= 0),
	CONSTRAINT ck_marketing_activity_month_is_first_of_month CHECK (date_trunc('month', month) = month),
	CONSTRAINT fk_marketing_activity_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
)
 PARTITION BY RANGE (month);
    """,
    """\
CREATE TABLE core.notifications (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	recipient_user_id UUID NOT NULL,
	kind VARCHAR(60) NOT NULL,
	severity VARCHAR(20) DEFAULT 'INFO' NOT NULL,
	title VARCHAR(200) NOT NULL,
	body VARCHAR(1000),
	link_path VARCHAR(300),
	read_at TIMESTAMP WITH TIME ZONE,
	requires_action BOOLEAN DEFAULT false NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_notifications PRIMARY KEY (id),
	CONSTRAINT fk_notifications_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.saved_views (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	owner_user_id UUID NOT NULL,
	page_key VARCHAR(60) NOT NULL,
	name VARCHAR(120) NOT NULL,
	filters JSONB DEFAULT '{}'::jsonb NOT NULL,
	is_shared BOOLEAN DEFAULT false NOT NULL,
	is_default BOOLEAN DEFAULT false NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_saved_views PRIMARY KEY (id),
	CONSTRAINT uq_saved_views_owner_page_name UNIQUE (tenant_id, owner_user_id, page_key, name),
	CONSTRAINT fk_saved_views_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.taxonomy_values (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	kind core.taxonomy_kind NOT NULL,
	code VARCHAR(60) NOT NULL,
	label VARCHAR(200) NOT NULL,
	parent_id UUID,
	sort_order INTEGER DEFAULT 0 NOT NULL,
	is_active BOOLEAN DEFAULT true NOT NULL,
	attributes JSONB,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_taxonomy_values PRIMARY KEY (id),
	CONSTRAINT uq_taxonomy_values_tenant_kind_code UNIQUE (tenant_id, kind, code),
	CONSTRAINT fk_taxonomy_values_parent_id_taxonomy_values FOREIGN KEY(parent_id) REFERENCES core.taxonomy_values (id) ON DELETE SET NULL,
	CONSTRAINT fk_taxonomy_values_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.vendors (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(200) NOT NULL,
	status core.vendor_status DEFAULT 'ACTIVE' NOT NULL,
	contact_email VARCHAR(320),
	allowed_email_domains JSONB,
	notes TEXT,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_vendors PRIMARY KEY (id),
	CONSTRAINT fk_vendors_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ingestion.identity_resolution_tasks (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	source_system VARCHAR(60) NOT NULL,
	source_hcp_id VARCHAR(120) NOT NULL,
	status core.identity_match_status NOT NULL,
	candidates JSONB,
	affected_row_count INTEGER DEFAULT 0 NOT NULL,
	first_seen_upload_id UUID,
	resolved_hcp_id UUID,
	resolved_at TIMESTAMP WITH TIME ZONE,
	resolved_by UUID,
	resolution_note VARCHAR(1000),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_identity_resolution_tasks PRIMARY KEY (id),
	CONSTRAINT uq_identity_resolution_tasks_source UNIQUE (tenant_id, source_system, source_hcp_id),
	CONSTRAINT fk_identity_resolution_tasks_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ingestion.raw_objects (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	object_key VARCHAR(1024) NOT NULL,
	bucket VARCHAR(200) NOT NULL,
	original_filename VARCHAR(500) NOT NULL,
	content_type VARCHAR(200),
	byte_size BIGINT NOT NULL,
	checksum_sha256 VARCHAR(64) NOT NULL,
	uploaded_by UUID,
	retention_until DATE,
	legal_hold BOOLEAN DEFAULT false NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_raw_objects PRIMARY KEY (id),
	CONSTRAINT uq_raw_objects_tenant_checksum UNIQUE (tenant_id, checksum_sha256),
	CONSTRAINT uq_raw_objects_object_key UNIQUE (object_key),
	CONSTRAINT ck_raw_objects_byte_size_positive CHECK (byte_size > 0),
	CONSTRAINT fk_raw_objects_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ml.model_specs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(200) NOT NULL,
	model_kind core.model_kind NOT NULL,
	brand_id UUID,
	algorithm VARCHAR(60) DEFAULT 'lightgbm' NOT NULL,
	objective VARCHAR(60),
	hyperparameters JSONB DEFAULT '{}'::jsonb NOT NULL,
	target_definition VARCHAR(200) NOT NULL,
	feature_set JSONB DEFAULT '[]'::jsonb NOT NULL,
	forbidden_features JSONB DEFAULT '[]'::jsonb NOT NULL,
	split_strategy VARCHAR(40) DEFAULT 'temporal' NOT NULL,
	holdout_months SMALLINT DEFAULT 6 NOT NULL,
	calibration_months SMALLINT DEFAULT 6 NOT NULL,
	min_training_rows INTEGER DEFAULT 200 NOT NULL,
	promotion_gates JSONB DEFAULT '{}'::jsonb NOT NULL,
	conformal_alpha NUMERIC(9, 6) DEFAULT 0.2 NOT NULL,
	pooling_hierarchy JSONB DEFAULT '[]'::jsonb NOT NULL,
	min_effective_sample NUMERIC(18, 6) DEFAULT 5 NOT NULL,
	is_active BOOLEAN DEFAULT true NOT NULL,
	note TEXT,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_model_specs PRIMARY KEY (id),
	CONSTRAINT ck_model_specs_holdout_months_positive CHECK (holdout_months >= 1),
	CONSTRAINT ck_model_specs_min_training_rows_positive CHECK (min_training_rows >= 1),
	CONSTRAINT fk_model_specs_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.optimizer_runs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	scenario_id UUID NOT NULL,
	run_id UUID,
	status core.optimizer_status NOT NULL,
	solver VARCHAR(40) DEFAULT 'HiGHS' NOT NULL,
	objective_value NUMERIC(18, 2),
	objective_value_conservative NUMERIC(18, 2),
	selected_count INTEGER DEFAULT 0 NOT NULL,
	candidates_considered INTEGER DEFAULT 0 NOT NULL,
	total_cost NUMERIC(18, 2),
	budget_utilisation NUMERIC(9, 6),
	solve_ms INTEGER,
	mip_gap NUMERIC(18, 6),
	binding_constraints JSONB,
	infeasibility JSONB,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_optimizer_runs PRIMARY KEY (id),
	CONSTRAINT ck_optimizer_runs_infeasible_run_explains_itself CHECK (status <> 'INFEASIBLE' OR infeasibility IS NOT NULL),
	CONSTRAINT fk_optimizer_runs_scenario_id_scenarios FOREIGN KEY(scenario_id) REFERENCES analytics.scenarios (id) ON DELETE CASCADE,
	CONSTRAINT fk_optimizer_runs_run_id_analysis_runs FOREIGN KEY(run_id) REFERENCES analytics.analysis_runs (id) ON DELETE SET NULL,
	CONSTRAINT fk_optimizer_runs_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.portfolio_aggregates (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_id UUID NOT NULL,
	level core.aggregation_level NOT NULL,
	level_key VARCHAR(120) NOT NULL,
	brand_id UUID,
	period_start DATE NOT NULL,
	period_end DATE NOT NULL,
	events_total INTEGER DEFAULT 0 NOT NULL,
	events_measured INTEGER DEFAULT 0 NOT NULL,
	events_not_estimable INTEGER DEFAULT 0 NOT NULL,
	attendees_verified INTEGER DEFAULT 0 NOT NULL,
	incremental_nrx NUMERIC(18, 4),
	incremental_nrx_low NUMERIC(18, 4),
	incremental_nrx_high NUMERIC(18, 4),
	total_cost NUMERIC(18, 2),
	net_roi NUMERIC(18, 2),
	benefit_cost_ratio NUMERIC(18, 6),
	currency VARCHAR(3),
	evidence_mix JSONB,
	dominant_grade core.evidence_grade,
	publication_state core.publication_state DEFAULT 'DRAFT' NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_portfolio_aggregates PRIMARY KEY (id),
	CONSTRAINT uq_portfolio_aggregates_grain UNIQUE (tenant_id, run_id, level, level_key, period_start),
	CONSTRAINT fk_portfolio_aggregates_brand_id_brands FOREIGN KEY(brand_id) REFERENCES core.brands (id) ON DELETE RESTRICT,
	CONSTRAINT fk_portfolio_aggregates_run_id_analysis_runs FOREIGN KEY(run_id) REFERENCES analytics.analysis_runs (id) ON DELETE CASCADE,
	CONSTRAINT fk_portfolio_aggregates_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.propensity_scores (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_id UUID NOT NULL,
	event_id UUID NOT NULL,
	hcp_id UUID NOT NULL,
	score NUMERIC(9, 6) NOT NULL,
	model_version_id UUID,
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_propensity_scores PRIMARY KEY (id),
	CONSTRAINT uq_propensity_scores_grain UNIQUE (tenant_id, run_id, event_id, hcp_id),
	CONSTRAINT ck_propensity_scores_score_is_probability CHECK (score >= 0 AND score <= 1),
	CONSTRAINT fk_propensity_scores_run_id_analysis_runs FOREIGN KEY(run_id) REFERENCES analytics.analysis_runs (id) ON DELETE CASCADE,
	CONSTRAINT fk_propensity_scores_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.scenario_constraints (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	scenario_id UUID NOT NULL,
	kind core.constraint_kind NOT NULL,
	key VARCHAR(120),
	min_value NUMERIC(18, 6),
	max_value NUMERIC(18, 6),
	is_hard BOOLEAN DEFAULT true NOT NULL,
	label VARCHAR(200),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_scenario_constraints PRIMARY KEY (id),
	CONSTRAINT ck_scenario_constraints_constraint_bounds_ordered CHECK (min_value IS NULL OR max_value IS NULL OR max_value >= min_value),
	CONSTRAINT fk_scenario_constraints_scenario_id_scenarios FOREIGN KEY(scenario_id) REFERENCES analytics.scenarios (id) ON DELETE CASCADE,
	CONSTRAINT fk_scenario_constraints_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE auth.membership_brand_scopes (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	membership_id UUID NOT NULL,
	brand_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_membership_brand_scopes PRIMARY KEY (id),
	CONSTRAINT uq_membership_brand_scopes_membership_brand UNIQUE (membership_id, brand_id),
	CONSTRAINT fk_membership_brand_scopes_membership_id_memberships FOREIGN KEY(membership_id) REFERENCES auth.memberships (id) ON DELETE CASCADE,
	CONSTRAINT fk_membership_brand_scopes_brand_id_brands FOREIGN KEY(brand_id) REFERENCES core.brands (id) ON DELETE CASCADE,
	CONSTRAINT fk_membership_brand_scopes_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE auth.membership_vendor_scopes (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	membership_id UUID NOT NULL,
	vendor_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_membership_vendor_scopes PRIMARY KEY (id),
	CONSTRAINT uq_membership_vendor_scopes_membership_vendor UNIQUE (membership_id, vendor_id),
	CONSTRAINT fk_membership_vendor_scopes_membership_id_memberships FOREIGN KEY(membership_id) REFERENCES auth.memberships (id) ON DELETE CASCADE,
	CONSTRAINT fk_membership_vendor_scopes_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES core.vendors (id) ON DELETE CASCADE,
	CONSTRAINT fk_membership_vendor_scopes_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.campaigns (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(200) NOT NULL,
	brand_id UUID NOT NULL,
	objective VARCHAR(200),
	topic_code VARCHAR(60),
	start_date DATE NOT NULL,
	end_date DATE,
	status core.campaign_status DEFAULT 'DRAFT' NOT NULL,
	owner_user_id UUID,
	planned_budget NUMERIC(18, 2),
	currency VARCHAR(3),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_campaigns PRIMARY KEY (id),
	CONSTRAINT ck_campaigns_campaign_dates_ordered CHECK (end_date IS NULL OR end_date >= start_date),
	CONSTRAINT fk_campaigns_brand_id_brands FOREIGN KEY(brand_id) REFERENCES core.brands (id) ON DELETE RESTRICT,
	CONSTRAINT fk_campaigns_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.finance_assumptions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	finance_version_id UUID NOT NULL,
	brand_id UUID NOT NULL,
	scenario core.finance_scenario DEFAULT 'BASE' NOT NULL,
	contribution_per_nrx NUMERIC(18, 2) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	persistence_months SMALLINT,
	note VARCHAR(500),
	data_version_id UUID,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	effective_from DATE NOT NULL,
	effective_to DATE,
	CONSTRAINT pk_finance_assumptions PRIMARY KEY (id),
	CONSTRAINT ck_finance_assumptions_effective_range_valid CHECK (effective_to IS NULL OR effective_to > effective_from),
	CONSTRAINT ex_finance_assumptions_no_overlap EXCLUDE USING gist (tenant_id WITH =, finance_version_id WITH =, brand_id WITH =, scenario WITH =, daterange(effective_from, effective_to, '[)') WITH &&),
	CONSTRAINT ck_finance_assumptions_contribution_non_negative CHECK (contribution_per_nrx >= 0),
	CONSTRAINT fk_finance_assumptions_finance_version_id_finance_versions FOREIGN KEY(finance_version_id) REFERENCES core.finance_versions (id) ON DELETE CASCADE,
	CONSTRAINT fk_finance_assumptions_brand_id_brands FOREIGN KEY(brand_id) REFERENCES core.brands (id) ON DELETE CASCADE,
	CONSTRAINT fk_finance_assumptions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.hcp_identifiers (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	source_system VARCHAR(60) NOT NULL,
	source_hcp_id VARCHAR(120) NOT NULL,
	hcp_id UUID,
	status core.identity_match_status NOT NULL,
	match_method core.match_method NOT NULL,
	confidence NUMERIC(9, 6),
	candidate_hcp_ids JSONB,
	resolved_by UUID,
	resolved_at TIMESTAMP WITH TIME ZONE,
	data_version_id UUID,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	effective_from DATE NOT NULL,
	effective_to DATE,
	CONSTRAINT pk_hcp_identifiers PRIMARY KEY (id),
	CONSTRAINT uq_hcp_identifiers_tenant_source_from UNIQUE (tenant_id, source_system, source_hcp_id, effective_from),
	CONSTRAINT ck_hcp_identifiers_effective_range_valid CHECK (effective_to IS NULL OR effective_to > effective_from),
	CONSTRAINT ex_hcp_identifiers_no_overlap EXCLUDE USING gist (tenant_id WITH =, source_system WITH =, source_hcp_id WITH =, daterange(effective_from, effective_to, '[)') WITH &&),
	CONSTRAINT ck_hcp_identifiers_confidence_is_probability CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
	CONSTRAINT ck_hcp_identifiers_matched_requires_master CHECK (status <> 'MATCHED' OR hcp_id IS NOT NULL),
	CONSTRAINT fk_hcp_identifiers_hcp_id_hcps FOREIGN KEY(hcp_id) REFERENCES core.hcps (id) ON DELETE RESTRICT,
	CONSTRAINT fk_hcp_identifiers_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.market_factors (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	brand_id UUID NOT NULL,
	region_code VARCHAR(60) NOT NULL,
	month DATE NOT NULL,
	access_index NUMERIC(18, 6),
	seasonality_index NUMERIC(18, 6),
	competitor_index NUMERIC(18, 6),
	market_size_index NUMERIC(18, 6),
	notes VARCHAR(500),
	data_version_id UUID,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_market_factors PRIMARY KEY (id),
	CONSTRAINT uq_market_factors_grain UNIQUE (tenant_id, brand_id, region_code, month),
	CONSTRAINT ck_market_factors_month_is_first_of_month CHECK (date_trunc('month', month) = month),
	CONSTRAINT fk_market_factors_brand_id_brands FOREIGN KEY(brand_id) REFERENCES core.brands (id) ON DELETE CASCADE,
	CONSTRAINT fk_market_factors_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.products (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	brand_id UUID NOT NULL,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(200) NOT NULL,
	formulation VARCHAR(80),
	strength VARCHAR(60),
	pack_size VARCHAR(60),
	is_active BOOLEAN DEFAULT true NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_products PRIMARY KEY (id),
	CONSTRAINT fk_products_brand_id_brands FOREIGN KEY(brand_id) REFERENCES core.brands (id) ON DELETE RESTRICT,
	CONSTRAINT fk_products_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.vendor_dataset_grants (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	vendor_id UUID NOT NULL,
	dataset_type core.dataset_type NOT NULL,
	access core.dataset_access DEFAULT 'WRITE' NOT NULL,
	granted_by UUID NOT NULL,
	granted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_vendor_dataset_grants PRIMARY KEY (id),
	CONSTRAINT uq_vendor_dataset_grants_scope UNIQUE (tenant_id, vendor_id, dataset_type),
	CONSTRAINT fk_vendor_dataset_grants_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES core.vendors (id) ON DELETE CASCADE,
	CONSTRAINT fk_vendor_dataset_grants_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ingestion.column_mapping_templates (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	dataset_type core.dataset_type NOT NULL,
	name VARCHAR(120) NOT NULL,
	vendor_id UUID,
	mapping JSONB NOT NULL,
	parse_options JSONB,
	is_default BOOLEAN DEFAULT false NOT NULL,
	last_used_at TIMESTAMP WITH TIME ZONE,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_column_mapping_templates PRIMARY KEY (id),
	CONSTRAINT uq_column_mapping_templates_scope_name UNIQUE (tenant_id, dataset_type, name),
	CONSTRAINT fk_column_mapping_templates_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES core.vendors (id) ON DELETE CASCADE,
	CONSTRAINT fk_column_mapping_templates_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ingestion.upload_sessions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	dataset_type core.dataset_type NOT NULL,
	status core.upload_status DEFAULT 'CREATED' NOT NULL,
	contract_version VARCHAR(20) NOT NULL,
	raw_object_id UUID,
	vendor_id UUID,
	brand_id UUID,
	campaign_id UUID,
	event_id UUID,
	period_start DATE,
	period_end DATE,
	file_format core.file_format,
	detected_encoding VARCHAR(40),
	detected_delimiter VARCHAR(4),
	confirmed_delimiter VARCHAR(4),
	sheet_name VARCHAR(200),
	header_row_index INTEGER DEFAULT 1 NOT NULL,
	column_mapping JSONB,
	row_count_total INTEGER,
	row_count_accepted INTEGER DEFAULT 0 NOT NULL,
	row_count_rejected INTEGER DEFAULT 0 NOT NULL,
	row_count_quarantined INTEGER DEFAULT 0 NOT NULL,
	error_count INTEGER DEFAULT 0 NOT NULL,
	warning_count INTEGER DEFAULT 0 NOT NULL,
	error_report_object_key VARCHAR(1024),
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	duration_ms INTEGER,
	failure_category core.failure_category,
	failure_message VARCHAR(1000),
	idempotency_key VARCHAR(120),
	correlation_id VARCHAR(64),
	task_id VARCHAR(120),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_upload_sessions PRIMARY KEY (id),
	CONSTRAINT uq_upload_sessions_tenant_idempotency UNIQUE (tenant_id, idempotency_key),
	CONSTRAINT ck_upload_sessions_row_dispositions_reconcile CHECK (row_count_accepted + row_count_rejected + row_count_quarantined <= COALESCE(row_count_total, 0)),
	CONSTRAINT ck_upload_sessions_failed_session_states_category CHECK (status <> 'FAILED' OR failure_category IS NOT NULL),
	CONSTRAINT fk_upload_sessions_raw_object_id_raw_objects FOREIGN KEY(raw_object_id) REFERENCES ingestion.raw_objects (id) ON DELETE RESTRICT,
	CONSTRAINT fk_upload_sessions_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES core.vendors (id) ON DELETE RESTRICT,
	CONSTRAINT fk_upload_sessions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ml.model_versions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	model_spec_id UUID NOT NULL,
	model_kind core.model_kind NOT NULL,
	brand_id UUID,
	version_number INTEGER NOT NULL,
	label VARCHAR(200),
	lifecycle_state core.model_lifecycle_state DEFAULT 'DRAFT' NOT NULL,
	artifact_key VARCHAR(500),
	artifact_checksum VARCHAR(64),
	artifact_bytes INTEGER,
	runtime_versions JSONB,
	training_run_id UUID,
	training_data_versions JSONB DEFAULT '{}'::jsonb NOT NULL,
	random_seed INTEGER,
	code_version VARCHAR(60),
	hyperparameters JSONB,
	training_rows INTEGER,
	validation_rows INTEGER,
	calibration_rows INTEGER,
	train_period_start DATE,
	train_period_end DATE,
	holdout_period_start DATE,
	holdout_period_end DATE,
	trained_at TIMESTAMP WITH TIME ZONE,
	activated_at TIMESTAMP WITH TIME ZONE,
	retired_at TIMESTAMP WITH TIME ZONE,
	rejection_reason VARCHAR(500),
	gates_passed BOOLEAN,
	gate_results JSONB,
	trained_on_synthetic BOOLEAN DEFAULT false NOT NULL,
	known_limitations TEXT,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_model_versions PRIMARY KEY (id),
	CONSTRAINT ck_model_versions_version_number_positive CHECK (version_number >= 1),
	CONSTRAINT ck_model_versions_active_version_has_artifact CHECK (lifecycle_state <> 'ACTIVE' OR artifact_key IS NOT NULL),
	CONSTRAINT ck_model_versions_rejected_version_states_reason CHECK (lifecycle_state <> 'REJECTED' OR rejection_reason IS NOT NULL),
	CONSTRAINT ck_model_versions_training_rows_non_negative CHECK (training_rows IS NULL OR training_rows >= 0),
	CONSTRAINT fk_model_versions_model_spec_id_model_specs FOREIGN KEY(model_spec_id) REFERENCES ml.model_specs (id) ON DELETE RESTRICT,
	CONSTRAINT fk_model_versions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.candidate_programs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(300),
	brand_id UUID NOT NULL,
	campaign_id UUID,
	topic_code VARCHAR(60),
	region_code VARCHAR(60),
	format core.event_format NOT NULL,
	planned_month DATE NOT NULL,
	expected_attendance INTEGER NOT NULL,
	planned_cost NUMERIC(18, 2) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	speaker_tier VARCHAR(40),
	is_compliance_eligible BOOLEAN DEFAULT true NOT NULL,
	compliance_note VARCHAR(500),
	notes TEXT,
	data_version_id UUID,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_candidate_programs PRIMARY KEY (id),
	CONSTRAINT ck_candidate_programs_expected_attendance_positive CHECK (expected_attendance > 0),
	CONSTRAINT ck_candidate_programs_planned_cost_non_negative CHECK (planned_cost >= 0),
	CONSTRAINT ck_candidate_programs_planned_month_is_first_of_month CHECK (date_trunc('month', planned_month) = planned_month),
	CONSTRAINT fk_candidate_programs_brand_id_brands FOREIGN KEY(brand_id) REFERENCES core.brands (id) ON DELETE CASCADE,
	CONSTRAINT fk_candidate_programs_campaign_id_campaigns FOREIGN KEY(campaign_id) REFERENCES core.campaigns (id) ON DELETE SET NULL,
	CONSTRAINT fk_candidate_programs_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.events (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(300),
	campaign_id UUID,
	brand_id UUID NOT NULL,
	event_date DATE NOT NULL,
	start_time TIME WITHOUT TIME ZONE,
	end_time TIME WITHOUT TIME ZONE,
	timezone VARCHAR(60),
	format core.event_format NOT NULL,
	topic_code VARCHAR(60),
	region_code VARCHAR(60),
	venue_city VARCHAR(120),
	venue_name VARCHAR(200),
	speaker_tier VARCHAR(40),
	planned_attendance INTEGER,
	status core.event_status DEFAULT 'PROPOSED' NOT NULL,
	workflow_status core.event_workflow_status DEFAULT 'DRAFT' NOT NULL,
	measurement_eligible BOOLEAN DEFAULT true NOT NULL,
	exclusion_reason core.exclusion_reason,
	exclusion_note VARCHAR(500),
	currency VARCHAR(3),
	data_version_id UUID,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_events PRIMARY KEY (id),
	CONSTRAINT ck_events_planned_attendance_non_negative CHECK (planned_attendance IS NULL OR planned_attendance >= 0),
	CONSTRAINT ck_events_ineligible_event_states_reason CHECK (measurement_eligible OR exclusion_reason IS NOT NULL),
	CONSTRAINT fk_events_campaign_id_campaigns FOREIGN KEY(campaign_id) REFERENCES core.campaigns (id) ON DELETE SET NULL,
	CONSTRAINT fk_events_brand_id_brands FOREIGN KEY(brand_id) REFERENCES core.brands (id) ON DELETE RESTRICT,
	CONSTRAINT fk_events_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ingestion.data_versions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	dataset_type core.dataset_type NOT NULL,
	version_number INTEGER NOT NULL,
	status core.data_version_status DEFAULT 'DRAFT' NOT NULL,
	upload_session_id UUID,
	row_count INTEGER DEFAULT 0 NOT NULL,
	period_start DATE,
	period_end DATE,
	published_at TIMESTAMP WITH TIME ZONE,
	published_by UUID,
	superseded_by_id UUID,
	superseded_at TIMESTAMP WITH TIME ZONE,
	content_checksum VARCHAR(64),
	note TEXT,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_data_versions PRIMARY KEY (id),
	CONSTRAINT uq_data_versions_tenant_type_num UNIQUE (tenant_id, dataset_type, version_number),
	CONSTRAINT ck_data_versions_version_number_positive CHECK (version_number > 0),
	CONSTRAINT ck_data_versions_row_count_non_negative CHECK (row_count >= 0),
	CONSTRAINT fk_data_versions_upload_session_id_upload_sessions FOREIGN KEY(upload_session_id) REFERENCES ingestion.upload_sessions (id) ON DELETE SET NULL,
	CONSTRAINT fk_data_versions_superseded_by_id_data_versions FOREIGN KEY(superseded_by_id) REFERENCES ingestion.data_versions (id) ON DELETE SET NULL,
	CONSTRAINT fk_data_versions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ingestion.quarantine_rows (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	upload_session_id UUID NOT NULL,
	dataset_type core.dataset_type NOT NULL,
	source_row_number INTEGER,
	reason_code VARCHAR(80) NOT NULL,
	payload_redacted JSONB NOT NULL,
	options JSONB,
	resolved_at TIMESTAMP WITH TIME ZONE,
	resolved_by UUID,
	resolution VARCHAR(40),
	resolution_note VARCHAR(1000),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_quarantine_rows PRIMARY KEY (id),
	CONSTRAINT fk_quarantine_rows_upload_session_id_upload_sessions FOREIGN KEY(upload_session_id) REFERENCES ingestion.upload_sessions (id) ON DELETE CASCADE,
	CONSTRAINT fk_quarantine_rows_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ingestion.upload_issues (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	upload_session_id UUID NOT NULL,
	source_row_number INTEGER,
	column_name VARCHAR(200),
	code VARCHAR(80) NOT NULL,
	severity core.issue_severity NOT NULL,
	message VARCHAR(1000) NOT NULL,
	remediation VARCHAR(1000),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_upload_issues PRIMARY KEY (id),
	CONSTRAINT fk_upload_issues_upload_session_id_upload_sessions FOREIGN KEY(upload_session_id) REFERENCES ingestion.upload_sessions (id) ON DELETE CASCADE,
	CONSTRAINT fk_upload_issues_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ml.conformal_calibration (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	model_version_id UUID NOT NULL,
	segment VARCHAR(120) DEFAULT 'ALL' NOT NULL,
	alpha NUMERIC(9, 6) DEFAULT 0.2 NOT NULL,
	quantile_low NUMERIC(18, 6),
	quantile_high NUMERIC(18, 6),
	n_calibration INTEGER DEFAULT 0 NOT NULL,
	empirical_coverage NUMERIC(9, 6),
	mean_interval_width NUMERIC(18, 6),
	is_fallback BOOLEAN DEFAULT false NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_conformal_calibration PRIMARY KEY (id),
	CONSTRAINT uq_conformal_calibration_grain UNIQUE (tenant_id, model_version_id, segment, alpha),
	CONSTRAINT ck_conformal_calibration_alpha_is_proper_fraction CHECK (alpha > 0 AND alpha < 1),
	CONSTRAINT ck_conformal_calibration_n_calibration_non_negative CHECK (n_calibration >= 0),
	CONSTRAINT ck_conformal_calibration_quantiles_ordered CHECK (quantile_low IS NULL OR quantile_high IS NULL OR quantile_high >= quantile_low),
	CONSTRAINT fk_conformal_calibration_model_version_id_model_versions FOREIGN KEY(model_version_id) REFERENCES ml.model_versions (id) ON DELETE CASCADE,
	CONSTRAINT fk_conformal_calibration_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ml.drift_snapshots (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	model_version_id UUID NOT NULL,
	computed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	feature_name VARCHAR(120) DEFAULT 'ALL' NOT NULL,
	psi NUMERIC(18, 6),
	kolmogorov_smirnov NUMERIC(18, 6),
	null_rate_delta NUMERIC(18, 6),
	out_of_support_rate NUMERIC(9, 6),
	prediction_mean NUMERIC(18, 6),
	prediction_mean_baseline NUMERIC(18, 6),
	realised_mae NUMERIC(18, 6),
	realised_coverage NUMERIC(9, 6),
	n_scored INTEGER,
	threshold NUMERIC(18, 6),
	breached BOOLEAN DEFAULT false NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_drift_snapshots PRIMARY KEY (id),
	CONSTRAINT uq_drift_snapshots_grain UNIQUE (tenant_id, model_version_id, computed_at, feature_name),
	CONSTRAINT fk_drift_snapshots_model_version_id_model_versions FOREIGN KEY(model_version_id) REFERENCES ml.model_versions (id) ON DELETE CASCADE,
	CONSTRAINT fk_drift_snapshots_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ml.model_features (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	model_version_id UUID NOT NULL,
	feature_name VARCHAR(120) NOT NULL,
	dtype VARCHAR(20),
	importance NUMERIC(18, 6),
	importance_rank SMALLINT,
	train_min NUMERIC(18, 6),
	train_max NUMERIC(18, 6),
	train_p01 NUMERIC(18, 6),
	train_p99 NUMERIC(18, 6),
	observed_categories JSONB,
	null_rate NUMERIC(9, 6),
	description VARCHAR(300),
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_model_features PRIMARY KEY (id),
	CONSTRAINT uq_model_features_version_name UNIQUE (tenant_id, model_version_id, feature_name),
	CONSTRAINT fk_model_features_model_version_id_model_versions FOREIGN KEY(model_version_id) REFERENCES ml.model_versions (id) ON DELETE CASCADE,
	CONSTRAINT fk_model_features_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ml.model_metrics (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	model_version_id UUID NOT NULL,
	split VARCHAR(20) NOT NULL,
	metric_name VARCHAR(60) NOT NULL,
	metric_value NUMERIC(18, 6),
	segment VARCHAR(120) DEFAULT 'ALL' NOT NULL,
	n_observations INTEGER,
	threshold NUMERIC(18, 6),
	passed BOOLEAN,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_model_metrics PRIMARY KEY (id),
	CONSTRAINT uq_model_metrics_grain UNIQUE (tenant_id, model_version_id, split, metric_name, segment),
	CONSTRAINT fk_model_metrics_model_version_id_model_versions FOREIGN KEY(model_version_id) REFERENCES ml.model_versions (id) ON DELETE CASCADE,
	CONSTRAINT fk_model_metrics_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ml.model_promotions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	model_version_id UUID NOT NULL,
	model_kind core.model_kind NOT NULL,
	brand_id UUID,
	previous_version_id UUID,
	from_state core.model_lifecycle_state,
	to_state core.model_lifecycle_state NOT NULL,
	decided_by UUID NOT NULL,
	is_rollback BOOLEAN DEFAULT false NOT NULL,
	justification TEXT,
	comparison JSONB,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_model_promotions PRIMARY KEY (id),
	CONSTRAINT fk_model_promotions_model_version_id_model_versions FOREIGN KEY(model_version_id) REFERENCES ml.model_versions (id) ON DELETE RESTRICT,
	CONSTRAINT fk_model_promotions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE ml.pooled_priors (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	model_version_id UUID NOT NULL,
	level SMALLINT NOT NULL,
	cell_key VARCHAR(300) NOT NULL,
	parent_cell_key VARCHAR(300),
	prior_mean NUMERIC(18, 4),
	prior_variance NUMERIC(18, 6),
	raw_mean NUMERIC(18, 4),
	shrinkage_weight NUMERIC(9, 6),
	n_observations INTEGER DEFAULT 0 NOT NULL,
	n_effective NUMERIC(18, 6),
	evidence_mix JSONB,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_pooled_priors PRIMARY KEY (id),
	CONSTRAINT uq_pooled_priors_grain UNIQUE (tenant_id, model_version_id, level, cell_key),
	CONSTRAINT ck_pooled_priors_n_observations_non_negative CHECK (n_observations >= 0),
	CONSTRAINT fk_pooled_priors_model_version_id_model_versions FOREIGN KEY(model_version_id) REFERENCES ml.model_versions (id) ON DELETE CASCADE,
	CONSTRAINT fk_pooled_priors_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.cohorts (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_id UUID NOT NULL,
	event_id UUID NOT NULL,
	control_strategy core.control_strategy NOT NULL,
	strategy_justification VARCHAR(500),
	treated_count INTEGER DEFAULT 0 NOT NULL,
	control_count INTEGER DEFAULT 0 NOT NULL,
	matched_pairs INTEGER DEFAULT 0 NOT NULL,
	dropped_off_support INTEGER DEFAULT 0 NOT NULL,
	dropped_no_match INTEGER DEFAULT 0 NOT NULL,
	caliper NUMERIC(18, 6),
	control_ratio SMALLINT,
	balance_summary JSONB DEFAULT '{}'::jsonb NOT NULL,
	max_abs_smd_after NUMERIC(18, 6),
	propensity_model_version_id UUID,
	common_support_overlap NUMERIC(9, 6),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_cohorts PRIMARY KEY (id),
	CONSTRAINT uq_cohorts_run_event UNIQUE (tenant_id, run_id, event_id),
	CONSTRAINT ck_cohorts_arm_counts_non_negative CHECK (treated_count >= 0 AND control_count >= 0),
	CONSTRAINT fk_cohorts_run_id_analysis_runs FOREIGN KEY(run_id) REFERENCES analytics.analysis_runs (id) ON DELETE CASCADE,
	CONSTRAINT fk_cohorts_event_id_events FOREIGN KEY(event_id) REFERENCES core.events (id) ON DELETE CASCADE,
	CONSTRAINT fk_cohorts_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.forecasts (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_id UUID NOT NULL,
	model_version_id UUID,
	candidate_program_id UUID,
	scenario_id UUID,
	brand_id UUID,
	mode core.forecast_mode NOT NULL,
	point_estimate NUMERIC(18, 4),
	pi_low NUMERIC(18, 4),
	pi_high NUMERIC(18, 4),
	alpha NUMERIC(9, 6) DEFAULT 0.2 NOT NULL,
	n_effective NUMERIC(18, 6),
	pooling_cell VARCHAR(200),
	pooling_level VARCHAR(40),
	blend_weight NUMERIC(9, 6),
	out_of_support_reasons JSONB,
	expected_attendance NUMERIC(18, 6),
	expected_attendance_low NUMERIC(18, 6),
	expected_attendance_high NUMERIC(18, 6),
	expected_incremental_nrx NUMERIC(18, 4),
	expected_cost NUMERIC(18, 2),
	expected_net_roi NUMERIC(18, 2),
	expected_net_roi_low NUMERIC(18, 2),
	currency VARCHAR(3),
	drivers JSONB,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_forecasts PRIMARY KEY (id),
	CONSTRAINT ck_forecasts_refusal_carries_no_estimate CHECK (mode <> 'OUT_OF_SUPPORT' OR point_estimate IS NULL),
	CONSTRAINT ck_forecasts_prediction_carries_estimate CHECK (mode = 'OUT_OF_SUPPORT' OR point_estimate IS NOT NULL),
	CONSTRAINT ck_forecasts_refusal_names_reasons CHECK (mode <> 'OUT_OF_SUPPORT' OR out_of_support_reasons IS NOT NULL),
	CONSTRAINT ck_forecasts_interval_ordered CHECK (pi_low IS NULL OR pi_high IS NULL OR pi_high >= pi_low),
	CONSTRAINT fk_forecasts_run_id_analysis_runs FOREIGN KEY(run_id) REFERENCES analytics.analysis_runs (id) ON DELETE CASCADE,
	CONSTRAINT fk_forecasts_candidate_program_id_candidate_programs FOREIGN KEY(candidate_program_id) REFERENCES core.candidate_programs (id) ON DELETE CASCADE,
	CONSTRAINT fk_forecasts_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.attendance (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_id UUID NOT NULL,
	hcp_id UUID NOT NULL,
	registration_status core.attendance_status NOT NULL,
	verified_attended BOOLEAN DEFAULT false NOT NULL,
	verification_source core.attendance_verification_source DEFAULT 'UNVERIFIED' NOT NULL,
	check_in_at TIMESTAMP WITH TIME ZONE,
	duration_minutes INTEGER,
	reconciliation_note VARCHAR(500),
	data_version_id UUID,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_attendance PRIMARY KEY (id),
	CONSTRAINT uq_attendance_tenant_event_hcp UNIQUE (tenant_id, event_id, hcp_id),
	CONSTRAINT ck_attendance_verified_requires_source CHECK (NOT verified_attended OR verification_source <> 'UNVERIFIED'),
	CONSTRAINT ck_attendance_duration_non_negative CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
	CONSTRAINT fk_attendance_event_id_events FOREIGN KEY(event_id) REFERENCES core.events (id) ON DELETE CASCADE,
	CONSTRAINT fk_attendance_hcp_id_hcps FOREIGN KEY(hcp_id) REFERENCES core.hcps (id) ON DELETE RESTRICT,
	CONSTRAINT fk_attendance_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.event_costs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_id UUID NOT NULL,
	category_code VARCHAR(60) NOT NULL,
	vendor_id UUID,
	amount NUMERIC(18, 2) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	amount_base NUMERIC(18, 2),
	fx_rate_id UUID,
	invoice_reference VARCHAR(120) DEFAULT '' NOT NULL,
	invoice_date DATE,
	approval_status core.approval_status DEFAULT 'DRAFT' NOT NULL,
	approved_by UUID,
	approved_at TIMESTAMP WITH TIME ZONE,
	is_outlier BOOLEAN DEFAULT false NOT NULL,
	note VARCHAR(500),
	data_version_id UUID,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_event_costs PRIMARY KEY (id),
	CONSTRAINT uq_event_costs_natural UNIQUE (tenant_id, event_id, category_code, vendor_id, invoice_reference),
	CONSTRAINT ck_event_costs_amount_non_negative CHECK (amount >= 0),
	CONSTRAINT ck_event_costs_approved_cost_has_approver CHECK (approval_status <> 'APPROVED' OR approved_by IS NOT NULL),
	CONSTRAINT fk_event_costs_event_id_events FOREIGN KEY(event_id) REFERENCES core.events (id) ON DELETE CASCADE,
	CONSTRAINT fk_event_costs_vendor_id_vendors FOREIGN KEY(vendor_id) REFERENCES core.vendors (id) ON DELETE SET NULL,
	CONSTRAINT fk_event_costs_fx_rate_id_fx_rates FOREIGN KEY(fx_rate_id) REFERENCES core.fx_rates (id) ON DELETE SET NULL,
	CONSTRAINT fk_event_costs_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.event_speakers (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_id UUID NOT NULL,
	hcp_id UUID,
	external_speaker_code VARCHAR(80),
	tier VARCHAR(40),
	speaking_role VARCHAR(60),
	honorarium_amount NUMERIC(18, 2),
	currency VARCHAR(3),
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_event_speakers PRIMARY KEY (id),
	CONSTRAINT ck_event_speakers_speaker_identified CHECK (hcp_id IS NOT NULL OR external_speaker_code IS NOT NULL),
	CONSTRAINT fk_event_speakers_event_id_events FOREIGN KEY(event_id) REFERENCES core.events (id) ON DELETE CASCADE,
	CONSTRAINT fk_event_speakers_hcp_id_hcps FOREIGN KEY(hcp_id) REFERENCES core.hcps (id) ON DELETE SET NULL,
	CONSTRAINT fk_event_speakers_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.event_workflow_transitions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_id UUID NOT NULL,
	from_status core.event_workflow_status,
	to_status core.event_workflow_status NOT NULL,
	actor_user_id UUID,
	run_id UUID,
	note VARCHAR(1000),
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_event_workflow_transitions PRIMARY KEY (id),
	CONSTRAINT fk_event_workflow_transitions_event_id_events FOREIGN KEY(event_id) REFERENCES core.events (id) ON DELETE CASCADE,
	CONSTRAINT fk_event_workflow_transitions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE core.invitations (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_id UUID NOT NULL,
	hcp_id UUID NOT NULL,
	invited_on DATE,
	channel core.invitation_channel,
	is_eligible BOOLEAN DEFAULT true NOT NULL,
	eligibility_reason VARCHAR(200),
	data_version_id UUID,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID,
	updated_by UUID,
	CONSTRAINT pk_invitations PRIMARY KEY (id),
	CONSTRAINT uq_invitations_tenant_event_hcp UNIQUE (tenant_id, event_id, hcp_id),
	CONSTRAINT fk_invitations_event_id_events FOREIGN KEY(event_id) REFERENCES core.events (id) ON DELETE CASCADE,
	CONSTRAINT fk_invitations_hcp_id_hcps FOREIGN KEY(hcp_id) REFERENCES core.hcps (id) ON DELETE RESTRICT,
	CONSTRAINT fk_invitations_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.cohort_members (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	cohort_id UUID NOT NULL,
	hcp_id UUID NOT NULL,
	arm core.cohort_arm NOT NULL,
	propensity_score NUMERIC(9, 6),
	match_group INTEGER,
	weight NUMERIC(18, 6),
	match_distance NUMERIC(18, 6),
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_cohort_members PRIMARY KEY (id),
	CONSTRAINT uq_cohort_members_cohort_hcp UNIQUE (tenant_id, cohort_id, hcp_id),
	CONSTRAINT fk_cohort_members_cohort_id_cohorts FOREIGN KEY(cohort_id) REFERENCES analytics.cohorts (id) ON DELETE CASCADE,
	CONSTRAINT fk_cohort_members_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.event_impacts (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_id UUID NOT NULL,
	event_id UUID NOT NULL,
	cohort_id UUID,
	outcome_metric core.outcome_metric NOT NULL,
	grain core.analysis_grain DEFAULT 'HCP' NOT NULL,
	estimator_kind core.estimator_kind NOT NULL,
	att NUMERIC(18, 6),
	standard_error NUMERIC(18, 6),
	ci_low NUMERIC(18, 6),
	ci_high NUMERIC(18, 6),
	p_value NUMERIC(18, 6),
	confidence_level NUMERIC(9, 6) DEFAULT 0.95 NOT NULL,
	incremental_nrx NUMERIC(18, 4),
	incremental_nrx_low NUMERIC(18, 4),
	incremental_nrx_high NUMERIC(18, 4),
	n_treated INTEGER DEFAULT 0 NOT NULL,
	n_control INTEGER DEFAULT 0 NOT NULL,
	pre_periods SMALLINT,
	post_periods SMALLINT,
	outcome_coverage NUMERIC(9, 6),
	twfe_att NUMERIC(18, 6),
	twfe_divergence_flag BOOLEAN DEFAULT false NOT NULL,
	evidence_status core.evidence_status NOT NULL,
	evidence_grade core.evidence_grade NOT NULL,
	not_estimable_reason VARCHAR(60),
	publication_state core.publication_state DEFAULT 'DRAFT' NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	published_by UUID,
	brand_id UUID,
	event_date DATE,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_event_impacts PRIMARY KEY (id),
	CONSTRAINT uq_event_impacts_grain UNIQUE (tenant_id, run_id, event_id, outcome_metric, grain),
	CONSTRAINT ck_event_impacts_estimated_impact_has_value CHECK (evidence_status <> 'ESTIMATED' OR att IS NOT NULL),
	CONSTRAINT ck_event_impacts_unestimable_impact_has_no_value CHECK (evidence_status = 'ESTIMATED' OR att IS NULL),
	CONSTRAINT ck_event_impacts_interval_ordered CHECK (ci_low IS NULL OR ci_high IS NULL OR ci_high >= ci_low),
	CONSTRAINT ck_event_impacts_unestimable_states_reason CHECK (evidence_status <> 'NOT_RELIABLY_ESTIMABLE' OR not_estimable_reason IS NOT NULL),
	CONSTRAINT fk_event_impacts_run_id_analysis_runs FOREIGN KEY(run_id) REFERENCES analytics.analysis_runs (id) ON DELETE CASCADE,
	CONSTRAINT fk_event_impacts_event_id_events FOREIGN KEY(event_id) REFERENCES core.events (id) ON DELETE CASCADE,
	CONSTRAINT fk_event_impacts_cohort_id_cohorts FOREIGN KEY(cohort_id) REFERENCES analytics.cohorts (id) ON DELETE SET NULL,
	CONSTRAINT fk_event_impacts_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.scenario_allocations (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	optimizer_run_id UUID NOT NULL,
	candidate_program_id UUID NOT NULL,
	forecast_id UUID,
	is_selected BOOLEAN DEFAULT false NOT NULL,
	allocated_cost NUMERIC(18, 2),
	expected_incremental_nrx NUMERIC(18, 4),
	expected_net_roi NUMERIC(18, 2),
	funded_from_exploration BOOLEAN DEFAULT false NOT NULL,
	exclusion_reason VARCHAR(80),
	rank INTEGER,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_allocations PRIMARY KEY (id),
	CONSTRAINT uq_scenario_allocations_run_candidate UNIQUE (tenant_id, optimizer_run_id, candidate_program_id),
	CONSTRAINT fk_scenario_allocations_optimizer_run_id_optimizer_runs FOREIGN KEY(optimizer_run_id) REFERENCES analytics.optimizer_runs (id) ON DELETE CASCADE,
	CONSTRAINT fk_scenario_allocations_candidate_program_id_candidate_programs FOREIGN KEY(candidate_program_id) REFERENCES core.candidate_programs (id) ON DELETE CASCADE,
	CONSTRAINT fk_scenario_allocations_forecast_id_forecasts FOREIGN KEY(forecast_id) REFERENCES analytics.forecasts (id) ON DELETE SET NULL,
	CONSTRAINT fk_scenario_allocations_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.event_impact_gates (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_impact_id UUID NOT NULL,
	gate core.evidence_gate NOT NULL,
	passed BOOLEAN NOT NULL,
	observed_value NUMERIC(18, 6),
	threshold NUMERIC(18, 6),
	is_critical BOOLEAN DEFAULT false NOT NULL,
	detail VARCHAR(500),
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_event_impact_gates PRIMARY KEY (id),
	CONSTRAINT uq_event_impact_gates_impact_gate UNIQUE (tenant_id, event_impact_id, gate),
	CONSTRAINT fk_event_impact_gates_event_impact_id_event_impacts FOREIGN KEY(event_impact_id) REFERENCES analytics.event_impacts (id) ON DELETE CASCADE,
	CONSTRAINT fk_event_impact_gates_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.event_study_points (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_impact_id UUID NOT NULL,
	relative_period SMALLINT NOT NULL,
	coefficient NUMERIC(18, 6),
	standard_error NUMERIC(18, 6),
	ci_low NUMERIC(18, 6),
	ci_high NUMERIC(18, 6),
	n_observations INTEGER,
	is_reference BOOLEAN DEFAULT false NOT NULL,
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_event_study_points PRIMARY KEY (id),
	CONSTRAINT uq_event_study_points_impact_period UNIQUE (tenant_id, event_impact_id, relative_period),
	CONSTRAINT fk_event_study_points_event_impact_id_event_impacts FOREIGN KEY(event_impact_id) REFERENCES analytics.event_impacts (id) ON DELETE CASCADE,
	CONSTRAINT fk_event_study_points_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.reviews (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_impact_id UUID,
	roi_result_id UUID,
	gate core.review_gate NOT NULL,
	decision core.review_decision NOT NULL,
	reviewer_user_id UUID NOT NULL,
	note TEXT,
	previous_state core.publication_state,
	new_state core.publication_state,
	evidence_snapshot JSONB,
	decided_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_reviews PRIMARY KEY (id),
	CONSTRAINT fk_reviews_event_impact_id_event_impacts FOREIGN KEY(event_impact_id) REFERENCES analytics.event_impacts (id) ON DELETE CASCADE,
	CONSTRAINT fk_reviews_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.roi_results (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_id UUID NOT NULL,
	level core.aggregation_level NOT NULL,
	event_id UUID,
	campaign_id UUID,
	brand_id UUID,
	event_impact_id UUID,
	finance_version_id UUID NOT NULL,
	scenario core.finance_scenario DEFAULT 'BASE' NOT NULL,
	contribution_per_nrx NUMERIC(18, 2),
	incremental_nrx NUMERIC(18, 4),
	incremental_nrx_low NUMERIC(18, 4),
	incremental_nrx_high NUMERIC(18, 4),
	gross_contribution NUMERIC(18, 2),
	total_cost NUMERIC(18, 2) DEFAULT 0 NOT NULL,
	net_roi NUMERIC(18, 2),
	benefit_cost_ratio NUMERIC(18, 6),
	benefit_cost_ratio_low NUMERIC(18, 6),
	benefit_cost_ratio_high NUMERIC(18, 6),
	cost_per_incremental_nrx NUMERIC(18, 2),
	cost_per_attendee NUMERIC(18, 2),
	currency VARCHAR(3) NOT NULL,
	reporting_currency VARCHAR(3),
	net_roi_reporting NUMERIC(18, 2),
	evidence_status core.evidence_status NOT NULL,
	evidence_grade core.evidence_grade NOT NULL,
	evidence_mix JSONB,
	events_measured INTEGER,
	events_excluded INTEGER,
	period_start DATE,
	period_end DATE,
	publication_state core.publication_state DEFAULT 'DRAFT' NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	tenant_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	row_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_roi_results PRIMARY KEY (id),
	CONSTRAINT ck_roi_results_total_cost_non_negative CHECK (total_cost >= 0),
	CONSTRAINT ck_roi_results_event_level_names_event CHECK (level <> 'EVENT' OR event_id IS NOT NULL),
	CONSTRAINT fk_roi_results_run_id_analysis_runs FOREIGN KEY(run_id) REFERENCES analytics.analysis_runs (id) ON DELETE CASCADE,
	CONSTRAINT fk_roi_results_event_id_events FOREIGN KEY(event_id) REFERENCES core.events (id) ON DELETE CASCADE,
	CONSTRAINT fk_roi_results_event_impact_id_event_impacts FOREIGN KEY(event_impact_id) REFERENCES analytics.event_impacts (id) ON DELETE SET NULL,
	CONSTRAINT fk_roi_results_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    """\
CREATE TABLE analytics.sensitivity_results (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	event_impact_id UUID NOT NULL,
	test core.sensitivity_test NOT NULL,
	passed BOOLEAN NOT NULL,
	statistic NUMERIC(18, 6),
	p_value NUMERIC(18, 6),
	alternative_estimate NUMERIC(18, 6),
	detail JSONB,
	tenant_id UUID NOT NULL,
	CONSTRAINT pk_sensitivity_results PRIMARY KEY (id),
	CONSTRAINT uq_sensitivity_results_impact_test UNIQUE (tenant_id, event_impact_id, test),
	CONSTRAINT fk_sensitivity_results_event_impact_id_event_impacts FOREIGN KEY(event_impact_id) REFERENCES analytics.event_impacts (id) ON DELETE CASCADE,
	CONSTRAINT fk_sensitivity_results_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE RESTRICT
);
    """,
    # --- Range partitions -----------------------------------------------
    """\
CREATE TABLE core.hcp_rx_monthly_y2019 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2020 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2021 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2022 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2023 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2024 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2025 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2026 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2027 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2028 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2028-01-01') TO ('2029-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2029 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2029-01-01') TO ('2030-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2030 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2030-01-01') TO ('2031-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2031 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2031-01-01') TO ('2032-01-01');
    """,
    """\
CREATE TABLE core.hcp_rx_monthly_y2032 PARTITION OF core.hcp_rx_monthly
    FOR VALUES FROM ('2032-01-01') TO ('2033-01-01');
    """,
    "CREATE TABLE core.hcp_rx_monthly_default PARTITION OF core.hcp_rx_monthly DEFAULT;",
    """\
CREATE TABLE core.marketing_activity_y2019 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2020 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2021 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2022 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2023 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2024 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2025 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2026 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2027 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2028 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2028-01-01') TO ('2029-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2029 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2029-01-01') TO ('2030-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2030 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2030-01-01') TO ('2031-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2031 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2031-01-01') TO ('2032-01-01');
    """,
    """\
CREATE TABLE core.marketing_activity_y2032 PARTITION OF core.marketing_activity
    FOR VALUES FROM ('2032-01-01') TO ('2033-01-01');
    """,
    "CREATE TABLE core.marketing_activity_default PARTITION OF core.marketing_activity DEFAULT;",
    """\
CREATE TABLE audit.audit_events_y2019 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2019-01-01 00:00:00+00') TO ('2020-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2020 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2020-01-01 00:00:00+00') TO ('2021-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2021 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2021-01-01 00:00:00+00') TO ('2022-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2022 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2022-01-01 00:00:00+00') TO ('2023-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2023 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2023-01-01 00:00:00+00') TO ('2024-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2024 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2024-01-01 00:00:00+00') TO ('2025-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2025 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2025-01-01 00:00:00+00') TO ('2026-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2026 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2026-01-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2027 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2027-01-01 00:00:00+00') TO ('2028-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2028 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2028-01-01 00:00:00+00') TO ('2029-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2029 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2029-01-01 00:00:00+00') TO ('2030-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2030 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2030-01-01 00:00:00+00') TO ('2031-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2031 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2031-01-01 00:00:00+00') TO ('2032-01-01 00:00:00+00');
    """,
    """\
CREATE TABLE audit.audit_events_y2032 PARTITION OF audit.audit_events
    FOR VALUES FROM ('2032-01-01 00:00:00+00') TO ('2033-01-01 00:00:00+00');
    """,
    "CREATE TABLE audit.audit_events_default PARTITION OF audit.audit_events DEFAULT;",
    # --- Indexes --------------------------------------------------------
    "CREATE INDEX ix_audit_events_action_created ON audit.audit_events (action, created_at);",
    "CREATE INDEX ix_audit_events_actor_created ON audit.audit_events (actor_user_id, created_at);",
    "CREATE INDEX ix_audit_events_correlation ON audit.audit_events (correlation_id);",
    "CREATE INDEX ix_audit_events_denied ON audit.audit_events (tenant_id, created_at) WHERE outcome = 'DENIED';",
    "CREATE INDEX ix_audit_events_resource ON audit.audit_events (tenant_id, resource_type, resource_id, created_at);",
    "CREATE INDEX ix_audit_events_tenant_created ON audit.audit_events (tenant_id, created_at);",
    "CREATE INDEX ix_erasure_requests_due ON audit.erasure_requests (due_by);",
    "CREATE INDEX ix_erasure_requests_tenant_status ON audit.erasure_requests (tenant_id, status);",
    "CREATE INDEX ix_export_log_kind ON audit.export_log (tenant_id, export_kind, created_at);",
    "CREATE INDEX ix_export_log_tenant_created ON audit.export_log (tenant_id, created_at);",
    "CREATE INDEX ix_export_log_user_created ON audit.export_log (tenant_id, user_id, created_at);",
    "CREATE INDEX ix_retention_policy_runs_tenant_created ON audit.retention_policy_runs (tenant_id, created_at);",
    "CREATE INDEX ix_login_attempts_at ON auth.login_attempts (attempted_at);",
    "CREATE INDEX ix_login_attempts_identifier_at ON auth.login_attempts (identifier_hash, attempted_at);",
    "CREATE INDEX ix_login_attempts_tenant_at ON auth.login_attempts (tenant_id, attempted_at DESC) WHERE tenant_id IS NOT NULL;",
    "CREATE INDEX ix_users_external_subject ON auth.users (auth_provider_kind, external_subject);",
    "CREATE UNIQUE INDEX uq_users_email_lower ON auth.users (lower(email));",
    "CREATE INDEX ix_fx_rates_lookup ON core.fx_rates (quote_currency, base_currency, rate_date);",
    "CREATE INDEX ix_tenants_status ON core.tenants (status);",
    "CREATE INDEX ix_dataset_contracts_active ON ingestion.dataset_contracts (dataset_type, is_active);",
    "CREATE INDEX ix_ai_interactions_tenant_created_at ON analytics.ai_interactions (tenant_id, created_at);",
    "CREATE INDEX ix_ai_interactions_tenant_intent_answer_mode ON analytics.ai_interactions (tenant_id, intent, answer_mode);",
    "CREATE INDEX ix_ai_interactions_tenant_refusal_reason ON analytics.ai_interactions (tenant_id, refusal_reason);",
    "CREATE INDEX ix_analysis_runs_tenant_created_at ON analytics.analysis_runs (tenant_id, created_at);",
    "CREATE INDEX ix_analysis_runs_tenant_run_kind_status ON analytics.analysis_runs (tenant_id, run_kind, status);",
    "CREATE INDEX ix_analysis_runs_tenant_status ON analytics.analysis_runs (tenant_id, status);",
    "CREATE INDEX ix_estimator_specs_tenant_is_active ON analytics.estimator_specs (tenant_id, is_active);",
    "CREATE UNIQUE INDEX uq_estimator_specs_tenant_code_version ON analytics.estimator_specs (tenant_id, code, version);",
    "CREATE INDEX ix_scenarios_tenant_status_brand_id ON analytics.scenarios (tenant_id, status, brand_id);",
    "CREATE UNIQUE INDEX uq_scenarios_tenant_code ON analytics.scenarios (tenant_id, code);",
    "CREATE INDEX ix_api_keys_tenant_revoked_at ON auth.api_keys (tenant_id, revoked_at);",
    "CREATE INDEX ix_delegated_access_grants_tenant_grantee_window ON auth.delegated_access_grants (tenant_id, grantee_user_id, effective_from);",
    "CREATE UNIQUE INDEX uq_identity_providers_tenant ON auth.identity_providers (tenant_id);",
    "CREATE INDEX ix_invitations_email_lower ON auth.invitations (lower(email));",
    "CREATE INDEX ix_invitations_tenant_status ON auth.invitations (tenant_id, status);",
    "CREATE INDEX ix_memberships_tenant_status_role ON auth.memberships (tenant_id, status, role);",
    "CREATE INDEX ix_memberships_user ON auth.memberships (user_id);",
    "CREATE INDEX ix_password_reset_tokens_user ON auth.password_reset_tokens (user_id, consumed_at);",
    "CREATE INDEX ix_sessions_absolute_expires_at ON auth.sessions (absolute_expires_at);",
    "CREATE INDEX ix_sessions_user_active ON auth.sessions (user_id, revoked_at);",
    "CREATE INDEX ix_brands_tenant_is_active ON core.brands (tenant_id, is_active);",
    "CREATE UNIQUE INDEX uq_brands_tenant_code ON core.brands (tenant_id, code);",
    "CREATE INDEX ix_finance_versions_tenant_is_active ON core.finance_versions (tenant_id, is_active);",
    "CREATE UNIQUE INDEX uq_finance_versions_tenant_code ON core.finance_versions (tenant_id, code);",
    "CREATE INDEX ix_hcp_rx_monthly_tenant_brand_month ON core.hcp_rx_monthly (tenant_id, brand_id, month);",
    "CREATE INDEX ix_hcp_rx_monthly_tenant_hcp_brand_month ON core.hcp_rx_monthly (tenant_id, hcp_id, brand_id, month);",
    "CREATE INDEX ix_hcps_tenant_is_active ON core.hcps (tenant_id, is_active);",
    "CREATE INDEX ix_hcps_tenant_specialty_code_region_code ON core.hcps (tenant_id, specialty_code, region_code);",
    "CREATE UNIQUE INDEX uq_hcps_tenant_master_hcp_id ON core.hcps (tenant_id, master_hcp_id);",
    "CREATE INDEX ix_marketing_activity_tenant_brand_month ON core.marketing_activity (tenant_id, brand_id, month);",
    "CREATE INDEX ix_marketing_activity_tenant_hcp_month ON core.marketing_activity (tenant_id, hcp_id, month);",
    "CREATE INDEX ix_notifications_tenant_recipient_unread ON core.notifications (tenant_id, recipient_user_id) WHERE read_at IS NULL;",
    "CREATE INDEX ix_notifications_tenant_recipient_user_id_recent ON core.notifications (tenant_id, recipient_user_id, created_at DESC);",
    "CREATE INDEX ix_saved_views_tenant_page_key_is_shared ON core.saved_views (tenant_id, page_key, is_shared);",
    "CREATE INDEX ix_taxonomy_values_tenant_kind_is_active ON core.taxonomy_values (tenant_id, kind, is_active);",
    "CREATE INDEX ix_vendors_tenant_status ON core.vendors (tenant_id, status);",
    "CREATE UNIQUE INDEX uq_vendors_tenant_code ON core.vendors (tenant_id, code);",
    "CREATE INDEX ix_identity_resolution_tasks_tenant_status_created_at ON ingestion.identity_resolution_tasks (tenant_id, status, created_at);",
    "CREATE INDEX ix_raw_objects_tenant_created_at ON ingestion.raw_objects (tenant_id, created_at);",
    "CREATE INDEX ix_model_specs_tenant_model_kind_is_active ON ml.model_specs (tenant_id, model_kind, is_active);",
    "CREATE UNIQUE INDEX uq_model_specs_tenant_code ON ml.model_specs (tenant_id, code);",
    "CREATE INDEX ix_optimizer_runs_tenant_scenario_id_created_at ON analytics.optimizer_runs (tenant_id, scenario_id, created_at);",
    "CREATE INDEX ix_optimizer_runs_tenant_status ON analytics.optimizer_runs (tenant_id, status);",
    "CREATE INDEX ix_portfolio_aggregates_tenant_brand_id_period_start ON analytics.portfolio_aggregates (tenant_id, brand_id, period_start);",
    "CREATE INDEX ix_scenario_constraints_tenant_scenario_id_kind ON analytics.scenario_constraints (tenant_id, scenario_id, kind);",
    "CREATE INDEX ix_membership_brand_scopes_tenant_brand_id ON auth.membership_brand_scopes (tenant_id, brand_id);",
    "CREATE INDEX ix_membership_vendor_scopes_tenant_vendor_id ON auth.membership_vendor_scopes (tenant_id, vendor_id);",
    "CREATE INDEX ix_campaigns_tenant_brand_id_status ON core.campaigns (tenant_id, brand_id, status);",
    "CREATE INDEX ix_campaigns_tenant_start_date ON core.campaigns (tenant_id, start_date);",
    "CREATE UNIQUE INDEX uq_campaigns_tenant_code ON core.campaigns (tenant_id, code);",
    "CREATE INDEX ix_finance_assumptions_tenant_brand_id_scenario_effective_from ON core.finance_assumptions (tenant_id, brand_id, scenario, effective_from);",
    "CREATE INDEX ix_finance_assumptions_tenant_finance_version_id ON core.finance_assumptions (tenant_id, finance_version_id);",
    "CREATE INDEX ix_hcp_identifiers_tenant_hcp_id ON core.hcp_identifiers (tenant_id, hcp_id);",
    "CREATE INDEX ix_hcp_identifiers_tenant_status ON core.hcp_identifiers (tenant_id, status);",
    "CREATE INDEX ix_market_factors_tenant_brand_id_month ON core.market_factors (tenant_id, brand_id, month);",
    "CREATE INDEX ix_products_tenant_brand_id ON core.products (tenant_id, brand_id);",
    "CREATE UNIQUE INDEX uq_products_tenant_code ON core.products (tenant_id, code);",
    "CREATE INDEX ix_column_mapping_templates_tenant_dataset_type_is_default ON ingestion.column_mapping_templates (tenant_id, dataset_type, is_default);",
    "CREATE INDEX ix_upload_sessions_tenant_created_at ON ingestion.upload_sessions (tenant_id, created_at);",
    "CREATE INDEX ix_upload_sessions_tenant_dataset_type_status ON ingestion.upload_sessions (tenant_id, dataset_type, status);",
    "CREATE INDEX ix_upload_sessions_tenant_status ON ingestion.upload_sessions (tenant_id, status);",
    "CREATE INDEX ix_upload_sessions_tenant_vendor_id ON ingestion.upload_sessions (tenant_id, vendor_id);",
    "CREATE INDEX ix_model_versions_tenant_model_kind_lifecycle_state ON ml.model_versions (tenant_id, model_kind, lifecycle_state);",
    "CREATE INDEX ix_model_versions_tenant_model_spec_id_created_at ON ml.model_versions (tenant_id, model_spec_id, created_at);",
    "CREATE UNIQUE INDEX uq_model_versions_single_active_champion ON ml.model_versions (tenant_id, model_kind, brand_id) WHERE lifecycle_state = 'ACTIVE';",
    "CREATE UNIQUE INDEX uq_model_versions_tenant_model_spec_id_version_number ON ml.model_versions (tenant_id, model_spec_id, version_number);",
    "CREATE INDEX ix_candidate_programs_tenant_brand_id_planned_month ON core.candidate_programs (tenant_id, brand_id, planned_month);",
    "CREATE UNIQUE INDEX uq_candidate_programs_tenant_code ON core.candidate_programs (tenant_id, code);",
    "CREATE INDEX ix_events_tenant_brand_id_event_date ON core.events (tenant_id, brand_id, event_date);",
    "CREATE INDEX ix_events_tenant_campaign_id ON core.events (tenant_id, campaign_id);",
    "CREATE INDEX ix_events_tenant_event_date_status ON core.events (tenant_id, event_date, status);",
    "CREATE INDEX ix_events_tenant_topic_format ON core.events (tenant_id, topic_code, format);",
    "CREATE INDEX ix_events_tenant_workflow_status ON core.events (tenant_id, workflow_status);",
    "CREATE UNIQUE INDEX uq_events_tenant_code ON core.events (tenant_id, code);",
    "CREATE INDEX ix_data_versions_tenant_dataset_type_status ON ingestion.data_versions (tenant_id, dataset_type, status);",
    "CREATE INDEX ix_quarantine_rows_tenant_reason_code ON ingestion.quarantine_rows (tenant_id, reason_code);",
    "CREATE INDEX ix_quarantine_rows_tenant_upload_session_id_resolved_at ON ingestion.quarantine_rows (tenant_id, upload_session_id, resolved_at);",
    "CREATE INDEX ix_upload_issues_code ON ingestion.upload_issues (tenant_id, code);",
    "CREATE INDEX ix_upload_issues_session_row ON ingestion.upload_issues (upload_session_id, source_row_number);",
    "CREATE INDEX ix_upload_issues_tenant_upload_session_id_severity ON ingestion.upload_issues (tenant_id, upload_session_id, severity);",
    "CREATE INDEX ix_drift_snapshots_tenant_breached ON ml.drift_snapshots (tenant_id, breached);",
    "CREATE INDEX ix_model_promotions_tenant_model_kind_created_at ON ml.model_promotions (tenant_id, model_kind, created_at);",
    "CREATE INDEX ix_model_promotions_tenant_model_version_id_created_at ON ml.model_promotions (tenant_id, model_version_id, created_at);",
    "CREATE INDEX ix_cohorts_tenant_event_id ON analytics.cohorts (tenant_id, event_id);",
    "CREATE INDEX ix_forecasts_tenant_candidate_program_id ON analytics.forecasts (tenant_id, candidate_program_id);",
    "CREATE INDEX ix_forecasts_tenant_mode ON analytics.forecasts (tenant_id, mode);",
    "CREATE INDEX ix_forecasts_tenant_run_id ON analytics.forecasts (tenant_id, run_id);",
    "CREATE INDEX ix_attendance_tenant_event_id_verified_attended ON core.attendance (tenant_id, event_id, verified_attended);",
    "CREATE INDEX ix_attendance_tenant_hcp_id ON core.attendance (tenant_id, hcp_id);",
    "CREATE INDEX ix_event_costs_tenant_approval_status ON core.event_costs (tenant_id, approval_status);",
    "CREATE INDEX ix_event_costs_tenant_vendor_id ON core.event_costs (tenant_id, vendor_id);",
    "CREATE INDEX ix_event_speakers_tenant_event_id ON core.event_speakers (tenant_id, event_id);",
    "CREATE INDEX ix_event_speakers_tenant_hcp_id ON core.event_speakers (tenant_id, hcp_id);",
    "CREATE INDEX ix_event_workflow_transitions_tenant_event_id_occurred_at ON core.event_workflow_transitions (tenant_id, event_id, occurred_at);",
    "CREATE INDEX ix_invitations_tenant_hcp_id ON core.invitations (tenant_id, hcp_id);",
    "CREATE INDEX ix_invitations_tenant_invited_on ON core.invitations (tenant_id, invited_on);",
    "CREATE INDEX ix_cohort_members_tenant_cohort_id_arm ON analytics.cohort_members (tenant_id, cohort_id, arm);",
    "CREATE INDEX ix_event_impacts_tenant_event_id_outcome_metric ON analytics.event_impacts (tenant_id, event_id, outcome_metric);",
    "CREATE INDEX ix_event_impacts_tenant_evidence_grade_publication_state ON analytics.event_impacts (tenant_id, evidence_grade, publication_state);",
    "CREATE INDEX ix_event_impacts_tenant_publication_state ON analytics.event_impacts (tenant_id, publication_state);",
    "CREATE INDEX ix_scenario_allocations_tenant_optimizer_run_id_is_selected ON analytics.scenario_allocations (tenant_id, optimizer_run_id, is_selected);",
    "CREATE INDEX ix_event_impact_gates_tenant_gate_passed ON analytics.event_impact_gates (tenant_id, gate, passed);",
    "CREATE INDEX ix_reviews_tenant_decision ON analytics.reviews (tenant_id, decision);",
    "CREATE INDEX ix_reviews_tenant_event_impact_id_created_at ON analytics.reviews (tenant_id, event_impact_id, created_at);",
    "CREATE INDEX ix_reviews_tenant_gate ON analytics.reviews (tenant_id, gate);",
    "CREATE INDEX ix_roi_results_tenant_brand_id_level ON analytics.roi_results (tenant_id, brand_id, level);",
    "CREATE INDEX ix_roi_results_tenant_event_id ON analytics.roi_results (tenant_id, event_id);",
    "CREATE INDEX ix_roi_results_tenant_publication_state ON analytics.roi_results (tenant_id, publication_state);",
    "CREATE INDEX ix_roi_results_tenant_run_id ON analytics.roi_results (tenant_id, run_id);",
    "CREATE INDEX ix_sensitivity_results_tenant_test_passed ON analytics.sensitivity_results (tenant_id, test, passed);",
    # --- Row-level security ---------------------------------------------
    "ALTER TABLE analytics.ai_interactions ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.ai_interactions
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.analysis_runs ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.analysis_runs
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.cohort_members ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.cohort_members
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.cohorts ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.cohorts
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.data_health_snapshots ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.data_health_snapshots
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.estimator_specs ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.estimator_specs
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.event_impact_gates ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.event_impact_gates
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.event_impacts ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.event_impacts
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.event_study_points ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.event_study_points
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.forecasts ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.forecasts
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.optimizer_runs ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.optimizer_runs
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.portfolio_aggregates ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.portfolio_aggregates
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.propensity_scores ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.propensity_scores
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.reviews ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.reviews
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.roi_results ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.roi_results
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.scenario_allocations ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.scenario_allocations
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.scenario_constraints ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.scenario_constraints
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.scenarios ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.scenarios
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE analytics.sensitivity_results ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON analytics.sensitivity_results
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE audit.audit_events ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_read ON audit.audit_events
    FOR SELECT
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           OR (tenant_id IS NULL AND current_setting('app.platform_scope', true) = 'on'));
    """,
    """\
CREATE POLICY tenant_write ON audit.audit_events
    FOR INSERT
    WITH CHECK (tenant_id IS NULL OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    "ALTER TABLE audit.erasure_requests ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_read ON audit.erasure_requests
    FOR SELECT
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           OR (tenant_id IS NULL AND current_setting('app.platform_scope', true) = 'on'));
    """,
    """\
CREATE POLICY tenant_write ON audit.erasure_requests
    FOR INSERT
    WITH CHECK (tenant_id IS NULL OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_modify ON audit.erasure_requests
    FOR UPDATE
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_delete ON audit.erasure_requests
    FOR DELETE
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    "ALTER TABLE audit.export_log ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_read ON audit.export_log
    FOR SELECT
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           OR (tenant_id IS NULL AND current_setting('app.platform_scope', true) = 'on'));
    """,
    """\
CREATE POLICY tenant_write ON audit.export_log
    FOR INSERT
    WITH CHECK (tenant_id IS NULL OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    "ALTER TABLE audit.retention_policy_runs ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_read ON audit.retention_policy_runs
    FOR SELECT
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           OR (tenant_id IS NULL AND current_setting('app.platform_scope', true) = 'on'));
    """,
    """\
CREATE POLICY tenant_write ON audit.retention_policy_runs
    FOR INSERT
    WITH CHECK (tenant_id IS NULL OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_modify ON audit.retention_policy_runs
    FOR UPDATE
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_delete ON audit.retention_policy_runs
    FOR DELETE
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    "ALTER TABLE auth.api_keys ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON auth.api_keys
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE auth.delegated_access_grants ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON auth.delegated_access_grants
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE auth.identity_providers ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_read ON auth.identity_providers
    FOR SELECT
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           OR (tenant_id IS NULL AND current_setting('app.platform_scope', true) = 'on'));
    """,
    """\
CREATE POLICY tenant_write ON auth.identity_providers
    FOR INSERT
    WITH CHECK (tenant_id IS NULL OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_modify ON auth.identity_providers
    FOR UPDATE
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_delete ON auth.identity_providers
    FOR DELETE
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    "ALTER TABLE auth.invitations ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON auth.invitations
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE auth.login_attempts ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_read ON auth.login_attempts
    FOR SELECT
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           OR (tenant_id IS NULL AND current_setting('app.platform_scope', true) = 'on'));
    """,
    """\
CREATE POLICY tenant_write ON auth.login_attempts
    FOR INSERT
    WITH CHECK (tenant_id IS NULL OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_modify ON auth.login_attempts
    FOR UPDATE
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_delete ON auth.login_attempts
    FOR DELETE
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """,
    "ALTER TABLE auth.membership_brand_scopes ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON auth.membership_brand_scopes
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE auth.membership_vendor_scopes ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON auth.membership_vendor_scopes
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE auth.memberships ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY identity_read ON auth.memberships
    FOR SELECT
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           OR user_id = nullif(current_setting('app.identity_user_id', true), '')::uuid);
    """,
    """\
CREATE POLICY tenant_insert ON auth.memberships
    FOR INSERT
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    """\
CREATE POLICY tenant_modify ON auth.memberships
    FOR UPDATE
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    """\
CREATE POLICY tenant_delete ON auth.memberships
    FOR DELETE
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.attendance ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.attendance
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.brands ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.brands
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.campaigns ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.campaigns
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.candidate_programs ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.candidate_programs
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.event_costs ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.event_costs
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.event_speakers ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.event_speakers
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.event_workflow_transitions ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.event_workflow_transitions
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.events ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.events
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.feature_flags ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.feature_flags
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.finance_assumptions ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.finance_assumptions
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.finance_versions ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.finance_versions
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.hcp_identifiers ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.hcp_identifiers
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.hcp_rx_monthly ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.hcp_rx_monthly
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.hcps ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.hcps
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.invitations ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.invitations
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.market_factors ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.market_factors
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.marketing_activity ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.marketing_activity
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.notifications ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.notifications
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.products ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.products
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.saved_views ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.saved_views
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.taxonomy_values ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.taxonomy_values
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.vendor_dataset_grants ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.vendor_dataset_grants
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE core.vendors ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON core.vendors
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ingestion.column_mapping_templates ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ingestion.column_mapping_templates
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ingestion.data_versions ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ingestion.data_versions
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ingestion.identity_resolution_tasks ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ingestion.identity_resolution_tasks
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ingestion.quarantine_rows ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ingestion.quarantine_rows
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ingestion.raw_objects ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ingestion.raw_objects
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ingestion.upload_issues ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ingestion.upload_issues
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ingestion.upload_sessions ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ingestion.upload_sessions
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ml.conformal_calibration ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ml.conformal_calibration
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ml.drift_snapshots ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ml.drift_snapshots
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ml.model_features ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ml.model_features
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ml.model_metrics ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ml.model_metrics
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ml.model_promotions ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ml.model_promotions
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ml.model_specs ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ml.model_specs
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ml.model_versions ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ml.model_versions
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    "ALTER TABLE ml.pooled_priors ENABLE ROW LEVEL SECURITY;",
    """\
CREATE POLICY tenant_isolation ON ml.pooled_priors
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """,
    # --- Privileges -----------------------------------------------------
    "REVOKE ALL ON SCHEMA public FROM PUBLIC;",
    "REVOKE ALL ON SCHEMA auth FROM PUBLIC;",
    "REVOKE ALL ON SCHEMA core FROM PUBLIC;",
    "REVOKE ALL ON SCHEMA ingestion FROM PUBLIC;",
    "REVOKE ALL ON SCHEMA analytics FROM PUBLIC;",
    "REVOKE ALL ON SCHEMA ml FROM PUBLIC;",
    "REVOKE ALL ON SCHEMA audit FROM PUBLIC;",
    """\
DO $$ BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO app_migrator, app_rw, app_ro',
                   current_database());
EXCEPTION WHEN insufficient_privilege THEN
    RAISE WARNING 'could not revoke PUBLIC access to the database;'
                  ' grant ownership to app_migrator and re-run';
END $$;
    """,
    "GRANT USAGE ON SCHEMA auth TO app_rw, app_ro;",
    "GRANT USAGE ON SCHEMA core TO app_rw, app_ro;",
    "GRANT USAGE ON SCHEMA ingestion TO app_rw, app_ro;",
    "GRANT USAGE ON SCHEMA analytics TO app_rw, app_ro;",
    "GRANT USAGE ON SCHEMA ml TO app_rw, app_ro;",
    "GRANT USAGE ON SCHEMA audit TO app_rw, app_ro;",
    "GRANT SELECT, INSERT ON analytics.ai_interactions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.analysis_runs TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.cohort_members TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.cohorts TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.data_health_snapshots TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.estimator_specs TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.event_impact_gates TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.event_impacts TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.event_study_points TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.forecasts TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.optimizer_runs TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.portfolio_aggregates TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.propensity_scores TO app_rw;",
    "GRANT SELECT, INSERT ON analytics.reviews TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.roi_results TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.scenario_allocations TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.scenario_constraints TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.scenarios TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.sensitivity_results TO app_rw;",
    "GRANT SELECT, INSERT ON audit.audit_events TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON audit.erasure_requests TO app_rw;",
    "GRANT SELECT, INSERT ON audit.export_log TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON audit.retention_policy_runs TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.api_keys TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.delegated_access_grants TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.identity_providers TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.invitations TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.login_attempts TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.membership_brand_scopes TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.membership_vendor_scopes TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.memberships TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.password_reset_tokens TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.sessions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth.users TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.attendance TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.brands TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.campaigns TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.candidate_programs TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.currencies TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.event_costs TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.event_speakers TO app_rw;",
    "GRANT SELECT, INSERT ON core.event_workflow_transitions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.events TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.feature_flags TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.finance_assumptions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.finance_versions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.fx_rates TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.hcp_identifiers TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.hcp_rx_monthly TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.hcps TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.invitations TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.market_factors TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.marketing_activity TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.notifications TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.products TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.saved_views TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.taxonomy_values TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.tenants TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.vendor_dataset_grants TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON core.vendors TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion.column_mapping_templates TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion.data_versions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion.dataset_contracts TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion.identity_resolution_tasks TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion.quarantine_rows TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion.raw_objects TO app_rw;",
    "GRANT SELECT, INSERT ON ingestion.upload_issues TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion.upload_sessions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ml.conformal_calibration TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ml.drift_snapshots TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ml.model_features TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ml.model_metrics TO app_rw;",
    "GRANT SELECT, INSERT ON ml.model_promotions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ml.model_specs TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ml.model_versions TO app_rw;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ml.pooled_priors TO app_rw;",
    "GRANT USAGE ON SCHEMA public TO app_rw, app_ro;",
    "GRANT SELECT ON public.alembic_version TO app_rw, app_ro;",
    """\
DO $$ BEGIN
    EXECUTE format('ALTER DATABASE %I SET app.platform_scope = ''off''',
                   current_database());
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'skipped ALTER DATABASE SET app.platform_scope'
                 ' (migration role does not own the database)';
END $$;
    """,
)

DOWNGRADE_SQL: tuple[str, ...] = (
    "DROP SCHEMA IF EXISTS audit CASCADE;",
    "DROP SCHEMA IF EXISTS ml CASCADE;",
    "DROP SCHEMA IF EXISTS analytics CASCADE;",
    "DROP SCHEMA IF EXISTS ingestion CASCADE;",
    "DROP SCHEMA IF EXISTS core CASCADE;",
    "DROP SCHEMA IF EXISTS auth CASCADE;",
)


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
