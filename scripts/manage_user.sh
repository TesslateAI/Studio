#!/usr/bin/env bash
#
# manage_user.sh - Create users and upgrade subscription plans across environments.
#
# Usage:
#   ./scripts/manage_user.sh <action> <environment> [options]
#
# Actions:
#   create-user   Create a new user account
#   upgrade-plan  Upgrade an existing user's subscription tier
#   all           Create a new user AND upgrade to specified tier
#
# Environments:
#   docker        Local Docker Compose (tesslate-orchestrator container)
#   local-k8s     Minikube / local Kubernetes (tesslate namespace)
#   beta          AWS EKS beta environment
#   production    AWS EKS production environment
#
# Options:
#   --email       User email (required)
#   --password    User password (required for create-user/all)
#   --name        Display name (required for create-user/all)
#   --username    Username (required for create-user/all)
#   --tier        Subscription tier: free|basic|pro|ultra (default: ultra)
#   --superuser   Make the user a superuser (flag, default: false)
#
# Examples:
#   ./scripts/manage_user.sh create-user docker --email dev@test.com --password secret123 --name "Dev User" --username devuser
#   ./scripts/manage_user.sh upgrade-plan docker --email dev@test.com --tier ultra
#   ./scripts/manage_user.sh all docker --email dev@test.com --password secret123 --name "Dev User" --username devuser --tier ultra
#   ./scripts/manage_user.sh all production --email admin@tesslate.com --password secret123 --name Admin --username admin --tier ultra --superuser

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
TIER="ultra"
SUPERUSER="false"
EMAIL=""
PASSWORD=""
NAME=""
USERNAME=""

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() {
    sed -n '2,/^$/{ s/^# \?//; p }' "$0"
    exit 1
}

# ── Parse Args ────────────────────────────────────────────────────────────────
[[ $# -lt 2 ]] && usage

ACTION="$1"; shift
ENV="$1"; shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --email)      EMAIL="$2";    shift 2 ;;
        --password)   PASSWORD="$2"; shift 2 ;;
        --name)       NAME="$2";     shift 2 ;;
        --username)   USERNAME="$2"; shift 2 ;;
        --tier)       TIER="$2";     shift 2 ;;
        --superuser)  SUPERUSER="true"; shift ;;
        -h|--help)    usage ;;
        *) err "Unknown option: $1"; usage ;;
    esac
done

# ── Validate ──────────────────────────────────────────────────────────────────
if [[ ! "$ACTION" =~ ^(create-user|upgrade-plan|all)$ ]]; then
    err "Invalid action: $ACTION (must be create-user|upgrade-plan|all)"
    exit 1
fi

if [[ ! "$ENV" =~ ^(docker|local-k8s|beta|production)$ ]]; then
    err "Invalid environment: $ENV (must be docker|local-k8s|beta|production)"
    exit 1
fi

if [[ ! "$TIER" =~ ^(free|basic|pro|ultra)$ ]]; then
    err "Invalid tier: $TIER (must be free|basic|pro|ultra)"
    exit 1
fi

if [[ -z "$EMAIL" ]]; then
    err "--email is required"
    exit 1
fi

if [[ "$ACTION" == "create-user" || "$ACTION" == "all" ]]; then
    if [[ -z "$PASSWORD" ]]; then
        err "--password is required for $ACTION"
        exit 1
    fi
    if [[ -z "$NAME" ]]; then
        err "--name is required for $ACTION"
        exit 1
    fi
    if [[ -z "$USERNAME" ]]; then
        err "--username is required for $ACTION"
        exit 1
    fi
fi

# ── Python Script Inline ─────────────────────────────────────────────────────
# Single Python script handles both actions. Passed as a string to exec in the
# target environment.

gen_python_script() {
    cat <<'PYEOF'
import asyncio
import sys
import os
import json

if os.path.exists("/app/app"):
    sys.path.insert(0, "/app")

args = json.loads(os.environ["MANAGE_USER_ARGS"])

action   = args["action"]
email    = args["email"]
password = args.get("password", "")
name     = args.get("name", "")
username = args.get("username", "")
tier     = args.get("tier", "ultra")
superuser = args.get("superuser", False)

from app.database import AsyncSessionLocal
import app.models  # noqa: F401 — register all SQLAlchemy models so relationships resolve
from app.models_auth import User
from app.models_team import Team, TeamMembership
from app.auth import get_password_hash
from app.config import get_settings
from sqlalchemy import select

settings = get_settings()

# Tier bundled credits mapping. After alembic 0035 (RBAC teams) and
# 0088 (drop user billing columns) the credits live on Team, not User —
# so each create-user also provisions a personal Team that owns billing
# state, and upgrade-plan targets that team instead of the user row.
TIER_CREDITS = {
    "free": settings.tier_bundled_credits_free,
    "basic": settings.tier_bundled_credits_basic,
    "pro": settings.tier_bundled_credits_pro,
    "ultra": settings.tier_bundled_credits_ultra,
}


async def _personal_team(session, user):
    """Return the user's personal team (the one this script created)."""
    result = await session.execute(
        select(Team)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .where(TeamMembership.user_id == user.id, Team.is_personal.is_(True))
    )
    return result.scalar_one_or_none()


async def create_user(session):
    result = await session.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        print(f"ERROR: User with email '{email}' already exists")
        sys.exit(1)

    result = await session.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        print(f"ERROR: Username '{username}' already taken")
        sys.exit(1)

    hashed_password = get_password_hash(password)

    from nanoid import generate
    user_slug = f"{username.lower().replace('_', '-').replace(' ', '-')}-{generate(size=6)}"
    referral_code = generate(size=8).upper()

    user = User(
        email=email,
        hashed_password=hashed_password,
        name=name,
        username=username,
        slug=user_slug,
        referral_code=referral_code,
        is_active=True,
        is_superuser=superuser,
        is_verified=True,
    )
    session.add(user)
    await session.flush()  # populates user.id

    # Personal team — owns billing state. Slug must be unique across teams.
    team = Team(
        name=name,
        slug=f"{username.lower().replace('_', '-').replace(' ', '-')}-team-{generate(size=6)}",
        is_personal=True,
        created_by_id=user.id,
        subscription_tier="free",
        bundled_credits=TIER_CREDITS["free"],
    )
    session.add(team)
    await session.flush()

    # Admin membership + default team pointer.
    session.add(
        TeamMembership(
            user_id=user.id, team_id=team.id, role="admin", is_active=True
        )
    )
    user.default_team_id = team.id

    await session.commit()
    await session.refresh(user)
    await session.refresh(team)
    print(
        f"Created user: {user.email} ({user.username}) [slug={user.slug}] "
        f"team={team.slug} tier={team.subscription_tier} credits={team.bundled_credits}"
    )
    return user


async def upgrade_plan(session):
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        print(f"ERROR: No user found with email '{email}'")
        sys.exit(1)

    team = await _personal_team(session, user)
    if not team:
        print(f"ERROR: No personal team found for {user.email}")
        sys.exit(1)

    old_tier = team.subscription_tier or "free"
    team.subscription_tier = tier
    team.bundled_credits = TIER_CREDITS.get(tier, TIER_CREDITS["free"])

    await session.commit()
    await session.refresh(team)
    print(
        f"Upgraded {user.email} (team={team.slug}): "
        f"{old_tier} -> {tier} (credits: {team.bundled_credits})"
    )
    return user


async def main():
    async with AsyncSessionLocal() as session:
        if action == "create-user":
            await create_user(session)
        elif action == "upgrade-plan":
            await upgrade_plan(session)
        elif action == "all":
            await create_user(session)
            await upgrade_plan(session)

asyncio.run(main())
PYEOF
}

# ── Build JSON args ───────────────────────────────────────────────────────────
ARGS_JSON=$(python3 -c "
import json, sys
print(json.dumps({
    'action': sys.argv[1],
    'email': sys.argv[2],
    'password': sys.argv[3],
    'name': sys.argv[4],
    'username': sys.argv[5],
    'tier': sys.argv[6],
    'superuser': sys.argv[7] == 'true',
}))" "$ACTION" "$EMAIL" "$PASSWORD" "$NAME" "$USERNAME" "$TIER" "$SUPERUSER")

# ── Execute per environment ───────────────────────────────────────────────────

SCRIPT_CONTENT=$(gen_python_script)

run_docker() {
    info "Running on Docker (tesslate-orchestrator)..."

    # Write script into container
    echo "$SCRIPT_CONTENT" | docker exec -i tesslate-orchestrator tee /tmp/_manage_user.py > /dev/null

    MSYS_NO_PATHCONV=1 docker exec \
        -e PYTHONPATH=/app \
        -e MANAGE_USER_ARGS="$ARGS_JSON" \
        tesslate-orchestrator \
        python /tmp/_manage_user.py
}

run_k8s() {
    local namespace="$1"
    local label="$2"
    local context_args=("${@:3}")

    POD=$(kubectl "${context_args[@]}" get pod -n "$namespace" -l "$label" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [[ -z "$POD" ]]; then
        err "No running pod found with label '$label' in namespace '$namespace'"
        exit 1
    fi
    info "Target pod: $POD (namespace: $namespace)"

    # Copy script to pod
    local tmp_script
    tmp_script=$(mktemp /tmp/manage_user_XXXXXX.py)
    echo "$SCRIPT_CONTENT" > "$tmp_script"
    kubectl "${context_args[@]}" cp "$tmp_script" "$namespace/$POD:/tmp/_manage_user.py"
    rm -f "$tmp_script"

    MSYS_NO_PATHCONV=1 kubectl "${context_args[@]}" exec -n "$namespace" "$POD" -- \
        env PYTHONPATH=/app MANAGE_USER_ARGS="$ARGS_JSON" \
        python /tmp/_manage_user.py
}

case "$ENV" in
    docker)
        run_docker
        ;;
    local-k8s)
        info "Environment: local Kubernetes (minikube)"
        run_k8s "tesslate" "app=tesslate-backend"
        ;;
    beta)
        info "Environment: AWS EKS (beta)"
        run_k8s "tesslate" "app=tesslate-backend"
        ;;
    production)
        warn "You are targeting PRODUCTION."
        read -rp "Type 'yes' to confirm: " confirm
        if [[ "$confirm" != "yes" ]]; then
            err "Aborted."
            exit 1
        fi
        run_k8s "tesslate" "app=tesslate-backend"
        ;;
esac

ok "Done! ($ACTION on $ENV)"
