"""Turn speech into text, on this machine.

Nemo listens only while you hold the key down, so this is handed a short
recording and asked for words. Everything about that is deliberate: no wake
word means no always-open microphone, and no always-open microphone means the
question of who else is in the room never arises.

Local for the same reason the brain is local. Audio of you talking in your own
house is the most personal thing this system will ever handle, and the cost of
keeping it here is one model download.

mlx-whisper rather than faster-whisper: this runs on Apple Silicon, and the
MLX build uses the GPU the machine already has.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, NamedTuple

# Small and fast. Speech to a desk assistant is short, close-mic and in one
# language; a larger model buys accuracy this does not need and pays for it
# in the seconds between letting go of the key and seeing your words.
DEFAULT_MODEL = "mlx-community/whisper-base-mlx"

# A recording longer than this is a stuck key, not a sentence.
MAX_SECONDS = 120
MAX_BYTES = 25 * 1024 * 1024


class Heard(NamedTuple):
    ok: bool
    text: str
    detail: str = ""
    seconds: float = 0.0


def model_name(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return env.get("RISTRETTO_WHISPER_MODEL", DEFAULT_MODEL)


def transcribe(audio: bytes, suffix: str = ".wav", environ: Mapping[str, str] | None = None) -> Heard:
    """Words from a recording. Never raises — Nemo must not die on a bad clip."""
    if not audio:
        return Heard(False, "", "nothing recorded")
    if len(audio) > MAX_BYTES:
        return Heard(False, "", f"recording too large ({len(audio) // 1024}KB)")

    started = time.monotonic()
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(audio)
            path = Path(handle.name)
        # Imported here, not at module scope: the dashboard imports this file
        # to serve a route, and loading MLX costs seconds and memory that a
        # fleet view has no use for.
        import mlx_whisper

        result = mlx_whisper.transcribe(str(path), path_or_hf_repo=model_name(environ))
        text = str(result.get("text") or "").strip()
        elapsed = round(time.monotonic() - started, 2)
        if not text:
            return Heard(False, "", "nothing recognisable in the recording", elapsed)
        return Heard(True, text, str(result.get("language") or ""), elapsed)
    except ImportError:
        return Heard(False, "", "mlx-whisper is not installed in this environment")
    except Exception as exc:  # noqa: BLE001 - a bad clip must not take Nemo down
        return Heard(False, "", f"could not transcribe: {exc}", round(time.monotonic() - started, 2))
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def warm(environ: Mapping[str, str] | None = None) -> bool:
    """Load the model before anyone is waiting on it.

    The first transcription pays for the download and the load. Doing that
    when Nemo starts rather than when you first speak is the difference
    between "it is thinking" and "it is broken".
    """
    try:
        import mlx_whisper

        silence = _silent_wav()
        mlx_whisper.transcribe(silence, path_or_hf_repo=model_name(environ))
        Path(silence).unlink(missing_ok=True)
        return True
    except Exception:  # noqa: BLE001 - warming is an optimisation, never a gate
        return False


def _silent_wav(seconds: float = 0.2, rate: int = 16000) -> str:
    """A moment of silence, for warming the model without a microphone."""
    import struct
    import wave

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(handle, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(struct.pack("<h", 0) * int(rate * seconds))
    return handle.name
