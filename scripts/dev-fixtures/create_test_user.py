#!/usr/bin/env python3
"""Create / mint-JWT / delete fully-initialized test users on a Tesslate
Studio target env, going through the same UserManager.create() →
on_after_register hook the public registration endpoint uses.

Why this script exists
----------------------
Raw `INSERT INTO users (...)` (e.g. from an ad-hoc `kubectl exec ... python`
session) produces a half-initialized user: no default_team_id, no LiteLLM
key, no Stripe customer, no default agent, no themes. Most product
features then 4xx or 500 against that account (we hit this with the
PR #490 showcase user — workspace creation broke because
`current_user.default_team_id` was NULL).

Subcommands
-----------
  create      Create (or recreate) a test user end-to-end.
  mint-jwt    Mint a fresh bearer JWT for an existing user.
  delete      Raw-SQL cleanup that survives broken ORM cascades.

All work happens INSIDE the backend pod via `kubectl exec` — the DB
isn't reachable from outside the cluster, and the pod already has the
right Python deps + import paths + secrets.

Examples
--------
  scripts/dev-fixtures/create_test_user.py create \\
      --env beta --email demo@tesslate.com --password 'Demo!2025'

  scripts/dev-fixtures/create_test_user.py mint-jwt \\
      --env beta --email demo@tesslate.com

  scripts/dev-fixtures/create_test_user.py delete \\
      --env beta --email demo@tesslate.com --force
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap

ENV_CONTEXTS: dict[str, str] = {
    "minikube": "tesslate",
    "beta": "tesslate-beta-eks",
    "prod": "tesslate-production-eks",
}


def exec_in_pod(env: str, script: str, stdin_payload: dict) -> str:
    """Pipe `script` into the backend pod's python interpreter, with
    `stdin_payload` available as JSON on the FIRST line of stdin."""
    context = ENV_CONTEXTS[env]
    cmd = [
        "kubectl", f"--context={context}", "-n", "tesslate",
        "exec", "-i", "deployment/tesslate-backend", "-c", "backend",
        "--", "python", "-c", script,
    ]
    proc = subprocess.run(
        cmd, input=json.dumps(stdin_payload), text=True, capture_output=True, check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        sys.exit(proc.returncode)
    return proc.stdout


CREATE_SCRIPT = textwrap.dedent('''\
    """Hit the same in-process FastAPI app that beta serves, registering
    via POST /api/auth/register so the full UserManager.create() →
    on_after_register flow runs in its proper request lifecycle (correct
    session scoping, no double-invocation of the hook, identical to what
    happens when a real user signs up). Then mint a bearer JWT for the
    new user."""
    import asyncio, json, sys
    import app.models  # noqa
    from httpx import AsyncClient, ASGITransport
    from sqlalchemy import select
    from app.main import app as fastapi_app
    from app.database import AsyncSessionLocal
    from app.users import bearer_backend
    from app.models_auth import User

    P = json.loads(sys.stdin.readline())

    async def go():
        body = {
            "email": P["email"],
            "password": P["password"],
            "name": P.get("name") or P["email"].split("@")[0].title(),
            "is_active": True,
            "is_verified": True,
        }
        transport = ASGITransport(app=fastapi_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post("/api/auth/register", json=body)
        if resp.status_code == 400 and "REGISTER_USER_ALREADY_EXISTS" in resp.text:
            print(json.dumps({"error": "already_exists", "email": P["email"]}))
            sys.exit(2)
        if resp.status_code >= 400:
            print(json.dumps({"error": "register_failed", "status": resp.status_code,
                              "body": resp.text[:500]}))
            sys.exit(3)

        # Pull fully-initialized user back from DB to verify the hook ran
        # (default_team_id + litellm key are the canaries).
        async with AsyncSessionLocal() as db:
            user = (await db.execute(
                select(User).where(User.email == P["email"])
            )).scalar_one()
            token = await bearer_backend.get_strategy().write_token(user)
        print(json.dumps({
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "default_team_id": str(user.default_team_id) if user.default_team_id else None,
            "litellm_user_id": user.litellm_user_id,
            "jwt": token,
        }))

    asyncio.run(go())
''')


MINT_JWT_SCRIPT = textwrap.dedent('''\
    import asyncio, json, sys
    import app.models  # noqa
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.users import bearer_backend
    from app.models_auth import User

    P = json.loads(sys.stdin.readline())

    async def go():
        async with AsyncSessionLocal() as db:
            user = (await db.execute(select(User).where(User.email == P["email"]))).scalar_one_or_none()
            if user is None:
                print(json.dumps({"error": "not_found", "email": P["email"]}))
                sys.exit(2)
            token = await bearer_backend.get_strategy().write_token(user)
        print(json.dumps({"id": str(user.id), "email": user.email, "jwt": token}))

    asyncio.run(go())
''')


# Delete uses raw SQL because the ORM cascade traverses through tables
# (e.g. agent_schedules) that may not exist in every env's schema, and
# we want a delete that survives partial migration drift.
DELETE_SCRIPT = textwrap.dedent('''\
    import asyncio, json, sys
    import app.models  # noqa
    from sqlalchemy import select, text
    from app.database import AsyncSessionLocal
    from app.models_auth import User

    P = json.loads(sys.stdin.readline())

    # Wide-net list of child tables that *might* exist and reference the user.
    # Each entry is (table, fk_column). Tables that don't exist in this env's
    # schema are silently skipped via a per-statement savepoint.
    USER_CHILD_TABLES = [
        ("workflow_health_snapshots", "automation_id_via_definition"),  # special-cased below
        ("workflow_proposals",        "automation_id_via_definition"),
        ("automation_step_runs",      "automation_id_via_definition"),
        ("automation_run_events",     "automation_id_via_definition"),
        ("automation_run_artifacts",  "automation_id_via_definition"),
        ("automation_runs",           "automation_id_via_definition"),
        ("automation_events",         "automation_id_via_definition"),
        ("automation_triggers",       "automation_id_via_definition"),
        ("automation_delivery_targets","automation_id_via_definition"),
        ("automation_actions",        "automation_id_via_definition"),
        ("workflow_versions",         "automation_id_via_definition"),
        ("user_purchased_agents",     "user_id"),
        ("user_library_themes",       "user_id"),
        ("external_api_keys",         "user_id"),
        ("team_memberships",          "user_id"),
        ("audit_logs",                "user_id"),
    ]

    async def safe_exec(db, sql, params):
        # Postgres aborts the whole tx on any error inside it. Commit between
        # each statement so a missing table doesn't poison subsequent deletes.
        try:
            res = await db.execute(text(sql), params)
            await db.commit()
            return res.rowcount
        except Exception as e:
            await db.rollback()
            return f"skip ({type(e).__name__})"

    async def go():
        async with AsyncSessionLocal() as db:
            user = (await db.execute(select(User).where(User.email == P["email"]))).scalar_one_or_none()
            if user is None:
                print(json.dumps({"error": "not_found", "email": P["email"]}))
                sys.exit(2)
            uid = str(user.id)
            report = {}

            for table, fk in USER_CHILD_TABLES:
                if fk == "automation_id_via_definition":
                    sql = (f"DELETE FROM {table} WHERE automation_id IN "
                           f"(SELECT id FROM automation_definitions WHERE owner_user_id = :u)")
                else:
                    sql = f"DELETE FROM {table} WHERE {fk} = :u"
                report[table] = await safe_exec(db, sql, {"u": uid})

            report["null_xrefs"] = await safe_exec(
                db,
                "UPDATE automation_definitions SET head_version_id = NULL, "
                "doctor_automation_id = NULL WHERE owner_user_id = :u",
                {"u": uid},
            )
            report["automation_definitions"] = await safe_exec(
                db, "DELETE FROM automation_definitions WHERE owner_user_id = :u", {"u": uid}
            )
            report["personal_teams"] = await safe_exec(
                db, "DELETE FROM teams WHERE created_by_id = :u AND is_personal = true", {"u": uid}
            )
            report["users"] = await safe_exec(
                db, "DELETE FROM users WHERE id = :u", {"u": uid}
            )

        print(json.dumps({"email": P["email"], "id": uid, "report": report}, default=str))

    asyncio.run(go())
''')


def cmd_create(args: argparse.Namespace) -> None:
    out = exec_in_pod(
        args.env, CREATE_SCRIPT,
        {"email": args.email, "password": args.password, "name": args.name},
    )
    print(out, end="")


def cmd_mint_jwt(args: argparse.Namespace) -> None:
    out = exec_in_pod(args.env, MINT_JWT_SCRIPT, {"email": args.email})
    print(out, end="")


def cmd_delete(args: argparse.Namespace) -> None:
    if args.env == "prod" and not args.force:
        sys.exit("refuse: deleting on prod requires --force (and you should not)")
    if not args.force:
        sys.exit("refuse: pass --force to actually delete")
    out = exec_in_pod(args.env, DELETE_SCRIPT, {"email": args.email})
    print(out, end="")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)

    pc = sp.add_parser("create", help="Create or recreate a fully-initialized test user.")
    pc.add_argument("--env", required=True, choices=ENV_CONTEXTS.keys())
    pc.add_argument("--email", required=True)
    pc.add_argument("--password", required=True)
    pc.add_argument("--name", default=None, help="Display name (default: derived from email)")
    pc.set_defaults(func=cmd_create)

    pm = sp.add_parser("mint-jwt", help="Mint a bearer JWT for an existing user.")
    pm.add_argument("--env", required=True, choices=ENV_CONTEXTS.keys())
    pm.add_argument("--email", required=True)
    pm.set_defaults(func=cmd_mint_jwt)

    pd = sp.add_parser("delete", help="Raw-SQL delete that survives ORM cascade drift.")
    pd.add_argument("--env", required=True, choices=ENV_CONTEXTS.keys())
    pd.add_argument("--email", required=True)
    pd.add_argument("--force", action="store_true", help="Required guardrail.")
    pd.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
