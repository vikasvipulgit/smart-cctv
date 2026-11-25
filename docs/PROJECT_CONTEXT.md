# Project context (from the planning chat, 25 Nov 2026)

A summary of the conversation in which this project was planned and built, so work can carry on
in VS Code / Claude Code with the same background.

## 1. The goal

"Build a smart camera application that captures the live feed from CCTV and, when a particular
event happens, catches it and raises an alert on my device. For example, a particular car passing
through traffic." Also requested:

- Events beyond vehicles: number plates, car type/colour, any vehicle in a zone, people,
  and custom events like **factory production-line problems** and **house theft**.
- A feature where the user **types a prompt to find a particular issue** in the footage.
- It must be a **web application** that can later be extended to **mobile and desktop** apps.

## 2. Requirements captured

| Area | Answer |
| --- | --- |
| Detection | Number plates (ANPR), car type/colour, any vehicle in a zone, people/objects, custom events (factory, theft) |
| Camera source | IP/CCTV cameras over RTSP |
| Processing | Local PC/laptop (owner's Mac, Apple Silicon) |
| Alert delivery | Own mobile app, web dashboard, email/SMS, Telegram/WhatsApp bot |
| App type | Web app first, extendable to mobile and desktop |
| Build scope | Full project skeleton, Phase 1 working |
| Location | ~/Documents/smart-cctv |

## 3. Architecture agreed

Cameras (RTSP) → capture service (OpenCV, 5-10 fps, auto-reconnect) → detection engine
(YOLO + ByteTrack, plate OCR, colour, zones) → rules + backend (FastAPI, events, snapshots) and
search index (attributes + CLIP vectors) → alert dispatcher → mobile app / web dashboard /
Telegram / email-SMS. Prompt search reads the index: an LLM turns text into filters, and a VLM checks the top matches.

### Event types → approach

| Event | Approach |
| --- | --- |
| Specific car | Plate detector + OCR, fuzzy match against a watchlist |
| Car type/colour | YOLO class + colour of the box, inside a zone |
| Vehicle/object in zone | Tracked object's anchor point in a polygon |
| People/intrusion | Person in zone during hours, loitering > N s |
| House theft | Intrusion after hours, loitering, object disappearing |
| Factory line | Counting across a line, line stopped, PPE missing, defects (custom models) |

### Prompt feature, three modes

1. **Search past footage**: "every white SUV at the gate yesterday after 6 pm"
2. **Create a live alert**: "alert me if anyone goes near the back door after midnight" (user confirms the rule)
3. **Ask about a clip**: "did the conveyor stop here? why?" (vision-language model)

Key design rule: index everything cheaply all the time, and run heavy AI (VLM) only on a short list.

## 4. Roadmap

1. MVP (1-2 weeks): one camera, YOLO, zone rules, Telegram alert + snapshot, events stored and indexed
2. Plates: OCR + watchlist, colour/type filters, clips
3. Web dashboard: live view, timeline, draw zones, edit rules
3.5 Prompt search
4. Mobile app: Flutter/Capacitor, FCM push, email/SMS, remote live view
5. Custom events: factory/theft models, many cameras, optional Jetson edge devices

## 5. Hardware and software advice given

- **Start with:** one 4MP RTSP camera + PoE injector + the existing Mac.
- **PC tiers:** starter (Ryzen 5/i5, 16 GB, RTX 3060 12GB or 5060) vs recommended (Ryzen 7/i7, 32-64 GB,
  RTX 5060 Ti 16GB+; 24 GB GPU for a strong local VLM). GPU prices in India were inflated in late 2026
  (RTX 5060 Ti 16GB launched ~₹47k, seen ~₹94k in Oct 2026).
- **Storage:** NVMe + surveillance HDD (WD Purple / SkyHawk). UPS recommended.
- **Software:** Ubuntu or macOS, Python 3.11, OpenCV/FFmpeg, Ultralytics YOLO, ByteTrack,
  YOLO-World/Grounding DINO, PaddleOCR/EasyOCR, CLIP + Qdrant/pgvector, FastAPI, Postgres/SQLite,
  Redis, React, Flutter/Capacitor, FCM, Telegram bot, MSG91/Twilio, Tailscale.
- **Ongoing costs:** cloud AI per use, SMS (DLT registration needed in India), VPS optional, app-store fees.

## 6. Cameras for India

- Since **1 April 2026**, CCTV cameras without STQC/BIS certification or ER compliance can't be sold
  in India. In practice this removed Hikvision and Dahua from new sales; existing installs keep working.
- **Recommendations:** CP Plus 4MP IP (budget, ~₹2.7k), Matrix (better image/firmware), varifocal 4MP
  for plates at a gate, dedicated ANPR for fast roads, WDR turret/dome for factories.
- **Checklist:** RTSP + ONVIF Profile S, wired PoE, sub-stream, H.264 option, 120 dB WDR, ≥1/2.8"
  sensor, IP67, manual shutter for plates, STQC certificate for the exact model, avoid consumer cloud cams.

### RTSP and ONVIF (as explained)

- **RTSP** carries the live video: `rtsp://user:pass@ip:554/path`, which OpenCV opens directly. Use the main
  stream for recording and the sub-stream for AI.
- **ONVIF** is the cross-brand standard for discovering and controlling cameras (find the RTSP URL, PTZ, zoom, time, events).
- Test any URL in VLC first. Finding the URL: `docs/RTSP_GUIDE.md` and `scripts/find_rtsp.py`.

## 7. Legal and licensing notes

- Ultralytics YOLO is AGPL-3.0: fine for personal/internal use; a commercial product needs a licence or permissive models (RT-DETR, YOLOX).
- India's DPDP Act applies to faces/plates beyond your own property; plate reading on public roads may need permission.

## 8. What was built and verified

- Backend and dashboard as described in `CLAUDE.md` and the README.
- Verified in a Linux workspace (not yet on the Mac): 10 unit tests pass; server runs end to end with the
  synthetic camera + mock detector (events, snapshots, search, rule proposal, rule CRUD, WebSocket,
  MJPEG stream); dashboard builds and renders; real YOLO11n + ByteTrack detection runs on a sample image.
- Bug fixed during testing: "after midnight" was parsed as "night" (20:00-06:00); now 00:00-06:00.

## 9. Where the design document lives

A longer development plan (architecture diagram, roadmap diagram, Phase 1 checklist) was written as a
Claude Doc: https://claude.ai/artifact/NtvMuZKWg3Nb4R7qn5bM7v. A Word copy lives in
`docs/Smart_CCTV_Development_Plan.docx`; it has a "Progress update" section for the 25 Nov 2026 build session
(section 10 below) and an updated "Open decisions and next steps" list. The Claude Doc was not updated.

## 10. Build session on the Mac (25 Nov 2026, Claude Code in VS Code)

First session on the owner's MacBook Pro (Apple M2, 16 GB, macOS, python.org Python 3.12, Node). The app now
runs with real YOLO detection on the Mac's webcam. 24 unit tests pass.

### Built

| Feature | Where | Notes |
| --- | --- | --- |
| Browser zone editor | `frontend/src/components/ZoneEditor.jsx`, `PUT /api/cameras/{id}/zones`, `GET .../snapshot?raw=true` | Draw/drag/insert/delete corners, rename, undo. Saves via ruamel.yaml so cameras.yaml comments survive (see the "end comments" note in `save_camera_zones`). Zones swap into the running worker without a restart. |
| Zone anchor per zone | `Zone.anchor` = `bottom` (default) / `center` / `overlap` (25%+ of the box), `rules/engine.py: in_zone` | Bottom-centre fails on webcams, where people are cut off at the bottom of the frame. The webcam's `zone_1` uses `overlap`. |
| Camera on/off switch | Cameras page, `PATCH /api/cameras/{id}/enabled`, `PipelineManager.set_enabled` | Starts/stops one worker; saved to cameras.yaml; refuses to enable a camera whose `${VAR}` is not set in .env. MJPEG streams end when their worker stops. |
| Number / text reading | `detection/text.py` (EasyOCR, shared model, one `TextScanner` thread per camera) | Runs only while an enabled rule has `text_pattern` for that camera. ~0.37 s per 720p frame on the M2 GPU (MPS) vs ~2.5 s on CPU. Text readings arrive as `label="text"` detections with `.text`. |
| New rule options | `RuleConfig.text_pattern`, `per_camera`, `message` | `text_pattern`: regex on OCR text (text rules ignore `classes`; text never matches ordinary object rules). `per_camera`: arrival mode, one alert per visit, re-armed after nothing matched for `cooldown_seconds`. `message`: template with {text} {label} {camera} {zone} {plate} {rule}. |
| Event fields | `Event.text`, `Event.message` | `db._add_missing_columns()` adds new nullable columns to existing databases at startup. |
| Clear alerts | `POST /api/events/ack-all`, button on the Live page | Acknowledges, doesn't delete. The Live list shows open alerts only. |

Rules added for the owner (rules.yaml): `person_seen` (webcam, person in `zone_1`, arrival mode, 30 s,
message "Person seen in {zone} on {camera}") and `number_seen` (webcam, `text_pattern` `\d{2,}`, 60 s,
message "Number seen: {text}"). Owner's .env now has `DETECTOR=yolo`; `LLM_PROVIDER=none`; Telegram not set up yet.

### Problems hit and their fixes

- `uvicorn --reload` hung forever when code changed while a browser held the MJPEG stream (the generator
  never ends). `scripts/dev.sh` now passes `--timeout-graceful-shutdown 3`. An old stuck process also had to
  be killed by hand once (`kill -9 <pid>` on the port 8000 listener).
- Another project's Vite server held port 5173, so the dashboard started on 5174. dev.sh now tells you to use
  the address Vite prints.
- python.org Python on macOS has no CA certificates until "Install Certificates.command" is run, so EasyOCR's
  model download (urllib) failed. `text.py` sets `SSL_CERT_FILE` to certifi's bundle. EasyOCR models
  (~100 MB) live in `~/.EasyOCR/model`; YOLO weights in `backend/yolo11n.pt`.
- ByteTrack gives a seated person a new track id often (22 ids in 10 minutes), so per-object cooldowns were
  noisy for "a person comes" alerts. Hence `per_camera` arrival mode.
- The mock detector labels any bright blob "person"; use `DETECTOR=yolo` with real cameras.

### Advice given (not built)

- **CP Plus camera:** `rtsp://USER:PASS@IP:554/cam/realmonitor?channel=N&subtype=1` in .env as
  `GATE_RTSP_URL` (quoted; percent-encode special characters in the password). On an NVR, `channel` = slot
  D1, D2... The CP Plus Device ID/serial is cloud (P2P) only and can't be used for RTSP. Some CP Plus Wi-Fi
  models (EzyKam) have no RTSP at all.
- **NVR at another site:** best long-term is a mini PC running Smart CCTV at that site. To start: Tailscale
  with a subnet router on an always-on machine there (works behind CGNAT, common on Jio/Airtel). Avoid
  port-forwarding RTSP. Each sub-stream needs ~0.5-1 Mbps upload.
- **Mobile app from anywhere:** the phone talks only to the site server, never to cameras. Alerts go out
  via FCM/APNs or Telegram (no tunnel needed). Opening the app needs Tailscale (personal) or Cloudflare
  Tunnel (many users). Needs login first. MJPEG (~2-5 Mbps) is too heavy for phones: plan WebRTC/HLS
  (go2rtc/MediaMTX) and event clips. As a product: site boxes connect out to a cloud service.
- **"What does the camera see?":** needs a vision model and a small build ("Ask about this camera" on each
  Live tile, using the raw frame). Waiting on the local (Ollama, `qwen2.5vl:7b`, fits 16 GB) vs cloud
  (Claude API) decision.

### Next steps agreed

Connect the CP Plus camera; Telegram alerts; login; event clips; "Ask about this camera" once the AI
location is chosen; Capacitor app with push notifications. Open questions: personal tool or product, first
real deployment site, and whether the remote NVR site has an always-on computer.
