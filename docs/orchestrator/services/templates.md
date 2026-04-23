# Template Services

Services for packaging, storing, and pre-building project templates. Templates power fast project creation: a new project from a base template clones via btrfs reflink in ~1ms instead of a 60-240s git clone + dependency install.

## When to load

Load this doc when:
- Adding a new base template.
- Debugging template-build failures on the Volume Hub.
- Working on project export (share-as-template) or import.

## File map

| File | Purpose |
|------|---------|
| `template_builder.py` | Pre-builds marketplace base templates as btrfs subvolumes. Invoked by the template-refresh cron. After build, new projects from that base are created via btrfs reflink snapshot. |
| `template_export.py` | Packages a project's files into a tar.gz archive so the user can share it as a template. Handles both Docker (filesystem read) and K8s (file-manager pod exec) modes. |
| `template_storage.py` | Stores, retrieves, and deletes tar.gz template archives on the local filesystem at `template_storage_path`. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| ARQ cron `refresh_templates` | `template_builder` |
| `routers/templates.py` | `template_export`, `template_storage` |
| `project_setup/source_acquisition.py` | consumes built templates via `hub_client.create_volume_from_template` |

## Related

- [volume-manager.md](./volume-manager.md): Volume Hub RPCs used for reflink clones.
- [project-setup.md](./project-setup.md): how templates are consumed during project creation.
