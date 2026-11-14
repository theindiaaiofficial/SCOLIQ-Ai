-- SCOLIQ AI: backend-only Supabase/PostgreSQL role and RLS setup.
-- Run as the Supabase project postgres/schema-owner role AFTER `alembic upgrade head`.
-- Replace the placeholder password with a newly generated password before execution.
-- Put that same value in Render DATABASE_URL (URL-encode special characters).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartattend_runtime') THEN
        CREATE ROLE smartattend_runtime;
    END IF;
END
$$;

ALTER ROLE smartattend_runtime
    WITH LOGIN
    PASSWORD 'REPLACE_WITH_A_LONG_RANDOM_DATABASE_PASSWORD'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE smartattend_runtime SET search_path = public;

GRANT CONNECT ON DATABASE postgres TO smartattend_runtime;
GRANT USAGE ON SCHEMA public TO smartattend_runtime;

-- The browser-facing Supabase roles must never read or write SCOLIQ AI records.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO smartattend_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO smartattend_runtime;

-- These defaults apply when Alembic creates future objects as the `postgres` role.
-- If migrations run as a different owner, change the FOR ROLE value accordingly.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO smartattend_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO smartattend_runtime;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'school_profile', 'users', 'admin_credentials', 'bootstrap_state',
        'teacher_access_requests', 'teacher_activation_tokens', 'passkey_credentials',
        'webauthn_challenges', 'app_sessions', 'classes', 'teacher_class_assignments',
        'students', 'student_class_enrollments', 'guardian_consent_records',
        'student_face_templates', 'attendance_sessions', 'attendance_scan_events',
        'attendance_session_marks', 'attendance_records', 'audit_logs'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('DROP POLICY IF EXISTS smartattend_backend_access ON public.%I', table_name);
        EXECUTE format(
            'CREATE POLICY smartattend_backend_access ON public.%I FOR ALL TO smartattend_runtime USING (true) WITH CHECK (true)',
            table_name
        );
    END LOOP;
END
$$;

-- Verify runtime role posture. The API service should connect using this role,
-- not `postgres`, `service_role`, `anon`, or `authenticated`.
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolinherit
FROM pg_roles
WHERE rolname = 'smartattend_runtime';
