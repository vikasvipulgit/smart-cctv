# How to find your camera's RTSP URL

An RTSP URL is the "web address" of a camera's live video. It looks like this:

```
rtsp://USERNAME:PASSWORD@CAMERA_IP:554/PATH
```

You need four things: the camera's **IP address**, its **username and password**, the **port** (almost always `554`), and the **path**, which depends on the brand.

## 1. Find the camera's IP address

Pick whichever is easiest:

- **Your router's admin page**, usually http://192.168.1.1 or http://192.168.0.1. Look under *Connected devices / DHCP clients* for a device named after the camera brand.
- **The brand's free tool:** CP Plus *IP Finder / Config Tool*, Hikvision *SADP*, Dahua *ConfigTool*, Matrix *Device Discovery*.
- **This project's finder** (same network as the camera):
  ```bash
  cd ~/Documents/smart-cctv && source backend/.venv/bin/activate
  python scripts/find_rtsp.py
  ```
- **The camera's mobile app**, under device info.

Tip: in your router, give the camera a **fixed (reserved) IP** so the URL never changes.

## 2. Make sure RTSP is on

Open `http://CAMERA_IP` in a browser and log in. Under *Network → Port / RTSP*, check that RTSP is enabled and note the port. Change the default password while you are there.

## 3. Common paths by brand

| Brand | Main stream (recording) | Sub-stream (use for AI) |
| --- | --- | --- |
| CP Plus / Dahua | `/cam/realmonitor?channel=1&subtype=0` | `/cam/realmonitor?channel=1&subtype=1` |
| Hikvision / Prama | `/Streaming/Channels/101` | `/Streaming/Channels/102` |
| Matrix | `/media/video1` | `/media/video2` |
| TP-Link VIGI / Tapo | `/stream1` | `/stream2` |

Example for a CP Plus camera at 192.168.1.64:

```
rtsp://admin:MyPass123@192.168.1.64:554/cam/realmonitor?channel=1&subtype=1
```

On an **NVR**, `channel=1` / `101` means camera 1. Use `channel=2` / `201` for camera 2, and so on.

To let the project try every common path for you:

```bash
python scripts/find_rtsp.py 192.168.1.64 admin MyPass123
```

## 4. Test it in VLC

VLC → *Media → Open Network Stream* → paste the URL → Play. If it plays in VLC, Smart CCTV can read it too.

## 5. Add it to Smart CCTV

1. In `.env` (never commit this file):
   ```
   GATE_RTSP_URL=rtsp://admin:MyPass123@192.168.1.64:554/cam/realmonitor?channel=1&subtype=1
   ```
2. In `backend/config/cameras.yaml`:
   ```yaml
   - id: gate
     name: Main gate
     source: "${GATE_RTSP_URL}"
     enabled: true
     fps: 6
     zones:
       - name: gate_area
         points: [[0.10, 0.50], [0.90, 0.50], [0.90, 0.98], [0.10, 0.98]]
   ```
3. Restart the backend, or click **Reload cameras.yaml** on the Cameras page.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Works in VLC, not in the app | Special characters in the password (`@ # : /`) must be URL-encoded, e.g. `@` → `%40` |
| "401 Unauthorized" | Wrong username/password, or RTSP authentication set to *digest only*; try again in the camera's web page |
| Picture freezes or is grey | The app already uses TCP. Use the sub-stream and lower the camera's bitrate |
| Nothing found by the finder | Computer and camera must be on the same network/VLAN; enable ONVIF in camera settings |
