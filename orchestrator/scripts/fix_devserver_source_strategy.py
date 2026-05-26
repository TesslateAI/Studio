"""One-time fix: clear source_strategy='image' on devserver containers.

The bundle config generator incorrectly inferred source_strategy='image'
for any container with an image field, including tesslate-devserver:latest.
The devserver is a generic runtime host whose source always comes from the
bundle PVC — it must be NULL (bundle) so the PVC gets mounted at /app.

This script:
  1. Finds all Container rows where image matches 'tesslate-devserver:*'
     AND source_strategy='image' AND state_mount_path IS NULL.
  2. Resets source_strategy to NULL on those rows.
  3. Deletes the live K8s Deployments for those containers so the next
     start_environment call recreates them with the correct PVC mount.

Run inside the backend pod:
    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \\
      python -m scripts.fix_devserver_source_strategy
"""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("fix_devserver_source_strategy")


async def main() -> int:
    from sqlalchemy import text

    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                UPDATE containers
                SET source_strategy = NULL
                WHERE image LIKE 'tesslate-devserver:%'
                  AND source_strategy = 'image'
                  AND state_mount_path IS NULL
                RETURNING id, name, project_id
                """
            )
        )
        fixed = result.fetchall()
        await db.commit()

    if not fixed:
        logger.info("no affected containers found — nothing to do")
        return 0

    logger.info("fixed %d container(s):", len(fixed))
    for row in fixed:
        logger.info("  id=%s name=%s project_id=%s", row.id, row.name, row.project_id)

    # Delete live K8s deployments for the affected containers so they are
    # recreated with the correct spec (PVC mounted at /app) on next open.
    try:
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()

        apps_v1 = k8s_client.AppsV1Api()
        deleted = 0
        for row in fixed:
            namespace = f"proj-{row.project_id}"
            label_selector = f"tesslate.io/container-id={row.id}"
            try:
                deploys = apps_v1.list_namespaced_deployment(
                    namespace=namespace, label_selector=label_selector
                )
                for deploy in deploys.items:
                    apps_v1.delete_namespaced_deployment(
                        name=deploy.metadata.name,
                        namespace=namespace,
                    )
                    logger.info("deleted deployment %s/%s", namespace, deploy.metadata.name)
                    deleted += 1
            except Exception as e:
                if "404" in str(e) or "not found" in str(e).lower():
                    logger.debug("namespace %s not found or no deployment — skipping", namespace)
                else:
                    logger.warning("could not delete deployment in %s: %s", namespace, e)

        logger.info("deleted %d stale deployment(s)", deleted)
    except ImportError:
        logger.warning("kubernetes client not available — skipping deployment cleanup")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
