"""
Deepgram STT Proxy — OpenAI-compatible /v1/audio/transcriptions endpoint.

Accepts requests in OpenAI Whisper format and forwards to Deepgram Nova-3.
Designed for Open WebUI's STT integration (AUDIO_STT_ENGINE=openai).

OWUI records WAV → converts to MP3 (lossy) before sending here.
This proxy converts MP3 → WAV 16kHz mono (optimal for Deepgram) before forwarding.

Usage:
    python scripts/deepgram_stt_proxy.py
    # Listens on :8200, forwards to Deepgram Nova-3 (ar-SA)
"""

import io
import os
import subprocess
import sys
import tempfile

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "64f50623934e269eabd651c7bd4f23f7fa282f6d")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3")
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "ar-SA")
PORT = int(os.getenv("STT_PROXY_PORT", "8200"))

app = FastAPI(title="Deepgram STT Proxy")


def _convert_to_wav16k(audio_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    """Convert any audio to WAV 16kHz mono PCM — optimal for Deepgram."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".in", delete=False) as inf:
            inf.write(audio_bytes)
            in_path = inf.name
        out_path = in_path + ".wav"
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1",
             "-sample_fmt", "s16", "-f", "wav", out_path],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            with open(out_path, "rb") as f:
                wav_bytes = f.read()
            print(f"[STT-PROXY] Converted {content_type} {len(audio_bytes)}B → WAV 16kHz {len(wav_bytes)}B", file=sys.stderr)
            return wav_bytes, "audio/wav"
        else:
            print(f"[STT-PROXY] ffmpeg failed: {result.stderr[:200]}", file=sys.stderr)
    except FileNotFoundError:
        print("[STT-PROXY] ffmpeg not found, sending original audio", file=sys.stderr)
    except Exception as e:
        print(f"[STT-PROXY] convert error: {e}", file=sys.stderr)
    finally:
        for p in (in_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass
    return audio_bytes, content_type


@app.get("/health")
def health():
    return {"status": "healthy", "model": f"deepgram/{DEEPGRAM_MODEL}", "language": DEEPGRAM_LANGUAGE}


@app.get("/")
def root():
    return {"service": "deepgram-stt-proxy", "model": DEEPGRAM_MODEL, "port": PORT}


@app.get("/v1/models")
def models():
    return {"data": [{"id": DEEPGRAM_MODEL, "object": "model"}]}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(default=None),
    language: str = Form(default=None),
):
    """OpenAI-compatible transcription endpoint → Deepgram Nova-3."""
    audio_bytes = await file.read()
    content_type = file.content_type or "audio/wav"

    print(f"[STT-PROXY] Received {len(audio_bytes)}B {content_type} ({file.filename})", file=sys.stderr)

    params = {
        "model": DEEPGRAM_MODEL,
        "language": DEEPGRAM_LANGUAGE,
        "smart_format": "true",
        "punctuate": "true",
        "numerals": "true",
        "diarize": "false",
        "filler_words": "false",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers={
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": content_type,
                },
                content=audio_bytes,
            )

        if resp.status_code != 200:
            print(f"[STT-PROXY] Deepgram error {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
            return JSONResponse(status_code=502, content={"error": f"Deepgram returned {resp.status_code}"})

        data = resp.json()
        transcript = (
            data.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        )

        print(f"[STT-PROXY] Transcribed {len(audio_bytes)} bytes → '{transcript}'", file=sys.stderr)

        # Return OpenAI-compatible response
        return {"text": transcript}

    except Exception as e:
        print(f"[STT-PROXY] Error: {e}", file=sys.stderr)
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    print(f"[STT-PROXY] Starting Deepgram proxy on :{PORT} (model={DEEPGRAM_MODEL}, lang={DEEPGRAM_LANGUAGE})")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
