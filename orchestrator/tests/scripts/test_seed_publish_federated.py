"""Tests for ``scripts._seed_publish_federated`` translation helpers.

The federated converter takes a 2025-02 manifest and projects it into the
``.tesslate/config.json`` shape that ``install_compute_materializer``
reads at install time. The source-strategy inferrer is the load-bearing
piece — getting it wrong causes either a missing /app mount (bundle
needed but image inferred) or a duplicate mount (image self-contained
but bundle inferred).

Pinned here:

* The platform's own ``tesslate-devserver*`` image (with or without an
  ECR / GHCR registry prefix) is bundle-strategy, not image-strategy.
  Otherwise any seed that pins the devserver image (e.g. crm-demo)
  silently regresses and its npm-run-dev startup can't find package.json
  because the bundle PVC isn't mounted.
* A genuine self-contained image (``ghcr.io/...``,
  ``tesslate-markitdown:*``) still infers image-strategy.
* An explicit ``source_strategy`` in the manifest always wins over the
  heuristic, in either direction.
"""

from __future__ import annotations

from scripts._seed_publish_federated import (
    _is_platform_devserver_image,
    derive_tesslate_config_from_manifest,
)

# ---------------------------------------------------------------------------
# _is_platform_devserver_image
# ---------------------------------------------------------------------------


def test_recognizes_devserver_with_and_without_registry_prefix():
    assert _is_platform_devserver_image("tesslate-devserver:latest")
    assert _is_platform_devserver_image("tesslate-devserver:beta")
    assert _is_platform_devserver_image(
        "<ECR_REGISTRY>/tesslate-devserver:beta"
    )
    assert _is_platform_devserver_image("ghcr.io/tesslate/tesslate-devserver:abc123")


def test_rejects_other_app_images():
    # Self-contained app images that the App Runtime Contract treats as
    # image-strategy by default.
    assert not _is_platform_devserver_image("tesslate-markitdown:latest")
    assert not _is_platform_devserver_image("ghcr.io/666ghj/mirofish:latest")
    assert not _is_platform_devserver_image("postgres:16-alpine")
    assert not _is_platform_devserver_image("")
    assert not _is_platform_devserver_image(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# derive_tesslate_config_from_manifest — source_strategy inference
# ---------------------------------------------------------------------------


def _manifest_with_image(image: str | None, *, explicit_strategy: str | None = None) -> dict:
    """Minimal manifest carrying a single web container with the given image."""
    container: dict = {
        "name": "web",
        "primary": True,
        "ports": [3000],
        "startup_command": "npm run dev",
        "env": {},
    }
    if image is not None:
        container["image"] = image
    if explicit_strategy is not None:
        container["source_strategy"] = explicit_strategy

    return {
        "manifest_schema_version": "2025-02",
        "app": {"id": "com.example.x", "slug": "x", "name": "X", "version": "0.1.0"},
        "compute": {"containers": [container]},
        "state": {"model": "per-install-volume"},
    }


def test_devserver_image_infers_bundle_strategy():
    cfg = derive_tesslate_config_from_manifest(_manifest_with_image("tesslate-devserver:latest"))
    assert cfg["apps"]["web"]["source_strategy"] == "bundle"


def test_devserver_image_with_ecr_prefix_infers_bundle_strategy():
    cfg = derive_tesslate_config_from_manifest(
        _manifest_with_image("<ECR_REGISTRY>/tesslate-devserver:beta")
    )
    assert cfg["apps"]["web"]["source_strategy"] == "bundle"


def test_no_image_infers_bundle_strategy():
    cfg = derive_tesslate_config_from_manifest(_manifest_with_image(None))
    assert cfg["apps"]["web"]["source_strategy"] == "bundle"


def test_self_contained_image_infers_image_strategy():
    cfg = derive_tesslate_config_from_manifest(_manifest_with_image("ghcr.io/owner/app:tag"))
    assert cfg["apps"]["web"]["source_strategy"] == "image"


def test_explicit_image_strategy_wins_over_devserver_heuristic():
    # If the creator explicitly says "image" for some reason — maybe they
    # built a fork of devserver with their app baked in — honour it.
    cfg = derive_tesslate_config_from_manifest(
        _manifest_with_image("tesslate-devserver:latest", explicit_strategy="image")
    )
    assert cfg["apps"]["web"]["source_strategy"] == "image"


def test_explicit_bundle_strategy_wins_over_image_heuristic():
    cfg = derive_tesslate_config_from_manifest(
        _manifest_with_image("ghcr.io/owner/app:tag", explicit_strategy="bundle")
    )
    assert cfg["apps"]["web"]["source_strategy"] == "bundle"


# ---------------------------------------------------------------------------
# resources — manifest pass-through and key whitelist
# ---------------------------------------------------------------------------


def _manifest_with_resources(resources: dict) -> dict:
    return {
        "manifest_schema_version": "2025-02",
        "app": {"id": "com.example.x", "slug": "x", "name": "X", "version": "0.1.0"},
        "compute": {
            "containers": [
                {
                    "name": "web",
                    "primary": True,
                    "ports": [3000],
                    "startup_command": "npm run dev",
                    "env": {},
                    "resources": resources,
                }
            ]
        },
    }


def test_resources_pass_through_when_all_keys_recognized():
    cfg = derive_tesslate_config_from_manifest(
        _manifest_with_resources(
            {
                "memory_request": "512Mi",
                "memory_limit": "2Gi",
                "cpu_request": "200m",
                "cpu_limit": "2000m",
            }
        )
    )
    assert cfg["apps"]["web"]["resources"] == {
        "memory_request": "512Mi",
        "memory_limit": "2Gi",
        "cpu_request": "200m",
        "cpu_limit": "2000m",
    }


def test_resources_unknown_keys_dropped():
    """Defence in depth — creators can't smuggle arbitrary K8s resource
    keys (gpu, ephemeral-storage, etc.) through this layer. Adding new
    keys requires updating both this whitelist AND the renderer."""
    cfg = derive_tesslate_config_from_manifest(
        _manifest_with_resources(
            {
                "memory_limit": "2Gi",
                "gpu": "1",  # not whitelisted
                "ephemeral-storage": "10Gi",  # not whitelisted
            }
        )
    )
    assert cfg["apps"]["web"]["resources"] == {"memory_limit": "2Gi"}


def test_resources_omitted_when_all_keys_invalid():
    cfg = derive_tesslate_config_from_manifest(_manifest_with_resources({"gpu": "1"}))
    # No ``resources`` key emitted at all when nothing survives the filter.
    assert "resources" not in cfg["apps"]["web"]


def test_resources_absent_in_manifest_means_absent_in_config():
    cfg = derive_tesslate_config_from_manifest(_manifest_with_image("tesslate-devserver:latest"))
    assert "resources" not in cfg["apps"]["web"]
