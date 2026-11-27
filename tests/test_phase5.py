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

    def test_deploy_images_are_consistent(self):
        compose = (ROOT / "deploy" / "ai.compose.yml").read_text(encoding="utf-8")
        startup = (ROOT / "scripts" / "startup-ai.sh").read_text(encoding="utf-8")
        self.assertEqual(compose.count("ollama/ollama:0.40.18"), 2)
        self.assertIn("ollama/ollama:0.40.18", startup)
        self.assertEqual(compose.count("qwen2.5:1.5b"), 2)
        self.assertEqual(compose.count('cpus: "4.00"'), 2)
        self.assertEqual(compose.count('OLLAMA_NUM_THREADS: "4"'), 2)

    def test_cloud_response_limits_are_configurable(self):
        compose = (ROOT / "deploy" / "edge.compose.yml").read_text(encoding="utf-8")
        startup = (ROOT / "scripts" / "startup-edge.sh").read_text(encoding="utf-8")
        config = (ROOT / "ada" / "config.py").read_text(encoding="utf-8")
        self.assertIn("ADA_NUM_CTX: ${ADA_NUM_CTX:-8192}", compose)
        self.assertIn("ADA_LIGHT_MAX_TOKENS: ${ADA_LIGHT_MAX_TOKENS:-4096}", compose)
        self.assertIn('ADA_NUM_CTX=%s', startup)
        self.assertIn('ADA_LIGHT_MAX_TOKENS=%s', startup)
        self.assertIn("num_ctx: int = 8192", config)
        self.assertIn("light_max_tokens: int = 4096", config)

    def test_orb_learning_signal_is_wired_through_the_cloud_ui(self):
        cloud_js = (ROOT / "web" / "cloud.js").read_text(encoding="utf-8")
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        web_py = (ROOT / "ada" / "web.py").read_text(encoding="utf-8")
        self.assertIn("async function syncOrbKnowledge()", cloud_js)
        self.assertIn("learning: extra.learning || null", cloud_js)
        self.assertIn("message.learning?.new_connections", app_js)
        self.assertIn("function knowledgeBand(kind)", app_js)
        self.assertIn('state.current === "learning"', app_js)
        self.assertIn("knowledge_snapshot(session_id)", web_py)

    def test_haproxy_dockerfile_uses_repo_relative_copy_paths(self):
        dockerfile = (ROOT / "deploy" / "haproxy" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY deploy/haproxy/haproxy.cfg.template", dockerfile)
        self.assertIn("COPY deploy/haproxy/render-and-start.sh", dockerfile)


if __name__ == "__main__":
    unittest.main()
