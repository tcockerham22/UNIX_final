"""Tests for Ada's image and diagram generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ada import images, tools as tool_mod
from ada.config import Config

SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.temp = tempfile.TemporaryDirectory()
        self.config.image_dir = self.temp.name
        self.config.image_backend = "svg"

    def tearDown(self):
        self.temp.cleanup()

    def test_clean_svg_extracts_and_sizes(self):
        cleaned = images._clean_svg(f"here you go:\n{SVG}\nhope that helps", 1024)
        self.assertIsNotNone(cleaned)
        self.assertTrue(cleaned.startswith("<svg"))
        self.assertIn('viewBox="0 0 1024 1024"', cleaned)
        self.assertIn('width="1024"', cleaned)
        self.assertIn('height="1024"', cleaned)

    def test_clean_svg_rejects_executable_content(self):
        bad = '<svg><script>alert(1)</script></svg>'
        self.assertIsNone(images._clean_svg(bad, 1024))
        self.assertIsNone(images._clean_svg('<svg onload="x()"></svg>', 1024))

    def test_generate_image_saves_svg(self):
        with patch.object(images, "_model_svg", return_value=SVG), \
             patch.object(images, "render_svg", return_value=False):
            result = images.generate_image("a red square", self.config)
        self.assertIn("Created image:", result)
        files = list(Path(self.temp.name).glob("image-a-red-square-*.svg"))
        self.assertEqual(len(files), 1)
        self.assertIn("<rect", files[0].read_text(encoding="utf-8"))

    def test_generate_diagram_calls_image_with_diagram_kind(self):
        with patch.object(images, "generate_image", return_value="ok") as generate:
            result = images.generate_diagram("A -> B", self.config)
        self.assertEqual(result, "ok")
        self.assertEqual(generate.call_args.args, ("A -> B", self.config))
        self.assertEqual(generate.call_args.kwargs, {"kind": "diagram"})

    def test_empty_prompt_is_rejected(self):
        self.assertTrue(images.generate_image("   ", self.config).startswith("ERROR"))

    def test_photorealistic_without_api_explains_limit(self):
        self.config.image_backend = "svg"
        result = images.generate_image("photorealistic render of a device", self.config)
        self.assertIn("image_api_url", result)

    def test_photorealistic_api_failure_does_not_fall_back_to_svg(self):
        self.config.image_api_url = "http://localhost:7860"
        with patch.object(images, "_sdwebui_image", side_effect=RuntimeError("offline")), \
             patch.object(images, "_model_svg") as model_svg:
            result = images.generate_image("photorealistic render of a device", self.config)
        self.assertIn("could not generate the photorealistic image", result)
        self.assertIn("http://localhost:7860", result)
        self.assertIn("running with its API enabled", result)
        self.assertIn("RuntimeError: offline", result)
        model_svg.assert_not_called()

    def test_raster_backend_uses_quality_settings(self):
        self.config.image_api_url = "http://localhost:7860"
        self.config.image_steps = 40
        self.config.image_sampler = "Euler a"
        self.config.image_negative_prompt = "blurry"
        response = Mock()
        response.json.return_value = {"images": []}
        with patch.object(images.httpx, "post", return_value=response) as post:
            self.assertIsNone(images._sdwebui_image("a detailed landscape", self.config))
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["steps"], 40)
        self.assertEqual(payload["sampler_index"], "Euler a")
        self.assertEqual(payload["negative_prompt"], "blurry")

    def test_api_is_used_when_configured_even_with_svg_legacy_setting(self):
        self.config.image_api_url = "http://localhost:7860"
        with patch.object(images, "_sdwebui_image", return_value=b"image"), \
             patch.object(images, "_model_svg") as model_svg, \
             patch.object(images, "emit"):
            result = images.generate_image("a colorful landscape", self.config)
        self.assertIn(".png", result)
        model_svg.assert_not_called()

    def test_tool_dispatch(self):
        with patch.object(tool_mod, "ensure_reminders"), \
             patch.object(images, "generate_image", return_value="saved.png") as generate:
            result = tool_mod.run_tool(
                "generate_image", {"prompt": "a cat"}, None, self.config
            )
        self.assertEqual(result, "saved.png")
        self.assertEqual(generate.call_args.args[0], "a cat")

        with patch.object(tool_mod, "ensure_reminders"), \
             patch.object(images, "generate_diagram", return_value="diagram.svg") as generate:
            result = tool_mod.run_tool(
                "generate_diagram", {"spec": "A -> B"}, None, self.config
            )
        self.assertEqual(result, "diagram.svg")
        self.assertEqual(generate.call_args.args[0], "A -> B")

    def test_config_defaults(self):
        config = Config()
        self.assertEqual(config.image_backend, "auto")
        self.assertIsNone(config.image_api_url)
        self.assertTrue(config.image_svg_fallback)


if __name__ == "__main__":
    unittest.main()
