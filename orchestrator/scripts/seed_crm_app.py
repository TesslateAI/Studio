"""Seed the Tesslate CRM Tesslate App via the federated marketplace.

Requires a cluster secret ``llama-api-credentials`` in the ``tesslate``
namespace with an ``api_key`` entry. Create it with::

    kubectl --context=tesslate -n tesslate create secret generic \\
      llama-api-credentials --from-literal=api_key='<your-llama-api-key>'

Run inside the backend pod (the seed_apps cron does this automatically):

    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \\
      python -m scripts.seed_crm_app

See ``seed_hello_node_app.py`` for the federated publish path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from scripts._seed_publish_federated import (
    already_published_on_hub,
    build_app_bundle,
    maybe_extras_for_config_injection,
    publish_app_via_federation,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_crm")

SLUG = "crm-demo"
_SEEDS_SLUG = "crm"
MANIFEST_FILENAME = "app.manifest.json"


def _resolve_assets_dir() -> Path:
    override = os.environ.get("TESSLATE_SEEDS_DIR")
    if override:
        p = Path(override) / _SEEDS_SLUG
        if p.is_dir():
            return p
    candidates = [
        Path(__file__).resolve().parents[2] / "seeds" / "apps" / _SEEDS_SLUG,
        Path("/app/seeds/apps") / _SEEDS_SLUG,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


ASSETS_DIR = _resolve_assets_dir()


def _warn_if_secret_missing(namespace: str = "tesslate") -> None:
    """Best-effort check for the llama-api-credentials secret.

    Logs a warning if the secret is absent so install attempts that need
    the LLM key fail loudly instead of crashlooping with a missing-env
    error inside the running container.
    """
    try:
        from kubernetes import client as k8s_client  # type: ignore[import-not-found]
        from kubernetes import config as k8s_config  # type: ignore[import-not-found]

        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        v1 = k8s_client.CoreV1Api()
        try:
            v1.read_namespaced_secret(name="llama-api-credentials", namespace=namespace)
            logger.info("verified secret llama-api-credentials exists in %s", namespace)
        except Exception:
            logger.warning(
                "secret 'llama-api-credentials' NOT found in namespace %s. "
                "Create it with: kubectl --context=tesslate -n %s create secret "
                "generic llama-api-credentials --from-literal=api_key='<key>'",
                namespace,
                namespace,
            )
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.info(
            "skipping cluster secret check (%s); ensure llama-api-credentials exists",
            e,
        )


async def main() -> int:
    if not ASSETS_DIR.exists():
        logger.error("assets dir missing: %s", ASSETS_DIR)
        return 2

    _warn_if_secret_missing()

    manifest_path = ASSETS_DIR / MANIFEST_FILENAME
    manifest_dict = json.loads(manifest_path.read_text())
    app_meta = manifest_dict.get("app", {})
    version = str(app_meta.get("version") or "0.1.0")
    name = str(app_meta.get("name") or "Tesslate CRM")
    description = str(app_meta.get("description") or "")
    category = app_meta.get("category")

    if await already_published_on_hub(SLUG, version=version):
        logger.info("hub already has %s@%s; nothing to do", SLUG, version)
        return 0

    extra_files = maybe_extras_for_config_injection(manifest_dict, ASSETS_DIR)
    bundle_bytes = build_app_bundle(ASSETS_DIR, extra_files=extra_files)
    logger.info(
        "built bundle for %s: %d bytes (tar.zst, %d files in tree, %d injected)",
        SLUG,
        len(bundle_bytes),
        sum(1 for p in ASSETS_DIR.rglob("*") if p.is_file()),
        len(extra_files),
    )

    envelope = await publish_app_via_federation(
        slug=SLUG,
        name=name,
        description=description,
        category=category,
        version=version,
        manifest=manifest_dict,
        bundle_bytes=bundle_bytes,
    )
    logger.info(
        "published %s@%s submission=%s state=%s",
        SLUG,
        version,
        envelope.get("id"),
        envelope.get("state"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
