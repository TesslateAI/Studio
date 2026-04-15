"""Unified node-configuration preset registry.

Presets define the form schema the agent (or user) is asked to fill in when a
new Container node is added to a project. Agent-supplied ``field_overrides``
are merged by ``resolve_schema`` — an override with the same ``key`` replaces
the preset field; new keys append.

Field types:
  * ``text``, ``url``, ``textarea``    — plaintext inputs.
  * ``secret``                         — password-style; always ``is_secret``.
  * ``select``                         — dropdown, ``options`` required.
  * ``number``                         — numeric input.

The split between ``environment_vars`` (plaintext) and ``encrypted_secrets``
(Fernet) is driven by ``is_secret``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

FieldType = Literal["text", "url", "secret", "select", "number", "textarea"]
DeploymentMode = Literal["external", "container"]


@dataclass
class FieldSchema:
    key: str
    label: str
    type: FieldType
    required: bool = False
    is_secret: bool = False
    placeholder: str | None = None
    help: str | None = None
    options: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Strip Nones so the JSON shipped to the UI stays compact and stable.
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class Preset:
    key: str
    display_name: str
    icon: str  # lucide icon name
    deployment_mode: DeploymentMode
    fields: list[FieldSchema] = field(default_factory=list)
    container_template: dict[str, Any] | None = None


@dataclass
class FormSchema:
    preset: str
    display_name: str
    icon: str
    deployment_mode: DeploymentMode
    fields: list[FieldSchema]

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "display_name": self.display_name,
            "icon": self.icon,
            "deployment_mode": self.deployment_mode,
            "fields": [f.to_dict() for f in self.fields],
        }

    def secret_keys(self) -> set[str]:
        return {f.key for f in self.fields if f.is_secret}

    def field_keys(self) -> set[str]:
        return {f.key for f in self.fields}


PRESETS: dict[str, Preset] = {
    "supabase": Preset(
        key="supabase",
        display_name="Supabase",
        icon="database",
        deployment_mode="external",
        fields=[
            FieldSchema(
                key="SUPABASE_URL",
                label="Supabase URL",
                type="url",
                required=True,
                placeholder="https://xxx.supabase.co",
            ),
            FieldSchema(
                key="SUPABASE_ANON_KEY",
                label="Anon Key",
                type="secret",
                required=True,
                is_secret=True,
            ),
            FieldSchema(
                key="SUPABASE_SERVICE_KEY",
                label="Service Role Key",
                type="secret",
                is_secret=True,
                help="Keep this server-side only.",
            ),
        ],
    ),
    "postgres": Preset(
        key="postgres",
        display_name="PostgreSQL",
        icon="database",
        deployment_mode="external",
        fields=[
            FieldSchema(
                key="POSTGRES_URL",
                label="Connection URL",
                type="url",
                required=True,
                placeholder="postgres://user:pass@host:5432/dbname",
            ),
            FieldSchema(key="POSTGRES_USER", label="User", type="text"),
            FieldSchema(
                key="POSTGRES_PASSWORD",
                label="Password",
                type="secret",
                is_secret=True,
            ),
            FieldSchema(key="POSTGRES_DB", label="Database", type="text"),
        ],
    ),
    "stripe": Preset(
        key="stripe",
        display_name="Stripe",
        icon="credit-card",
        deployment_mode="external",
        fields=[
            FieldSchema(
                key="STRIPE_PUBLISHABLE_KEY",
                label="Publishable Key",
                type="text",
                required=True,
                placeholder="pk_test_...",
            ),
            FieldSchema(
                key="STRIPE_SECRET_KEY",
                label="Secret Key",
                type="secret",
                required=True,
                is_secret=True,
                placeholder="sk_test_...",
            ),
            FieldSchema(
                key="STRIPE_WEBHOOK_SECRET",
                label="Webhook Secret",
                type="secret",
                is_secret=True,
                placeholder="whsec_...",
            ),
        ],
    ),
    "rest_api": Preset(
        key="rest_api",
        display_name="REST API",
        icon="globe",
        deployment_mode="external",
        fields=[
            FieldSchema(
                key="API_BASE_URL",
                label="Base URL",
                type="url",
                required=True,
                placeholder="https://api.example.com",
            ),
            FieldSchema(
                key="API_KEY",
                label="API Key",
                type="secret",
                is_secret=True,
            ),
            FieldSchema(
                key="API_AUTH_HEADER",
                label="Auth Header",
                type="text",
                placeholder="Authorization",
            ),
        ],
    ),
    "external_generic": Preset(
        key="external_generic",
        display_name="External Service",
        icon="plug",
        deployment_mode="external",
        fields=[],
    ),
}


def _field_from_override(raw: dict[str, Any]) -> FieldSchema:
    """Build a FieldSchema from an agent-supplied override dict.

    Unknown keys are ignored to avoid breaking on forward-compatible agents.
    """
    if "key" not in raw or "label" not in raw or "type" not in raw:
        raise ValueError(
            f"Override missing required fields (key/label/type): {raw}"
        )
    return FieldSchema(
        key=str(raw["key"]),
        label=str(raw["label"]),
        type=raw["type"],
        required=bool(raw.get("required", False)),
        is_secret=bool(raw.get("is_secret", False)) or raw["type"] == "secret",
        placeholder=raw.get("placeholder"),
        help=raw.get("help"),
        options=raw.get("options"),
    )


def resolve_schema(
    preset_key: str,
    overrides: list[dict[str, Any]] | None = None,
) -> FormSchema:
    """Resolve the effective form schema for a preset + override list.

    Overrides with a key that matches an existing preset field *replace* it
    (preserving position). Overrides with new keys are appended in order.
    """
    preset = PRESETS.get(preset_key)
    if preset is None:
        raise KeyError(
            f"Unknown node-config preset '{preset_key}'. "
            f"Available: {sorted(PRESETS)}"
        )

    fields = [FieldSchema(**asdict(f)) for f in preset.fields]  # deep-copy-ish
    override_fields = [_field_from_override(o) for o in (overrides or [])]

    # Replace-by-key, append new.
    existing_idx = {f.key: i for i, f in enumerate(fields)}
    for of in override_fields:
        if of.key in existing_idx:
            fields[existing_idx[of.key]] = of
        else:
            fields.append(of)
            existing_idx[of.key] = len(fields) - 1

    return FormSchema(
        preset=preset.key,
        display_name=preset.display_name,
        icon=preset.icon,
        deployment_mode=preset.deployment_mode,
        fields=fields,
    )
