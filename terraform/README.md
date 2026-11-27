# Phase 6: Terraform infrastructure

This directory creates the Ada deployment from code: a dedicated VPC and
subnet, Cloud NAT, firewalls, two VMs with LVM-ready data disks, a least-
privilege service account, and Secret Manager secrets with boot-time access.
Frank helped with this Phase 6 code.

The AI VM has no external IP. It reaches the internet through Cloud NAT for
Docker pulls and model downloads. The edge VM owns the reserved public address
and is the only VM exposed on HTTP/80. SSH is limited to the IAP forwarding
range unless extra CIDRs are added to `ssh_source_ranges`.

## Files

- `versions.tf` - Terraform and provider versions.
- `variables.tf` - all tunable inputs.
- `main.tf` - infrastructure resources.
- `outputs.tf` - addresses, SSH command, and chat URL.
- `terraform.tfvars.example` - safe values; contains no passwords.

## First deployment

```sh
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform/terraform.tfvars with your project and naming choices.

terraform -chdir=terraform init
terraform -chdir=terraform fmt -check
terraform -chdir=terraform validate
terraform -chdir=terraform plan
terraform -chdir=terraform apply
```

If `plan` reports that application default credentials are missing, run
`gcloud auth application-default login` once, or set
`GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"` for that shell.

Leave `db_password` and `grafana_admin_password` unset to let Terraform
generate random values. They are stored as Secret Manager versions and in the
gitignored Terraform state. Do not commit `terraform.tfvars` or `.tfstate`.

Startup-script metadata clones the repository into `/opt/ada`, then calls
`scripts/startup.sh`. The `ada-role` attribute selects `edge` or `ai`, and the
edge VM receives the AI private IP through `ada-ai-ip`. Both roles attach the
data disk as `data-disk`, which is the device name expected by
`scripts/setup-lvm.sh`.

## Current manual deployment

The manual VMs already use the older `default` network and the default compute
service account. A clean Terraform apply creates a parallel stack with the
`-tf` resource names in the example tfvars. To avoid duplicate secret or
address names, either keep those example names or import the existing ones:

```sh
terraform -chdir=terraform import google_compute_address.edge \
  projects/PROJECT/regions/REGION/addresses/ada-edge-ip
terraform -chdir=terraform import google_secret_manager_secret.ada[\"db-password\"] \
  projects/PROJECT/secrets/db-password
```

Importing a secret does not import its versions. Prefer a fresh secret name or
record the existing version number and import that version as well before
applying. Do not import the default-network VMs into this configuration: the
Terraform design intentionally uses a dedicated VPC and service account.

## Verification

```sh
curl -fsS http://$(terraform -chdir=terraform output -raw edge_public_ip)/healthz
terraform -chdir=terraform output ai_private_ip
```
