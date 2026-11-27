"""Static checks for the Phase 6 Terraform configuration."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERRAFORM = ROOT / "terraform"


class Phase6TerraformTests(unittest.TestCase):
    def test_required_files_exist(self):
        for name in (
            "versions.tf",
            "variables.tf",
            "main.tf",
            "outputs.tf",
            "terraform.tfvars.example",
            "README.md",
        ):
            with self.subTest(name=name):
                self.assertTrue((TERRAFORM / name).is_file())

    def test_tfvars_example_is_not_ignored_by_git(self):
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(TERRAFORM / "terraform.tfvars.example")],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, "terraform.tfvars.example must be tracked")

    def test_configuration_covers_the_required_infrastructure(self):
        main = (TERRAFORM / "main.tf").read_text(encoding="utf-8")
        required = (
            'resource "google_compute_network" "ada"',
            'resource "google_compute_subnetwork" "ada"',
            'resource "google_compute_router_nat" "ada"',
            'resource "google_compute_firewall" "public_http"',
            'resource "google_compute_firewall" "ssh"',
            'resource "google_compute_firewall" "edge_to_ai"',
            'resource "google_service_account" "ada_vm"',
            'resource "google_secret_manager_secret" "ada"',
            'resource "google_secret_manager_secret_version" "ada"',
            'resource "google_compute_disk" "edge_data"',
            'resource "google_compute_disk" "ai_data"',
            'resource "google_compute_instance" "edge"',
            'resource "google_compute_instance" "ai"',
            'device_name = "data-disk"',
            "metadata_startup_script = local.startup_script",
            "apt-get install -y git",
            "DB_SECRET_NAME=",
            "GRAFANA_SECRET_NAME=",
            "ada-role  = \"edge\"",
            "ada-ai-ip = google_compute_instance.ai.network_interface[0].network_ip",
            "ada-role = \"ai\"",
        )
        for needle in required:
            with self.subTest(needle=needle):
                self.assertIn(needle, main)

    def test_secret_variables_are_optional_and_sensitive(self):
        variables = (TERRAFORM / "variables.tf").read_text(encoding="utf-8")
        self.assertIn('variable "db_password"', variables)
        self.assertIn('variable "grafana_admin_password"', variables)
        self.assertEqual(variables.count("sensitive   = true"), 2)
        self.assertEqual(variables.count("default     = null"), 2)

    def test_tfvars_example_contains_no_secrets(self):
        example = (TERRAFORM / "terraform.tfvars.example").read_text(encoding="utf-8")
        self.assertIn('project_id = "ubuntu-server-506716"', example)
        self.assertIn('db_secret_name            = "ada-db-password"', example)
        self.assertIn('grafana_secret_name       = "ada-grafana-admin-password"', example)
        self.assertNotIn("db_password =", example)
        self.assertNotIn("grafana_admin_password =", example)

    def test_secret_helper_can_seed_terraform_managed_secrets(self):
        helper = (ROOT / "scripts" / "manage-secrets.sh").read_text(encoding="utf-8")
        self.assertIn("seed)", helper)
        self.assertIn("gcloud secrets versions add", helper)
        subprocess.run(["bash", "-n", str(ROOT / "scripts" / "manage-secrets.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
