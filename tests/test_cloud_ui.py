"""Static checks for the simplified cloud page layout."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CloudUiTests(unittest.TestCase):
    def test_page_has_a_viewport_and_unique_ids(self):
        html = (ROOT / "web" / "cloud.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', html)
        ids = re.findall(r'id="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))

    def test_repeated_header_labels_are_removed(self):
        html = (ROOT / "web" / "cloud.html").read_text(encoding="utf-8")
        self.assertNotIn('class="panel-eyebrow"', html)
        self.assertIn('<h2 class="panel-title">Chat with Ada</h2>', html)
        self.assertIn('<h2 class="panel-title">Service metrics</h2>', html)

    def test_phone_layout_compacts_the_orb_and_composer(self):
        css = (ROOT / "web" / "cloud.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 700px)", css)
        for needle in (
            ".orb-stage, .orb-caption, .orb-glow { display: none; }",
            ".chat-shell {\n    grid-template-rows: auto minmax(0, 1fr);",
            ".view-tabs { width: 100%; }",
            ".composer-surface {\n    flex-direction: row;",
            ".composer-actions .send-button span { display: none; }",
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, css)
        self.assertNotIn("@media (max-width: 640px)", css)

    def test_tab_switch_resets_the_visible_pane(self):
        script = (ROOT / "web" / "cloud.js").read_text(encoding="utf-8")
        self.assertIn("metricsView.scrollTop = 0;", script)
        self.assertIn("scrollToBottom();", script)


if __name__ == "__main__":
    unittest.main()
