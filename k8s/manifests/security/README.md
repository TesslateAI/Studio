# Kubernetes Secrets Configuration

This directory contains secret templates for Tesslate Studio.

## Quick Start

**Choose ONE approach:**

### Option A: Manual Configuration (Recommended for Production)

```bash
# 1. Copy the example file
cp app-secrets.yaml.example app-secrets.yaml

# 2. Generate secure secrets
openssl rand -base64 64  # For SECRET_KEY and JWT_SECRET
openssl rand -base64 32  # For database password

# 3. Edit app-secrets.yaml with your values
# Replace all REPLACE_WITH_* placeholders

# 4. Apply the secrets
kubectl apply -f app-secrets.yaml

# 5. Apply database secrets (if using PostgreSQL)
cp postgres-secret.yaml.example postgres-secret.yaml
# Edit postgres-secret.yaml
kubectl apply -f postgres-secret.yaml
```

### Option B: Auto-Generate (Quick Testing Only)

```bash
# Run the auto-generation script
cd ../../scripts/deployment
./setup-app-secrets.sh

# This will:
# - Auto-generate SECRET_KEY and database password
# - Use default Tesslate API configuration
# - Create both tesslate-app-secrets and postgres-secret
```

## Files

- `app-secrets.yaml.example` - Application secrets template (JWT, AI API, DB)
- `postgres-secret.yaml.example` - PostgreSQL credentials template
- `README.md` - This file

## Security Best Practices

✅ **DO:**
- Use Option A (manual) for production deployments
- Generate secrets with `openssl rand -base64 64`
- Store secrets in a password manager or vault
- Rotate secrets every 90 days
- Use different secrets for each environment (dev/staging/prod)

❌ **DON'T:**
- Commit secrets to version control (*.yaml files are gitignored)
- Use the auto-generate script for production
- Reuse secrets across environments
- Use weak or predictable values

## Secret Rotation

To rotate secrets:

```bash
# 1. Generate new values
openssl rand -base64 64

# 2. Update app-secrets.yaml with new values

# 3. Apply updated secrets
kubectl apply -f app-secrets.yaml

# 4. Rolling restart pods to pick up new secrets
kubectl rollout restart deployment -n tesslate
```

## Troubleshooting

**Secrets not found:**
```bash
# Check if secrets exist
kubectl get secrets -n tesslate

# View secret (base64 encoded)
kubectl get secret tesslate-app-secrets -n tesslate -o yaml

# Decode a secret value
kubectl get secret tesslate-app-secrets -n tesslate -o jsonpath='{.data.SECRET_KEY}' | base64 -d
```

**Need to update a single value:**
```bash
# Edit secret directly
kubectl edit secret tesslate-app-secrets -n tesslate

# Or patch it
kubectl patch secret tesslate-app-secrets -n tesslate \
  -p='{"stringData":{"OPENAI_API_KEY":"new-key-value"}}'
```
