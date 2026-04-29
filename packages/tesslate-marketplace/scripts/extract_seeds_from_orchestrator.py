"""
One-shot extractor: pull the orchestrator's canonical seed dicts and write them
out as portable JSON files under `app/seeds/`.

The orchestrator's seed modules import SQLAlchemy + auth models, so we can't
just `import` them in this lightweight package. Instead we use Python's AST
module to read each file and walk the literal-only assignments
(`DEFAULT_AGENTS = [...]`, `MCP_SERVERS = [...]`, etc.). Anything that isn't a
plain literal expression (function calls, list comprehensions) is skipped with
a warning.

Run after `pip install` from the package root:

    python scripts/extract_seeds_from_orchestrator.py \
        --orchestrator-seeds ../../orchestrator/app/seeds \
        --output app/seeds
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("seed_extractor")


# (orchestrator_module, dict_name, output_filename, target_kind)
EXTRACT_PLAN: list[tuple[str, str, str, str]] = [
    ("marketplace_agents.py", "DEFAULT_AGENTS", "agents.json", "agent"),
    ("opensource_agents.py", "OPENSOURCE_AGENTS", "opensource_agents.json", "agent"),
    ("marketplace_bases.py", "DEFAULT_BASES", "bases.json", "base"),
    ("community_bases.py", "COMMUNITY_BASES", "community_bases.json", "base"),
    ("skills.py", "OPENSOURCE_SKILLS", "skills_opensource.json", "skill"),
    ("skills.py", "TESSLATE_SKILLS", "skills_tesslate.json", "skill"),
    ("mcp_servers.py", "MCP_SERVERS", "mcp_servers.json", "mcp_server"),
    ("workflow_templates.py", "WORKFLOW_TEMPLATES", "workflow_templates.json", "workflow_template"),
]


_SKIP = object()


def _module_constants(tree: ast.Module) -> dict[str, Any]:
    """Return every module-level `NAME = literal` (or `NAME: T = literal`)
    assignment as a {name: value} map.

    This lets us resolve simple in-file references like
    `_AGENT_BUILDER_SYSTEM_PROMPT` (a string constant) when they appear inside
    a larger list literal we want to extract.
    """
    out: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = value
        elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            out[node.target.id] = value
    return out


def _resolve_node(node: ast.AST, constants: dict[str, Any]) -> Any:
    """Recursive resolver that handles literals + Name references to constants.

    Any other unsupported node type (function calls, comprehensions, attr access)
    raises RuntimeError so the extractor surfaces a clear failure instead of
    silently skipping seed entries.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_resolve_node(elt, constants) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_resolve_node(elt, constants) for elt in node.elts)
    if isinstance(node, ast.Set):
        return {_resolve_node(elt, constants) for elt in node.elts}
    if isinstance(node, ast.Dict):
        return {
            _resolve_node(k, constants): _resolve_node(v, constants)
            for k, v in zip(node.keys, node.values, strict=False)
            if k is not None  # skip **kwargs splats
        }
    if isinstance(node, ast.Name):
        if node.id in constants:
            return constants[node.id]
        if node.id in ("True", "False", "None"):
            return ast.literal_eval(node)
        raise RuntimeError(f"unresolved Name reference: {node.id}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = _resolve_node(node.operand, constants)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.JoinedStr):
        # Plain f-string with constant parts
        parts: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(str(part.value))
            elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Constant):
                parts.append(str(part.value.value))
            else:
                raise RuntimeError("f-string with dynamic value not supported")
        return "".join(parts)
    raise RuntimeError(f"unsupported node type: {type(node).__name__}")


def _extract_dict_from_module(path: Path, name: str) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = _module_constants(tree)
    for node in tree.body:
        targets: list[ast.Name] = []
        value_node: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            targets = [node.target]
            value_node = node.value
        for target in targets:
            if target.id == name and value_node is not None:
                try:
                    value = _resolve_node(value_node, constants)
                except RuntimeError as exc:
                    raise RuntimeError(
                        f"{name} in {path.name} cannot be resolved: {exc}"
                    ) from exc
                if not isinstance(value, list):
                    raise RuntimeError(f"{name} in {path.name} is not a list (got {type(value)!r})")
                return value
    raise RuntimeError(f"{name} not found in {path.name}")


def _normalise_entry(entry: dict[str, Any], kind: str) -> dict[str, Any]:
    """Coerce a seed entry into the marketplace-service's seed JSON shape.

    Keeps the dict roughly compatible with the orchestrator's columns so the
    publish pipeline can consume it without further transformation.
    """
    if "slug" not in entry:
        raise RuntimeError(f"seed entry missing slug: {entry!r}")
    out = dict(entry)
    out.setdefault("kind", kind)
    out.setdefault("name", entry.get("name", entry["slug"]))
    out.setdefault("is_active", True)
    out.setdefault("is_published", entry.get("is_published", True))
    out.setdefault("tags", entry.get("tags") or [])
    out.setdefault("features", entry.get("features") or [])
    out.setdefault("tech_stack", entry.get("tech_stack") or [])
    out.setdefault("pricing_type", entry.get("pricing_type", "free"))
    out.setdefault("price", entry.get("price", 0))
    return out


def _normalise_themes(themes_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted(themes_dir.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if "id" not in data:
            logger.warning("theme %s missing 'id' field; skipping", p.name)
            continue
        normalised = {
            "kind": "theme",
            "slug": data["id"],
            "name": data.get("name", data["id"]),
            "description": data.get("description"),
            "category": data.get("category", "general"),
            "tags": data.get("tags", []),
            "icon": data.get("icon", "palette"),
            "is_active": True,
            "is_published": True,
            "is_featured": data.get("is_featured", False),
            "pricing_type": "free",
            "price": 0,
            "extra_metadata": {
                "mode": data.get("mode", "dark"),
                "author": data.get("author", "Community"),
                "version": data.get("version", "1.0.0"),
                "theme_json": {
                    "colors": data.get("colors", {}),
                    "typography": data.get("typography", {}),
                    "spacing": data.get("spacing", {}),
                    "animation": data.get("animation", {}),
                    "borderless": bool(data.get("borderless", False)),
                },
            },
        }
        out.append(normalised)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orchestrator-seeds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    seeds_dir: Path = args.orchestrator_seeds
    out_dir: Path = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    if not seeds_dir.is_dir():
        logger.error("orchestrator seeds dir not found: %s", seeds_dir)
        return 2

    # ---- AST-based extracts ----
    consolidated: dict[str, list[dict[str, Any]]] = {kind: [] for _, _, _, kind in EXTRACT_PLAN}
    for filename, dict_name, output_name, target_kind in EXTRACT_PLAN:
        path = seeds_dir / filename
        if not path.exists():
            logger.warning("missing %s; skipping %s", path, dict_name)
            continue
        try:
            entries = _extract_dict_from_module(path, dict_name)
        except RuntimeError as exc:
            logger.warning("could not extract %s from %s: %s", dict_name, filename, exc)
            continue
        normalised = [_normalise_entry(e, target_kind) for e in entries]
        (out_dir / output_name).write_text(json.dumps(normalised, indent=2), encoding="utf-8")
        logger.info("wrote %d %s entries -> %s", len(normalised), target_kind, output_name)
        consolidated[target_kind].extend(normalised)

    # Themes live as standalone JSON files
    themes_dir = seeds_dir / "themes"
    if themes_dir.is_dir():
        themes = _normalise_themes(themes_dir)
        (out_dir / "themes.json").write_text(json.dumps(themes, indent=2), encoding="utf-8")
        logger.info("wrote %d theme entries -> themes.json", len(themes))
        consolidated["theme"] = themes
    else:
        (out_dir / "themes.json").write_text("[]", encoding="utf-8")
        logger.warning("no themes dir at %s; wrote empty themes.json", themes_dir)

    # Empty placeholders so the loader doesn't have to short-circuit
    (out_dir / "apps.json").write_text(json.dumps([], indent=2), encoding="utf-8")

    # Consolidated lookup map (per-kind)
    summary = {k: len(v) for k, v in consolidated.items()}
    (out_dir / "_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("summary: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
