#!/usr/bin/env python3
"""Find IP cameras on your network and work out their RTSP URL.

    python scripts/find_rtsp.py                       # discover cameras (ONVIF) on your LAN
    python scripts/find_rtsp.py 192.168.1.64 admin MyPassword   # try common RTSP paths on one camera

Step 1 uses ONVIF WS-Discovery (UDP multicast), so it only finds cameras on the same
network as this computer, and only cameras with ONVIF enabled in their settings.
Step 2 tries the RTSP paths used by CP Plus, Hikvision, Dahua, Matrix, TP-Link and
other common brands, and prints the ones that return video.

Needs: opencv-python (already in backend/requirements.txt).
"""
from __future__ import annotations

import re
import socket
import sys
import time
import uuid
from urllib.parse import quote

PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <e:Header>
  <w:MessageID>uuid:{id}</w:MessageID>
  <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
  <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
 </e:Header>
 <e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>"""

# Common RTSP paths. Most CP Plus / Dahua models share the Dahua format; Matrix has its own.
# Prefer the SUB-stream for AI analysis (lower resolution, faster).
RTSP_PATHS = [
    ("CP Plus / Dahua - main", "/cam/realmonitor?channel=1&subtype=0"),
    ("CP Plus / Dahua - sub", "/cam/realmonitor?channel=1&subtype=1"),
    ("Hikvision / Prama - main", "/Streaming/Channels/101"),
    ("Hikvision / Prama - sub", "/Streaming/Channels/102"),
    ("Matrix - main", "/media/video1"),
    ("Matrix - sub", "/media/video2"),
    ("TP-Link VIGI / Tapo - main", "/stream1"),
    ("TP-Link VIGI / Tapo - sub", "/stream2"),
    ("Generic ONVIF profile", "/onvif1"),
    ("Generic H.264", "/h264"),
    ("Generic live", "/live"),
    ("Generic ch0", "/ch0_0.h264"),
    ("Generic 11", "/11"),
    ("Generic 12", "/12"),
    ("Generic root", "/"),
]


def discover(timeout: float = 4.0) -> list[dict]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    sock.sendto(PROBE.format(id=uuid.uuid4()).encode(), ("239.255.255.250", 3702))
    found: dict[str, dict] = {}
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, (ip, _) = sock.recvfrom(65535)
        except socket.timeout:
            continue
        text = data.decode(errors="ignore")
        xaddrs = re.findall(r"<[^>]*XAddrs>([^<]+)<", text)
        scopes = " ".join(re.findall(r"<[^>]*Scopes>([^<]+)<", text))
        name = re.search(r"onvif://www\.onvif\.org/name/([^\s]+)", scopes)
        hw = re.search(r"onvif://www\.onvif\.org/hardware/([^\s]+)", scopes)
        found[ip] = {
            "ip": ip,
            "name": name.group(1) if name else "",
            "hardware": hw.group(1) if hw else "",
            "onvif_service": xaddrs[0].split()[0] if xaddrs else "",
        }
    return list(found.values())


def try_rtsp(ip: str, user: str, password: str, port: int = 554) -> list[tuple[str, str, str]]:
    import os

    import cv2

    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;4000000"
    creds = f"{quote(user, safe='')}:{quote(password, safe='')}@" if user else ""
    working = []
    for label, path in RTSP_PATHS:
        url = f"rtsp://{creds}{ip}:{port}{path}"
        safe = url.replace(f":{quote(password, safe='')}@", ":***@") if password else url
        print(f"  trying {label:<28} {safe} ... ", end="", flush=True)
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        if ok and frame is not None:
            h, w = frame.shape[:2]
            print(f"OK  {w}x{h}")
            working.append((label, safe, f"{w}x{h}"))
        else:
            print("no")
    return working


def main() -> None:
    if len(sys.argv) >= 2:
        ip = sys.argv[1]
        user = sys.argv[2] if len(sys.argv) > 2 else "admin"
        password = sys.argv[3] if len(sys.argv) > 3 else ""
        print(f"Trying common RTSP paths on {ip} (user {user!r})")
        working = try_rtsp(ip, user, password)
        if working:
            print("\nWorking URLs (replace *** with your password, keep it in .env):")
            for label, url, res in working:
                print(f"  {label:<28} {res:<10} {url}")
            print("\nUse the sub-stream for GATE_RTSP_URL in .env. Test it first in VLC: Media > Open Network Stream.")
        else:
            print("\nNo path worked. Check: password, that RTSP is enabled in the camera's web page,"
                  " the RTSP port (often 554), and the brand's manual or the camera's ONVIF page.")
        return

    print("Searching for ONVIF cameras on your network (4 s)...")
    cams = discover()
    if not cams:
        print("No ONVIF cameras answered. Make sure this computer is on the same network as the cameras and that ONVIF is enabled in each camera's settings.")
        print("You can still try one camera directly: python scripts/find_rtsp.py <camera-ip> <user> <password>")
        return
    for c in cams:
        print(f"  {c['ip']:<16} {c['name']} {c['hardware']}  ONVIF: {c['onvif_service']}")
    print("\nNext: python scripts/find_rtsp.py <ip> <user> <password>  to find the RTSP URL")


if __name__ == "__main__":
    main()
