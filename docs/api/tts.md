# Text-to-Speech API Documentation

## 1. Overview

**Base Router Path:** `/api`

This section covers the text-to-speech synthesis endpoint. It synthesises speech from a text string using the ElevenLabs API and streams the resulting MP3 audio back to the caller. The endpoint is used by the frontend to voice clinical alerts and assistant answers aloud.

Requires the `ELEVENLABS_API_KEY` environment variable. The voice and model can be overridden via `ELEVENLABS_VOICE_ID` and `ELEVENLABS_MODEL_ID` environment variables.

**Default voice:** Rachel (`21m00Tcm4TlvDq8ikWAM`) — a clear, professional voice suited for clinical alert narration.

**Default model:** `eleven_turbo_v2` — the lowest-latency ElevenLabs model.

---

## 1.1 Interface Definitions

### TTSRequest
| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Text to synthesise into speech. Must not be empty or whitespace-only |

### TTSResponse
The response body is a streaming MP3 audio binary, not a JSON object.

| Header | Value |
|--------|-------|
| `Content-Type` | `audio/mpeg` |

---

## 2. REST API Endpoints

| Method | Path | Function | Success Response Type | Body Type |
|--------|------|----------|-----------------------|-----------|
| POST | `/api/tts` | Synthesise speech and stream MP3 audio | audio/mpeg stream | TTSRequest |

---

## 3. Endpoint Details

### POST `/api/tts`

Synthesise speech via ElevenLabs and stream the MP3 audio back to the caller. The response is a streaming binary MP3; callers should consume it with an audio player or write it to a file.

The voice and model used for synthesis can be configured via environment variables without requiring a code change:
- `ELEVENLABS_VOICE_ID` — override the default Rachel voice
- `ELEVENLABS_MODEL_ID` — override the default `eleven_turbo_v2` model

**Request Body** — `TTSRequest`
```json
{
  "text": "Warning: potential drug interaction detected between Warfarin and Aspirin. Please review before prescribing."
}
```

**Response** — streaming `audio/mpeg`

The response body is a binary MP3 stream. Example browser usage:
```js
const res = await fetch('/api/tts', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text: 'Clinical alert.' }),
});
const blob = await res.blob();
const url = URL.createObjectURL(blob);
new Audio(url).play();
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 400 | `text` is empty or contains only whitespace |
| 503 | `ELEVENLABS_API_KEY` environment variable is not configured |
| 500 | ElevenLabs API call or audio synthesis failure |
