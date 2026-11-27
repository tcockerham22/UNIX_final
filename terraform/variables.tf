variable "project_id" {
  description = "GCP project that owns the Ada deployment."
  type        = string
}

variable "region" {
  description = "Region for the subnet, static address, router, and NAT gateway."
  type        = string
  default     = "us-east1"
}

variable "zone" {
  description = "Zone that hosts both Ada VMs and their data disks."
  type        = string
  default     = "us-east1-b"
}

variable "network_name" {
  description = "Name of the dedicated Ada VPC."
  type        = string
  default     = "ada-vpc"
}

variable "subnetwork_name" {
  description = "Name of the dedicated Ada subnet."
  type        = string
  default     = "ada-subnet"
}

variable "subnet_cidr" {
  description = "IPv4 range for the Ada subnet."
  type        = string
  default     = "10.10.0.0/24"
}

variable "static_ip_name" {
  description = "Reserved external address for the edge VM."
  type        = string
  default     = "ada-edge-ip-tf"
}

variable "router_name" {
  description = "Cloud Router used by the AI VM's Cloud NAT gateway."
  type        = string
  default     = "ada-nat-router"
}

variable "nat_name" {
  description = "Cloud NAT gateway name."
  type        = string
  default     = "ada-nat"
}

variable "edge_instance_name" {
  description = "Name of the public edge VM."
  type        = string
  default     = "ada-edge-tf"
}

variable "ai_instance_name" {
  description = "Name of the private AI inference VM."
  type        = string
  default     = "ada-ai-tf"
}

variable "edge_tag" {
  description = "Network tag used by edge firewall rules."
  type        = string
  default     = "ada-edge"
}

variable "ai_tag" {
  description = "Network tag used by AI firewall rules."
  type        = string
  default     = "ada-ai"
}

variable "edge_machine_type" {
  description = "Machine type for the web, load balancer, and database VM."
  type        = string
  default     = "e2-standard-4"
}

variable "ai_machine_type" {
  description = "Machine type for the CPU-only Ollama VM."
  type        = string
  default     = "n2-standard-8"
}

variable "boot_disk_size_gb" {
  description = "Size of each VM's boot disk in gigabytes."
  type        = number
  default     = 20

  validation {
    condition     = var.boot_disk_size_gb >= 20
    error_message = "boot_disk_size_gb must be at least 20."
  }
}

variable "edge_data_disk_size_gb" {
  description = "Size of the edge VM's LVM data disk in gigabytes."
  type        = number
  default     = 40

  validation {
    condition     = var.edge_data_disk_size_gb >= 40
    error_message = "edge_data_disk_size_gb must be at least 40 so LVM has snapshot space."
  }
}

variable "ai_data_disk_size_gb" {
  description = "Size of the AI VM's model disk in gigabytes."
  type        = number
  default     = 64

  validation {
    condition     = var.ai_data_disk_size_gb >= 40
    error_message = "ai_data_disk_size_gb must be at least 40 so LVM has snapshot space."
  }
}

variable "disk_type" {
  description = "Persistent disk type for boot and data disks."
  type        = string
  default     = "pd-balanced"
}

variable "source_image" {
  description = "Boot image for both VMs."
  type        = string
  default     = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
}

variable "service_account_id" {
  description = "Account id for the least-privilege VM service account."
  type        = string
  default     = "ada-vm"
}

variable "grant_logging_and_metrics" {
  description = "Grant the VM service account the standard logging and metrics writer roles."
  type        = bool
  default     = true
}

variable "operator_members" {
  description = "IAM members that may read Ada secrets, for example user:name@example.com."
  type        = list(string)
  default     = []
}

variable "ssh_source_ranges" {
  description = "CIDR ranges allowed to SSH through IAP. The IAP range is included by default."
  type        = list(string)
  default     = ["35.235.240.0/20"]
}

variable "public_http_source_ranges" {
  description = "CIDR ranges allowed to reach the public edge HTTP port."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "repo_url" {
  description = "Git repository cloned into /opt/ada by startup-script metadata."
  type        = string
  default     = "https://github.com/tcockerham22/UNIX_final.git"
}

variable "repo_ref" {
  description = "Git ref checked out by startup-script metadata."
  type        = string
  default     = "main"
}

variable "pull_repo_on_boot" {
  description = "Reset /opt/ada to the configured ref on every boot before starting Ada."
  type        = bool
  default     = true
}

variable "allow_stopping_for_update" {
  description = "Allow Terraform to stop a VM when an update requires it."
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Prevent Terraform from destroying the VMs."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Extra labels applied to Ada resources."
  type        = map(string)
  default     = {}
}

variable "db_secret_name" {
  description = "Secret Manager name for this stack's PostgreSQL password."
  type        = string
  default     = "ada-db-password"
}

variable "grafana_secret_name" {
  description = "Secret Manager name for this stack's Grafana admin password."
  type        = string
  default     = "ada-grafana-admin-password"
}

variable "db_password" {
  description = "Optional PostgreSQL password. Leave null to generate one in Secret Manager."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "grafana_admin_password" {
  description = "Optional Grafana admin password. Leave null to generate one in Secret Manager."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}
