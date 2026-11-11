"""Ada's voice: local Piper speech synthesis with sentence-level streaming.

    python -m ada.voice        -> audition every voice found in assets/voices
    from ada.voice import Speaker  -> Speaker().speak("Good evening.")

Pick the voice with ADA_VOICE (file name without .onnx) or config.json.
"""

from __future__ import annotations

import io
import queue
import re
import threading
import time
import wave
from collections import OrderedDict
from pathlib import Path

import numpy as np

from .events import emit

ROOT = Path(__file__).resolve().parent.parent
VOICES_DIR = ROOT / "assets" / "voices"
DEFAULT_VOICE = "en_GB-cori-medium"

AUDITION_LINES = [
    "Good evening. The kitchen lights are now at forty percent.",
    "I should be glad to. Shall I also dim the living room?",
    "A curious problem. Let us see what the numbers say.",
]

_CACHE: "OrderedDict[tuple[str, str], tuple[np.ndarray, int]]" = OrderedDict()
_CACHE_LIMIT = 24


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "the link", text)
    text = re.sub(r"[*_#>|]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def resolve_device(value):
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else text


class SentenceSplitter:
    """Turn a stream of token fragments into speakable sentences."""

    _BOUNDARY = re.compile(r'[.!?]+["\')\]]*\s+|\n{2,}')
    _MIN_LENGTH = 12

    def __init__(self) -> None:
        self.buffer = ""
        self.carry = ""

    def add(self, chunk: str) -> list[str]:
        self.buffer += chunk
        sentences: list[str] = []
        while True:
            match = self._BOUNDARY.search(self.buffer)
            if not match:
                break
            candidate = (self.carry + self.buffer[: match.end()]).strip()
            self.buffer = self.buffer[match.end() :]
            self.carry = ""
            if len(candidate) >= self._MIN_LENGTH:
                sentences.append(candidate)
            else:
                self.carry = candidate + " "
        return sentences

    def flush(self) -> list[str]:
        tail = (self.carry + self.buffer).strip()
        self.buffer = ""
        self.carry = ""
        return [tail] if tail else []


class Speaker:
    def __init__(self, voice_name: str | None = None, output_device=None):
        from piper import PiperVoice

        name = voice_name or DEFAULT_VOICE
        model = VOICES_DIR / f"{name}.onnx"
        if not model.exists():
            raise FileNotFoundError(
                f"Voice '{name}' not found in {VOICES_DIR}. Run ./scripts/get-voices.sh first."
            )
        self.name = name
        self.voice = PiperVoice.load(str(model))
        self.output_device = resolve_device(output_device)
        if self.output_device is not None:
            import sounddevice as sd

            try:
                sd.check_output_settings(device=self.output_device)
            except Exception as err:
                print(f"[voice] output device unavailable ({err}); using default.")
                self.output_device = None

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        cleaned = clean_for_speech(text)
        if not cleaned:
            return np.zeros(0, dtype=np.int16), 22050

        key = (self.name, cleaned)
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self.voice.synthesize_wav(cleaned, wav_file)
        with wave.open(io.BytesIO(buffer.getvalue())) as wav_file:
            rate = wav_file.getframerate()
            audio = np.frombuffer(
                wav_file.readframes(wav_file.getnframes()), dtype=np.int16
            ).copy()

        _CACHE[key] = (audio, rate)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
        return audio, rate

    def speak(self, text: str, stop_event: threading.Event | None = None) -> bool:
        """Play audio. Returns False if interrupted."""
        import sounddevice as sd

        audio, rate = self.synthesize(text)
        if not audio.size:
            return True

        sd.play(audio, rate, device=self.output_device)
        samples = None
        try:
            samples = audio.astype(np.float32) / 32768.0
        except Exception:
            samples = None
        start = time.time()
        while True:
            try:
                stream = sd.get_stream()
                active = bool(stream and stream.active)
            except Exception:
                active = False
            if stop_event and stop_event.is_set():
                try:
                    sd.stop()
                except Exception:
                    pass
                emit("voice", action="level", level=0.0)
                return False
            if not active:
                break
            if samples is not None and rate:
                idx = int((time.time() - start) * rate)
                if 0 <= idx < len(samples):
                    seg = samples[idx: idx + max(1, int(rate * 0.05))]
                    if seg.size:
                        level = float(np.sqrt(np.mean(seg * seg)))
                        emit("voice", action="level", level=min(1.0, level * 6.0))
            time.sleep(0.04)
        try:
            sd.wait()
        except Exception:
            pass
        emit("voice", action="level", level=0.0)
        return not (stop_event and stop_event.is_set())


class VoiceOutput:
    """Speak sentences on a worker thread so generation keeps flowing."""

    def __init__(self, speaker: Speaker):
        self.speaker = speaker
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self.speaking = False
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def feed(self, text: str) -> None:
        text = text.strip()
        if text and not self._stop.is_set():
            self._queue.put(text)

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            try:
                if text is None:
                    return
                if self._stop.is_set():
                    continue
                self.speaking = True
                emit("voice", action="start", text=text)
                try:
                    completed = self.speaker.speak(text, stop_event=self._stop)
                    if not completed:
                        self._stop.clear()
                finally:
                    self.speaking = False
                    emit("voice", action="end", text=text)
            except Exception as err:
                print(f"\n[audio error] {type(err).__name__}: {err}")
            finally:
                self._queue.task_done()

    def wait(self) -> None:
        self._queue.join()

    def interrupt(self) -> None:
        self._stop.set()
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        self.clear_pending()

    def clear_pending(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self._queue.task_done()

    def stop(self) -> None:
        self.interrupt()


def audition() -> None:
    models = sorted(VOICES_DIR.glob("*.onnx"))
    if not models:
        print("No voices found. Run ./scripts/get-voices.sh first.")
        return
    for model in models:
        print(f"\n=== {model.stem} ===")
        speaker = Speaker(model.stem)
        for line in AUDITION_LINES:
            print(f"  {line}")
            speaker.speak(line)


if __name__ == "__main__":
    audition()
