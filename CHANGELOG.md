# Changelog

## 1.0.0
- Security: Session token moved from query string (`?token=`) to URL fragment (`#token`) so it is never sent to the server in HTTP requests and never recorded in access logs or `Referrer` headers.
- Security: `RateLimiter.locked_until` dict is now pruned of expired entries on every `record_failure` call, preventing unbounded memory growth during long sessions with many unique IPs.
- Security: Added explicit CORS middleware (`CORSMiddleware` with `allow_origins=[]`) in the FastAPI factory so cross-origin browser requests are blocked intentionally rather than relying on framework defaults.
- Hardening: WebSocket `text_sync` handler now explicitly checks `len(content) <= MAX_CLIPBOARD_CHARS` before forwarding to the clipboard manager, adding a defence-in-depth guard alongside the manager's own check.
- UI: Removed `translateY(-2px) scale(1.05)` transform from `.btn-secondary:hover` so Copy/Send buttons no longer jump or shift the surrounding layout when the mouse passes over them.

## 1.0.0
- Removed install-to-home-screen (PWA manifest, service worker, Install button) and the Wake badge from the phone page.
- Screen wake lock kept and fixed: uses the Wake Lock API on HTTPS and a silent-video fallback on plain http (Wi-Fi / Hotspot).
- Security: Only the PC can approve phone-to-PC uploads (`by_pc=True`); phones can only reject staged PC-to-phone offers.
- Security: Removed `kick_device` and `unblock_device` WebSocket handlers so only the desktop app can kick or unblock devices.
- Security: Enforced device ownership (`actor`) on pause, resume, cancel, cancel-all, and share removal across WebSocket and HTTP endpoints.
- Security: Server-side collision check on client-supplied `request_id` generates a fresh `req_<hex>` when an ID is already in use.
- Security: Hardened Cloud Link (`cloudflared` quick tunnel): pinned download to `2026.7.3` with mandatory SHA-256 verification before placement, deleted tampered cached binaries, removed SSH/`localhost.run` fallback, restricted `CF-Connecting-IP` trust to loopback peers only, removed `X-Forwarded-For` trust, tightened `trycloudflare.com` URL matching, and added a desktop UI warning note.
- Security: Made `DesktopApi._ctx` private so `pywebview` does not expose internal application state to JS.
- Security: Added strict `Content-Security-Policy` headers (`sandbox` on inline/stream downloads).
- Hardening: Removed URL percent-decoding from `sanitize_filename`, added periodic pruning of old terminal transfers and stale upload locks, switched single-instance mutex to `Local\ByteDropSingleInstanceMutex`, and made final upload path reservation atomic (`_move_to_unique_path`).

## 1.0.0
- Local Wi-Fi, Windows Mobile Hotspot (detection + QR) and automatic Cloud link (cloudflared quick tunnel).
- Phone to PC and PC to phone transfers with resume, Pause / Resume / Cancel, Cancel all, folder archiving (cancellable).
- Speed and time-left indicator, connection-lost handling, waiting/expiry of unstarted files.
- Live clipboard sync, device list with kick / block / allow, session regeneration.
- Appearance (theme, accent, language) is controlled only from the PC app; the phone page has no settings and follows the app live. English and Arabic (RTL).
- Smooth animated button labels (width change + label swap) for Pause / Resume, Disconnect, Copy and the clipboard toggle.
- Windows integration: tray, notifications, single instance, optional autostart, installer (Inno Setup) and PyInstaller build.
