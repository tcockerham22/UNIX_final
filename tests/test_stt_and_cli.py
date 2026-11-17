"""Tests for speech-input thresholds and wake-word detection."""

from __future__ import annotations

import unittest

from ada.cli import find_wake_word
from ada.config import Config
from ada.stt import Listener


class WakeWordTests(unittest.TestCase):
    WORDS = ["hey ada", "ada", "hey lovelace", "lovelace"]

    def test_exact_wake_word(self):
        text = "hey ada what time is it"
        end = find_wake_word(text, self.WORDS)
        self.assertIsNotNone(end)
        self.assertEqual(text[end:].strip(), "what time is it")

    def test_fuzzy_single_word(self):
        # Whisper often mishears short names.
        self.assertIsNotNone(find_wake_word("aida, turn on the light", ["ada"]))
        self.assertIsNotNone(find_wake_word("love lace, hello", ["lovelace"]))

    def test_no_wake_word(self):
        self.assertIsNone(find_wake_word("what time is it", self.WORDS))


class ThresholdTests(unittest.TestCase):
    def test_higher_sensitivity_lowers_thresholds(self):
        quiet = Listener(sensitivity=0.0)
        sensitive = Listener(sensitivity=1.0)
        onset_q, silence_q = quiet._thresholds(0.02)
        onset_s, silence_s = sensitive._thresholds(0.02)
        self.assertLess(onset_s, onset_q)
        self.assertLess(silence_s, silence_q)

    def test_noisy_room_does_not_make_detection_impossible(self):
        onset, silence = Listener(sensitivity=0.5)._thresholds(0.2)
        self.assertLessEqual(onset, 0.05)
        self.assertLessEqual(silence, 0.035)

    def test_config_defaults(self):
        config = Config()
        self.assertEqual(config.stt_sensitivity, 0.5)
        self.assertFalse(config.stt_debug)


if __name__ == "__main__":
    unittest.main()
