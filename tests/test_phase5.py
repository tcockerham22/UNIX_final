"""Static checks for the Phase 5 boot and storage scripts."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPTS = (
    "gcp-metadata.sh",
    "get-secret.sh",
    "install-docker.sh",
    "manage-secrets.sh",
    "setup-lvm.sh",
    "startup.sh",
    "startup-ai.sh",
    "startup-edge.sh",
    "lvm-snapshot.sh",
)


class Phase5ScriptTests(unittest.TestCase):
    def test_shell_syntax(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                subprocess.run(
                    ["bash", "-n", str(ROOT / "scripts" / name)],
                    check=True,
                    capture_output=True,
                )

    def test_startup_guide_covers_both_roles_and_secrets(self):
        guide = (ROOT / "docs" / "startup.md").read_text(encoding="utf-8")
        for expected in (
            "startup-edge.sh",
            "startup-ai.sh",
            "db-password",
            "grafana-admin-password",
            "ada-ai-ip",
            "/data/db",
            "/models",
            "lvm-snapshot.sh",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, guide)

    def test_setup_lvm_has_safe_reformatting_guard(self):
        setup = (ROOT / "scripts" / "setup-lvm.sh").read_text(encoding="utf-8")
        self.assertIn("refusing to wipe it", setup)
        self.assertIn('SETUP_DB="${SETUP_DB:-1}"', setup)
        self.assertIn('SETUP_MODELS="${SETUP_MODELS:-1}"', setup)

    def test_manage_secrets_enables_secret_manager_api(self):
        manager = (ROOT / "scripts" / "manage-secrets.sh").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "startup.md").read_text(encoding="utf-8")
        self.assertIn("gcloud services enable secretmanager.googleapis.com", manager)
        self.assertIn("gcloud services enable secretmanager.googleapis.com", guide)

    def test_manage_secrets_detects_iam_member_type(self):
        manager = (ROOT / "scripts" / "manage-secrets.sh").read_text(encoding="utf-8")
        self.assertIn('*@*.gserviceaccount.com) member="serviceAccount:$member"', manager)
        self.assertIn('*@*) member="user:$member"', manager)


if __name__ == "__main__":
    unittest.main()
