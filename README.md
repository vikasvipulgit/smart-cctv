# Smart CCTV

AI event detection and alerts for IP/CCTV cameras, with a web dashboard and plain-English search.

- **Live view** of every camera with detection boxes and zones drawn on
- **Event rules**: object type, zone, colour, number-plate watchlist, time window, loitering (dwell), cooldown
- **Alerts** to the web dashboard (with browser notifications), Telegram, email and SMS
- **Ask AI**: "white car in gate area yesterday after 6 pm", or "Alert me if anyone is at the gate after midnight"
- **Search index**: everything the cameras see is recorded, not only alerts

Built as a web app (FastAPI + React) so the same backend can later serve mobile and desktop apps.

## Quick start (macOS)

```bash
cd ~/Documents/smart-cctv
bash scripts/setup_mac.sh     # one time: Python venv, packages, .env, web packages
bash scripts/dev.sh           # starts backend + dashboard
```

Open **http://localhost:5173**. Out of the box it runs a **synthetic test camera** with `DETECTOR=mock`, so you can see live view, alerts, rules and search working before any camera or AI model is set up.

### Turn on real AI detection

In `.env` set `DETECTOR=yolo`. The first start downloads `yolo11n.pt` (~6 MB). On Apple Silicon it runs on the Mac's GPU (`mps`) automatically.

### Use your webcam (no CCTV camera yet)

In `backend/config/cameras.yaml`, set the demo camera's `source: "0"`. macOS will ask to allow camera access for Terminal.

### Add a real camera

See **[docs/RTSP_GUIDE.md](docs/RTSP_GUIDE.md)**. In short: find the RTSP URL (`python scripts/find_rtsp.py`), test it in VLC, put it in `.env`, and reference it from `cameras.yaml`.

### Telegram alerts (2 minutes)

1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Message your new bot once, then message **@userinfobot** to get your chat id.
3. Put both in `.env` as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, then restart.

## Project structure

```
smart-cctv/
├── backend/                  FastAPI + video/AI pipeline (Python)
│   ├── app/
│   │   ├── main.py           app entry, routes, WebSocket, serves built dashboard
│   │   ├── config.py         settings from .env
│   │   ├── config_store.py   cameras.yaml / rules.yaml models
│   │   ├── capture/          RTSP / webcam / file / synthetic readers, auto-reconnect
│   │   ├── detection/        YOLO + ByteTrack, colour, number plates
│   │   ├── rules/            rule engine (zones, colour, plates, time, dwell, cooldown)
│   │   ├── alerts/           dispatcher + websocket, telegram, email, sms, push
│   │   ├── indexing/         search index of every tracked object (+ optional CLIP)
│   │   ├── search/           prompt -> filters, prompt -> rule, ask-a-VLM
│   │   ├── pipeline/         one worker thread per camera
│   │   ├── storage/          snapshots, overlays
│   │   └── api/              REST endpoints
│   ├── config/cameras.yaml   your cameras and zones
│   ├── config/rules.yaml     your alert rules (also editable in the dashboard)
│   ├── data/                 database + snapshots (created at runtime)
│   └── tests/                pytest
├── frontend/                 React + Vite web dashboard (installable PWA)
├── scripts/                  setup_mac.sh, dev.sh, find_rtsp.py
├── docs/                     RTSP guide, architecture
├── mobile/                   Phase 4 plan (Capacitor / Flutter)
└── desktop/                  later: Tauri / Electron
```

## How it works

```
Camera (RTSP) -> capture thread (latest frame only) -> YOLO + ByteTrack (5-10 fps)
   -> colour / plate enrichment -> zone test -> search index
   -> rule engine -> event (DB + snapshot) -> alert dispatcher -> websocket / telegram / email / sms
```

API docs (auto-generated): **http://localhost:8000/docs**

| Endpoint | Purpose |
| --- | --- |
| `GET /api/cameras` | camera status |
| `GET /api/cameras/{id}/stream` | live MJPEG view (works in an `<img>` tag) |
| `GET /api/events` | event history with filters |
| `GET/POST/PUT/DELETE /api/rules` | manage rules (saved to rules.yaml, applied live) |
| `POST /api/search` | plain-English search |
| `POST /api/search/rule` | turn a prompt into a proposed rule |
| `POST /api/search/ask` | ask a vision model about an event snapshot |
| `WS /ws/events` | live events |

## Roadmap status

| Phase | Status |
| --- | --- |
| 1. Capture, YOLO, zones, Telegram, events, index | **Working** |
| 2. Number plates, colour, clips | Plates (EasyOCR, `PLATE_OCR=1`) and colour **working, basic**; plate-detector model and video clips TODO |
| 3. Web dashboard | **Working**: live, events, rules, cameras, zone drawing in the browser (Cameras → Edit zones). Camera add/edit UI: TODO |
| 3.5 Prompt search | **Working**: keyword parser built in; Claude / Ollama via `LLM_PROVIDER`; CLIP via `EMBEDDINGS=1` |
| 4. Mobile app + push | PWA works now; native app plan in `mobile/README.md` |
| 5. Custom models (factory, theft) | Train with Label Studio + Ultralytics, then set `YOLO_MODEL` to your weights |

## Production build

```bash
cd frontend && npm run build      # creates frontend/dist
cd ../backend && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000   # serves API + dashboard on one port
```

## Tests

```bash
cd backend && source .venv/bin/activate && pytest -q
```

## Notes

- **Licence:** Ultralytics YOLO is AGPL-3.0. That's fine for personal or internal use. To sell this as a product, buy an Ultralytics licence or switch to a permissive model.
- **Privacy:** India's DPDP Act applies to faces and plates when used beyond your own property. Keep `.env` private and change camera default passwords.
- **Security:** the dashboard has no login yet. Keep it on your local network or behind Tailscale until auth is added.
