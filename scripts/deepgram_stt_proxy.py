"""
Deepgram STT Proxy — OpenAI-compatible /v1/audio/transcriptions endpoint.

Accepts requests in OpenAI Whisper format and forwards to Deepgram Nova-3.
Designed for Open WebUI's STT integration (AUDIO_STT_ENGINE=openai).

Usage:
    python scripts/deepgram_stt_proxy.py
    # Listens on :8200, forwards to Deepgram Nova-3 (ar-SA)
"""

import os
import sys
import time
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "64f50623934e269eabd651c7bd4f23f7fa282f6d")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3")
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "ar-SA")
PORT = int(os.getenv("STT_PROXY_PORT", "8200"))

DEEPGRAM_PARAMS = {
    "model": DEEPGRAM_MODEL,
    "language": DEEPGRAM_LANGUAGE,
    "smart_format": "true",
    "punctuate": "true",
    "numerals": "true",
    "diarize": "false",
    "filler_words": "false",
}

DEEPGRAM_HEADERS = {
    "Authorization": f"Token {DEEPGRAM_API_KEY}",
}

# Persistent HTTP client — reuses TCP connection to Deepgram
_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=30,
        http2=True,
        limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=300),
    )
    print(f"[STT-PROXY] HTTP/2 client ready, connection pool initialized", file=sys.stderr)
    yield
    await _http_client.aclose()


app = FastAPI(title="Deepgram STT Proxy", lifespan=lifespan)


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
    t0 = time.monotonic()
    audio_bytes = await file.read()
    content_type = file.content_type or "audio/wav"

    print(f"[STT-PROXY] Received {len(audio_bytes)}B {content_type} ({file.filename})", file=sys.stderr)

    try:
        t1 = time.monotonic()
        resp = await _http_client.post(
            "https://api.deepgram.com/v1/listen",
            params=DEEPGRAM_PARAMS,
            headers={**DEEPGRAM_HEADERS, "Content-Type": content_type},
            content=audio_bytes,
        )
        t2 = time.monotonic()

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

        print(
            f"[STT-PROXY] '{transcript}' — deepgram={t2-t1:.1f}s total={t2-t0:.1f}s",
            file=sys.stderr,
        )

        return {"text": transcript}

    except Exception as e:
        print(f"[STT-PROXY] Error: {e}", file=sys.stderr)
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    print(f"[STT-PROXY] Starting Deepgram proxy on :{PORT} (model={DEEPGRAM_MODEL}, lang={DEEPGRAM_LANGUAGE})")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
