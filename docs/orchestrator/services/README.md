# Orchestrator Services Documentation

This directory indexes every service module under `orchestrator/app/services/`. Services implement the core business logic for container orchestration, AI agents, payments, deployments, apps, storage, and more.

The services layer sits between the API routers and the data models. Routers stay thin and delegate to services; services own retries, encryption, external I/O, and coordination primitives.

## Service Index (by grouping doc)

### Container orchestration and compute

| File(s) | Doc |
|---------|-----|
| `orchestration/base.py`, `orchestration/deployment_mode.py`, `orchestration/factory.py`, `orchestration/docker.py`, `orchestration/local.py`, `orchestration/local_ports.py`, `orchestration/kubernetes_orchestrator.py`, `orchestration/kubernetes/client.py`, `orchestration/kubernetes/helpers.py`, `orchestration/kubernetes/manager.py`, `orchestration/kubernetes/__init__.py`, `orchestration/__init__.py` | [orchestration.md](./orchestration.md) |
| `compute_manager.py`, `hibernate.py`, `idle_monitor.py`, `activity_tracker.py`, `checkpoint_manager.py`, `namespace_reaper.py` | [compute-lifecycle.md](./compute-lifecycle.md) |
| `container_initializer.py`, `startup_generator.py`, `framework_detector.py`, `secret_manager_env.py`, `service_definitions.py`, `node_config_presets.py`, `command_validator.py`, `pty_broker.py`, `shell_session_manager.py`, `session_router.py` | [runtime-support.md](./runtime-support.md) |

### Storage, volumes, templates

| File(s) | Doc |
|---------|-----|
| `volume_manager.py`, `hub_client.py`, `fileops_client.py`, `nodeops_client.py`, `node_discovery.py` | [volume-manager.md](./volume-manager.md) |
| `snapshot_manager.py` | [snapshot-manager.md](./snapshot-manager.md) |
| `template_builder.py`, `template_export.py`, `template_storage.py` | [templates.md](./templates.md) |
| `project_fs.py`, `project_patcher.py`, `export_resolver.py`, `config_sync.py`, `base_config_parser.py` | [project-filesystem.md](./project-filesystem.md) |

### Project setup pipeline

| File(s) | Doc |
|---------|-----|
| `project_setup/__init__.py`, `project_setup/config_resolver.py`, `project_setup/container_creation.py`, `project_setup/file_placement.py`, `project_setup/naming.py`, `project_setup/pipeline.py`, `project_setup/source_acquisition.py` | [project-setup.md](./project-setup.md) |

### AI agents, models, context

| File(s) | Doc |
|---------|-----|
| `agent_context.py` | [agent-context.md](./agent-context.md) |
| `agent_task.py` | [agent-task.md](./agent-task.md) |
| `agent_handlers.py` | [worker.md](./worker.md) |
| `agent_approval.py`, `agent_budget.py`, `agent_tickets.py`, `agent_audit.py`, `subagent_configs.py`, `plan_manager.py`, `context_compaction.py`, `prompt_caching.py`, `model_adapters.py`, `model_health.py`, `model_vision.py`, `tesslate_agent_adapter.py`, `tesslate_parser.py` | [agent-runtime.md](./agent-runtime.md) |
| `skill_discovery.py`, `skill_markers.py` | [skill-discovery.md](./skill-discovery.md) |

### Task queue and pubsub

| File(s) | Doc |
|---------|-----|
| `task_queue/base.py`, `task_queue/arq_queue.py`, `task_queue/local_queue.py`, `task_queue/__init__.py` | [task-queue.md](./task-queue.md) |
| `pubsub/base.py`, `pubsub/redis_pubsub.py`, `pubsub/local_pubsub.py`, `pubsub/__init__.py` | [pubsub.md](./pubsub.md) |
| `distributed_lock.py` | [distributed-lock.md](./distributed-lock.md) |
| `task_manager.py` | [utilities.md](./utilities.md) |

### Messaging and gateway

| File(s) | Doc |
|---------|-----|
| `channels/base.py`, `channels/registry.py`, `channels/formatting.py`, `channels/media.py`, `channels/telegram.py`, `channels/slack.py`, `channels/discord_bot.py`, `channels/whatsapp.py`, `channels/signal.py`, `channels/cli_websocket.py`, `channels/__init__.py` | [channels.md](./channels.md) |
| `gateway/runner.py`, `gateway/scheduler.py`, `gateway/schedule_parser.py`, `gateway/__init__.py` | [gateway.md](./gateway.md) |

### MCP integration

| File(s) | Doc |
|---------|-----|
| `mcp/client.py`, `mcp/bridge.py`, `mcp/manager.py`, `mcp/oauth_flow.py`, `mcp/oauth_storage.py`, `mcp/sampling.py`, `mcp/scoping.py`, `mcp/security.py`, `mcp/__init__.py` | [mcp.md](./mcp.md) |

### Git and version control

| File(s) | Doc |
|---------|-----|
| `git_manager.py`, `git_diff.py` | [git-manager.md](./git-manager.md) |
| `git_providers/base.py`, `git_providers/manager.py`, `git_providers/url_utils.py`, `git_providers/credential_service.py`, `git_providers/oauth/github.py`, `git_providers/oauth/gitlab.py`, `git_providers/oauth/bitbucket.py`, `git_providers/providers/github.py`, `git_providers/providers/gitlab.py`, `git_providers/providers/bitbucket.py`, `git_providers/__init__.py`, `git_providers/oauth/__init__.py`, `git_providers/providers/__init__.py` | [git-providers.md](./git-providers.md) |
| `github_client.py`, `github_oauth.py` | [git-providers.md](./git-providers.md) |

### Deployments (external hosting)

| File(s) | Doc |
|---------|-----|
| `deployment/base.py`, `deployment/manager.py`, `deployment/builder.py`, `deployment/container_base.py`, `deployment/guards.py`, `deployment/providers/*.py`, `deployment/__init__.py`, `deployment/providers/__init__.py`, `deployment/providers/utils.py` | [deployment-providers.md](./deployment-providers.md) |
| `deployment_encryption.py`, `credential_manager.py` | [utilities.md](./utilities.md) |

### Payments, credits, LiteLLM, usage

| File(s) | Doc |
|---------|-----|
| `stripe_service.py` | [stripe.md](./stripe.md) |
| `litellm_service.py`, `litellm_keys.py` | [litellm.md](./litellm.md) |
| `model_pricing.py` | [model-pricing.md](./model-pricing.md) |
| `credit_service.py`, `daily_credit_reset.py`, `usage_service.py` | [credit-system.md](./credit-system.md) |
| `cache_service.py`, `base_cache_manager.py` | [cache.md](./cache.md) |

### Auth, security, notifications

| File(s) | Doc |
|---------|-----|
| `two_fa_service.py`, `magic_link_service.py`, `email_service.py`, `oauth_state.py`, `auth_tokens.py`, `rate_limit.py`, `audit_service.py`, `agent_audit.py` | [auth-security.md](./auth-security.md) |
| `discord_service.py`, `ntfy_service.py` | [auth-security.md](./auth-security.md) |

### Tesslate Apps (marketplace runtime, publisher, approval)

| File(s) | Doc |
|---------|-----|
| `apps/installer.py`, `apps/publisher.py`, `apps/submissions.py`, `apps/runtime.py`, `apps/runtime_urls.py`, `apps/hosted_agent_runtime.py`, `apps/warm_pool.py`, `apps/key_lifecycle.py`, `apps/fork.py`, `apps/bundles.py`, `apps/yanks.py`, `apps/app_invocations.py`, `apps/app_manifest.py`, `apps/manifest_parser.py`, `apps/manifest_merger.py`, `apps/compatibility.py`, `apps/stage1_scanner.py`, `apps/stage2_sandbox.py`, `apps/monitoring.py`, `apps/monitoring_sweep.py`, `apps/schedule_triggers.py`, `apps/billing_dispatcher.py`, `apps/settlement_worker.py`, `apps/event_bus.py`, `apps/db_event_dispatcher.py`, `apps/env_resolver.py`, `apps/secret_propagator.py`, `apps/source_view.py`, `apps/project_scopes.py`, `apps/reserved_handles.py`, `apps/install_reaper.py`, `apps/audit.py`, `apps/_auto_approve_flag.py`, `apps/__init__.py` | [apps.md](./apps.md) |

### Desktop (sidecar) services

| File(s) | Doc |
|---------|-----|
| `desktop_auth.py`, `desktop_paths.py`, `runtime_probe.py`, `token_store.py`, `cloud_client.py`, `sync_client.py`, `handoff_client.py`, `marketplace_installer.py`, `tsinit_client.py` | [desktop-services.md](./desktop-services.md) |

### Public-router service layer

| File(s) | Doc |
|---------|-----|
| `public/handoff_service.py`, `public/marketplace_install_service.py`, `public/sync_service.py`, `public/__init__.py` | [public-services.md](./public-services.md) |

### Design view

| File(s) | Doc |
|---------|-----|
| `design/ast_client.py`, `design/circuit_breaker.py`, `design/__init__.py` | [design.md](./design.md) |

### Misc utilities

| File(s) | Doc |
|---------|-----|
| `feature_flags.py`, `recommendations.py`, `task_manager.py` | [utilities.md](./utilities.md) |
| `services/__init__.py` | no standalone doc (re-exports only) |

### Shell sessions and worker

| File(s) | Doc |
|---------|-----|
| `shell_session_manager.py`, `pty_broker.py`, `session_router.py` | [shell-sessions.md](./shell-sessions.md), [session-router.md](./session-router.md), [runtime-support.md](./runtime-support.md) |
| worker bodies in `orchestrator/app/worker.py` | [worker.md](./worker.md) |

## Cross-cutting docs

| Doc | Scope |
|-----|-------|
| [CLAUDE.md](./CLAUDE.md) | Agent context + common patterns |
| [config-json.md](./config-json.md) | `.tesslate/config.json` schema and lifecycle |
| [cloud-client.md](./cloud-client.md) | Desktop-to-cloud HTTP client |

## Architecture patterns

- **Singleton**: stateful services (`snapshot_manager`, `litellm_service`, `cache`) use module-level singletons via `get_*()` accessors.
- **Factory**: `get_orchestrator()`, `get_task_queue()`, `get_pubsub()`, `DeploymentManager.get_provider()` select a backend based on settings.
- **Abstract base class**: polymorphic layers (`BaseOrchestrator`, `AbstractChannel`, `BaseDeploymentProvider`, `TaskQueue` Protocol, `PubSub` Protocol) keep Docker, Kubernetes, local, and cloud paths interchangeable.
- **Dependency injection**: DB sessions are always passed in, never created inside a service. Settings come from `get_settings()` cached in `__init__`.
- **Async by default**: all I/O uses `await`; blocking K8s/SDK calls wrap in `asyncio.to_thread`.
- **Lazy imports**: services that depend on each other import inside functions to avoid circular imports.

## Navigation tips

1. Look up a file in the tables above. Each row links to the doc that covers the file.
2. Open the doc; each doc lists every file it covers, the key classes/functions, and callers.
3. If a file is missing from this index, the README is out of date: add the row and update the corresponding doc.
