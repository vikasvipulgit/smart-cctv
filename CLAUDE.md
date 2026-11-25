# CLAUDE.md - Smart CCTV

Claude Code reads this file automatically. It carries the context from the planning chat
where this project was designed and scaffolded. Full background: `docs/PROJECT_CONTEXT.md`.

## What this project is

A smart CCTV web application: read live IP camera feeds (RTSP), detect events with AI
(specific cars / number plates, car type and colour, objects or people in a zone, theft,
factory-line issues), raise alerts on the user's devices, and let users search footage or
create alerts with natural-language prompts.

Owner is in India (Asia/Calcutta). Development machine: MacBook Pro, Apple M2, 16 GB (arm64), python.org Python 3.12.
Current setup: Mac webcam (`webcam`, source "0") with `DETECTOR=yolo`; a CP Plus camera/NVR (possibly at another
site) is next. Latest session log: `docs/PROJECT_CONTEXT.md` section 10.

## Decisions already made (don't re-litigate without asking)

- **Web application first** (FastAPI backend + React/Vite dashboard). Must stay extendable to
  mobile (Capacitor or Flutter, see `mobile/README.md`) and desktop (Tauri, see `desktop/README.md`).
  Keep all features behind the REST + WebSocket API so other clients can reuse them.
- **Cameras:** IP/CCTV over RTSP. Processing runs on a local PC/Mac.
- **Alerts:** web dashboard (WebSocket + browser notifications), Telegram, email, SMS (MSG91), mobile push later (FCM).
- **Detection:** Ultralytics YOLO + ByteTrack, one detector instance per camera (tracking state lives in the model).
  `DETECTOR=mock` + camera `source: "synthetic"` runs the whole app with no hardware or model.
- **Prompt search:** index everything seen (`sightings` table), keyword parser by default,
  optional LLM (`LLM_PROVIDER=anthropic|ollama`) and CLIP embeddings (`EMBEDDINGS=1`).
  Prompts that start with "Alert me..." become a *proposed* rule the user confirms; never auto-activate.
- **Camera hardware advice for India:** only STQC-certified cameras (rule in force since 1 Apr 2026),
  CP Plus for budget, Matrix for quality, wired PoE, RTSP + ONVIF, use the sub-stream for AI.
- **Secrets** (RTSP passwords, bot tokens, API keys) live only in `.env`. cameras.yaml references them as `${VAR}`.
- **Timestamps** are stored as naive UTC in the DB (`models.utcnow`, `to_utc_naive`, `utc_iso`, `local_of`).

## Layout

```
backend/app/
  main.py            FastAPI app, lifespan starts pipeline, /ws/events, serves frontend/dist if built
  config.py          Settings from .env
  config_store.py    Pydantic models for cameras.yaml / rules.yaml, load/save
  capture/stream.py  Threaded reader (RTSP/webcam/file/synthetic), keeps latest frame, auto-reconnect
  detection/         detector.py (YOLO, Mock), color.py (HSV heuristic), plates.py (EasyOCR + fuzzy match),
                     text.py (shared EasyOCR model + TextScanner thread per camera for text_pattern rules)
  rules/engine.py    Zones (normalised coords; per-zone anchor bottom|center|overlap), classes, colours, plates,
                     text_pattern, time window (overnight ok), dwell, cooldown per (rule, camera, track),
                     per_camera arrival mode, message templates (render_message)
  pipeline/manager.py One CameraWorker thread per camera -> detect -> enrich -> index -> rules -> events -> alerts
  indexing/indexer.py Sighting rows per track (+ optional CLIP vectors)
  search/prompt.py   parse_keywords / parse_prompt (LLM) / search / rule_from_prompt / ask_about_image
  alerts/            hub.py (WebSocket), channels.py (telegram, email, sms, push stub), dispatcher.py (thread pool)
  api/               cameras.py (status, MJPEG stream, snapshot ?raw, PUT zones, PATCH enabled),
                     events.py (incl. POST ack-all), rules.py, search.py
backend/config/      cameras.yaml, rules.yaml
frontend/src/        App.jsx (hash routing), api.js, useEventSocket.js, components/* (ZoneEditor at #/cameras/<id>)
scripts/             setup_mac.sh, dev.sh, find_rtsp.py (ONVIF discovery + common RTSP paths)
docs/                RTSP_GUIDE.md, PROJECT_CONTEXT.md
```

## Commands

```bash
bash scripts/setup_mac.sh                     # one-time setup (venv in backend/.venv, npm install, .env)
bash scripts/dev.sh                           # backend :8000 + dashboard :5173 (Vite picks 5174+ if taken)
cd backend && source .venv/bin/activate && pytest -q      # tests (must stay green)
cd frontend && npm run build                  # production build, then backend serves it on :8000
python scripts/find_rtsp.py <ip> <user> <pw>  # find a camera's RTSP URL
```

API docs at http://localhost:8000/docs when the backend runs.

## Conventions

- Python 3.10+, type hints, `from __future__ import annotations`. Keep heavy imports (ultralytics, torch, easyocr, open_clip) lazy.
- Worker threads never block on alerts: use `dispatcher.dispatch()`. WebSocket sends from threads go through `hub.broadcast_threadsafe()`.
- Every new rule condition: add it to `RuleConfig`, `RuleEngine.evaluate`, the Rules page `describe()`, and a test in `backend/tests/test_core.py`.
- Edit cameras.yaml only through `config_store._edit_camera` (ruamel round-trip). Comments after a camera hang on the
  end of its `zones` list, so mutate that list in place (see `save_camera_zones`).
- New nullable DB columns are added to existing databases by `db._add_missing_columns()`; no migration tool yet.
- OCR text arrives as `label="text"` detections with `.text`; they only match rules with `text_pattern`.
- `scripts/dev.sh` must keep `--timeout-graceful-shutdown`: the MJPEG stream never ends, so reloads would hang.
- New alert channel: add a function in `alerts/channels.py`, register it in `CHANNELS`, and document its .env keys in `.env.example`.
- Frontend: plain React (no router or UI library yet), styles in `src/styles.css` (dark theme, CSS variables). API base comes from `VITE_API_URL` so mobile/desktop builds can point at a remote server.
- Don't commit `.env`, `backend/data/`, `*.pt` weights.

## Roadmap and next tasks

Status by phase (see README "Roadmap status"):
1. Capture, YOLO, zones, Telegram, events, index: **done**
2. Plates/colour: basic. TODO: YOLO plate detector trained on Indian plates (HSRP + old styles), pre/post-event video clips (H.264 so browsers can play them)
3. Dashboard: done, incl. browser zone editor, camera on/off switch, Clear alerts. TODO: camera add/edit UI
3.2 Rules: text/number reading (`text_pattern`, EasyOCR), arrival mode (`per_camera`), alert `message` templates: done
3.5 Prompt search: done (keywords; LLM + CLIP optional). TODO: VLM verification of top search results;
   "Ask about this camera" on Live tiles (needs the local vs cloud AI decision)
4. Mobile: PWA works. TODO: Capacitor app, `POST /api/devices` + FCM in `send_push()`, remote access via
   Tailscale / Cloudflare Tunnel (needs login first), lighter live stream (WebRTC/HLS) for phones
5. Custom models (factory line stop/count, PPE, theft). TODO: training workflow with Label Studio + Ultralytics

Cross-cutting TODO: authentication (the dashboard has no login yet), multi-camera performance testing,
Postgres option, Docker deployment, retention/cleanup of old snapshots.

## Open decisions to ask the owner about

- Prompt-search AI: local (Ollama, private, needs more GPU) vs cloud (Claude API)
- Personal tool vs commercial product (YOLO is AGPL-3.0; a product needs an Ultralytics licence or permissive models)
- First real deployment: home gate, traffic road, or factory line
- Remote NVR site: is there an always-on computer there (site server + Tailscale) or not
