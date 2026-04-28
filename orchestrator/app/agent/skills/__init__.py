"""Built-in agent skills (Phase 5).

Skill bodies are plain markdown loaded on-demand by the ``load_skill``
agent tool. The directory layout matches the canonical
``.agents/skills/{name}/SKILL.md`` convention so skills can be authored
in-tree and surfaced through the same skill-discovery service the
marketplace uses.

Each skill is a directory under this package containing:

- ``SKILL.md`` — markdown body (with optional YAML frontmatter for
  ``name`` + ``description``).
- Optional supporting files referenced by the skill body.

Currently shipping:
- ``agent-builder`` — orchestrates depth-1 child-agent creation via the
  ``marketplace_ops`` tool group.
"""
