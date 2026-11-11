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
    def __init__(
        self,
        model_name: str = "base.en",
        input_device=None,
        beam_size: int = 5,
        vad_filter: bool = True,
    ):
        self.model_name = model_name
        self.input_device = resolve_device(input_device, "input")
        self.beam_size = max(1, int(beam_size))
        self.vad_filter = bool(vad_filter)
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
        kwargs = dict(
            language="en",
            beam_size=self.beam_size,
            best_of=self.beam_size,
            vad_filter=self.vad_filter,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        if self.vad_filter:
            kwargs["vad_parameters"] = dict(
                min_silence_duration_ms=350,
                speech_pad_ms=200,
            )
        try:
            segments, _info = self._model.transcribe(audio, **kwargs)
        except TypeError:
            # fallback for older faster-whisper versions
            kwargs.pop("best_of", None)
            kwargs.pop("vad_parameters", None)
            segments, _info = self._model.transcribe(audio, **kwargs)
        return " ".join(segment.text.strip() for segment in segments).strip()

    def record_phrase(
        self,
        max_seconds: float = 20.0,
        start_timeout: float = 8.0,
        silence_seconds: float = 1.2,
        preroll_seconds: float = 0.4,
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
            for _ in range(20):
                sample = stream.read(block)[0][:, 0]
                ambient.append(_rms(sample - sample.mean()))
            noise_floor = float(np.median(ambient)) if ambient else 0.0
            onset = max(0.012, min(0.07, noise_floor * 3.5))
            silence_threshold = max(0.008, min(0.045, noise_floor * 2.2))

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
                    loud_blocks = loud_blocks + 1 if level > onset else max(0, loud_blocks - 1)
                    if loud_blocks >= 3:
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
                        noise_floor = 0.985 * noise_floor + 0.015 * level
                        silence_threshold = max(0.008, min(0.045, noise_floor * 2.2))
                    if now - last_voice > silence_seconds or now - started > max_seconds:
                        break

        if not frames:
            return None
        audio = _resample(np.concatenate(frames), rate)
        self.last_audio_seconds = audio.size / SAMPLE_RATE
        if self.last_audio_seconds < 0.25:
            return None
        return audio

    def listen_for_barge_in(self, should_stop, max_wait: float = 30.0, silence_seconds: float = 0.9):
        """Listen while should_stop() is False; return captured speech if user interrupts, else None."""
        import sounddevice as sd

        block = int(SAMPLE_RATE * BLOCK_SECONDS)
        try:
            stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                    device=self.input_device, blocksize=block)
            rate = SAMPLE_RATE
        except Exception:
            info = sd.query_devices(self.input_device, "input")
            rate = int(info["default_samplerate"]) or 48000
            block = int(rate * BLOCK_SECONDS)
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                    device=self.input_device, blocksize=block)

        with stream:
            # quick ambient calibration, but keep responsive
            ambient = []
            for _ in range(8):
                if should_stop():
                    return None
                sample = stream.read(block)[0][:, 0]
                ambient.append(_rms(sample - sample.mean()))
            noise_floor = float(np.median(ambient)) if ambient else 0.0
            onset = max(0.014, min(0.09, noise_floor * 4.0 + 0.006))
            silence_threshold = max(0.009, min(0.05, noise_floor * 2.3))
            preroll = deque(maxlen=max(1, int(0.45 / BLOCK_SECONDS)))
            frames = []
            started = None
            last_voice = 0.0
            loud_blocks = 0
            began = time.time()

            while not should_stop():
                if time.time() - began > max_wait:
                    return None
                data, _overflowed = stream.read(block)
                mono = data[:, 0].copy()
                mono -= mono.mean()
                level = _rms(mono)
                preroll.append(mono)

                if started is None:
                    # while assistant is speaking, require a bit more evidence to avoid echo/self-trigger
                    loud_blocks = loud_blocks + 1 if level > onset else max(0, loud_blocks - 1)
                    need = 4
                    if loud_blocks >= need:
                        started = time.time()
                        last_voice = started
                        frames.extend(preroll)
                else:
                    frames.append(mono)
                    now = time.time()
                    if level > silence_threshold:
                        last_voice = now
                    else:
                        noise_floor = 0.99 * noise_floor + 0.01 * level
                        silence_threshold = max(0.009, min(0.05, noise_floor * 2.3))
                        onset = max(0.014, min(0.09, noise_floor * 4.0 + 0.006))
                    if now - last_voice > silence_seconds or now - started > 20.0:
                        break

        if not frames:
            return None
        audio = _resample(np.concatenate(frames), rate)
        self.last_audio_seconds = audio.size / SAMPLE_RATE
        if self.last_audio_seconds < 0.25:
            return None
        return audio
