-- Initialisation script for the Docker Compose PostgreSQL container.
-- Mirrors the role and database setup in scripts/devtools/pg.py.

-- Roles
CREATE ROLE app_migrator LOGIN PASSWORD 'app_migrator_pw' CREATEROLE;
CREATE ROLE app_rw LOGIN PASSWORD 'app_rw_pw';
CREATE ROLE app_ro LOGIN PASSWORD 'app_ro_pw';

-- Databases
CREATE DATABASE speaker_roi OWNER app_migrator;
CREATE DATABASE speaker_roi_test OWNER app_migrator;

-- Schemas and grants (applied to both databases)
\connect speaker_roi
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION app_migrator;
CREATE SCHEMA IF NOT EXISTS core AUTHORIZATION app_migrator;
CREATE SCHEMA IF NOT EXISTS ingestion AUTHORIZATION app_migrator;
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION app_migrator;
CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION app_migrator;
GRANT USAGE ON SCHEMA auth, core, ingestion, audit, analytics TO app_rw, app_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migrator IN SCHEMA auth, core, ingestion, audit, analytics
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migrator IN SCHEMA auth, core, ingestion, audit, analytics
    GRANT SELECT ON TABLES TO app_ro;

\connect speaker_roi_test
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION app_migrator;
CREATE SCHEMA IF NOT EXISTS core AUTHORIZATION app_migrator;
CREATE SCHEMA IF NOT EXISTS ingestion AUTHORIZATION app_migrator;
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION app_migrator;
CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION app_migrator;
GRANT USAGE ON SCHEMA auth, core, ingestion, audit, analytics TO app_rw, app_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migrator IN SCHEMA auth, core, ingestion, audit, analytics
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migrator IN SCHEMA auth, core, ingestion, audit, analytics
    GRANT SELECT ON TABLES TO app_ro;
