"""Speech to text: record a phrase from the microphone and transcribe it locally."""

from __future__ import annotations

import os
import time
from collections import deque

import numpy as np

SAMPLE_RATE = 16000
BLOCK_SECONDS = 0.03


def resolve_device(value, kind: str = "input"):
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def _rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(block))) + 1e-12)


def _resample(audio: np.ndarray, source: int, target: int = SAMPLE_RATE) -> np.ndarray:
    if source == target or audio.size == 0:
        return audio
    duration = audio.size / source
    count = int(duration * target)
    old = np.linspace(0.0, duration, num=audio.size, endpoint=False)
    new = np.linspace(0.0, duration, num=count, endpoint=False)
    return np.interp(new, old, audio).astype(np.float32)


class Listener:
    def __init__(self, model_name: str = "base.en", input_device=None):
        self.model_name = model_name
        self.input_device = resolve_device(input_device, "input")
        self._model = None
        self.last_audio_seconds = 0.0

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        threads = max(1, os.cpu_count() or 4)
        self._model = WhisperModel(
            self.model_name,
            device="cpu",
            compute_type="int8",
            cpu_threads=threads,
        )

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def record_phrase(
        self,
        max_seconds: float = 15.0,
        start_timeout: float = 7.0,
        silence_seconds: float = 0.8,
        preroll_seconds: float = 0.35,
        status=None,
    ) -> np.ndarray | None:
        import sounddevice as sd

        block = int(SAMPLE_RATE * BLOCK_SECONDS)
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self.input_device,
                blocksize=block,
            )
            rate = SAMPLE_RATE
        except Exception:
            info = sd.query_devices(self.input_device, "input")
            rate = int(info["default_samplerate"]) or 48000
            block = int(rate * BLOCK_SECONDS)
            stream = sd.InputStream(
                samplerate=rate,
                channels=1,
                dtype="float32",
                device=self.input_device,
                blocksize=block,
            )

        with stream:
            ambient = []
            for _ in range(16):
                sample = stream.read(block)[0][:, 0]
                ambient.append(_rms(sample - sample.mean()))
            noise_floor = float(np.median(ambient)) if ambient else 0.0
            onset = max(0.018, min(0.08, noise_floor * 4.0))
            silence_threshold = max(0.010, min(0.05, noise_floor * 2.5))

            if status:
                status("listening")
            preroll = deque(maxlen=max(1, int(preroll_seconds / BLOCK_SECONDS)))
            frames: list[np.ndarray] = []
            started = None
            last_voice = 0.0
            loud_blocks = 0
            began = time.time()

            while True:
                data, _overflowed = stream.read(block)
                mono = data[:, 0].copy()
                mono -= mono.mean()
                level = _rms(mono)
                preroll.append(mono)

                if started is None:
                    loud_blocks = loud_blocks + 1 if level > onset else 0
                    if loud_blocks >= 5:
                        started = time.time()
                        last_voice = started
                        frames.extend(preroll)
                        if status:
                            status("recording")
                    elif time.time() - began > start_timeout:
                        return None
                else:
                    frames.append(mono)
                    now = time.time()
                    if level > silence_threshold:
                        last_voice = now
                    else:
                        noise_floor = 0.97 * noise_floor + 0.03 * level
                        silence_threshold = max(0.010, min(0.05, noise_floor * 2.5))
                    if now - last_voice > silence_seconds or now - started > max_seconds:
                        break

        if not frames:
            return None
        audio = _resample(np.concatenate(frames), rate)
        self.last_audio_seconds = audio.size / SAMPLE_RATE
        if self.last_audio_seconds < 0.25:
            return None
        return audio
