locals {
  common_labels = merge(
    {
      project                  = "ada"
      "goog-terraform-managed" = "true"
    },
    var.labels,
  )

  secrets = {
    "db-password" = {
      description = "PostgreSQL password for the Ada edge stack."
    }
    "grafana-admin-password" = {
      description = "Initial Grafana admin password for the Ada edge stack."
    }
  }

  db_password            = var.db_password != null ? var.db_password : random_password.db[0].result
  grafana_admin_password = var.grafana_admin_password != null ? var.grafana_admin_password : random_password.grafana[0].result

  startup_script = <<-EOT
    #!/bin/bash
    set -euo pipefail

    if [[ ! -d /opt/ada/.git ]]; then
      mkdir -p /opt/ada
      git clone --depth 1 --branch "${var.repo_ref}" "${var.repo_url}" /opt/ada
    fi

    cd /opt/ada
    if [[ "${var.pull_repo_on_boot ? "true" : "false"}" == "true" ]]; then
      git fetch --depth 1 origin "${var.repo_ref}" || true
      git reset --hard FETCH_HEAD || true
    fi

    sudo ./scripts/startup.sh
  EOT
}

resource "google_project_service" "apis" {
  for_each = toset([
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "ada" {
  name                    = var.network_name
  description             = "Dedicated VPC for the Ada cloud deployment."
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "ada" {
  name                     = var.subnetwork_name
  description              = "Private subnet for the Ada edge and AI VMs."
  ip_cidr_range            = var.subnet_cidr
  region                   = var.region
  network                  = google_compute_network.ada.id
  private_ip_google_access = true

  depends_on = [google_project_service.apis]
}

resource "google_compute_router" "ada" {
  name        = var.router_name
  description = "Cloud Router for Ada's private AI VM egress."
  region      = var.region
  network     = google_compute_network.ada.id

  depends_on = [google_project_service.apis]
}

resource "google_compute_router_nat" "ada" {
  name                               = var.nat_name
  router                             = google_compute_router.ada.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.ada.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

resource "google_compute_address" "edge" {
  name         = var.static_ip_name
  description  = "Reserved public address for the Ada edge VM."
  address_type = "EXTERNAL"
  region       = var.region

  depends_on = [google_project_service.apis]
}

resource "google_compute_firewall" "public_http" {
  name          = "${var.network_name}-allow-public-http"
  description   = "Allow public HTTP to the Ada edge VM."
  network       = google_compute_network.ada.name
  target_tags   = [var.edge_tag]
  source_ranges = var.public_http_source_ranges

  allow {
    protocol = "tcp"
    ports    = ["80"]
  }

  depends_on = [google_project_service.apis]
}

resource "google_compute_firewall" "ssh" {
  name          = "${var.network_name}-allow-iap-ssh"
  description   = "Allow SSH from the IAP forwarding range and any configured admin CIDRs."
  network       = google_compute_network.ada.name
  target_tags   = [var.edge_tag, var.ai_tag]
  source_ranges = var.ssh_source_ranges

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  depends_on = [google_project_service.apis]
}

resource "google_compute_firewall" "edge_to_ai" {
  name        = "${var.network_name}-allow-edge-to-ai"
  description = "Allow the edge HAProxy to reach the AI readiness shims."
  network     = google_compute_network.ada.name
  source_tags = [var.edge_tag]
  target_tags = [var.ai_tag]

  allow {
    protocol = "tcp"
    ports    = ["11434", "11435"]
  }

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "ada_vm" {
  account_id   = var.service_account_id
  display_name = "Ada VM"
  description  = "Least-privilege service account attached to both Ada VMs."
  project      = var.project_id

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "log_writer" {
  count   = var.grant_logging_and_metrics ? 1 : 0
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.ada_vm.email}"
}

resource "google_project_iam_member" "metric_writer" {
  count   = var.grant_logging_and_metrics ? 1 : 0
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.ada_vm.email}"
}

resource "random_password" "db" {
  count   = var.db_password == null ? 1 : 0
  length  = 24
  special = false
  numeric = true
}

resource "random_password" "grafana" {
  count   = var.grafana_admin_password == null ? 1 : 0
  length  = 24
  special = false
  numeric = true
}

resource "google_secret_manager_secret" "ada" {
  for_each  = local.secrets
  secret_id = each.key
  project   = var.project_id
  labels    = local.common_labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "ada" {
  for_each    = google_secret_manager_secret.ada
  secret      = each.value.id
  secret_data = each.key == "db-password" ? local.db_password : local.grafana_admin_password

  # Secret Manager is the source of truth after the first version is created.
  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_iam_member" "vm" {
  for_each  = google_secret_manager_secret.ada
  project   = var.project_id
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ada_vm.email}"
}

resource "google_secret_manager_secret_iam_member" "operator" {
  for_each = {
    for pair in setproduct(keys(google_secret_manager_secret.ada), var.operator_members) :
    "${pair[0]}|${pair[1]}" => {
      secret = pair[0]
      member = pair[1]
    }
  }

  project   = var.project_id
  secret_id = google_secret_manager_secret.ada[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member
}

resource "google_compute_disk" "edge_data" {
  name   = "${var.edge_instance_name}-data-disk"
  type   = var.disk_type
  size   = var.edge_data_disk_size_gb
  zone   = var.zone
  labels = local.common_labels

  depends_on = [google_project_service.apis]
}

resource "google_compute_disk" "ai_data" {
  name   = "${var.ai_instance_name}-data-disk"
  type   = var.disk_type
  size   = var.ai_data_disk_size_gb
  zone   = var.zone
  labels = local.common_labels

  depends_on = [google_project_service.apis]
}

resource "google_compute_instance" "edge" {
  name                      = var.edge_instance_name
  machine_type              = var.edge_machine_type
  zone                      = var.zone
  tags                      = [var.edge_tag]
  labels                    = merge(local.common_labels, { role = "edge" })
  allow_stopping_for_update = var.allow_stopping_for_update
  deletion_protection       = var.deletion_protection

  boot_disk {
    auto_delete = true

    initialize_params {
      image = var.source_image
      size  = var.boot_disk_size_gb
      type  = var.disk_type
    }
  }

  attached_disk {
    source      = google_compute_disk.edge_data.id
    device_name = "data-disk"
    mode        = "READ_WRITE"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.ada.id

    access_config {
      nat_ip = google_compute_address.edge.address
    }
  }

  metadata = {
    ada-role  = "edge"
    ada-ai-ip = google_compute_instance.ai.network_interface[0].network_ip
  }

  metadata_startup_script = local.startup_script

  service_account {
    email  = google_service_account.ada_vm.email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  depends_on = [
    google_compute_firewall.public_http,
    google_compute_firewall.ssh,
    google_compute_firewall.edge_to_ai,
    google_compute_router_nat.ada,
    google_project_iam_member.log_writer,
    google_project_iam_member.metric_writer,
    google_secret_manager_secret_iam_member.vm,
    google_secret_manager_secret_version.ada,
  ]
}

resource "google_compute_instance" "ai" {
  name                      = var.ai_instance_name
  machine_type              = var.ai_machine_type
  zone                      = var.zone
  tags                      = [var.ai_tag]
  labels                    = merge(local.common_labels, { role = "ai" })
  allow_stopping_for_update = var.allow_stopping_for_update
  deletion_protection       = var.deletion_protection

  boot_disk {
    auto_delete = true

    initialize_params {
      image = var.source_image
      size  = var.boot_disk_size_gb
      type  = var.disk_type
    }
  }

  attached_disk {
    source      = google_compute_disk.ai_data.id
    device_name = "data-disk"
    mode        = "READ_WRITE"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.ada.id
  }

  metadata = {
    ada-role = "ai"
  }

  metadata_startup_script = local.startup_script

  service_account {
    email  = google_service_account.ada_vm.email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  depends_on = [
    google_compute_firewall.ssh,
    google_compute_firewall.edge_to_ai,
    google_compute_router_nat.ada,
    google_project_iam_member.log_writer,
    google_project_iam_member.metric_writer,
    google_secret_manager_secret_iam_member.vm,
    google_secret_manager_secret_version.ada,
  ]
}
