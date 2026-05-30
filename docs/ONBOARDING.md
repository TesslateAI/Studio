# OpenSail dev environment onboarding

Entry point for anyone setting up a local OpenSail dev environment - whether you're building a feature, fixing a bug, testing the product, or contributing to the open-source project.

By the end of this doc you will have:

- All the dev tools installed.
- A working local OpenSail running on Minikube at `http://localhost`.
- Verified end-to-end with a sign-up and first project.

If you want a quick orientation to what OpenSail is first, skim the root [README.md](../README.md).

---

## Install the dev tools

**Docker** - the container runtime that backs Minikube and your project containers:

| OS | Recommended |
|----|-------------|
| **Linux** | Native Docker Engine. Follow [Docker's official install guide](https://docs.docker.com/engine/install/) for your distro. Add your user to the `docker` group so you don't need `sudo`. |
| **macOS** | [OrbStack](https://orbstack.dev/) (recommended - faster and lighter, great on Apple Silicon) or [Docker Desktop](https://www.docker.com/products/docker-desktop/). |
| **Windows** | [Docker Desktop](https://www.docker.com/products/docker-desktop/) with the WSL 2 backend enabled. Run all commands from inside your WSL 2 distro (Ubuntu 22.04+), never from PowerShell or Git Bash. |

**Kubernetes tooling:**

| Tool | Min version | Purpose | Install |
|------|-------------|---------|---------|
| `minikube` | 1.33 | Local Kubernetes cluster | [Official install guide](https://minikube.sigs.k8s.io/docs/start/) - one-line installers for every OS |
| `kubectl` | 1.29 | Kubernetes CLI | [Official install guide](https://kubernetes.io/docs/tasks/tools/), or `brew install kubectl` on macOS / Linuxbrew |

**Everything else:**

| Tool | Purpose | Notes |
|------|---------|-------|
| `git` | Clone the OpenSail repo | Built into macOS and most Linux distros. Windows: in WSL, `sudo apt install git`. |
| `bash` or `zsh` | Run the `scripts/minikube.sh` helpers | Built into Linux / macOS. Windows: use **WSL 2** - not Git Bash, not PowerShell. |
| `python3` | Generate secret values during setup | Built into macOS / Linux. Windows WSL: `sudo apt install python3`. |

**Hardware budget**: at least 4 CPU cores and 8 GB RAM available to Docker, plus ~40 GB free disk for the Minikube VM image and built images. Less and Minikube will get OOM-killed under load.

**Sanity check** - open your shell and confirm everything is on PATH:

```bash
docker --version
minikube version
kubectl version --client
git --version
python3 --version
```

If any of those error out, fix it before continuing.

---

## Stand up the platform

Clone the repo and follow [guides/minikube-setup.md](guides/minikube-setup.md). It walks from an empty machine through cluster startup, secret files, image builds, NGINX Ingress, btrfs CSI, Volume Hub, MinIO, Postgres, Redis, and database seeding to a working `http://localhost`. The `scripts/minikube.sh` helpers do most of the heavy lifting.

Short version:

```bash
git clone https://github.com/TesslateAI/opensail.git
cd opensail
./scripts/minikube.sh init    # generates secret YAML files under k8s/overlays/minikube/secrets/
# edit the generated secret files - at minimum:
#   SECRET_KEY            (python -c "import secrets; print(secrets.token_hex(32))")
#   INTERNAL_API_SECRET   (same)
#   LITELLM_API_BASE      (your LiteLLM proxy or OpenAI-compatible endpoint)
#   LITELLM_MASTER_KEY
./scripts/minikube.sh start   # builds images, starts cluster, deploys, seeds
./scripts/minikube.sh tunnel  # leave running in a second terminal
```

Open `http://localhost`.

Common first-run gotchas:

- **No LiteLLM endpoint** -> the platform boots but the AI agent does nothing. Point `LITELLM_API_BASE` at a real proxy.
- **Tunnel not running** -> `http://localhost` does not respond at all. `scripts/minikube.sh tunnel` must stay running in its own terminal.
- **Pods stuck in `ImagePullBackOff`** -> local images not loaded into the Minikube node. See the [minikube guide's troubleshooting section](guides/minikube-setup.md#14-troubleshooting).
- **WSL on `/mnt/c/...`** -> bind mounts are slow and drop file events. Keep the repo inside the WSL filesystem (e.g. `~/code/opensail`).

---

## Verify end-to-end

Before you start working, confirm the platform is healthy:

1. **Sign up** at `http://localhost` with a fresh email and password.
2. **Create a project** from any template base (Vite + React + FastAPI is a safe default).
3. **Wait for it to start** - the live preview should load within a minute.
4. **Send the agent a trivial prompt** ("add a heading saying hello to the homepage") and confirm it returns a diff.
5. **Refresh the page** - your project and chat history should still be there.

If any step fails, your setup is incomplete - fix it before you start real work, because the failure will look like a product bug.

---

## Where to go next

| You are... | Read |
|------------|------|
| **Working on a backend feature** | [orchestrator/CLAUDE.md](orchestrator/CLAUDE.md) |
| **Working on the frontend** | [app/CLAUDE.md](app/CLAUDE.md) |
| **Touching infrastructure / K8s** | [infrastructure/CLAUDE.md](infrastructure/CLAUDE.md), [infrastructure/kubernetes/CLAUDE.md](infrastructure/kubernetes/CLAUDE.md) |
| **Working on the desktop app** | [desktop/CLAUDE.md](desktop/CLAUDE.md) |
| **Adding an API endpoint** | [orchestrator/routers/CLAUDE.md](orchestrator/routers/CLAUDE.md) |
| **Extending the AI agent** | [orchestrator/agent/CLAUDE.md](orchestrator/agent/CLAUDE.md) |
| **Building a Tesslate App** | [apps/CLAUDE.md](apps/CLAUDE.md) |
| **Manual / QA testing the product** | [testing/manual-test-plan/README.md](testing/manual-test-plan/README.md) |
| **Running automated tests** | [testing/CLAUDE.md](testing/CLAUDE.md) |
| **Deploying to production** | [guides/aws-deployment.md](guides/aws-deployment.md) |

The root [docs/CLAUDE.md](CLAUDE.md) is the full navigation index across the knowledge graph.

---

The hardest part is the one-time setup. After that, the iteration loop (rebuild image, rollout restart, refresh) is fast.
