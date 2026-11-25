# Mobile app (Phase 4)

The web dashboard already works on a phone's browser and can be installed to the home screen (it is a PWA: open it in Safari/Chrome → *Share → Add to Home Screen*).

## Plan for the native app

Recommended: **Capacitor**, which wraps the existing React dashboard in a native iOS/Android shell. You get one codebase plus native push notifications. If you later want a fully native UI, use **Flutter** (you already have Flutter installed) talking to the same REST + WebSocket API.

### Capacitor steps

```bash
cd frontend
npm install @capacitor/core @capacitor/cli @capacitor/ios @capacitor/android @capacitor/push-notifications
npx cap init "Smart CCTV" com.yourname.smartcctv --web-dir dist
VITE_API_URL=https://your-server-address npm run build
npx cap add ios && npx cap add android
npx cap open ios        # opens Xcode
```

### Push notifications (backend TODO)

1. Create a Firebase project and add the iOS/Android apps; download the service account JSON.
2. Backend: add `POST /api/devices` to store each phone's FCM token.
3. Implement `send_push()` in `backend/app/alerts/channels.py` with `firebase-admin`.
4. Add `push` to the `channels` of the rules that should notify phones.

### Remote access

The phone must reach the backend when you are away from home. Easiest options are **Tailscale** (free for personal use) or **Cloudflare Tunnel**. Never expose port 8000 directly to the internet without authentication.
