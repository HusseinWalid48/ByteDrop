# ByteDrop v1.0.0

First public release.

## Highlights
- **3 connection modes**: Local Wi-Fi (LAN), Windows Mobile Hotspot, and a public Cloud Link via Cloudflare Quick Tunnels — no account needed on either device.
- **Bidirectional transfers with resume**: chunked phone→PC uploads (HTTP Range resume), drag-and-drop PC→phone with on-the-fly folder zipping.
- **Live clipboard sync** between PC and connected browsers.
- **Device management**: see connected devices, block/kick at any time.
- Session-token auth (128-bit, constant-time compare) + per-IP rate limiting on failed auth.
- Cloudflared binary is SHA-256 verified before execution.

## Install
- **Windows installer**: download `ByteDrop-Setup-1.0.0.exe` below, run it (no admin rights needed unless you opt into the firewall rule).
- **From source**: clone the repo, then double-click `Start.bat` (requires Python 3.10+ and WebView2 Runtime).

## Requirements
- Windows 10/11 (recommended — fully tested)
- Mobile Hotspot mode requires Windows 10/11 specifically; LAN and Cloud Link modes may work on older Windows with Python 3.10+ and WebView2, but are untested

## Known limitations
- Windows only for the packaged installer; source can run cross-platform for the server piece but the desktop window targets Windows.

---
**Checksums** — fill in after building the installer:
```
ByteDrop-Setup-1.0.0.exe   SHA-256: <paste here>
ByteDrop.exe               SHA-256: <paste here>
```
