"""Resolve Container.environment_vars into Kubernetes V1EnvVar entries.

Values of the form ``${secret:<name>/<key>}`` become a ``valueFrom``
reference to the named Kubernetes Secret (no plaintext ever touches the
pod spec). Everything else is passed through as a literal ``value``.

This helper is the single source of truth for env translation for any
Container row — used by the Deployment builder in start_project and by
schedule-triggered Jobs.
"""

from __future__ import annotations

import re

from kubernetes.client import V1EnvVar, V1EnvVarSource, V1SecretKeySelector

__all__ = ["SECRET_REF_RE", "resolve_env_for_pod", "extract_secret_refs"]


def extract_secret_refs(env: dict[str, str] | None) -> set[str]:
    """Return the set of unique secret names referenced by ${secret:name/key} values."""
    if not env:
        return set()
    names: set[str] = set()
    for raw in env.values():
        if raw is None:
            continue
        m = SECRET_REF_RE.match(str(raw))
        if m:
            names.add(m.group(1))
    return names

# Match the full string (no leading/trailing chars) to avoid partial matches.
SECRET_REF_RE = re.compile(r"^\$\{secret:([^/}]+)/([^}]+)\}$")


def resolve_env_for_pod(env: dict[str, str] | None) -> list[V1EnvVar]:
    """Translate a plain ``{key: value}`` env dict into a pod-spec env list.

    * ``value = "${secret:name/key}"`` → ``V1EnvVar(valueFrom=SecretKeyRef(name,key))``
    * Any other string → ``V1EnvVar(value=str(value))``
    * ``None``/missing → ``V1EnvVar(value="")`` (K8s rejects ``None`` value).
    """
    if not env:
        return []
    out: list[V1EnvVar] = []
    for key, raw in env.items():
        if raw is None:
            out.append(V1EnvVar(name=str(key), value=""))
            continue
        value = str(raw)
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
        else:
            out.append(V1EnvVar(name=str(key), value=value))
    return out
