"""Kokoro TTS (via mlx-audio) generation, with retry/fallback and a disk cache.

Ported from v1's CLI skills (.claude/skills/{markdown-to-audio,pdf-to-audio}/scripts/),
which already fixed real bugs the original Tauri app's sidecar/tts_server.py never got:

  - lang_code is derived from the voice prefix (af_/am_ -> "a" US English, bf_/bm_ ->
    "b" UK English) and passed explicitly to model.generate(); v1's app-side sidecar
    never did this and risked mis-phonemizing UK voices with the US pipeline.
  - generate_segment_audio() retries a segment that trips Kokoro's MLX
    `broadcast_shapes` decoder bug (a small fraction of phoneme lengths hit it) by
    stripping trailing punctuation, then falls back to recursively bisecting the
    segment and stitching the halves -- this fix previously existed ONLY in the CLI
    skill, not in the app itself. It's included here from day one.

The model is loaded exactly once, as a module-level singleton, at process startup
(see app.py). v1's biggest perf smell was the Tauri sidecar spawning a brand new
Python process -- and therefore reloading the whole Kokoro model -- for every single
segment. A persistent FastHTML process avoids that for free, as long as nothing here
ever calls load_model() more than once.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass

import numpy as np

import cache

VOICES = [
    {"id": "af_heart", "name": "Heart", "language": "US", "gender": "female"},
    {"id": "af_nova", "name": "Nova", "language": "US", "gender": "female"},
    {"id": "af_sky", "name": "Sky", "language": "US", "gender": "female"},
    {"id": "am_adam", "name": "Adam", "language": "US", "gender": "male"},
    {"id": "am_michael", "name": "Michael", "language": "US", "gender": "male"},
    {"id": "bf_emma", "name": "Emma", "language": "UK", "gender": "female"},
    {"id": "bm_george", "name": "George", "language": "UK", "gender": "male"},
]
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
SAMPLE_RATE = 24000

_model = None
_model_lock = threading.Lock()
# Kokoro/MLX is a single shared GPU/ANE resource -- serialize ALL generation calls
# process-wide rather than reasoning about MLX thread-safety under concurrency.
# Fine for a single-user LAN app; the cost is that lookahead prefetch for other
# segments waits behind whichever generation is currently in flight.
_generate_lock = threading.Lock()


def load_model():
    global _model
    with _model_lock:
        if _model is None:
            from mlx_audio import tts
            _model = tts.load_model("prince-canuma/Kokoro-82M")
    return _model


def get_model():
    if _model is None:
        return load_model()
    return _model


def _lang_code_for_voice(voice: str) -> str:
    """Kokoro voice ids are prefixed with their language code (af_/am_ -> US English,
    bf_/bm_ -> UK English, etc). Passing the matching lang_code avoids mis-phonemizing
    UK voices with the US English pipeline (and vice versa)."""
    return voice[0] if voice else "a"


def pad_if_short(text: str) -> str:
    """Kokoro's duration predictor throws an MLX broadcast_shapes error on inputs
    under ~3 words. Pad with a neutral filler rather than fail the segment."""
    if len(text.split()) < 3:
        return text.rstrip(".!?") + ". Right."
    return text


def _generate_raw(model, text: str, voice: str, speed: float) -> np.ndarray | None:
    arrays = []
    lang_code = _lang_code_for_voice(voice)
    for chunk in model.generate(text, voice=voice, speed=speed, lang_code=lang_code):
        audio = getattr(chunk, "audio", None)
        if audio is None:
            continue
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim > 1:
            arr = arr.flatten()
        arrays.append(arr)
    return np.concatenate(arrays) if arrays else None


def generate_segment_audio(model, text: str, voice: str, speed: float, depth: int = 0) -> np.ndarray | None:
    """Generate audio for one segment, working around a known shape-mismatch bug in
    mlx_audio's Kokoro decoder that a small fraction of phoneme lengths trigger
    (ValueError: [broadcast_shapes] ...). Retries with trailing punctuation
    stripped (often enough to dodge it), then falls back to splitting the segment
    in half and stitching the halves together."""
    try:
        return _generate_raw(model, text, voice, speed)
    except ValueError as e:
        if "broadcast_shapes" not in str(e):
            raise

    stripped = text.rstrip(".!?,;: ")
    if stripped and stripped != text:
        try:
            return _generate_raw(model, stripped, voice, speed)
        except ValueError as e:
            if "broadcast_shapes" not in str(e):
                raise

    words = text.split()
    if depth >= 4 or len(words) < 4:
        return None  # give up; caller will skip this segment

    mid = len(words) // 2
    left = generate_segment_audio(model, " ".join(words[:mid]), voice, speed, depth + 1)
    right = generate_segment_audio(model, " ".join(words[mid:]), voice, speed, depth + 1)
    parts = [p for p in (left, right) if p is not None]
    return np.concatenate(parts) if parts else None


def estimate_word_timings(text: str, duration: float) -> list[dict]:
    """Estimate per-word timings based on character length. Kokoro/mlx-audio does not
    expose real forced-alignment word timestamps through its public API (only a
    per-phoneme frame-count array internal to the decoder), so this is a deliberate
    approximation -- not perfect, but gives smooth word-by-word highlighting."""
    words = re.findall(r"\S+", text)
    if not words:
        return []

    char_counts = [len(w) for w in words]
    total_chars = sum(char_counts)
    if total_chars == 0:
        return []

    timings = []
    current_time = 0.0
    for word, chars in zip(words, char_counts):
        word_duration = (chars / total_chars) * duration
        if word[-1] in ".!?":
            word_duration *= 1.3
        elif word[-1] in ",;:":
            word_duration *= 1.1
        timings.append({
            "word": word,
            "start": round(current_time, 3),
            "end": round(current_time + word_duration, 3),
        })
        current_time += word_duration

    if timings and timings[-1]["end"] > 0:
        scale = duration / timings[-1]["end"]
        for t in timings:
            t["start"] = round(t["start"] * scale, 3)
            t["end"] = round(t["end"] * scale, 3)

    return timings


def _audio_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    import struct

    audio = np.clip(audio.astype(np.float32), -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)
    pcm_bytes = pcm.tobytes()

    num_samples = len(pcm)
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", chunk_size, b"WAVE",
        b"fmt ", 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )
    return header + pcm_bytes


@dataclass
class TTSResult:
    wav_bytes: bytes
    duration: float
    word_timings: list[dict]


def get_or_generate(content_hash: str, segment_index: int, text: str, voice: str, speed: float) -> TTSResult | None:
    """Cache-aware entrypoint: the only code path that ever calls Kokoro or writes
    cache files. Returns None if the segment could not be spoken at all (e.g. it
    deterministically crashes the decoder even after the bisection fallback)."""
    wav_path, json_path = cache.cache_paths(content_hash, segment_index, voice, speed)

    if wav_path.exists():
        meta = cache.read_cached_timings(json_path)
        if meta is not None:
            return TTSResult(wav_bytes=wav_path.read_bytes(), duration=meta["duration"], word_timings=meta["word_timings"])

    with _generate_lock:
        # Re-check after acquiring the lock: another request may have generated
        # this exact segment while we were waiting.
        if wav_path.exists():
            meta = cache.read_cached_timings(json_path)
            if meta is not None:
                return TTSResult(wav_bytes=wav_path.read_bytes(), duration=meta["duration"], word_timings=meta["word_timings"])

        model = get_model()
        padded = pad_if_short(text)
        audio = generate_segment_audio(model, padded, voice, speed)
        if audio is None:
            return None

        duration = len(audio) / SAMPLE_RATE
        wav_bytes = _audio_to_wav_bytes(audio, SAMPLE_RATE)
        word_timings = estimate_word_timings(padded, duration)
        cache.write_cache(wav_path, json_path, wav_bytes, {"duration": round(duration, 3), "word_timings": word_timings})

        return TTSResult(wav_bytes=wav_bytes, duration=duration, word_timings=word_timings)
