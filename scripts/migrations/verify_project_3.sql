-- Check project 3 and its dependencies
SELECT 'Projects' as table_name, COUNT(*) as count FROM projects WHERE id = 3
UNION ALL
SELECT 'Shell Sessions', COUNT(*) FROM shell_sessions WHERE project_id = 3
UNION ALL
SELECT 'Chats', COUNT(*) FROM chats WHERE project_id = 3
UNION ALL
SELECT 'Agent Command Logs', COUNT(*) FROM agent_command_logs WHERE project_id = 3;
