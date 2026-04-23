# LiteLLM Scripts

> Scripts for managing LiteLLM teams, virtual keys, default models, and user budgets. Run these after changes to `LITELLM_DEFAULT_MODELS`, `LITELLM_TEAM_ID`, or `LITELLM_INITIAL_BUDGET`.

## Context

LiteLLM is the model gateway between OpenSail and OpenAI / Anthropic / Qwen / Llama. Each user gets:

- A LiteLLM account.
- A virtual key issued in the `internal` team (or whatever `LITELLM_TEAM_ID` is set to).
- A budget cap (defaults to `LITELLM_INITIAL_BUDGET`).

When defaults drift, existing keys have to be patched. That is what these scripts do.

## One-shot setup

| Step | Script |
|------|--------|
| 1. Create the `internal` team | `litellm/create_litellm_team.py` |
| 2. Issue keys for any missing users | `litellm/fix_user_keys.py` |
| 3. Add users to the team + refresh their keys | `litellm/setup_user_litellm.py` |
| 4. Confirm every model is reachable | `litellm/check_models.py` |

## Ongoing operations

| Script | When to run |
|--------|-------------|
| `litellm/update_litellm_models.py` | `LITELLM_DEFAULT_MODELS` changed; user keys need the new allowlist. |
| `litellm/update_litellm_team.py` | Team rename or rotation; rewrite keys to the new team. |
| `litellm/migrate_litellm_keys.py` | Per-user keys feature just shipped; backfill keys for pre-existing users. |
| `litellm/create_virtual_key_for_user.py` | Issue or rotate a single user's key without touching others. |
| `litellm/create_key_direct.py` | Spot-create a key outside the user flow (testing only). |
| `litellm/test_litellm_endpoints.py` | Probe URL permutations when LiteLLM responses look wrong. |
| `scripts/regenerate_user_keys.py` (root) | Re-issue every user key without per-key model restrictions. |
| `scripts/seed/bump_litellm_budgets.py` | Raise every budget cap to the new default. |

## Environment

Most scripts pull `LITELLM_API_BASE` and `LITELLM_MASTER_KEY` from the current orchestrator `.env` or directly from the beta k8s cluster. See [/home/smirk/Tesslate-Studio/.env.example](../../.env.example) for required variables.

## Related

- LiteLLM service implementation: `orchestrator/app/services/litellm_service.py`
- Model pricing doc: [docs/orchestrator/services/model-pricing.md](../orchestrator/services/model-pricing.md)
- Credit system: [docs/orchestrator/services/credit-system.md](../orchestrator/services/credit-system.md)
