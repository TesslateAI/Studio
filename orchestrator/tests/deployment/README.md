# Deployment Tests

Comprehensive test suite for Phase 1 of the deployment implementation (Secrets & Credential Management).

## Test Coverage

### Phase 1: Secrets & Credential Management ✅

**Total Tests: 57 (All Passing)**

#### Unit Tests (45 tests)

**DeploymentEncryptionService** (24 tests):
- Service initialization with different key sources
- Encryption and decryption operations
- Round-trip encryption/decryption
- Key validation and generation
- Error handling for invalid keys and corrupted data
- Unicode and special character support
- Edge cases (empty strings, very long credentials, null bytes)
- Global singleton service management

**DeploymentCredential Model** (11 tests):
- Model structure and required fields
- Instance creation (default and project-specific)
- Complex JSON metadata storage
- Multiple providers support
- Table and relationship configuration
- Database constraints (nullable fields, required fields)

**Deployment Model** (10 tests):
- Model structure and required fields
- Deployment instance creation
- Log and metadata storage
- Status progression
- Error handling
- Table and relationship configuration

#### Integration Tests (12 tests)

**Credential Storage Workflow**:
- Complete encrypt-store-retrieve-decrypt flow
- Multiple providers management
- Default credentials and project-specific overrides
- Credential updates and rotation
- Key rotation scenarios
- Project isolation
- Global service consistency
- Provider-specific metadata variations
- Error handling in workflows
- Empty token handling

## Test Organization

```
tests/deployment/
├── __init__.py
├── README.md                      # This file
├── unit/                          # Unit tests (45 tests)
│   ├── __init__.py
│   ├── test_encryption_service.py # Encryption service tests (24)
│   └── test_credential_model.py   # Model structure tests (21)
└── integration/                   # Integration tests (12 tests)
    ├── __init__.py
    └── test_credential_storage.py # Workflow tests (12)
```

## Running Tests

### Run All Deployment Tests
```bash
pytest tests/deployment/ -v
```

### Run by Category
```bash
# Unit tests only
pytest tests/deployment/unit/ -v

# Integration tests only
pytest tests/deployment/integration/ -v
```

### Run Specific Test Files
```bash
# Encryption service tests
pytest tests/deployment/unit/test_encryption_service.py -v

# Model tests
pytest tests/deployment/unit/test_credential_model.py -v

# Workflow tests
pytest tests/deployment/integration/test_credential_storage.py -v
```

### Run by Marker
```bash
# All unit tests
pytest tests/deployment/ -m unit -v

# All integration tests
pytest tests/deployment/ -m integration -v
```

### With Coverage
```bash
pytest tests/deployment/ --cov=app.services.deployment_encryption --cov=app.models --cov-report=html
```

## Implementation Status

### ✅ Completed Components

1. **DeploymentCredential Model** (`orchestrator/app/models.py:243`)
   - Fields: id, user_id, project_id, provider, access_token_encrypted, provider_metadata
   - Relationships: User, Project
   - Supports both default credentials and project-specific overrides

2. **Deployment Model** (`orchestrator/app/models.py:280`)
   - Fields: id, project_id, user_id, provider, deployment_id, deployment_url, status, error, logs, deployment_metadata
   - Tracks deployment history and status

3. **DeploymentEncryptionService** (`orchestrator/app/services/deployment_encryption.py`)
   - Fernet symmetric encryption
   - Key derivation from settings
   - Encrypt/decrypt operations
   - Key validation and generation
   - Global singleton pattern

4. **Database Migration** (`orchestrator/alembic/versions/a1b2c3d4e5f6_add_deployment_models.py`)
   - Creates deployment_credentials table
   - Creates deployments table
   - Proper indexes and constraints

### 📝 Important Notes

**Metadata Field Naming**:
- The database column is named `metadata`
- Python attribute is `provider_metadata` for DeploymentCredential
- Python attribute is `deployment_metadata` for Deployment
- This avoids conflicts with SQLAlchemy's reserved `metadata` attribute

**Credential Storage Pattern**:
- `project_id = NULL`: Default credential for the user/provider
- `project_id = <uuid>`: Project-specific override
- Unique constraint: `(user_id, provider, project_id)`
- PostgreSQL treats NULL values as distinct, allowing multiple NULL project_ids

**Security**:
- All credentials are encrypted before storage using Fernet symmetric encryption
- Encryption key can be set via `DEPLOYMENT_ENCRYPTION_KEY` env var
- Falls back to deriving key from `SECRET_KEY` if not set
- Key validation ensures encryption/decryption works correctly

## Future Tests (Phase 2+)

When API endpoints and deployment providers are implemented, add:
- E2E tests for OAuth flows (Vercel, Netlify)
- E2E tests for API token management (Cloudflare)
- API endpoint tests for CRUD operations
- Provider-specific deployment tests
- Multi-provider deployment scenarios

## Test Maintenance

Last Updated: 2025-01-15
Test Count: 57 tests
Coverage: 100% of Phase 1 implementation
Status: All Passing ✅
