# Desktop app (later)

The same React dashboard can ship as a desktop app:

- **Tauri** (recommended: small, fast): `npm create tauri-app`, point it at `frontend/dist`, and set `VITE_API_URL` to the backend address.
- **Electron**: simpler JavaScript-only setup, but larger app size.

A desktop build can also bundle and start the Python backend itself, so a customer installs one app that both records and shows alerts. Use PyInstaller to package `backend/` and launch it as a Tauri sidecar.
