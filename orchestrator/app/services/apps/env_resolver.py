"""Resolve Container.environment_vars into Kubernetes V1EnvVar entries.

Values of the form ``${secret:<name>/<key>}`` become a ``valueFrom``
reference to the named Kubernetes Secret (no plaintext ever touches the
pod spec). Everything else is passed through as a literal ``value``.

Compound values — a string that embeds ``${secret:...}`` alongside other
text (e.g. a DATABASE_URL with a password inline) — are handled via K8s
environment variable substitution: a synthetic ``__tsecret_<name>_<key>``
var is emitted first as a secretKeyRef, then the compound value references
it using the K8s ``$(VAR_NAME)`` syntax. K8s resolves ``$(...)`` at
container start using earlier entries in the same env list.

This helper is the single source of truth for env translation for any
Container row — used by the Deployment builder in start_project and by
schedule-triggered Jobs.
"""

from __future__ import annotations

import re

from kubernetes.client import V1EnvVar, V1EnvVarSource, V1SecretKeySelector

__all__ = ["SECRET_REF_RE", "EMBEDDED_SECRET_RE", "resolve_env_for_pod", "extract_secret_refs"]

# Matches a value where the ENTIRE string is a secret ref.
SECRET_REF_RE = re.compile(r"^\$\{secret:([^/}]+)/([^}]+)\}$")

# Matches ${secret:name/key} anywhere within a string (for compound values).
EMBEDDED_SECRET_RE = re.compile(r"\$\{secret:([^/}]+)/([^}]+)\}")


def extract_secret_refs(env: dict[str, str] | None) -> set[str]:
    """Return the set of unique secret names referenced by ${secret:name/key} values.

    Handles both pure references (entire value is a secret ref) and compound
    values where the ref is embedded in a larger string.
    """
    if not env:
        return set()
    names: set[str] = set()
    for raw in env.values():
        if raw is None:
            continue
        for m in EMBEDDED_SECRET_RE.finditer(str(raw)):
            names.add(m.group(1))
    return names


def resolve_env_for_pod(env: dict[str, str] | None) -> list[V1EnvVar]:
    """Translate a plain ``{key: value}`` env dict into a pod-spec env list.

    * ``value = "${secret:name/key}"`` → ``V1EnvVar(valueFrom=SecretKeyRef(name,key))``
    * ``value`` containing ``${secret:name/key}`` embedded in a larger string →
      emits a synthetic ``__tsecret_<name>_<key>`` secretKeyRef var first, then
      the main var with ``$(__tsecret_...)`` K8s substitution syntax.
    * Any other string → ``V1EnvVar(value=str(value))``
    * ``None``/missing → ``V1EnvVar(value="")`` (K8s rejects ``None`` value).
    """
    if not env:
        return []

    intermediates: list[V1EnvVar] = []
    seen_intermediates: set[str] = set()
    out: list[V1EnvVar] = []

    for key, raw in env.items():
        if raw is None:
            out.append(V1EnvVar(name=str(key), value=""))
            continue
        value = str(raw)

        # Pure secret ref: the entire value is ${secret:name/key}
        m = SECRET_REF_RE.match(value)
        if m:
            secret_name, secret_key = m.group(1), m.group(2)
            out.append(
                V1EnvVar(
                    name=str(key),
                    value_from=V1EnvVarSource(
                        secret_key_ref=V1SecretKeySelector(
                            name=secret_name,
                            key=secret_key,
                        )
                    ),
                )
            )
            continue

        # Compound value: ${secret:name/key} embedded in a larger string.
        # Use K8s $(VAR) substitution so the secret never appears in plaintext.
        all_matches = list(EMBEDDED_SECRET_RE.finditer(value))
        if all_matches:
            expanded = value
            for em in all_matches:
                secret_name, secret_key = em.group(1), em.group(2)
                intermediate_name = (
                    "__tsecret_"
                    + re.sub(r"[^a-zA-Z0-9]", "_", secret_name)
                    + "_"
                    + re.sub(r"[^a-zA-Z0-9]", "_", secret_key)
                )
                if intermediate_name not in seen_intermediates:
                    seen_intermediates.add(intermediate_name)
                    intermediates.append(
                        V1EnvVar(
                            name=intermediate_name,
                            value_from=V1EnvVarSource(
                                secret_key_ref=V1SecretKeySelector(
                                    name=secret_name,
                                    key=secret_key,
                                )
                            ),
                        )
                    )
                expanded = expanded.replace(em.group(0), f"$({intermediate_name})")
            out.append(V1EnvVar(name=str(key), value=expanded))
            continue

        out.append(V1EnvVar(name=str(key), value=value))

    # Intermediate vars must precede the vars that reference them via $(...).
    return intermediates + out
