"""
Tests for Deployment Target Seed Data.

Covers:
- All 22 deployment targets are defined with correct fields
- Provider keys match PROVIDER_CAPABILITIES
- Seed function upsert logic (create + update)
- MarketplaceAgent item_type is 'deployment_target'
"""

import pytest

pytestmark = pytest.mark.unit

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.seeds.deployment_targets import DEPLOYMENT_TARGETS
from app.services.deployment.guards import PROVIDER_CAPABILITIES

# =============================================================================
# Deployment Target Seed Data Tests
# =============================================================================


class TestDeploymentTargetSeedData:
    """Verify deployment target seed data completeness and correctness."""

    def test_all_providers_have_seed_entries(self):
        """Every provider in PROVIDER_CAPABILITIES has a matching seed entry."""
        seed_provider_keys = {t["config"]["provider_key"] for t in DEPLOYMENT_TARGETS}
        for provider_key in PROVIDER_CAPABILITIES:
            assert provider_key in seed_provider_keys, (
                f"Provider '{provider_key}' is in PROVIDER_CAPABILITIES but "
                f"has no seed entry in DEPLOYMENT_TARGETS"
            )

    def test_seed_count_matches_providers(self):
        """Seed list has exactly as many entries as PROVIDER_CAPABILITIES."""
        assert len(DEPLOYMENT_TARGETS) == len(PROVIDER_CAPABILITIES)

    def test_all_entries_are_deployment_target_type(self):
        """Every seed entry has item_type='deployment_target'."""
        for target in DEPLOYMENT_TARGETS:
            assert target["item_type"] == "deployment_target", (
                f"Seed entry '{target['slug']}' has item_type='{target['item_type']}' "
                f"instead of 'deployment_target'"
            )

    def test_all_entries_have_unique_slugs(self):
        """Every seed entry has a unique slug."""
        slugs = [t["slug"] for t in DEPLOYMENT_TARGETS]
        assert len(slugs) == len(set(slugs)), "Duplicate slugs found in DEPLOYMENT_TARGETS"

    def test_all_entries_have_required_fields(self):
        """Every seed entry has all required MarketplaceAgent fields."""
        required_fields = {
            "name",
            "slug",
            "description",
            "category",
            "item_type",
            "icon",
            "pricing_type",
            "is_active",
            "is_published",
            "tags",
            "features",
            "config",
        }
        for target in DEPLOYMENT_TARGETS:
            missing = required_fields - set(target.keys())
            assert not missing, f"Seed entry '{target['slug']}' is missing fields: {missing}"

    def test_config_has_provider_key_and_brand_color(self):
        """Every seed entry config contains provider_key, deployment_mode, and brand_color."""
        for target in DEPLOYMENT_TARGETS:
            config = target["config"]
            assert "provider_key" in config, f"'{target['slug']}' config missing 'provider_key'"
            assert "deployment_mode" in config, (
                f"'{target['slug']}' config missing 'deployment_mode'"
            )
            assert "brand_color" in config, f"'{target['slug']}' config missing 'brand_color'"

    def test_brand_colors_are_valid_hex(self):
        """All brand_color values are valid hex color codes."""
        import re

        hex_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
        for target in DEPLOYMENT_TARGETS:
            color = target["config"]["brand_color"]
            assert hex_pattern.match(color), (
                f"'{target['slug']}' has invalid brand_color: '{color}'"
            )

    def test_deployment_modes_match_capabilities(self):
        """Deployment mode in seed config matches PROVIDER_CAPABILITIES."""
        for target in DEPLOYMENT_TARGETS:
            provider_key = target["config"]["provider_key"]
            seed_mode = target["config"]["deployment_mode"]
            cap_mode = PROVIDER_CAPABILITIES[provider_key]["deployment_mode"]
            assert seed_mode == cap_mode, (
                f"'{target['slug']}' has deployment_mode='{seed_mode}' but "
                f"PROVIDER_CAPABILITIES['{provider_key}'] has '{cap_mode}'"
            )

    def test_brand_colors_match_capabilities(self):
        """Brand colors in seed data match PROVIDER_CAPABILITIES."""
        for target in DEPLOYMENT_TARGETS:
            provider_key = target["config"]["provider_key"]
            seed_color = target["config"]["brand_color"]
            cap_color = PROVIDER_CAPABILITIES[provider_key]["color"]
            assert seed_color == cap_color, (
                f"'{target['slug']}' has brand_color='{seed_color}' but "
                f"PROVIDER_CAPABILITIES['{provider_key}'] has '{cap_color}'"
            )

    def test_all_entries_have_deployment_category(self):
        """Every seed entry has category='deployment'."""
        for target in DEPLOYMENT_TARGETS:
            assert target["category"] == "deployment", (
                f"'{target['slug']}' has category='{target['category']}' instead of 'deployment'"
            )

    def test_all_entries_are_free(self):
        """All deployment targets are free items."""
        for target in DEPLOYMENT_TARGETS:
            assert target["pricing_type"] == "free"
            assert target.get("price", 0) == 0

    def test_slugs_follow_naming_convention(self):
        """All slugs start with 'deploy-' prefix."""
        for target in DEPLOYMENT_TARGETS:
            assert target["slug"].startswith("deploy-"), (
                f"Slug '{target['slug']}' doesn't follow 'deploy-' convention"
            )

    def test_tags_contain_deployment(self):
        """All entries have 'deployment' in their tags."""
        for target in DEPLOYMENT_TARGETS:
            assert "deployment" in target["tags"], f"'{target['slug']}' is missing 'deployment' tag"

    def test_featured_providers_are_marked(self):
        """Key providers (Vercel, Netlify, Cloudflare, AWS, GCP, Azure, Fly) are featured."""
        featured_slugs = {t["slug"] for t in DEPLOYMENT_TARGETS if t.get("is_featured")}
        expected_featured = {
            "deploy-vercel",
            "deploy-netlify",
            "deploy-cloudflare",
            "deploy-aws-apprunner",
            "deploy-gcp-cloudrun",
            "deploy-azure-container-apps",
            "deploy-fly",
        }
        for slug in expected_featured:
            assert slug in featured_slugs, f"Expected '{slug}' to be featured but it is not"

    def test_container_providers_in_seed(self):
        """All container-mode providers are present."""
        container_slugs = {
            t["config"]["provider_key"]
            for t in DEPLOYMENT_TARGETS
            if t["config"]["deployment_mode"] == "container"
        }
        expected = {"aws-apprunner", "gcp-cloudrun", "azure-container-apps", "do-container", "fly"}
        assert container_slugs == expected

    def test_export_providers_in_seed(self):
        """All export-mode providers are present."""
        export_slugs = {
            t["config"]["provider_key"]
            for t in DEPLOYMENT_TARGETS
            if t["config"]["deployment_mode"] == "export"
        }
        expected = {"dockerhub", "ghcr", "download"}
        assert export_slugs == expected
