#!/bin/bash
# Assign passwords and schema setup for Supabase internal service roles.
# Runs once at container first-start via docker-entrypoint-initdb.d.
#
# The public.ecr.aws/supabase/postgres image creates these roles WITHOUT passwords
# (SCRAM auth fails). We assign POSTGRES_PASSWORD so gotrue/postgrest/realtime
# can connect. We also create the _realtime schema and transfer auth ownership.
set -e

PW="${POSTGRES_PASSWORD:-postgres}"

# The public.ecr.aws/supabase/postgres image uses 'supabase_admin' as the superuser
SUPER_USER="${POSTGRES_USER:-supabase_admin}"
psql -v ON_ERROR_STOP=1 --username "$SUPER_USER" --dbname "${POSTGRES_DB:-postgres}" <<EOSQL
-- Set passwords for service roles
DO \$body\$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
    EXECUTE format('ALTER ROLE supabase_auth_admin WITH PASSWORD %L', '$PW');
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticator') THEN
    EXECUTE format('ALTER ROLE authenticator WITH PASSWORD %L', '$PW');
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_replication_admin') THEN
    EXECUTE format('ALTER ROLE supabase_replication_admin WITH PASSWORD %L', '$PW');
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_admin') THEN
    EXECUTE format('ALTER ROLE supabase_admin WITH PASSWORD %L', '$PW');
  END IF;
END \$body\$;

-- Transfer auth schema/function ownership so gotrue migrations can run
DO \$body\$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth') THEN
    EXECUTE 'ALTER SCHEMA auth OWNER TO supabase_auth_admin';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace=n.oid WHERE n.nspname='auth' AND p.proname='uid') THEN
    EXECUTE 'ALTER FUNCTION auth.uid() OWNER TO supabase_auth_admin';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace=n.oid WHERE n.nspname='auth' AND p.proname='role') THEN
    EXECUTE 'ALTER FUNCTION auth.role() OWNER TO supabase_auth_admin';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace=n.oid WHERE n.nspname='auth' AND p.proname='email') THEN
    EXECUTE 'ALTER FUNCTION auth.email() OWNER TO supabase_auth_admin';
  END IF;
END \$body\$;

-- Create _realtime schema for supabase-realtime service
CREATE SCHEMA IF NOT EXISTS _realtime;
DO \$body\$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_replication_admin') THEN
    EXECUTE 'GRANT ALL ON SCHEMA _realtime TO supabase_replication_admin';
    EXECUTE 'ALTER ROLE supabase_replication_admin SET search_path TO _realtime';
  END IF;
END \$body\$;
EOSQL
