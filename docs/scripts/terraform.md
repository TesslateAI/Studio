# Terraform Scripts

> Helpers for AWS Secrets Manager-backed Terraform state. The Terraform module trees live under [k8s/terraform/](../../k8s/terraform/); these scripts manage the `.tfvars` files that drive them.

## Files

| File | Purpose |
|------|---------|
| `scripts/terraform/QUICKSTART.md` | Fast path for running Terraform against a new environment. |
| `scripts/terraform/README.md` | Full reference for the AWS stack layout and variables. |
| `scripts/terraform/secrets.sh` | Upload, download, and view `terraform.{env}.tfvars` via AWS Secrets Manager. Avoids checking secrets into git. |

## Typical flow

1. Pull the latest tfvars: `./secrets.sh pull <env>` writes `terraform.<env>.tfvars`.
2. Edit locally.
3. Run Terraform (`terraform plan` / `apply`).
4. Push back: `./secrets.sh push <env>` re-uploads the edited file.

The `aws-deploy` skill wraps all of this for the full deploy flow.

## Related

- Terraform modules: [k8s/terraform/](../../k8s/terraform/) and [docs/infrastructure/terraform/CLAUDE.md](../infrastructure/terraform/CLAUDE.md)
- `aws-deploy` skill (production deploy orchestration)
