# DeerFlow (seed)

Upstream: https://github.com/bytedance/deer-flow (2.0)

DeerFlow's production setup is four containers (nginx + frontend + gateway +
langgraph). This seed collapses it to a single container that runs
`make dev` — fine for install + click-through verification, not production.

## Build

The image must exist in minikube's node cache before install. The build is
heavy (~2GB image, ~5-10 min) because upstream pulls all of Python 3.12 + uv
+ Node 22 + pnpm and installs both backend (uv sync) and frontend
(pnpm install) dependencies.

```bash
# Build into minikube's docker daemon directly.
eval $(minikube -p tesslate docker-env)
docker build -t tesslate-deerflow:latest seeds/apps/deer-flow/
```

(If WSL/Docker integration isn't available, build on any machine with docker,
save to tar, and `minikube -p tesslate image load deerflow.tar`.)

## Secrets

Reuses the existing `llama-api-credentials` secret pattern:

```bash
kubectl --context=tesslate -n tesslate create secret generic \
  llama-api-credentials --from-literal=api_key='<your-llama-api-key>'
```

`LLM_BASE_URL` and `LLM_MODEL` in the manifest target Meta's Llama API
endpoint (OpenAI-compatible). Point them at any OpenAI-compatible LLM by
editing the manifest before publishing.

## Known limitations

- `BETTER_AUTH_SECRET` in the manifest is a hard-coded placeholder. For any
  real use, override it per-install via a namespace-scoped secret (same
  pattern as `pg-creds` on the `crm-with-postgres` app).
- The upstream sandbox (`SANDBOX_MODE=disabled` in `config.yaml`) is off
  because nested-docker isn't wired in this seed. Sandbox-needing skills
  will no-op.
- First boot takes a long time: `make dev` runs frontend + backend + langgraph
  and each has its own warm-up. Allow ≥ 90s for the surface to become
  reachable.
