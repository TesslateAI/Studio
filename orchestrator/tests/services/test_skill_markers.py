"""Unit tests for services/skill_markers.py.

Each of the 8 live-rendered markers must produce a non-empty, sensible
block sourced from the real Python authority (Pydantic schema,
``SERVICES`` catalog, validation constants, etc.). The per-process cache
must return the same rendered body on repeated calls without re-running
the renderers.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

from app.services import skill_markers
from app.services.skill_markers import (
    MARKER_RENDERERS,
    _reset_cache_for_tests,
    get_rendered_body,
    render_markers,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


class TestConfigSchemaMarker:
    def test_renders_valid_json_schema(self):
        out = MARKER_RENDERERS["{{TESSLATE_CONFIG_SCHEMA}}"]()
        # Fenced as ```json ... ```
        assert out.startswith("```json")
        assert out.rstrip().endswith("```")
        payload = out.split("```json", 1)[1].rsplit("```", 1)[0].strip()
        schema = json.loads(payload)
        assert schema["type"] == "object"
        # TesslateConfigCreate has these fields
        assert "apps" in schema["properties"]
        assert "primaryApp" in schema["properties"]
        # $defs for AppConfigSchema / InfraConfigSchema etc.
        assert "$defs" in schema


class TestStartupCommandRulesMarker:
    def test_contains_safe_prefixes(self):
        out = MARKER_RENDERERS["{{STARTUP_COMMAND_RULES}}"]()
        assert "npm" in out
        assert "uvicorn" in out
        assert "10,000" in out or "10000" in out
        assert "0.0.0.0" in out

    def test_contains_dangerous_patterns(self):
        out = MARKER_RENDERERS["{{STARTUP_COMMAND_RULES}}"]()
        assert "rm" in out and "rf" in out
        assert "sudo" in out


class TestServiceCatalogMarker:
    def test_contains_postgres_and_redis(self):
        out = MARKER_RENDERERS["{{SERVICE_CATALOG}}"]()
        assert "postgres" in out.lower()
        assert "redis" in out.lower()
        # Connection template section surfaces a DB URL pattern
        assert "postgresql://" in out

    def test_grouped_by_category(self):
        out = MARKER_RENDERERS["{{SERVICE_CATALOG}}"]()
        # Categories we know exist in SERVICES
        assert "Database" in out
        assert "Cache" in out or "cache" in out


class TestConnectionSemanticsMarker:
    def test_describes_three_behaviors(self):
        out = MARKER_RENDERERS["{{CONNECTION_SEMANTICS}}"]()
        assert "from_node" in out
        assert "to_node" in out
        # Explains ordering + env injection + DNS
        assert "start" in out.lower()  # ordering
        assert "env" in out.lower()


class TestDeploymentCompatibilityMarker:
    def test_lists_providers(self):
        out = MARKER_RENDERERS["{{DEPLOYMENT_COMPATIBILITY}}"]()
        assert "Vercel" in out
        assert "Netlify" in out
        assert "Cloudflare" in out
        # Framework-level detail
        assert "nextjs" in out or "Next.js" in out


class TestContainerTypesMarker:
    def test_explains_base_vs_service(self):
        out = MARKER_RENDERERS["{{CONTAINER_TYPES}}"]()
        assert "base" in out
        assert "service" in out
        assert "apps" in out
        assert "infrastructure" in out


class TestUrlPatternsMarker:
    def test_mentions_docker_and_kubernetes(self):
        out = MARKER_RENDERERS["{{URL_PATTERNS}}"]()
        assert "Docker" in out
        assert "Kubernetes" in out or "K8s" in out
        assert "app-domain" in out or "domain" in out


class TestLifecycleToolsMarker:
    def test_lists_every_tool(self):
        out = MARKER_RENDERERS["{{LIFECYCLE_TOOLS}}"]()
        for name in (
            "apply_setup_config",
            "project_start",
            "project_stop",
            "project_restart",
            "container_start",
            "container_stop",
            "container_restart",
            "project_control",
        ):
            assert name in out, f"missing: {name}"


class TestRenderMarkers:
    def test_substitutes_every_known_marker(self):
        body = "head\n\n{{TESSLATE_CONFIG_SCHEMA}}\n\nmiddle\n\n{{SERVICE_CATALOG}}\n\ntail"
        rendered = render_markers(body)
        assert "{{TESSLATE_CONFIG_SCHEMA}}" not in rendered
        assert "{{SERVICE_CATALOG}}" not in rendered
        assert "head" in rendered and "tail" in rendered

    def test_unknown_marker_left_in_place(self):
        rendered = render_markers("pre {{NOT_A_REAL_MARKER}} post")
        assert "{{NOT_A_REAL_MARKER}}" in rendered

    def test_renderer_failure_leaves_marker_intact(self):
        def _boom():
            raise RuntimeError("renderer failed")

        with patch.dict(
            skill_markers.MARKER_RENDERERS,
            {"{{TESSLATE_CONFIG_SCHEMA}}": _boom},
        ):
            rendered = render_markers("a {{TESSLATE_CONFIG_SCHEMA}} b")

        assert "{{TESSLATE_CONFIG_SCHEMA}}" in rendered


class TestCache:
    def test_first_call_renders_second_call_cached(self):
        """Renderer must run exactly once for a given slug."""
        call_count = {"n": 0}

        def _counting_renderer():
            call_count["n"] += 1
            return "CANNED-SCHEMA"

        with patch.dict(
            skill_markers.MARKER_RENDERERS,
            {"{{TESSLATE_CONFIG_SCHEMA}}": _counting_renderer},
        ):
            body = "x {{TESSLATE_CONFIG_SCHEMA}} y"
            r1 = get_rendered_body("some-slug", body)
            r2 = get_rendered_body("some-slug", body)
            r3 = get_rendered_body("some-slug", body)

        assert r1 == r2 == r3
        assert "CANNED-SCHEMA" in r1
        # One render, three dict lookups.
        assert call_count["n"] == 1

    def test_different_slug_renders_separately(self):
        body = "x {{TESSLATE_CONFIG_SCHEMA}} y"
        r1 = get_rendered_body("slug-a", body)
        r2 = get_rendered_body("slug-b", body)
        assert r1 == r2  # Same body → same rendered result.
        # Both keys populated — two cache entries.
        assert "slug-a" in skill_markers._RENDERED
        assert "slug-b" in skill_markers._RENDERED


def _load_marketplace_tesslate_skills() -> list[dict]:
    """Read canonical Tesslate-authored skills from the federated marketplace.

    After Wave 10 the orchestrator no longer ships seed Python modules;
    skill bodies are authored upstream at
    ``packages/tesslate-marketplace/app/seeds/skills_tesslate.json`` and
    arrive in the orchestrator's catalog cache via the federation sync
    worker. The marker-rendering contract is asserted against the upstream
    source of truth.
    """
    import json
    from pathlib import Path

    seed_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "tesslate-marketplace"
        / "app"
        / "seeds"
        / "skills_tesslate.json"
    )
    return json.loads(seed_path.read_text(encoding="utf-8"))


class TestBuiltinSkillIntegration:
    """End-to-end check: the project-architecture seed body renders cleanly."""

    def test_project_architecture_body_renders(self):
        skills = _load_marketplace_tesslate_skills()

        pa = next(s for s in skills if s["slug"] == "project-architecture")
        assert pa.get("is_builtin") is True

        raw = pa["skill_body"]
        rendered = render_markers(raw)

        # Zero unresolved markers.
        import re

        assert not re.findall(r"\{\{[A-Z_]+\}\}", rendered)

        # Rendered body is materially bigger than the template.
        assert len(rendered) > len(raw) * 3

        # Representative substrings from every renderer.
        assert "apps" in rendered
        assert "postgres" in rendered.lower()
        assert "Vercel" in rendered
        assert "apply_setup_config" in rendered

    def test_every_builtin_marker_has_a_renderer(self):
        """Catch rename drift: every ``{{TOKEN}}`` referenced in a built-in
        skill body must have a registered renderer. Breaks if someone edits
        the seed template to introduce a new marker without adding its
        renderer to MARKER_RENDERERS.
        """
        import re

        skills = _load_marketplace_tesslate_skills()
        marker_pattern = re.compile(r"\{\{[A-Z_]+\}\}")

        missing: dict[str, set[str]] = {}
        for entry in skills:
            if not entry.get("is_builtin"):
                continue
            body = entry.get("skill_body", "")
            tokens = set(marker_pattern.findall(body))
            unregistered = tokens - set(MARKER_RENDERERS.keys())
            if unregistered:
                missing[entry["slug"]] = unregistered

        assert not missing, (
            f"Built-in skills reference markers with no registered renderer: "
            f"{missing}. Add the renderer to "
            f"orchestrator/app/services/skill_markers.py:MARKER_RENDERERS."
        )
