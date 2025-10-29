-- Migration: Add CASCADE DELETE to project foreign key constraints
-- This fixes foreign key violation errors when deleting projects

BEGIN;

-- 1. Update shell_sessions.project_id constraint
ALTER TABLE shell_sessions DROP CONSTRAINT IF EXISTS shell_sessions_project_id_fkey;
ALTER TABLE shell_sessions ADD CONSTRAINT shell_sessions_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- 2. Update chats.project_id constraint
ALTER TABLE chats DROP CONSTRAINT IF EXISTS chats_project_id_fkey;
ALTER TABLE chats ADD CONSTRAINT chats_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- 3. Update agent_command_logs.project_id constraint
ALTER TABLE agent_command_logs DROP CONSTRAINT IF EXISTS agent_command_logs_project_id_fkey;
ALTER TABLE agent_command_logs ADD CONSTRAINT agent_command_logs_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

COMMIT;

-- Verify constraints
SELECT
    tc.table_name,
    tc.constraint_name,
    rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.referential_constraints rc
    ON tc.constraint_name = rc.constraint_name
WHERE tc.constraint_name IN (
    'shell_sessions_project_id_fkey',
    'chats_project_id_fkey',
    'agent_command_logs_project_id_fkey'
)
ORDER BY tc.table_name;
