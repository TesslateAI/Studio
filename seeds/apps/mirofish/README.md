# MiroFish (seed)

Upstream: https://github.com/666ghj/MiroFish

Uses the upstream-published image `ghcr.io/666ghj/mirofish:latest` directly —
no Dockerfile is shipped in this seed directory because the upstream repo
already provides a reproducible image.

## Prerequisite: load the image into minikube

The image must exist in minikube's node cache before install (our
`K8S_IMAGE_PULL_POLICY=Never` setting for minikube means K8s won't try to
pull from GHCR at pod-create time):

```bash
# One-time: pull to host Docker, then import into minikube.
docker pull ghcr.io/666ghj/mirofish:latest
minikube -p tesslate image load ghcr.io/666ghj/mirofish:latest
```

## Secrets

The manifest references `${secret:llama-api-credentials/api_key}`. Ensure the
secret already exists in the `tesslate` namespace (same pattern as the CRM
demo app):

```bash
kubectl --context=tesslate -n tesslate create secret generic \
  llama-api-credentials --from-literal=api_key='<your-llama-api-key>'
```

Update `LLM_BASE_URL` / `LLM_MODEL_NAME` in the manifest if you prefer a
different OpenAI-compatible backend (e.g. Alibaba Qwen via Bailian — the
upstream README's default).

## Ports

- `3000` — Next.js frontend (primary surface)
- `5001` — FastAPI backend (proxied by the frontend; not exposed as a
  separate surface in the Tesslate manifest)
