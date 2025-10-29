# Agent Shell Command Execution API

## Overview

The Agent API provides a secure, auditable interface for AI agents to execute shell commands in user development pods. This implementation follows modern security best practices and leverages the existing Kubernetes infrastructure.

## Architecture

### Components

1. **Command Validator** (`orchestrator/app/services/command_validator.py`)
   - Validates commands against allowlist/blocklist
   - Detects dangerous patterns (command injection, shell escaping, etc.)
   - Assesses risk levels (safe, moderate, high, blocked)
   - Sanitizes commands for safe execution

2. **Audit Service** (`orchestrator/app/services/agent_audit.py`)
   - Logs all command executions to database
   - Provides command history and statistics
   - Detects suspicious activity patterns
   - Enables compliance and security monitoring

3. **Agent Router** (`orchestrator/app/routers/agent.py`)
   - RESTful API endpoints for command execution
   - JWT authentication and authorization
   - Rate limiting (30 commands/minute per user)
   - Project ownership verification

4. **Database Model** (`orchestrator/app/models.py` - AgentCommandLog)
   - Stores comprehensive audit trail
   - Tracks success/failure, duration, risk level
   - Links commands to users and projects

## Security Features

### 1. Authentication & Authorization
- **JWT Token Required**: All requests must include valid Bearer token
- **User Verification**: Only project owners can execute commands in their pods
- **Project Isolation**: Users can only access their own projects

### 2. Command Validation

**Allowed Commands:**
```
File operations: cat, ls, mkdir, touch, rm, cp, mv, pwd, find, grep, etc.
Build tools: npm, npx, node, yarn, pnpm, vite, webpack
Git operations: git
Process management: ps, kill, pkill (limited)
Utilities: echo, date, whoami, tar, zip
```

**Blocked Commands:**
```
Privilege escalation: sudo, su, systemctl
Network operations: curl, wget, nc, telnet (unless explicitly enabled)
System modification: mount, reboot, shutdown
Dangerous shells: eval, exec, source
Compilers: gcc, python3, perl, ruby (prevent code execution)
```

**Dangerous Patterns Detected:**
```
rm -rf /                    # Recursive delete from root
$(command)                  # Command substitution
`command`                   # Backtick substitution
| sh / | bash              # Piping to shell
> /etc/ or > /dev/         # Writing to system directories
/var/run/docker.sock       # Docker socket access
```

### 3. Rate Limiting
- **30 commands per minute** per user
- Prevents command spam and potential abuse
- Returns HTTP 429 when limit exceeded

### 4. Audit Logging
- **All commands logged** to database (successful and failed)
- Tracks: user, project, command, output, duration, risk level
- **Suspicious activity detection**:
  - Rapid command execution (>50 commands in 5 minutes)
  - High failure rate (>50% failures)
  - Excessive file deletions (>10 rm commands)
  - Repeated high-risk commands (>5 in 5 minutes)

### 5. Dry-Run Mode
- Test commands without actual execution
- Validates command safety before running
- Useful for agent development and testing

## API Endpoints

### 1. Execute Command
**POST** `/api/agent/execute`

Execute a shell command in a user's development pod.

**Request:**
```json
{
  "project_id": 123,
  "command": "npm run build",
  "working_dir": ".",
  "timeout": 60,
  "dry_run": false
}
```

**Parameters:**
- `project_id` (int, required): Project ID to execute command in
- `command` (string, required): Shell command to execute (max 1000 chars)
- `working_dir` (string, optional): Working directory relative to `/app/project` (default: ".")
- `timeout` (int, optional): Command timeout in seconds (1-300, default: 60)
- `dry_run` (bool, optional): If true, validates command without executing (default: false)

**Response (200 OK):**
```json
{
  "success": true,
  "command": "npm run build",
  "stdout": "Build completed successfully...",
  "stderr": "",
  "exit_code": 0,
  "duration_ms": 1234,
  "risk_level": "safe",
  "dry_run": false,
  "command_id": 42,
  "message": "Command executed successfully"
}
```

**Error Responses:**
- `400 Bad Request`: Command validation failed
- `401 Unauthorized`: Invalid or missing JWT token
- `404 Not Found`: Project not found or access denied
- `429 Too Many Requests`: Rate limit exceeded
- `503 Service Unavailable`: Development environment not ready

### 2. Get Command History
**GET** `/api/agent/history/{project_id}?limit=50`

Get command execution history for a project.

**Parameters:**
- `project_id` (path, int): Project ID
- `limit` (query, int): Maximum entries to return (default: 50, max: 200)

**Response (200 OK):**
```json
[
  {
    "id": 42,
    "user_id": 1,
    "project_id": 123,
    "command": "npm run build",
    "working_dir": ".",
    "success": true,
    "exit_code": 0,
    "duration_ms": 1234,
    "risk_level": "safe",
    "dry_run": false,
    "created_at": "2025-01-15T10:30:00Z"
  }
]
```

### 3. Get Command Statistics
**GET** `/api/agent/stats?days=7`

Get command execution statistics for the current user.

**Parameters:**
- `days` (query, int): Days to look back (default: 7, max: 30)

**Response (200 OK):**
```json
{
  "total_commands": 150,
  "successful_commands": 145,
  "failed_commands": 5,
  "high_risk_commands": 3,
  "average_duration_ms": 2500,
  "period_days": 7
}
```

### 4. Health Check
**GET** `/api/agent/health`

Check agent API service health.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "agent-api",
  "features": {
    "command_execution": true,
    "audit_logging": true,
    "rate_limiting": true,
    "command_validation": true
  }
}
```

## Usage Examples

### Using curl

```bash
# 1. Get JWT token
TOKEN=$(curl -X POST http://localhost:8000/api/auth/token \
  -d "username=testuser&password=testpass" | jq -r .access_token)

# 2. Execute command
curl -X POST http://localhost:8000/api/agent/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 123,
    "command": "npm run build",
    "timeout": 120
  }'

# 3. Try dry-run first
curl -X POST http://localhost:8000/api/agent/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 123,
    "command": "rm -rf node_modules",
    "dry_run": true
  }'

# 4. Get command history
curl http://localhost:8000/api/agent/history/123?limit=10 \
  -H "Authorization: Bearer $TOKEN"

# 5. Get statistics
curl http://localhost:8000/api/agent/stats?days=7 \
  -H "Authorization: Bearer $TOKEN"
```

### Using Python

```python
import requests

# Get token
response = requests.post(
    "http://localhost:8000/api/auth/token",
    data={"username": "testuser", "password": "testpass"}
)
token = response.json()["access_token"]

# Execute command
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

response = requests.post(
    "http://localhost:8000/api/agent/execute",
    headers=headers,
    json={
        "project_id": 123,
        "command": "npm run build",
        "timeout": 120
    }
)

result = response.json()
print(f"Success: {result['success']}")
print(f"Output: {result['stdout']}")
print(f"Duration: {result['duration_ms']}ms")
```

### Using JavaScript/TypeScript

```typescript
// Get token
const authResponse = await fetch("http://localhost:8000/api/auth/token", {
  method: "POST",
  body: new URLSearchParams({
    username: "testuser",
    password: "testpass"
  })
});
const { access_token } = await authResponse.json();

// Execute command
const response = await fetch("http://localhost:8000/api/agent/execute", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${access_token}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    project_id: 123,
    command: "npm run build",
    timeout: 120
  })
});

const result = await response.json();
console.log(`Success: ${result.success}`);
console.log(`Output: ${result.stdout}`);
console.log(`Duration: ${result.duration_ms}ms`);
```

## Common Use Cases

### 1. Build Project
```json
{
  "project_id": 123,
  "command": "npm run build",
  "timeout": 180
}
```

### 2. Install Dependencies
```json
{
  "project_id": 123,
  "command": "npm install",
  "timeout": 180
}
```

### 3. Run Tests
```json
{
  "project_id": 123,
  "command": "npm test",
  "timeout": 120
}
```

### 4. List Files
```json
{
  "project_id": 123,
  "command": "ls -la src/",
  "working_dir": "."
}
```

### 5. Read File Content
```json
{
  "project_id": 123,
  "command": "cat package.json"
}
```

### 6. Git Status
```json
{
  "project_id": 123,
  "command": "git status"
}
```

## Testing

Run the test suite to verify command validation:

```bash
cd orchestrator
python test_agent_api.py
```

The test suite validates:
- Safe command allowlist
- Dangerous command blocklist
- Pattern-based security detection
- Command sanitization
- Edge cases and malformed input

## Deployment

### 1. Database Migration
The `AgentCommandLog` table will be automatically created when you start the orchestrator service (using SQLAlchemy's `create_all` on startup).

For production, create a proper migration:

```bash
# If using Alembic
alembic revision --autogenerate -m "Add AgentCommandLog table"
alembic upgrade head
```

### 2. Start Service
```bash
cd orchestrator
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Verify Health
```bash
curl http://localhost:8000/api/agent/health
```

## Monitoring & Operations

### Audit Logs
Query the `agent_command_logs` table to:
- Review command history
- Investigate security incidents
- Monitor agent behavior
- Generate compliance reports

```sql
-- Recent commands by user
SELECT command, success, created_at
FROM agent_command_logs
WHERE user_id = 1
ORDER BY created_at DESC
LIMIT 10;

-- Failed commands
SELECT user_id, command, stderr, created_at
FROM agent_command_logs
WHERE success = false
ORDER BY created_at DESC;

-- High-risk commands
SELECT user_id, command, risk_level, created_at
FROM agent_command_logs
WHERE risk_level IN ('high', 'moderate')
ORDER BY created_at DESC;
```

### Rate Limiting
The rate limiter is in-memory per backend instance. For production with multiple backend replicas, consider:
- Redis for distributed rate limiting
- Nginx rate limiting at ingress level
- API Gateway rate limiting

### Suspicious Activity Alerts
Implement alerting based on the suspicious activity detection:

```python
from orchestrator.app.services.agent_audit import get_audit_service

audit_service = get_audit_service(db)
suspicious = await audit_service.detect_suspicious_activity(
    user_id=user_id,
    time_window_minutes=5
)

if suspicious["is_suspicious"]:
    for alert in suspicious["alerts"]:
        # Send alert to monitoring system
        logger.warning(f"Security Alert: {alert['message']}")
```

## Future Enhancements

1. **WebSocket Streaming** (optional): Add real-time command output streaming for long-running commands
2. **Command Templates**: Pre-approved command templates for common operations
3. **Multi-command Transactions**: Execute multiple commands atomically
4. **Resource Monitoring**: Track CPU/memory usage during command execution
5. **Interactive Shell**: PTY support for interactive terminal sessions (advanced use case)

## Security Considerations

### DO ✅
- Always use JWT authentication
- Verify project ownership
- Enable audit logging
- Monitor suspicious activity
- Use dry-run mode for testing
- Set appropriate timeouts
- Review command history regularly

### DON'T ❌
- Bypass command validation
- Execute commands as root
- Disable rate limiting
- Allow unlimited command length
- Execute untrusted user input directly
- Disable audit logging
- Grant network access without justification

## Support & Troubleshooting

### Common Issues

**1. "Development environment not found"**
- Ensure the dev server is started for the project
- Check pod status: `kubectl get pods -n tesslate-user-environments`

**2. "Rate limit exceeded"**
- Wait 60 seconds for rate limit window to reset
- Reduce command frequency
- Contact admin if legitimate high-frequency use case

**3. "Command validation failed"**
- Review command against allowlist/blocklist
- Check for dangerous patterns
- Use dry-run mode to test validation
- Request command whitelist addition if needed

**4. "Command timed out"**
- Increase timeout value
- Check if command is actually long-running
- Consider splitting into multiple commands

For additional support, see the test script (`test_agent_api.py`) for examples.
