# litellm config

Path: `k8s/litellm/config.yaml`. LiteLLM proxy configuration used by the in-cluster LiteLLM pod.

## Purpose

LiteLLM sits between OpenSail's backend and every upstream model provider (OpenAI, Anthropic, Azure, Together, etc.). The `config.yaml` defines the model list, routing rules, rate limits, and fallback chains.

## Consumed by

- AWS: Terraform `k8s/terraform/aws/litellm.tf` deploys a LiteLLM Deployment that mounts this file via ConfigMap.
- Minikube: the backend talks to LiteLLM via `LITELLM_API_BASE`; for pure-local dev the proxy is optional.

## Editing

1. Update `config.yaml` with new models or routing tweaks.
2. Apply via `kubectl apply -k k8s/overlays/aws-production --context=tesslate-production-eks` (the overlay picks up ConfigMap changes through Terraform on the next `apply`).
3. Restart LiteLLM so it re-reads the config: `kubectl rollout restart deployment/litellm -n tesslate`.

## Related

- `orchestrator/app/services/litellm_service.py` for the client side.
- `docs/orchestrator/services/model-pricing.md` for pricing metadata that flows from this config.
