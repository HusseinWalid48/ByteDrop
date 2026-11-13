/**
 * ByteDrop v1.0.0 Phone/Web Client (/ui/web/app.js)
 * Features:
 *   - Token-authenticated HTTP/WebSocket session (zero encryption overhead)
 *   - Section 3.1: No "total" text; single item shows name (size) once; multi-item shows count + per-file list
 *   - Section 3.2: EWMA speed & clamped ETA via ByteDropFormat.SpeedEstimator + summarizeActivity
 *   - Section 3.3: Stops reconnecting on kicked / 4001, shows kicked/blocked banner via i18n
 *   - Section 5.4: Single Select Files button, folder drop rejection, PUT /api/upload/{transfer_id} with resume
 */
"use strict";

const MIN_CHUNK_SIZE = 1 * 1024 * 1024;
const MAX_CHUNK_SIZE = 8 * 1024 * 1024;
let currentChunkSize = 2 * 1024 * 1024;

const Fmt = window.ByteDropFormat;
const I18n = window.ByteDropI18n;

const ACCENT_PALETTES = Fmt.ACCENT_PALETTES;
const inferCategory = Fmt.inferCategory;
const formatBytes = Fmt.formatBytes;
const formatSpeed = Fmt.formatSpeed;
const formatEta = Fmt.formatEta;
const formatTransferRowDetail = Fmt.formatTransferRowDetail;
const formatPromptSummary = Fmt.formatPromptSummary;
const summarizeActivity = Fmt.summarizeActivity;
const SpeedEstimator = Fmt.SpeedEstimator;
const t = I18n.t;

const LEGACY_WEB_PREF_KEYS = ["bytedrop_web_prefs", "bytedrop_web_prefs_v2"];

function resolveAuthToken() {
    // Primary: bare fragment  /#<token>  — never sent to server, never logged
    const hashRaw = (window.location.hash || "").replace(/^#/, "").trim();
    if (hashRaw && !hashRaw.includes("=") && !hashRaw.includes("/")) {
        return hashRaw;
    }
    // Legacy key=value fragment  /#?token=…  or  /#token=…
    const tokenMatch = hashRaw.match(/(?:^|[?&])token=([^&#]+)/);
    if (tokenMatch) {
        return decodeURIComponent(tokenMatch[1]);
    }
    // Fallback: query string  /?token=…  (kept for direct manual use)
    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.get("token")) {
        return searchParams.get("token");
    }
    return "";
}

function getOrCreateDeviceId() {
    try {
        let id = localStorage.getItem("bytedrop_device_id");
        if (!id) {
            const rnd = Math.random().toString(16).slice(2, 10) + Date.now().toString(16).slice(-4);
            id = "dev-" + rnd;
            localStorage.setItem("bytedrop_device_id", id);
        }
        return id;
    } catch (err) {
        console.error("localStorage device_id error:", err);
        return "dev-" + Math.random().toString(16).slice(2, 10);
    }
}

function detectFriendlyDeviceName() {
    const ua = navigator.userAgent || "";
    if (/iPhone/i.test(ua)) return "iPhone";
    if (/iPad/i.test(ua)) return "iPad";
    if (/Android/i.test(ua)) {
        const m = ua.match(/Android\s+[\d.]+;\s*([^;)]+)/i);
        return m && m[1] ? m[1].trim().slice(0, 32) : "Android Phone";
    }
    if (/Macintosh/i.test(ua)) return "Mac Browser";
    if (/Windows/i.test(ua)) return "Windows Browser";
    return "Mobile Browser";
}

function detectDefaultBrowserLang() {
    const navLang = (typeof navigator !== "undefined" && navigator.language) ? String(navigator.language) : "en";
    return /^ar\b/i.test(navLang) ? "ar" : "en";
}

function appDefaultPrefs() {
    const base = { theme: "dark", accent: "blue", language: detectDefaultBrowserLang() };
    const a = (window.__BYTEDROP_CONFIG__ || {}).app_appearance;
    if (!a || typeof a !== "object") return base;
    return {
        theme: a.theme === "light" ? "light" : "dark",
        accent: ACCENT_PALETTES[a.accent] ? a.accent : base.accent,
        language: a.language === "ar" ? "ar" : (a.language === "en" ? "en" : base.language)
    };
}

const TOKEN = resolveAuthToken();
const DEVICE_ID = getOrCreateDeviceId();
const DEVICE_NAME = detectFriendlyDeviceName();

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const selectFilesBtn = document.getElementById("select-files-btn");
const toastContainer = document.getElementById("toast-container");
const toastBanner = document.getElementById("toast-banner");
const kickedBanner = document.getElementById("kicked-banner");
const kickedBannerText = document.getElementById("kicked-banner-text");
const reconnectBtn = document.getElementById("reconnect-btn");
const transfersList = document.getElementById("transfers-list");
const sharedList = document.getElementById("shared-list");
const historyList = document.getElementById("history-list");
const statusBadge = document.getElementById("status-badge");
const speedIndicator = document.getElementById("speed-indicator");
const activeCountSub = document.getElementById("active-count-sub");
const cancelAllBtn = document.getElementById("cancel-all-btn");
const confirmCancelAllModal = document.getElementById("confirm-cancel-all-modal");
const dismissCancelAllBtn = document.getElementById("dismiss-cancel-all-btn");
const confirmCancelAllBtn = document.getElementById("confirm-cancel-all-btn");
const cloudSlowBanner = document.getElementById("cloud-slow-banner");
const dismissCloudHintBtn = document.getElementById("dismiss-cloud-hint-btn");
const syncInput = document.getElementById("sync-input");
const copyTextBtn = document.getElementById("copy-text-btn");

const permModal = document.getElementById("perm-modal");
const permText = document.getElementById("perm-text");
const permFileList = document.getElementById("perm-file-list");
const permExpandBtn = document.getElementById("perm-expand-btn");
const permPreviews = document.getElementById("perm-previews");
const acceptModalBtn = document.getElementById("accept-modal-btn");
const rejectModalBtn = document.getElementById("reject-modal-btn");

const streamModal = document.getElementById("stream-modal");
const streamTitle = document.getElementById("stream-title");
const streamContainer = document.getElementById("stream-player-container");
const closeStreamBtn = document.getElementById("close-stream-btn");

let wakeLock = null;
let ws = null;
let wsReconnectAttempts = 0;
let reconnectTimer = null;
let kickedByPc = false;
let blockedByPc = false;
let connectionState = "connecting";
let lastSeq = 0;
let copyBtnCopiedState = false;
let cloudHintDismissed = false;

function defaultViaLabel() {
    const h = (typeof window !== "undefined" && window.location && window.location.hostname) ? String(window.location.hostname) : "";
    if (!h || h === "localhost" || h === "127.0.0.1" || /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.)/.test(h)) {
        return "Wi-Fi";
    }
    return "Cloud";
}

let uploadQueue = [];
let uploadEntriesById = new Map();
let pausedTransfers = new Map();
let cancelledTransferIds = new Set();
let activeXhrMap = new Map();
let isUploading = false;
let activeTransferId = null;

// Track active transfers and preparing rows for single speed indicator & re-i18n
let activeTransferStates = new Map();
let preparingArchiveStates = new Map();
let serverActivitySummary = null;
let lastIndicatorEta = null;

let pendingBatches = {};
let currentSharedFiles = [];
let currentHistoryItems = [];
let removalTimers = {};
let syncDebounceTimer = null;

const initialPrefs = appDefaultPrefs();
let currentTheme = initialPrefs.theme;
let currentAccent = initialPrefs.accent;
let currentLang = initialPrefs.language;

let requestQueue = [];
let isProcessingRequest = false;
let currentIncomingRequest = null;
let promptExpanded = false;

function showToast(message, isError = false, durationMs = 4200) {
    if (toastContainer) {
        while (toastContainer.children.length >= 3) {
            toastContainer.firstElementChild.remove();
        }
        const item = document.createElement("div");
        item.className = "toast-banner" + (isError ? " error" : "");
        item.textContent = message;
        toastContainer.appendChild(item);
        setTimeout(() => {
            if (item.parentNode) item.remove();
        }, durationMs);
        return;
    }
    if (!toastBanner) return;
    toastBanner.textContent = message;
    toastBanner.classList.toggle("error", isError);
    toastBanner.style.display = "block";
    clearTimeout(toastBanner._timer);
    toastBanner._timer = setTimeout(() => {
        toastBanner.style.display = "none";
    }, durationMs);
}

/* ---------------- Connection Status Pure Render Path (F1) ---------------- */
function setConnectionState(newState) {
    connectionState = newState;
    applyConnectionStatusToDom();
}

function applyConnectionStatusToDom() {
    if (!statusBadge) return;
    const rendered = I18n.renderConnectionStatus({ state: connectionState }, currentLang);
    statusBadge.textContent = rendered.text;
    statusBadge.className = rendered.cssClass;
    if (kickedBanner && kickedBannerText) {
        if (connectionState === "kicked" || connectionState === "blocked") {
            kickedBannerText.textContent = rendered.text;
            kickedBanner.classList.add("visible");
        } else {
            kickedBanner.classList.remove("visible");
        }
    }
}

function updateDynamicLabels() {
    applyConnectionStatusToDom();
    if (copyTextBtn) {
        ByteDropFormat.setButtonLabel(copyTextBtn, copyBtnCopiedState ? t("copied_btn") : t("copy_btn"));
    }
    renderSpeedIndicator();
    rerenderAllActiveTransferCards();
    renderSharedFiles(currentSharedFiles);
    if (currentHistoryItems.length > 0 || (historyList && historyList.querySelector(".empty-placeholder"))) {
        renderHistory(currentHistoryItems);
    }
    if (currentIncomingRequest) {
        renderIncomingModalItems();
    }
}

/* ---------------- Speed / Time-Left Indicator Single Source of Truth (F4 & Section 2) ---------------- */
function updateCancelAllButtonVisibility() {
    if (!cancelAllBtn) return;
    let nonTerminalCount = preparingArchiveStates.size;
    for (const tx of activeTransferStates.values()) {
        const st = String(tx.state || "").toLowerCase();
        if (st !== "completed" && st !== "done" && st !== "cancelled" && st !== "declined" && st !== "rejected" && st !== "failed") {
            nonTerminalCount++;
        }
    }
    cancelAllBtn.style.display = nonTerminalCount >= 2 ? "inline-block" : "none";
}

function updateCloudSlowBanner() {
    if (!cloudSlowBanner) return;
    let hasLargeCloudTransfer = false;
    if (!cloudHintDismissed) {
        for (const tx of activeTransferStates.values()) {
            const st = String(tx.state || "").toLowerCase();
            const isNonTerminal = st !== "completed" && st !== "done" && st !== "cancelled" && st !== "declined" && st !== "rejected" && st !== "failed";
            if (isNonTerminal && tx.via === "Cloud" && Number(tx.size || 0) > 100 * 1024 * 1024) {
                hasLargeCloudTransfer = true;
                break;
            }
        }
    }
    cloudSlowBanner.style.display = hasLargeCloudTransfer ? "flex" : "none";
    cloudSlowBanner.classList.toggle("hidden", !hasLargeCloudTransfer);
}
window.updateCloudSlowBanner = updateCloudSlowBanner;

function computeEffectiveActivitySummary() {
    const items = [];
    for (const prep of preparingArchiveStates.values()) {
        items.push({
            state: "preparing",
            preparing: true,
            size: 0,
            offset: 0,
            speed_bps: 0
        });
    }
    for (const tx of activeTransferStates.values()) {
        const st = String(tx.state || "").toLowerCase();
        if (st === "completed" || st === "done" || st === "cancelled" || st === "declined" || st === "rejected" || st === "failed") {
            continue;
        }
        items.push(tx);
    }
    // Include queued uploads of the same batch that haven't started yet
    for (const q of uploadQueue) {
        if (q.transferId && !activeTransferStates.has(q.transferId)) {
            items.push({
                id: q.transferId,
                state: "queued",
                size: Number(q.file ? q.file.size : 0),
                offset: Number(q.lastOffset || 0),
                speed_bps: 0
            });
        }
    }

    if (items.length === 0) {
        serverActivitySummary = null;
        lastIndicatorEta = null;
        return { state: "idle", speed_bps: 0, eta_seconds: null, active_count: 0 };
    }

    const localSummary = summarizeActivity(items, Date.now() / 1000, lastIndicatorEta);
    if (localSummary.state !== "idle") {
        lastIndicatorEta = localSummary.eta_seconds;
        return localSummary;
    }
    if (serverActivitySummary && serverActivitySummary.state && serverActivitySummary.state !== "idle") {
        lastIndicatorEta = serverActivitySummary.eta_seconds;
        return serverActivitySummary;
    }
    lastIndicatorEta = null;
    return localSummary;
}

function renderSpeedIndicator(explicitSummary) {
    updateCancelAllButtonVisibility();
    updateCloudSlowBanner();
    if (!speedIndicator) return;
    if (explicitSummary && typeof explicitSummary === "object") {
        serverActivitySummary = explicitSummary;
    }
    const summary = computeEffectiveActivitySummary();
    const state = summary.state || "idle";
    const speedBps = Number(summary.speed_bps || 0);
    const etaSeconds = summary.eta_seconds;
    const activeCount = Number(summary.active_count || 0);

    speedIndicator.classList.remove("idle", "paused", "preparing", "stalled", "waiting");

    if (state === "preparing") {
        speedIndicator.classList.add("preparing");
        speedIndicator.innerHTML = `<bdi dir="auto">${t("status_preparing")}</bdi>`;
    } else if (state === "waiting") {
        speedIndicator.classList.add("waiting");
        speedIndicator.innerHTML = `<bdi dir="auto">${t("status_waiting")}</bdi>`;
    } else if (state === "paused") {
        speedIndicator.classList.add("paused");
        speedIndicator.innerHTML = `<bdi dir="auto">${t("status_paused")}</bdi>`;
    } else if (state === "stalled") {
        speedIndicator.classList.add("stalled");
        speedIndicator.innerHTML = `<bdi dir="auto">${t("status_stalled")}</bdi>`;
    } else if (state === "active") {
        const speedStr = formatSpeed(speedBps);
        const etaStr = (etaSeconds === null || etaSeconds === undefined || !isFinite(etaSeconds))
            ? t("status_calculating")
            : formatEta(etaSeconds, t);
        speedIndicator.innerHTML = `<bdi dir="ltr">${speedStr}</bdi> • <bdi dir="ltr">${etaStr}</bdi>`;
    } else {
        speedIndicator.classList.add("idle");
        speedIndicator.innerHTML = `<bdi dir="auto">${t("status_idle")}</bdi>`;
    }

    if (activeCountSub) {
        if (activeCount > 0 && state !== "idle") {
            activeCountSub.textContent = t("active_count_label", { count: activeCount });
            activeCountSub.style.display = "inline-block";
        } else {
            activeCountSub.textContent = "";
            activeCountSub.style.display = "none";
        }
    }
}

/* ---------------- Appearance: the phone page has no settings, it follows the PC app ---------------- */
function applyTheme(theme) {
    const isLight = theme === "light";
    currentTheme = isLight ? "light" : "dark";
    document.body.classList.toggle("light-mode", isLight);
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    if (themeMeta) themeMeta.setAttribute("content", isLight ? "#eff6ff" : "#0b1120");
}

function applyAccent(accentName) {
    const validName = ACCENT_PALETTES[accentName] ? accentName : "blue";
    currentAccent = validName;
    const p = ACCENT_PALETTES[validName];
    const root = document.documentElement;
    root.style.setProperty("--accent-from", p.from);
    root.style.setProperty("--accent-to", p.to);
    root.style.setProperty("--accent-light", p.light);
    root.style.setProperty("--accent-rgb", p.rgb);
    root.style.setProperty("--accent-dark-rgb", p.darkRgb);
}

function applyLanguage(lang) {
    currentLang = I18n.setLanguage(lang);
    updateDynamicLabels();
}

/* Applies the app's look (from the boot config, the snapshot, or an `appearance_updated` event). */
function applyAppearance(appearance) {
    if (!appearance || typeof appearance !== "object") return;
    if ((appearance.theme === "light" || appearance.theme === "dark") && appearance.theme !== currentTheme) {
        applyTheme(appearance.theme);
    }
    if (ACCENT_PALETTES[appearance.accent] && appearance.accent !== currentAccent) {
        applyAccent(appearance.accent);
    }
    if ((appearance.language === "ar" || appearance.language === "en") && appearance.language !== currentLang) {
        applyLanguage(appearance.language);
    }
}

function initAppearance() {
    try {
        LEGACY_WEB_PREF_KEYS.forEach((key) => localStorage.removeItem(key));
    } catch (err) {
        console.error("localStorage legacy cleanup error:", err);
    }
    const a = appDefaultPrefs();
    applyTheme(a.theme);
    applyAccent(a.accent);
    applyLanguage(a.language);
}

function adjustDynamicChunkSize(bytesSent, elapsedSeconds) {
    if (elapsedSeconds <= 0) return;
    const bytesPerSec = bytesSent / elapsedSeconds;
    if (bytesPerSec > 12 * 1024 * 1024) {
        currentChunkSize = MAX_CHUNK_SIZE;
    } else if (bytesPerSec > 5 * 1024 * 1024) {
        currentChunkSize = 4 * 1024 * 1024;
    } else if (bytesPerSec > 2 * 1024 * 1024) {
        currentChunkSize = 2 * 1024 * 1024;
    } else {
        currentChunkSize = MIN_CHUNK_SIZE;
    }
}

const NOSLEEP_MP4 = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAANMbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAB9AAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAnZ0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAB9AAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAEAAAABAAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAfQAAAAAAABAAAAAAHubWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAoAAAAUABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABmW1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAVlzdGJsAAAAuXN0c2QAAAAAAAAAAQAAAKlhdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAEAAQABIAAAASAAAAAAAAAABFUxhdmM2MC4zMS4xMDIgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAAL2F2Y0MBQsAK/+EAF2dCwArZBCbARAAAAwAEAAADACg8SJkgAQAFaMuDyyAAAAAQcGFzcAAAAAEAAAABAAAAFGJ0cnQAAAAAAAALqAAAC6gAAAAYc3R0cwAAAAAAAAABAAAACgAACAAAAAAUc3RzcwAAAAAAAAABAAAAAQAAABxzdHNjAAAAAAAAAAEAAAABAAAACgAAAAEAAAA8c3RzegAAAAAAAAAAAAAACgAAAo8AAAAKAAAACwAAAAoAAAAKAAAACgAAAAoAAAAKAAAACgAAAAoAAAAUc3RjbwAAAAAAAAABAAADfAAAAGJ1ZHRhAAAAWm1ldGEAAAAAAAAAIWhkbHIAAAAAAAAAAG1kaXJhcHBsAAAAAAAAAAAAAAAALWlsc3QAAAAlqXRvbwAAAB1kYXRhAAAAAQAAAABMYXZmNjAuMTYuMTAwAAAACGZyZWUAAALybWRhdAAAAnAGBf//bNxF6b3m2Ui3lizYINkj7u94MjY0IC0gY29yZSAxNjQgcjMxMDggMzFlMTlmOSAtIEguMjY0L01QRUctNCBBVkMgY29kZWMgLSBDb3B5bGVmdCAyMDAzLTIwMjMgLSBodHRwOi8vd3d3LnZpZGVvbGFuLm9yZy94MjY0Lmh0bWwgLSBvcHRpb25zOiBjYWJhYz0wIHJlZj0zIGRlYmxvY2s9MTowOjAgYW5hbHlzZT0weDE6MHgxMTEgbWU9aGV4IHN1Ym1lPTcgcHN5PTEgcHN5X3JkPTEuMDA6MC4wMCBtaXhlZF9yZWY9MSBtZV9yYW5nZT0xNiBjaHJvbWFfbWU9MSB0cmVsbGlzPTEgOHg4ZGN0PTAgY3FtPTAgZGVhZHpvbmU9MjEsMTEgZmFzdF9wc2tpcD0xIGNocm9tYV9xcF9vZmZzZXQ9LTIgdGhyZWFkcz0xIGxvb2thaGVhZF90aHJlYWRzPTEgc2xpY2VkX3RocmVhZHM9MCBucj0wIGRlY2ltYXRlPTEgaW50ZXJsYWNlZD0wIGJsdXJheV9jb21wYXQ9MCBjb25zdHJhaW5lZF9pbnRyYT0wIGJmcmFtZXM9MCB3ZWlnaHRwPTAga2V5aW50PTI1MCBrZXlpbnRfbWluPTUgc2NlbmVjdXQ9NDAgaW50cmFfcmVmcmVzaD0wIHJjX2xvb2thaGVhZD00MCByYz1jcmYgbWJ0cmVlPTEgY3JmPTIzLjAgcWNvbXA9MC42MCBxcG1pbj0wIHFwbWF4PTY5IHFwc3RlcD00IGlwX3JhdGlvPTEuNDAgYXE9MToxLjAwAIAAAAAXZYiEBHyYoAA2IycnJ1111111111114AAAAAGQZo4CPhGAAAAB0GaVAI+EYAAAAAGQZpgEfCMAAAABkGagBHwjAAAAAZBmqAR8IwAAAAGQZrAEfCMAAAABkGa4BHwjAAAAAZBmwAQ8IwAAAAGQZsgP8Iw";
const NOSLEEP_WEBM = "data:video/webm;base64,GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQJChYECGFOAZwEAAAAAAALCEU2bdLpNu4tTq4QVSalmU6yBoU27i1OrhBZUrmtTrIHYTbuMU6uEElTDZ1OsggEeTbuMU6uEHFO7a1OsggKs7AEAAAAAAABZAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAVSalmsirXsYMPQkBNgI1MYXZmNjAuMTYuMTAwV0GNTGF2ZjYwLjE2LjEwMESJiECfQAAAAAAAFlSua8GuAQAAAAAAADjXgQFzxYhZybNwR+TngZyBACK1nIN1bmSIgQCGhVZfVlA4g4EBI+ODhAvrwgDgibCBQLqBQJqBAhJUw2f8c3OgY8CAZ8iaRaOHRU5DT0RFUkSHjUxhdmY2MC4xNi4xMDBzc9ZjwItjxYhZybNwR+TngWfIoUWjh0VOQ09ERVJEh5RMYXZjNjAuMzEuMTAyIGxpYnZweGfIoUWjiERVUkFUSU9ORIeTMDA6MDA6MDIuMDAwMDAwMDAwAB9DtnVBB+eBAKOqgQAAgPACAJ0BKkAAQAAARwiFhYiFhIgCAgAGcDxCYAqyIPcwAP7/q1CAo5aBAMgA0QEAARAQABgAGFgv9AAIjoAAo5aBAZAA0QEAARAQABgAGFgv9AAIjoAAo5aBAlgA0QEAARAQABgAGFgv9AAIjoAAo5aBAyAA0QEAARAQABgAGFgv9AAIjoAAo5aBA+gA0QEAARAQABgAGFgv9AAIjoAAo5aBBLAA0QEAARAQABgAGFgv9AAIjoAAo5aBBXgA0QEAARAQFGAAYWC/0AAiOgAAo5aBBkAA0QEAARAQABgAGFgv9AAIjoAAo5aBBwgA0QEAARAQABgAGFgv9AAIjoAAHFO7a5G7j7OBALeK94EB8YIBn/CBAw==";
let noSleepVideo = null;

function isWakeActive() {
    return wakeLock !== null || (noSleepVideo !== null && !noSleepVideo.paused);
}

function startNoSleepVideo() {
    // Fallback for plain http (Wi-Fi / Hotspot) where the Screen Wake Lock API is unavailable:
    // a tiny silent looping video keeps the screen on. Needs a user gesture on most phones.
    try {
        if (!noSleepVideo) {
            const v = document.createElement("video");
            v.setAttribute("playsinline", "");
            v.setAttribute("muted", "");
            v.setAttribute("aria-hidden", "true");
            v.muted = true;
            v.loop = true;
            v.disablePictureInPicture = true;
            v.style.cssText = "position:fixed;width:1px;height:1px;opacity:0.01;pointer-events:none;bottom:0;left:0;";
            const mp4 = document.createElement("source");
            mp4.src = NOSLEEP_MP4;
            mp4.type = "video/mp4";
            const webm = document.createElement("source");
            webm.src = NOSLEEP_WEBM;
            webm.type = "video/webm";
            v.appendChild(mp4);
            v.appendChild(webm);
            document.body.appendChild(v);
            noSleepVideo = v;
        }
        if (noSleepVideo.paused) {
            const p = noSleepVideo.play();
            if (p && typeof p.catch === "function") p.catch(() => {});
        }
    } catch (err) {
        // ignore: best effort only
    }
}

async function requestWakeLock() {
    if (document.visibilityState !== "visible" || isWakeActive()) return;
    if (window.isSecureContext && "wakeLock" in navigator) {
        try {
            const lock = await navigator.wakeLock.request("screen");
            wakeLock = lock;
            lock.addEventListener("release", () => {
                if (wakeLock === lock) wakeLock = null;
                if (document.visibilityState === "visible") requestWakeLock();
            });
            return;
        } catch (err) {
            wakeLock = null;
        }
    }
    startNoSleepVideo();
}

document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
        requestWakeLock();
        if (uploadQueue.length > 0 && !isUploading && !kickedByPc) {
            processQueue();
        }
    }
});

["pointerdown", "touchend", "click"].forEach((evt) => {
    document.addEventListener(evt, () => {
        if (!isWakeActive()) requestWakeLock();
    }, { passive: true });
});

window.addEventListener("pageshow", () => { requestWakeLock(); });
requestWakeLock();

// Remove any service worker left over from earlier versions (install-to-home-screen was removed).
if ("serviceWorker" in navigator) {
    navigator.serviceWorker.getRegistrations()
        .then((regs) => regs.forEach((r) => r.unregister()))
        .catch(() => {});
}

function getSafeId(idStr) {
    return "item-" + Array.from(new TextEncoder().encode(String(idStr)))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");
}

function checkEmptyTransfersList() {
    if (!transfersList) return;
    const cards = transfersList.querySelectorAll(".item-card");
    if (cards.length === 0 && !transfersList.querySelector(".empty-placeholder")) {
        transfersList.innerHTML = `<div class="empty-placeholder" data-i18n="transfers_idle">${t("transfers_idle")}</div>`;
    }
}

function scheduleCardRemoval(cardKey, delayMs = 3800) {
    const id = getSafeId(cardKey);
    if (removalTimers[id]) {
        clearTimeout(removalTimers[id]);
    }
    removalTimers[id] = setTimeout(() => {
        const card = document.getElementById(id);
        if (card) {
            card.classList.add("row-exiting");
            setTimeout(() => {
                if (card.parentNode) card.remove();
                activeTransferStates.delete(cardKey);
                preparingArchiveStates.delete(cardKey);
                checkEmptyTransfersList();
                renderSpeedIndicator();
            }, 220);
        } else {
            activeTransferStates.delete(cardKey);
            preparingArchiveStates.delete(cardKey);
            checkEmptyTransfersList();
            renderSpeedIndicator();
        }
        delete removalTimers[id];
    }, delayMs);
}

/* ---------------- Preparing Archive Row (F2 & Section 3) ---------------- */
function updatePreparingArchiveCard(prepId, filename, progressPct, requestId = null) {
    if (!transfersList) return;
    const placeholder = transfersList.querySelector(".empty-placeholder");
    if (placeholder) placeholder.remove();

    const cardKey = `prep-${prepId}`;
    const safeId = getSafeId(cardKey);
    const pct = Math.max(0, Math.min(100, Math.floor(Number(progressPct) || 0)));

    preparingArchiveStates.set(cardKey, {
        id: prepId,
        request_id: requestId || prepId,
        name: filename || "Archive",
        progress: pct
    });

    let card = document.getElementById(safeId);
    if (!card) {
        card = document.createElement("div");
        card.className = "item-card";
        card.id = safeId;
        card.dataset.prepId = String(prepId);
        card.innerHTML = `
            <div class="item-top">
                <div class="item-header">
                    <div class="item-title-group">
                        <span class="cat-tag">ZIP</span>
                        <span class="item-name"><bdi dir="auto"></bdi></span>
                    </div>
                </div>
            </div>
            <div class="item-meta" dir="ltr"></div>
            <div class="progress-track">
                <div class="progress-fill"></div>
            </div>
            <div class="item-controls">
                <button type="button" class="ctrl-btn danger cancel-prep-btn"></button>
            </div>
        `;
        transfersList.prepend(card);
    }

    const nameEl = card.querySelector(".item-name bdi");
    const metaEl = card.querySelector(".item-meta");
    const fillEl = card.querySelector(".progress-fill");
    const cancelBtn = card.querySelector(".cancel-prep-btn");

    const titleText = t("preparing_archive_named", { name: filename || "Archive" });
    if (nameEl) {
        nameEl.textContent = titleText;
        card.querySelector(".item-name").title = titleText;
    }
    if (metaEl) metaEl.textContent = `${t("status_preparing")} • ${pct}%`;
    if (fillEl) fillEl.style.width = `${pct}%`;
    if (cancelBtn) {
        cancelBtn.textContent = t("cancel_btn");
        cancelBtn.onclick = () => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: "cancel",
                    id: prepId,
                    share_id: prepId,
                    request_id: requestId || prepId
                }));
            }
            removePreparingArchiveCard(prepId);
        };
    }

    if (pct >= 100) {
        scheduleCardRemoval(cardKey, 1200);
    }
    renderSpeedIndicator();
}

function removePreparingArchiveCard(prepId) {
    if (!prepId) return;
    const keysToRemove = [`prep-${prepId}`];
    for (const [k, v] of preparingArchiveStates.entries()) {
        if (v && (v.id === prepId || v.request_id === prepId)) {
            if (!keysToRemove.includes(k)) keysToRemove.push(k);
        }
    }
    keysToRemove.forEach((cardKey) => {
        preparingArchiveStates.delete(cardKey);
        const safeId = getSafeId(cardKey);
        if (removalTimers[safeId]) {
            clearTimeout(removalTimers[safeId]);
            delete removalTimers[safeId];
        }
        const card = document.getElementById(safeId);
        if (card) card.remove();
    });
    checkEmptyTransfersList();
    renderSpeedIndicator();
}

/* ---------------- Per-File Transfer Card (F2, F5, G2, G3, G4, G7) ---------------- */
function ensureTransferCard(cardKey, displayName, totalSize, initialDetailText = "0%", thumbnail = null, category = null, queueEntry = null, batchIndex = 0, batchSize = 0, viaLabel = null, isWaiting = false) {
    if (!transfersList) return null;
    const placeholder = transfersList.querySelector(".empty-placeholder");
    if (placeholder) placeholder.remove();

    const id = getSafeId(cardKey);
    if (removalTimers[id]) {
        clearTimeout(removalTimers[id]);
        delete removalTimers[id];
    }

    let card = document.getElementById(id);
    if (!card) {
        card = document.createElement("div");
        card.className = "item-card" + (isWaiting ? " waiting-row" : "");
        card.id = id;
        card.dataset.cardKey = String(cardKey);
        card.innerHTML = `
            <div class="item-top">
                <img class="thumb-img" alt="">
                <div class="item-header">
                    <div class="item-title-group">
                        <span class="cat-tag" style="display:none"></span>
                        <span class="via-tag" style="display:none"></span>
                        <span class="item-name"><bdi dir="auto"></bdi></span>
                    </div>
                    <span class="pos-tag" dir="ltr" style="display:none"></span>
                </div>
            </div>
            <div class="item-meta" dir="ltr"></div>
            <div class="progress-track">
                <div class="progress-fill"></div>
            </div>
            <div class="item-controls" style="display:none;">
                <button type="button" class="ctrl-btn pause-resume-btn"></button>
                <button type="button" class="ctrl-btn danger cancel-upl-btn"></button>
            </div>
        `;
        const nameBdi = card.querySelector(".item-name bdi");
        if (nameBdi) nameBdi.textContent = displayName;
        const nameSpan = card.querySelector(".item-name");
        if (nameSpan) nameSpan.title = displayName;
        const metaEl = card.querySelector(".item-meta");
        if (metaEl) metaEl.textContent = initialDetailText;
        if (isWaiting) {
            transfersList.appendChild(card);
        } else {
            const firstWaiting = transfersList.querySelector(".waiting-row");
            if (firstWaiting) {
                transfersList.insertBefore(card, firstWaiting);
            } else {
                transfersList.prepend(card);
            }
        }
    } else {
        card.classList.remove("row-exiting");
        const wasWaiting = card.classList.contains("waiting-row");
        card.classList.toggle("waiting-row", isWaiting);
        if (wasWaiting && !isWaiting) {
            const firstWaiting = transfersList.querySelector(".waiting-row");
            if (firstWaiting && firstWaiting !== card) {
                transfersList.insertBefore(card, firstWaiting);
            }
        }
        const nameBdi = card.querySelector(".item-name bdi");
        if (nameBdi && displayName) nameBdi.textContent = displayName;
        const nameSpan = card.querySelector(".item-name");
        if (nameSpan && displayName) nameSpan.title = displayName;
    }

    const viaTag = card.querySelector(".via-tag");
    const effectiveVia = viaLabel || defaultViaLabel();
    if (viaTag) {
        viaTag.textContent = t(effectiveVia === "Cloud" ? "via_cloud" : "via_wifi");
        viaTag.style.display = "inline-block";
    }

    const posTag = card.querySelector(".pos-tag");
    const effectiveBatchIndex = batchIndex || (queueEntry ? queueEntry.fileIndex + 1 : 0);
    const effectiveBatchSize = batchSize || (queueEntry ? queueEntry.batchSize : 0);
    if (posTag) {
        if (effectiveBatchSize > 1 && effectiveBatchIndex > 0) {
            posTag.textContent = t("batch_pos_tag", { index: effectiveBatchIndex, total: effectiveBatchSize });
            posTag.style.display = "inline-block";
        } else {
            posTag.style.display = "none";
        }
    }

    const effectiveEntry = queueEntry || uploadEntriesById.get(cardKey) || pausedTransfers.get(cardKey) || null;
    const isServerTransfer = Boolean(
        effectiveEntry ||
        (cardKey && !String(cardKey).startsWith("pending-"))
    );

    if (isServerTransfer) {
        const transferId = effectiveEntry ? effectiveEntry.transferId : String(cardKey);
        const ctrls = card.querySelector(".item-controls");
        const prBtn = card.querySelector(".pause-resume-btn");
        const cancelBtn = card.querySelector(".cancel-upl-btn");
        if (ctrls && prBtn && cancelBtn) {
            ctrls.style.display = "flex";
            const existingState = activeTransferStates.get(cardKey);
            const isPaused = pausedTransfers.has(transferId) || (existingState && existingState.state === "Paused");
            const isDownload = !effectiveEntry && (!existingState || existingState.direction === "pc_to_phone" || existingState.state === "Downloading" || existingState.state === "Interrupted" || existingState.state === "Waiting");
            const tooltipText = isDownload ? t("browser_download_tooltip") : "";
            ByteDropFormat.setButtonLabel(prBtn, isPaused ? t("resume_btn") : t("pause_btn"));
            prBtn.title = tooltipText;
            cancelBtn.textContent = t("cancel_btn");
            cancelBtn.title = tooltipText;

            prBtn.onclick = async () => {
                if (effectiveEntry) {
                    if (pausedTransfers.has(transferId)) {
                        const entry = pausedTransfers.get(transferId);
                        pausedTransfers.delete(transferId);
                        if (entry.estimator) entry.estimator.resume();
                        ByteDropFormat.setButtonLabel(prBtn, t("pause_btn"));
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({ type: "transfer_resume", transfer_id: transferId }));
                        }
                        if (!uploadQueue.some((q) => q.transferId === transferId)) {
                            uploadQueue.unshift(entry);
                        }
                        processQueue();
                        renderSpeedIndicator();
                    } else {
                        pausedTransfers.set(transferId, effectiveEntry);
                        if (effectiveEntry.estimator) effectiveEntry.estimator.pause();
                        uploadQueue = uploadQueue.filter((q) => q.transferId !== transferId);
                        const activeXhr = activeXhrMap.get(transferId);
                        if (activeXhr) activeXhr.abort();
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({ type: "transfer_pause", transfer_id: transferId }));
                        }
                        ByteDropFormat.setButtonLabel(prBtn, t("resume_btn"));
                        renderTransferCardState(cardKey, {
                            id: transferId,
                            name: displayName,
                            size: totalSize,
                            offset: effectiveEntry.lastOffset || 0,
                            state: "Paused",
                            category: category,
                            via: effectiveVia,
                            batch_index: effectiveBatchIndex,
                            batch_size: effectiveBatchSize
                        });
                    }
                } else {
                    const currRecord = activeTransferStates.get(cardKey);
                    const currentlyPaused = currRecord && currRecord.state === "Paused";
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({
                            type: currentlyPaused ? "transfer_resume" : "transfer_pause",
                            transfer_id: transferId
                        }));
                    }
                }
            };

            cancelBtn.onclick = async () => {
                if (effectiveEntry) {
                    cancelledTransferIds.add(transferId);
                    pausedTransfers.delete(transferId);
                    uploadEntriesById.delete(transferId);
                    uploadQueue = uploadQueue.filter((q) => q.transferId !== transferId);
                    const activeXhr = activeXhrMap.get(transferId);
                    if (activeXhr) activeXhr.abort();
                    try {
                        await fetch(`/api/upload/${encodeURIComponent(transferId)}?token=${encodeURIComponent(TOKEN)}&device_id=${encodeURIComponent(DEVICE_ID)}`, {
                            method: "DELETE"
                        });
                    } catch (err) {
                        console.error("Cancel upload DELETE failed:", err);
                    }
                    if (!isUploading && uploadQueue.length > 0) {
                        processQueue();
                    }
                } else if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: "transfer_cancel", transfer_id: transferId }));
                }
                ctrls.style.display = "none";
                setTransferStatusText(cardKey, displayName, t("status_cancelled"), true);
            };
        }
    }

    if (thumbnail && typeof thumbnail === "string" && thumbnail.startsWith("data:image/")) {
        const img = card.querySelector(".thumb-img");
        if (img) {
            img.src = thumbnail;
            img.classList.add("visible");
        }
    }
    if (category) {
        const tag = card.querySelector(".cat-tag");
        if (tag) {
            tag.textContent = category;
            tag.style.display = "inline-block";
        }
    }
    return card;
}

function setTransferStatusText(cardKey, displayName, statusText, isFinalState = false) {
    const card = ensureTransferCard(cardKey, displayName, 0, statusText);
    if (!card) return;
    card.classList.remove("waiting-row");
    // F5: Do not repeat displayName in the detail line
    const meta = card.querySelector(".item-meta");
    if (meta) meta.textContent = statusText;
    if (isFinalState) {
        activeTransferStates.delete(cardKey);
        const ctrls = card.querySelector(".item-controls");
        if (ctrls) ctrls.style.display = "none";
        scheduleCardRemoval(cardKey, 3000);
    }
    renderSpeedIndicator();
}

function renderTransferCardState(cardKey, txObj) {
    const name = txObj.name || txObj.filename || "file";
    const size = Number(txObj.size ?? txObj.total ?? 0);
    const offset = Number(txObj.offset ?? txObj.received ?? 0);
    const stateStr = txObj.state || ((size > 0 && offset >= size) ? "Completed" : "Uploading");
    const isDone = stateStr === "Completed" || stateStr === "done" || (size > 0 && offset >= size);
    const pct = size > 0 ? Math.min(100, Math.floor((offset / size) * 100)) : (isDone ? 100 : 0);
    const viaVal = txObj.via || defaultViaLabel();

    const record = {
        id: txObj.id || cardKey,
        cardKey: cardKey,
        name: name,
        size: size,
        offset: offset,
        bytes_done: offset,
        state: isDone ? "Completed" : stateStr,
        direction: txObj.direction || "",
        via: viaVal,
        speed_bps: Number(txObj.speed_bps || 0),
        avg_speed_bps: Number(txObj.avg_speed_bps || 0),
        eta_seconds: txObj.eta_seconds,
        duration_sec: txObj.duration_sec,
        stalled: Boolean(txObj.stalled) && offset > 0,
        waiting_for_phone: Boolean(txObj.waiting_for_phone) && offset > 0,
        connection_lost: Boolean(txObj.connection_lost) && offset > 0,
        offline_will_resume: Boolean(txObj.offline_will_resume),
        thumbnail: txObj.thumbnail || null,
        category: txObj.category || null,
        batch_index: Number(txObj.batch_index || 0),
        batch_size: Number(txObj.batch_size || 0),
        started_at: txObj.started_at || (Date.now() / 1000)
    };
    activeTransferStates.set(cardKey, record);
    updateCloudSlowBanner();

    const isWaitingCard = record.state === "Waiting";
    const card = ensureTransferCard(
        cardKey,
        name,
        size,
        "0%",
        record.thumbnail,
        record.category,
        null,
        record.batch_index,
        record.batch_size,
        record.via,
        isWaitingCard
    );
    if (!card) return;
    const meta = card.querySelector(".item-meta");
    const fill = card.querySelector(".progress-fill");

    // F5, Section 2.3 & G4: Detail line shows size/pct/state (with phone-specific Interrupted copy)
    const detailText = formatTransferRowDetail(record, t, { isPhone: true });

    if (meta) meta.textContent = detailText;
    if (fill) fill.style.width = `${pct}%`;

    if (isDone) {
        uploadEntriesById.delete(cardKey);
        pausedTransfers.delete(cardKey);
        const ctrls = card.querySelector(".item-controls");
        if (ctrls) ctrls.style.display = "none";
        scheduleCardRemoval(cardKey, 3200);
    } else {
        const prBtn = card.querySelector(".pause-resume-btn");
        const cancelBtn = card.querySelector(".cancel-upl-btn");
        const isWaitingOrInterrupted = record.state === "Waiting" || record.state === "Interrupted";
        if (prBtn) {
            if (isWaitingOrInterrupted) {
                prBtn.style.display = "none";
            } else {
                prBtn.style.display = "inline-block";
                const isPausedState = record.state === "Paused" || pausedTransfers.has(cardKey);
                ByteDropFormat.setButtonLabel(prBtn, isPausedState ? t("resume_btn") : t("pause_btn"));
            }
        }
        if (cancelBtn) {
            cancelBtn.style.display = "inline-block";
            cancelBtn.textContent = t("cancel_btn");
        }
    }
    renderSpeedIndicator();
}

function rerenderAllActiveTransferCards() {
    for (const [cardKey, record] of activeTransferStates.entries()) {
        renderTransferCardState(cardKey, record);
    }
    for (const [, prep] of preparingArchiveStates.entries()) {
        updatePreparingArchiveCard(prep.id, prep.name, prep.progress);
    }
    checkEmptyTransfersList();
}

/* ---------------- G3: Cancel All Active & Waiting Transfers ---------------- */
async function cancelAllTransfers(skipConfirm = false) {
    if (!skipConfirm && confirmCancelAllModal) {
        confirmCancelAllModal.classList.add("active");
        return;
    }
    if (confirmCancelAllModal) {
        confirmCancelAllModal.classList.remove("active");
    }

    for (const [tid, xhr] of activeXhrMap.entries()) {
        cancelledTransferIds.add(tid);
        try {
            xhr.abort();
        } catch (err) {
            console.error("XHR abort error:", err);
        }
    }
    activeXhrMap.clear();
    uploadQueue.forEach((q) => {
        if (q.transferId) cancelledTransferIds.add(q.transferId);
    });
    uploadQueue = [];
    pausedTransfers.clear();
    uploadEntriesById.clear();

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "cancel_all", device_id: DEVICE_ID }));
    } else {
        try {
            await fetch(`/api/transfers/cancel_all?token=${encodeURIComponent(TOKEN)}&device_id=${encodeURIComponent(DEVICE_ID)}`, {
                method: "POST"
            });
        } catch (err) {
            console.error("cancel_all HTTP error:", err);
        }
    }

    const keys = Array.from(activeTransferStates.keys());
    keys.forEach((cardKey) => {
        const rec = activeTransferStates.get(cardKey);
        setTransferStatusText(cardKey, (rec && rec.name) || "file", t("status_cancelled"), true);
    });
    const prepIds = Array.from(preparingArchiveStates.values()).map((p) => p.id);
    prepIds.forEach((pid) => removePreparingArchiveCard(pid));
    serverActivitySummary = null;
    renderSpeedIndicator();
}
window.cancelAllTransfers = cancelAllTransfers;

if (cancelAllBtn) {
    cancelAllBtn.onclick = () => cancelAllTransfers(false);
}
if (dismissCancelAllBtn && confirmCancelAllModal) {
    dismissCancelAllBtn.onclick = () => confirmCancelAllModal.classList.remove("active");
}
if (confirmCancelAllBtn) {
    confirmCancelAllBtn.onclick = () => cancelAllTransfers(true);
}
if (dismissCloudHintBtn && cloudSlowBanner) {
    dismissCloudHintBtn.onclick = () => {
        cloudHintDismissed = true;
        updateCloudSlowBanner();
    };
}

/* ---------------- Native Downloads & HTTP 206 Media Streaming ---------------- */
function triggerNativeDownload(file) {
    const url = `/api/download/${encodeURIComponent(file.id)}?token=${encodeURIComponent(TOKEN)}&device_id=${encodeURIComponent(DEVICE_ID)}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = file.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function openMediaStreamModal(file) {
    if (!streamModal || !streamContainer) return;
    streamContainer.innerHTML = "";
    if (streamTitle) streamTitle.textContent = file.name;
    const streamUrl = `/api/download/${encodeURIComponent(file.id)}?token=${encodeURIComponent(TOKEN)}&inline=1&device_id=${encodeURIComponent(DEVICE_ID)}`;
    const isVideo = file.category === "Videos";
    const mediaEl = document.createElement(isVideo ? "video" : "audio");
    mediaEl.controls = true;
    mediaEl.autoplay = true;
    mediaEl.playsInline = true;
    mediaEl.src = streamUrl;
    streamContainer.appendChild(mediaEl);
    streamModal.classList.add("active");
}

if (closeStreamBtn && streamModal) {
    closeStreamBtn.onclick = () => {
        streamModal.classList.remove("active");
        if (streamContainer) streamContainer.innerHTML = "";
    };
    streamModal.addEventListener("click", (e) => {
        if (e.target === streamModal) {
            streamModal.classList.remove("active");
            if (streamContainer) streamContainer.innerHTML = "";
        }
    });
}

async function fetchSharedFiles() {
    try {
        const res = await fetch(`/api/shared?token=${encodeURIComponent(TOKEN)}`);
        if (!res.ok) return;
        const data = await res.json();
        currentSharedFiles = data.files || [];
        renderSharedFiles(currentSharedFiles);
    } catch (err) {
        console.error("fetchSharedFiles error:", err);
    }
}

function renderSharedFiles(files) {
    if (!sharedList) return;
    currentSharedFiles = Array.isArray(files) ? files : [];
    sharedList.innerHTML = "";
    if (currentSharedFiles.length === 0) {
        sharedList.innerHTML = `<div class="empty-placeholder" data-i18n="no_shared_files">${t("no_shared_files")}</div>`;
        return;
    }

    currentSharedFiles.forEach((file) => {
        const card = document.createElement("div");
        card.className = "item-card shared-row";
        card.dataset.shareId = String(file.id || "");

        const left = document.createElement("div");
        left.className = "shared-left";

        if (file.thumbnail && typeof file.thumbnail === "string" && file.thumbnail.startsWith("data:image/")) {
            const thumb = document.createElement("img");
            thumb.className = "thumb-img visible";
            thumb.src = file.thumbnail;
            thumb.alt = "";
            left.appendChild(thumb);
        }

        const isUnreadyFolder = Boolean((file.is_folder || file.is_dir) && file.archive_ready === false);
        const sizeLabel = (isUnreadyFolder || (file.is_folder && (!file.size || file.size <= 0)))
            ? t("status_preparing")
            : formatBytes(file.size || 0);

        const info = document.createElement("div");
        info.style.overflow = "hidden";
        info.innerHTML = `
            <div class="item-name"><bdi dir="auto"></bdi></div>
            <div class="item-meta" dir="ltr"></div>
        `;
        const nameBdi = info.querySelector(".item-name bdi");
        if (nameBdi) nameBdi.textContent = file.name;
        const nameDiv = info.querySelector(".item-name");
        if (nameDiv) nameDiv.title = file.name;
        info.querySelector(".item-meta").textContent = `${file.category || "File"} • ${sizeLabel}`;
        left.appendChild(info);

        const actions = document.createElement("div");
        actions.className = "shared-actions";

        if (file.category === "Videos" || file.category === "Audio") {
            const streamBtn = document.createElement("button");
            streamBtn.type = "button";
            streamBtn.className = "stream-btn";
            streamBtn.textContent = t("stream_btn");
            streamBtn.onclick = () => openMediaStreamModal(file);
            actions.appendChild(streamBtn);
        }

        const dlBtn = document.createElement("a");
        dlBtn.className = "download-btn";
        dlBtn.href = `/api/download/${encodeURIComponent(file.id)}?token=${encodeURIComponent(TOKEN)}&device_id=${encodeURIComponent(DEVICE_ID)}`;
        dlBtn.download = file.name;
        dlBtn.textContent = t("download_btn");
        actions.appendChild(dlBtn);

        const rmBtn = document.createElement("button");
        rmBtn.type = "button";
        rmBtn.className = "ctrl-btn danger";
        rmBtn.textContent = "×";
        rmBtn.title = t("remove_btn");
        rmBtn.setAttribute("aria-label", t("remove_btn"));
        rmBtn.onclick = async () => {
            try {
                await fetch(`/api/shared/${encodeURIComponent(file.id)}?token=${encodeURIComponent(TOKEN)}&device_id=${encodeURIComponent(DEVICE_ID)}`, {
                    method: "DELETE"
                });
                await fetchSharedFiles();
            } catch (err) {
                console.error("Failed to remove shared file:", err);
            }
        };
        actions.appendChild(rmBtn);

        card.appendChild(left);
        card.appendChild(actions);
        sharedList.appendChild(card);
    });
}

function handleSizeUpdated(data) {
    const shareId = data.share_id || data.id || data.request_id;
    const newSize = Number(data.size || 0);
    if (shareId) {
        removePreparingArchiveCard(shareId);
    }
    let updated = false;
    currentSharedFiles = currentSharedFiles.map((item) => {
        if ((shareId && item.id === shareId) || (data.name && item.name === data.name)) {
            updated = true;
            return Object.assign({}, item, {
                size: newSize,
                archive_ready: true
            });
        }
        return item;
    });
    if (updated) {
        renderSharedFiles(currentSharedFiles);
    }
}

function renderHistory(items) {
    if (!historyList) return;
    currentHistoryItems = Array.isArray(items) ? items.slice() : [];
    historyList.innerHTML = "";
    if (currentHistoryItems.length === 0) {
        historyList.innerHTML = `<div class="empty-placeholder" data-i18n="no_history">${t("no_history")}</div>`;
        return;
    }
    currentHistoryItems.slice().reverse().forEach((entry) => {
        prependHistoryRow(entry, false);
    });
}

function prependHistoryRow(entry, trackInArray = true) {
    if (!historyList) return;
    if (trackInArray) {
        currentHistoryItems.unshift(entry);
        if (currentHistoryItems.length > 50) currentHistoryItems.pop();
    }
    const placeholder = historyList.querySelector(".empty-placeholder");
    if (placeholder) placeholder.remove();
    const row = document.createElement("div");
    row.className = "item-card";
    row.innerHTML = `
        <div class="item-header">
            <span class="item-name"><bdi dir="auto"></bdi></span>
            <span class="cat-tag"></span>
            <span class="item-meta" dir="ltr"></span>
        </div>
    `;
    const nameEl = row.querySelector(".item-name");
    const nameBdi = row.querySelector(".item-name bdi");
    if (nameBdi) nameBdi.textContent = entry.filename;
    if (nameEl) nameEl.title = entry.filename;
    row.querySelector(".cat-tag").textContent = entry.category || "File";
    row.querySelector(".item-meta").textContent = `${entry.direction} • ${formatBytes(entry.size || 0)}`;
    historyList.prepend(row);
    while (historyList.children.length > 50) {
        historyList.lastElementChild.remove();
    }
}

/* ---------------- Section 3.1 Incoming PC Share Prompt ---------------- */
function renderIncomingModalItems() {
    if (!currentIncomingRequest) return;
    const files = currentIncomingRequest.files || [];
    const summary = formatPromptSummary(files, "PC", t);
    if (permText) permText.textContent = summary.headerText;
    if (!permFileList || !permExpandBtn) return;
    permFileList.innerHTML = "";

    if (summary.isSingle) {
        permFileList.style.display = "none";
        permExpandBtn.style.display = "none";
    } else {
        permFileList.style.display = "flex";
        const items = promptExpanded
            ? summary.visibleItems.concat(summary.hiddenItems)
            : summary.visibleItems;
        items.forEach((line) => {
            const div = document.createElement("div");
            div.textContent = `• ${line}`;
            permFileList.appendChild(div);
        });
        if (summary.moreCount > 0) {
            permExpandBtn.style.display = "inline-block";
            permExpandBtn.textContent = promptExpanded
                ? t("show_less")
                : t("more_items", { count: summary.moreCount });
        } else {
            permExpandBtn.style.display = "none";
        }
    }
}

function processNextRequest() {
    if (isProcessingRequest || requestQueue.length === 0) return;
    isProcessingRequest = true;
    currentIncomingRequest = requestQueue.shift();
    promptExpanded = false;

    renderIncomingModalItems();

    if (permPreviews) {
        permPreviews.innerHTML = "";
        (currentIncomingRequest.files || []).forEach((f) => {
            if (f.thumbnail && typeof f.thumbnail === "string" && f.thumbnail.startsWith("data:image/")) {
                const img = document.createElement("img");
                img.src = f.thumbnail;
                img.alt = "";
                permPreviews.appendChild(img);
            }
        });
    }
    if (permModal) permModal.classList.add("active");
}

if (permExpandBtn) {
    permExpandBtn.onclick = () => {
        promptExpanded = !promptExpanded;
        renderIncomingModalItems();
    };
}

/* ---------------- Section 3.3 Kicked / Blocked State & WebSocket ---------------- */
function enterKickedState(isBlocked = false) {
    kickedByPc = true;
    blockedByPc = isBlocked;
    clearTimeout(reconnectTimer);

    for (const xhr of activeXhrMap.values()) {
        try {
            xhr.abort();
        } catch (err) {
            console.error("XHR abort error:", err);
        }
    }
    activeXhrMap.clear();
    uploadQueue = [];

    setConnectionState(isBlocked ? "blocked" : "kicked");
}

if (reconnectBtn) {
    reconnectBtn.onclick = async () => {
        try {
            const res = await fetch(
                `/api/verify?token=${encodeURIComponent(TOKEN)}&device_id=${encodeURIComponent(DEVICE_ID)}`
            );
            if (res.status === 403) {
                const data = await res.json().catch(() => ({}));
                if (data.code === "DEVICE_BLOCKED") {
                    enterKickedState(true);
                    showToast(t("status_blocked_pc"), true);
                    return;
                }
            }
            if (res.ok) {
                kickedByPc = false;
                blockedByPc = false;
                setConnectionState("connecting");
                connectWebSocket();
            }
        } catch (err) {
            console.error("Reconnect verify error:", err);
            showToast(t("cannot_reach_pc"), true);
        }
    };
}

function applySnapshotTransfers(transfersArray) {
    if (!Array.isArray(transfersArray)) return;
    const seenActiveIds = new Set();
    transfersArray.forEach((tr) => {
        const tid = tr.id || tr.transfer_id;
        if (!tid) return;
        const fObj = tr.file || {};
        const stateRaw = String(tr.state || "").toLowerCase();
        if (stateRaw === "done" || stateRaw === "completed" || stateRaw === "cancelled" || stateRaw === "declined" || stateRaw === "rejected" || stateRaw === "expired") {
            activeTransferStates.delete(tid);
            const oldCard = document.getElementById(getSafeId(tid));
            if (oldCard) oldCard.remove();
            return;
        }
        seenActiveIds.add(tid);
        if (tid !== activeTransferId) {
            const isDownload = tr.direction === "pc_to_phone";
            const bytesDone = Number(tr.bytes_done ?? tr.received ?? 0);
            const speedVal = Number(tr.speed ?? tr.speed_bps ?? 0);
            let mappedState = isDownload ? "Downloading" : "Uploading";
            if (stateRaw === "paused") mappedState = "Paused";
            else if (stateRaw === "interrupted") mappedState = "Interrupted";
            else if (stateRaw === "accepted" || stateRaw === "waiting" || stateRaw === "pending" || (isDownload && bytesDone === 0 && speedVal === 0)) {
                mappedState = "Waiting";
            }
            const baseName = fObj.name || tr.filename || "file";
            renderTransferCardState(tid, {
                id: tid,
                name: isDownload && !baseName.startsWith("↓ ") ? `↓ ${baseName}` : baseName,
                size: fObj.size ?? tr.total ?? 0,
                offset: bytesDone,
                state: mappedState,
                direction: tr.direction || "",
                via: tr.via || defaultViaLabel(),
                speed_bps: speedVal,
                avg_speed_bps: tr.avg_speed ?? tr.avg_speed_bps ?? 0,
                eta_seconds: tr.eta !== undefined ? tr.eta : tr.eta_seconds,
                duration_sec: tr.elapsed !== undefined ? tr.elapsed : tr.duration_sec,
                stalled: Boolean(tr.stalled) && bytesDone > 0,
                waiting_for_phone: Boolean(tr.waiting_for_phone) && bytesDone > 0,
                connection_lost: Boolean(tr.connection_lost) && bytesDone > 0,
                category: fObj.category || tr.category,
                batch_index: tr.batch_index || 0,
                batch_size: tr.batch_size || 0
            });
        }
    });
    for (const existingId of Array.from(activeTransferStates.keys())) {
        if (!seenActiveIds.has(existingId) && existingId !== activeTransferId && !uploadEntriesById.has(existingId)) {
            activeTransferStates.delete(existingId);
            const staleCard = document.getElementById(getSafeId(existingId));
            if (staleCard) staleCard.remove();
        }
    }
    checkEmptyTransfersList();
    updateCloudSlowBanner();
}

function connectWebSocket() {
    if (kickedByPc) return;
    clearTimeout(reconnectTimer);
    setConnectionState(wsReconnectAttempts > 0 ? "reconnecting" : "connecting");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(TOKEN)}&device_id=${encodeURIComponent(DEVICE_ID)}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        wsReconnectAttempts = 0;
        setConnectionState("online");
        ws.send(JSON.stringify({
            type: "hello",
            device_id: DEVICE_ID,
            device_name: DEVICE_NAME
        }));
        fetchSharedFiles();
        resumeOfflineUploadsIfReady();
    };

    ws.onmessage = async (event) => {
        try {
            const data = JSON.parse(event.data);

            if (typeof data.seq === "number") {
                if (lastSeq > 0 && data.seq > lastSeq + 1 && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: "get_snapshot" }));
                }
                lastSeq = data.seq;
            }

            if (data.type === "kicked") {
                enterKickedState(false);
                return;
            }

            if (data.type === "handshake" || data.type === "snapshot") {
                if (data.appearance) applyAppearance(data.appearance);
                if (data.history) renderHistory(data.history);
                if (data.shares) renderSharedFiles(data.shares);
                if (data.transfers) applySnapshotTransfers(data.transfers);
                if (Array.isArray(data.preparing_items)) {
                    data.preparing_items.forEach((prep) => {
                        const pid = prep.share_id || prep.id || prep.request_id || "archive";
                        updatePreparingArchiveCard(pid, prep.filename || prep.name || "Archive", prep.progress ?? 0, prep.request_id || pid);
                    });
                }
                if (data.activity_summary) renderSpeedIndicator(data.activity_summary);
                else renderSpeedIndicator();
                if (typeof data.clipboard_text === "string" && syncInput && syncInput.value !== data.clipboard_text) {
                    syncInput.value = data.clipboard_text;
                }
            } else if (data.type === "appearance_updated") {
                applyAppearance(data.appearance);
            } else if (data.type === "activity_summary") {
                renderSpeedIndicator(data);
            } else if (data.type === "zip_progress" || data.type === "scan_progress") {
                const prepId = data.share_id || data.id || data.request_id || data.filename || "archive";
                const pct = data.type === "scan_progress" ? 0 : (data.progress ?? 0);
                updatePreparingArchiveCard(prepId, data.filename || data.name || "Archive", pct, data.request_id || prepId);
            } else if (data.type === "size_updated") {
                handleSizeUpdated(data);
                renderSpeedIndicator();
            } else if (data.type === "transfer_expired") {
                if (data.request_id) removePreparingArchiveCard(data.request_id);
                const expiredIds = Array.isArray(data.transfer_ids) ? data.transfer_ids.slice() : [];
                if (data.transfer_id && !expiredIds.includes(data.transfer_id)) {
                    expiredIds.push(data.transfer_id);
                }
                expiredIds.forEach((tid) => {
                    activeTransferStates.delete(tid);
                    const card = document.getElementById(getSafeId(tid));
                    if (card) card.remove();
                });
                checkEmptyTransfersList();
                renderSpeedIndicator();
                showToast(t(data.reason === "waiting_timeout" ? "transfer_expired_phone" : "transfer_expired_msg"), true, 5000);
            } else if (data.type === "share_removed" || data.type === "shared_removed") {
                if (Array.isArray(data.shares)) {
                    renderSharedFiles(data.shares);
                } else {
                    await fetchSharedFiles();
                }
            } else if (data.type === "history_cleared") {
                renderHistory([]);
            } else if (data.type === "download_progress" || data.type === "download_complete") {
                const cardKey = data.transfer_id || data.id || `dl-${data.file_id || data.share_id}`;
                const isDone = data.type === "download_complete";
                renderTransferCardState(cardKey, {
                    id: cardKey,
                    name: `↓ ${data.filename || data.name}`,
                    size: data.total || data.size || 0,
                    offset: data.received || data.bytes_done || (isDone ? (data.total || data.size || 0) : 0),
                    state: isDone ? "Completed" : "Downloading",
                    direction: "pc_to_phone",
                    via: data.via || defaultViaLabel(),
                    speed_bps: isDone ? 0 : (data.speed || data.speed_bps || 0),
                    avg_speed_bps: data.avg_speed || data.avg_speed_bps || 0,
                    eta_seconds: data.eta !== undefined ? data.eta : data.eta_seconds,
                    duration_sec: data.elapsed !== undefined ? data.elapsed : data.duration_sec,
                    category: data.category
                });
                renderSpeedIndicator();
            } else if (data.type === "transfer_cancelled") {
                const tr = data.transfer || {};
                const fObj = tr.file || {};
                const tid = data.transfer_id || data.id || tr.id || data.share_id || data.request_id;
                const cancelledByPc = (data.cancelled_by || tr.cancelled_by) === "pc";
                if (data.id) removePreparingArchiveCard(data.id);
                if (data.share_id) removePreparingArchiveCard(data.share_id);
                if (data.request_id) removePreparingArchiveCard(data.request_id);
                if (tid) {
                    removePreparingArchiveCard(tid);
                    cancelledTransferIds.add(tid);
                    pausedTransfers.delete(tid);
                    uploadEntriesById.delete(tid);
                    uploadQueue = uploadQueue.filter((q) => q.transferId !== tid);
                    const activeXhr = activeXhrMap.get(tid);
                    if (activeXhr) activeXhr.abort();
                    const existingRecord = activeTransferStates.get(tid);
                    const displayName = fObj.name || data.filename || data.name || (existingRecord && existingRecord.name) || "";
                    if (existingRecord || document.getElementById(getSafeId(tid))) {
                        const cancelLabel = cancelledByPc ? t("status_cancelled_pc") : t("status_cancelled");
                        setTransferStatusText(tid, displayName || "file", cancelLabel, true);
                    }
                    if (!isUploading && uploadQueue.length > 0) {
                        processQueue();
                    }
                }
                if (Array.isArray(data.shares)) {
                    renderSharedFiles(data.shares);
                }
                renderSpeedIndicator();
            } else if (data.type === "transfer_updated" || data.type === "progress") {
                const tr = data.transfer || data;
                const tid = tr.id || tr.transfer_id;
                const fObj = tr.file || {};
                const rawState = String(tr.state || "").toLowerCase();
                const isDone = rawState === "done" || rawState === "completed" || tr.progress >= 100;

                if (tid && rawState === "paused") {
                    const entry = uploadEntriesById.get(tid);
                    if (entry && !pausedTransfers.has(tid)) {
                        pausedTransfers.set(tid, entry);
                        if (entry.estimator) entry.estimator.pause();
                        uploadQueue = uploadQueue.filter((q) => q.transferId !== tid);
                        const activeXhr = activeXhrMap.get(tid);
                        if (activeXhr) activeXhr.abort();
                    }
                } else if (tid && rawState === "active" && pausedTransfers.has(tid)) {
                    const entry = pausedTransfers.get(tid);
                    pausedTransfers.delete(tid);
                    if (entry) {
                        if (entry.estimator) entry.estimator.resume();
                        if (!uploadQueue.some((q) => q.transferId === tid) && activeTransferId !== tid) {
                            uploadQueue.unshift(entry);
                        }
                        processQueue();
                    }
                }

                if ((tid && tid !== activeTransferId) || isDone || rawState === "paused" || rawState === "interrupted") {
                    const isDownload = tr.direction === "pc_to_phone";
                    const baseName = fObj.name || tr.filename || "file";
                    const bytesDone = Number(tr.bytes_done ?? tr.received ?? 0);
                    const speedVal = Number(tr.speed ?? tr.speed_bps ?? 0);
                    let mappedState = isDone ? "Completed" : (isDownload ? "Downloading" : "Uploading");
                    if (!isDone) {
                        if (rawState === "paused") mappedState = "Paused";
                        else if (rawState === "interrupted") mappedState = "Interrupted";
                        else if (rawState === "accepted" || rawState === "waiting" || rawState === "pending" || (isDownload && bytesDone === 0 && speedVal === 0)) {
                            mappedState = "Waiting";
                        }
                    }
                    renderTransferCardState(tid || baseName, {
                        id: tid,
                        name: isDownload && !baseName.startsWith("↓ ") ? `↓ ${baseName}` : baseName,
                        size: fObj.size ?? tr.total ?? 0,
                        offset: bytesDone,
                        state: mappedState,
                        direction: tr.direction || "",
                        via: tr.via || defaultViaLabel(),
                        speed_bps: isDone || rawState === "paused" || rawState === "interrupted" ? 0 : speedVal,
                        avg_speed_bps: tr.avg_speed ?? tr.avg_speed_bps ?? 0,
                        eta_seconds: tr.eta !== undefined ? tr.eta : tr.eta_seconds,
                        duration_sec: tr.elapsed !== undefined ? tr.elapsed : tr.duration_sec,
                        stalled: Boolean(tr.stalled) && bytesDone > 0,
                        waiting_for_phone: Boolean(tr.waiting_for_phone) && bytesDone > 0,
                        connection_lost: Boolean(tr.connection_lost) && bytesDone > 0,
                        category: fObj.category || tr.category,
                        batch_index: tr.batch_index || 0,
                        batch_size: tr.batch_size || 0
                    });
                }
                renderSpeedIndicator();
            } else if (data.type === "shared_updated") {
                await fetchSharedFiles();
            } else if (data.type === "history_updated" && data.entry) {
                prependHistoryRow(data.entry);
            } else if (data.type === "text_sync") {
                if (typeof data.content === "string" && syncInput && syncInput.value !== data.content) {
                    syncInput.value = data.content;
                }
            } else if (data.type === "transfer_request" && data.target === "mobile") {
                requestQueue.push(data);
                processNextRequest();
            } else if (data.type === "transfer_accepted") {
                if (data.direction === "pc_to_phone") {
                    if (Array.isArray(data.shares)) {
                        renderSharedFiles(data.shares);
                    } else {
                        await fetchSharedFiles();
                    }
                    const committedFiles = data.files || [];
                    if (data.accepted_by_device_id === DEVICE_ID && committedFiles.length > 0) {
                        const firstShare = committedFiles[0];
                        if (firstShare.auto_download_allowed !== false) {
                            triggerNativeDownload(firstShare);
                            if (committedFiles.length > 1) {
                                showToast(t("downloading_first_toast", { name: firstShare.name }));
                            }
                        }
                    }
                } else if (data.target === "mobile") {
                    const batchFiles = pendingBatches[data.request_id];
                    const serverTransfers = data.transfers || [];
                    if (batchFiles) {
                        delete pendingBatches[data.request_id];
                        const totalInBatch = batchFiles.length;
                        batchFiles.forEach((file, idx) => {
                            const pendingKey = `pending-${file.name}`;
                            const pendingCard = document.getElementById(getSafeId(pendingKey));
                            if (pendingCard) pendingCard.remove();
                            activeTransferStates.delete(pendingKey);

                            const matchedTx = serverTransfers.find((st) => st.batch_index === idx + 1) || serverTransfers[idx];
                            if (matchedTx) {
                                const entry = {
                                    file: file,
                                    transferId: matchedTx.id,
                                    fileIndex: idx,
                                    batchSize: totalInBatch,
                                    lastOffset: 0,
                                    estimator: null
                                };
                                uploadEntriesById.set(matchedTx.id, entry);
                                ensureTransferCard(
                                    matchedTx.id,
                                    file.name,
                                    file.size,
                                    `${t("status_accepted")} • ${t("starting_upload")}`,
                                    null,
                                    inferCategory(file.name),
                                    entry,
                                    idx + 1,
                                    totalInBatch
                                );
                                uploadQueue.push(entry);
                            }
                        });
                        renderSpeedIndicator();
                        processQueue();
                    }
                }
            } else if (data.type === "transfer_rejected") {
                if (data.request_id) removePreparingArchiveCard(data.request_id);
                if (data.target === "mobile") {
                    const batchFiles = pendingBatches[data.request_id];
                    if (batchFiles) {
                        delete pendingBatches[data.request_id];
                        batchFiles.forEach((file) => {
                            setTransferStatusText(`pending-${file.name}`, file.name, t("declined_by_pc"), true);
                        });
                    }
                }
            }
        } catch (err) {
            console.error("WebSocket message handler error:", err);
        }
    };

    ws.onclose = (event) => {
        if (event.code === 4001) {
            enterKickedState(false);
            return;
        }
        if (event.code === 4003) {
            enterKickedState(true);
            return;
        }
        if (kickedByPc) return;

        wsReconnectAttempts++;
        setConnectionState("reconnecting");
        const delay = Math.min(10000, 1500 * Math.pow(1.4, wsReconnectAttempts - 1));
        reconnectTimer = setTimeout(connectWebSocket, delay);
    };
}

if (acceptModalBtn) {
    acceptModalBtn.addEventListener("click", () => {
        if (!currentIncomingRequest) return;
        const req = currentIncomingRequest;
        currentIncomingRequest = null;
        if (permModal) permModal.classList.remove("active");

        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: "transfer_accepted",
                target: "pc",
                request_id: req.request_id,
                files: req.files || []
            }));
        }

        isProcessingRequest = false;
        processNextRequest();
    });
}

if (rejectModalBtn) {
    rejectModalBtn.addEventListener("click", () => {
        if (!currentIncomingRequest) return;
        const req = currentIncomingRequest;
        currentIncomingRequest = null;
        if (permModal) permModal.classList.remove("active");

        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: "transfer_rejected",
                target: "pc",
                request_id: req.request_id,
                files: req.files || []
            }));
        }

        isProcessingRequest = false;
        processNextRequest();
    });
}

if (syncInput) {
    syncInput.addEventListener("input", () => {
        clearTimeout(syncDebounceTimer);
        syncDebounceTimer = setTimeout(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: "text_sync",
                    content: syncInput.value,
                    source: "mobile"
                }));
            }
        }, 180);
    });
}

if (copyTextBtn) {
    copyTextBtn.addEventListener("click", async () => {
        const text = syncInput ? syncInput.value : "";
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
        } catch (err) {
            if (syncInput) {
                syncInput.select();
                document.execCommand("copy");
            }
        }
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: "text_sync",
                content: text,
                source: "mobile"
            }));
        }
        copyBtnCopiedState = true;
        ByteDropFormat.setButtonLabel(copyTextBtn, t("copied_btn"));
        setTimeout(() => {
            copyBtnCopiedState = false;
            ByteDropFormat.setButtonLabel(copyTextBtn, t("copy_btn"));
        }, 1500);
    });
}

async function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function sendChunkPutWithLiveProgress(transferId, headers, bodyBlob, onLiveProgress) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        activeXhrMap.set(transferId, xhr);
        xhr.open("PUT", `/api/upload/${encodeURIComponent(transferId)}`, true);
        xhr.timeout = Math.max(60000, Math.round((bodyBlob.size / (256 * 1024)) * 1000));

        Object.entries(headers).forEach(([k, v]) => {
            if (v !== undefined && v !== null) {
                xhr.setRequestHeader(k, v);
            }
        });
        xhr.upload.onprogress = (event) => {
            if (event.lengthComputable && onLiveProgress) {
                onLiveProgress(event.loaded, event.total);
            }
        };
        xhr.onload = () => {
            activeXhrMap.delete(transferId);
            let parsed = {};
            try {
                parsed = JSON.parse(xhr.responseText || "{}");
            } catch (err) {
                console.error("Failed to parse upload response JSON:", err);
            }
            resolve({ status: xhr.status, ok: xhr.status >= 200 && xhr.status < 300, data: parsed });
        };
        xhr.onerror = () => {
            activeXhrMap.delete(transferId);
            reject(new Error("Network error during chunk upload"));
        };
        xhr.ontimeout = () => {
            activeXhrMap.delete(transferId);
            reject(new Error("Chunk upload timed out"));
        };
        xhr.onabort = () => {
            activeXhrMap.delete(transferId);
            reject(new Error("ABORTED"));
        };
        xhr.send(bodyBlob);
    });
}

async function uploadSingleEntry(entry) {
    await requestWakeLock();
    const { file, transferId, fileIndex, batchSize } = entry;
    cancelledTransferIds.delete(transferId);
    activeTransferId = transferId;

    const pendingCard = document.getElementById(getSafeId(`pending-${file.name}`));
    if (pendingCard) pendingCard.remove();
    activeTransferStates.delete(`pending-${file.name}`);

    const category = inferCategory(file.name);
    const trueFileSize = Number(file.size) || 0;

    let offset = 0;
    try {
        const statusRes = await fetch(`/api/upload/${encodeURIComponent(transferId)}?token=${encodeURIComponent(TOKEN)}`);
        if (statusRes.ok) {
            const statusData = await statusRes.json();
            offset = Number(statusData.offset) || 0;
        }
    } catch (err) {
        console.error("Initial upload offset check failed:", err);
        offset = 0;
    }

    if (offset >= trueFileSize && trueFileSize > 0) {
        offset = 0;
    }

    const estimator = new SpeedEstimator(trueFileSize, offset);
    entry.estimator = estimator;
    entry.lastOffset = offset;

    ensureTransferCard(transferId, file.name, trueFileSize, "0%", null, category, entry, fileIndex + 1, batchSize);

    let retries = 0;
    let consecutive409 = 0;

    while (offset < trueFileSize || (trueFileSize === 0 && offset === 0)) {
        if (kickedByPc || cancelledTransferIds.has(transferId) || pausedTransfers.has(transferId)) {
            activeTransferId = null;
            renderSpeedIndicator();
            return;
        }

        const sliceSize = currentChunkSize;
        const rawChunk = file.slice(offset, offset + sliceSize);
        const rawByteLength = rawChunk.size;

        try {
            const headers = {
                "Content-Type": "application/octet-stream",
                "X-Token": TOKEN,
                "X-Chunk-Offset": offset.toString()
            };

            const t0 = performance.now();

            const response = await sendChunkPutWithLiveProgress(transferId, headers, rawChunk, (loadedBytes, totalPayloadBytes) => {
                const ratio = totalPayloadBytes > 0 ? Math.min(1, loadedBytes / totalPayloadBytes) : 0;
                const effectiveChunkBytes = Math.round(rawByteLength * ratio);
                const liveOffset = Math.min(trueFileSize, offset + effectiveChunkBytes);
                entry.lastOffset = liveOffset;

                const snap = estimator.update(liveOffset, false);
                renderTransferCardState(transferId, {
                    id: transferId,
                    name: file.name,
                    size: trueFileSize,
                    offset: liveOffset,
                    state: "Uploading",
                    speed_bps: snap.speed_bps,
                    avg_speed_bps: snap.avg_speed_bps,
                    eta_seconds: snap.eta_seconds,
                    stalled: snap.stalled,
                    category: category,
                    batch_index: fileIndex + 1,
                    batch_size: batchSize
                });
            });

            const elapsedSec = Math.max(0.001, (performance.now() - t0) / 1000);

            if (kickedByPc || cancelledTransferIds.has(transferId) || pausedTransfers.has(transferId)) {
                activeTransferId = null;
                renderSpeedIndicator();
                return;
            }

            if (response.status === 409) {
                if (response.data && response.data.code === "TRANSFER_PAUSED") {
                    if (response.data.offset !== undefined) {
                        offset = Number(response.data.offset) || offset;
                        entry.lastOffset = offset;
                    }
                    pausedTransfers.set(transferId, entry);
                    estimator.pause();
                    renderTransferCardState(transferId, {
                        id: transferId,
                        name: file.name,
                        size: trueFileSize,
                        offset: offset,
                        state: "Paused",
                        category: category,
                        batch_index: fileIndex + 1,
                        batch_size: batchSize
                    });
                    activeTransferId = null;
                    renderSpeedIndicator();
                    return;
                }
                if (response.data && response.data.code === "INVALID_TRANSFER_STATE") {
                    cancelledTransferIds.add(transferId);
                    pausedTransfers.delete(transferId);
                    uploadEntriesById.delete(transferId);
                    setTransferStatusText(transferId, file.name, t("status_cancelled"), true);
                    activeTransferId = null;
                    renderSpeedIndicator();
                    return;
                }
                consecutive409++;
                if (consecutive409 > 5) {
                    pausedTransfers.set(transferId, entry);
                    estimator.pause();
                    renderTransferCardState(transferId, {
                        id: transferId,
                        name: file.name,
                        size: trueFileSize,
                        offset: offset,
                        state: "Paused",
                        category: category,
                        batch_index: fileIndex + 1,
                        batch_size: batchSize
                    });
                    activeTransferId = null;
                    return;
                }
                offset = Number(response.data.offset) || 0;
                estimator.resetForResume(offset);
                continue;
            }
            consecutive409 = 0;

            if (response.status === 403 && response.data && response.data.code === "DEVICE_BLOCKED") {
                enterKickedState(true);
                return;
            }

            if (response.status >= 400 && response.status < 500) {
                const msg = response.data.detail || t("upload_failed");
                showToast(msg, true);
                setTransferStatusText(transferId, file.name, msg, true);
                activeTransferId = null;
                return;
            }

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            retries = 0;
            adjustDynamicChunkSize(rawByteLength, elapsedSec);

            offset = Number(response.data.offset) || (offset + rawByteLength);
            entry.lastOffset = offset;
            const finalSnap = estimator.update(offset, true);

            const isDone = offset >= trueFileSize;
            renderTransferCardState(transferId, {
                id: transferId,
                name: file.name,
                size: trueFileSize,
                offset: offset,
                state: isDone ? "Completed" : "Uploading",
                speed_bps: isDone ? 0 : finalSnap.speed_bps,
                avg_speed_bps: response.data.avg_speed_bps || finalSnap.avg_speed_bps,
                eta_seconds: finalSnap.eta_seconds,
                duration_sec: response.data.duration_sec || finalSnap.elapsed_sec,
                category: response.data.category || category,
                batch_index: fileIndex + 1,
                batch_size: batchSize
            });

            if (trueFileSize === 0) break;
        } catch (err) {
            if (err && err.message === "ABORTED") {
                activeTransferId = null;
                renderSpeedIndicator();
                return;
            }
            if (!navigator.onLine || connectionState === "reconnecting" || connectionState === "offline") {
                if (estimator) estimator.pause();
                renderTransferCardState(transferId, {
                    id: transferId,
                    name: file.name,
                    size: trueFileSize,
                    offset: offset,
                    state: "Uploading",
                    offline_will_resume: true,
                    category: category,
                    batch_index: fileIndex + 1,
                    batch_size: batchSize
                });
                if (!uploadQueue.some((q) => q.transferId === transferId)) {
                    uploadQueue.unshift(entry);
                }
                activeTransferId = null;
                renderSpeedIndicator();
                return;
            }
            retries++;
            if (retries > 8) {
                pausedTransfers.set(transferId, entry);
                estimator.pause();
                renderTransferCardState(transferId, {
                    id: transferId,
                    name: file.name,
                    size: trueFileSize,
                    offset: offset,
                    state: "Paused",
                    category: category,
                    batch_index: fileIndex + 1,
                    batch_size: batchSize
                });
                activeTransferId = null;
                return;
            }
            currentChunkSize = MIN_CHUNK_SIZE;
            await sleep(1500);
            try {
                const recoveryRes = await fetch(`/api/upload/${encodeURIComponent(transferId)}?token=${encodeURIComponent(TOKEN)}`);
                if (recoveryRes.ok) {
                    const recoveryData = await recoveryRes.json();
                    offset = Number(recoveryData.offset) || 0;
                    estimator.resetForResume(offset);
                }
            } catch (recErr) {
                console.error("Recovery offset fetch failed:", recErr);
            }
        }
    }

    activeTransferId = null;
    renderSpeedIndicator();
}

function markActiveUploadsOfflineWillResume() {
    for (const [tid, entry] of uploadEntriesById.entries()) {
        if (pausedTransfers.has(tid) || cancelledTransferIds.has(tid)) continue;
        const activeXhr = activeXhrMap.get(tid);
        if (activeXhr) {
            try {
                activeXhr.abort();
            } catch (err) {
                console.error("Abort offline upload XHR error:", err);
            }
        }
        const rec = activeTransferStates.get(tid);
        if (rec && rec.state !== "Completed") {
            renderTransferCardState(tid, Object.assign({}, rec, {
                offline_will_resume: true,
                speed_bps: 0
            }));
        }
        if (!uploadQueue.some((q) => q.transferId === tid)) {
            uploadQueue.unshift(entry);
        }
    }
    renderSpeedIndicator();
}

function resumeOfflineUploadsIfReady() {
    if (!navigator.onLine || kickedByPc) return;
    let hasResumable = false;
    for (const [tid, rec] of activeTransferStates.entries()) {
        if (rec && rec.offline_will_resume) {
            rec.offline_will_resume = false;
            hasResumable = true;
        }
    }
    if ((hasResumable || uploadQueue.length > 0) && !isUploading) {
        processQueue();
    }
}

window.addEventListener("offline", () => {
    markActiveUploadsOfflineWillResume();
});

window.addEventListener("online", () => {
    if (!kickedByPc && (!ws || ws.readyState !== WebSocket.OPEN)) {
        connectWebSocket();
    } else {
        resumeOfflineUploadsIfReady();
    }
});

async function processQueue() {
    if (isUploading || kickedByPc) return;
    isUploading = true;
    try {
        while (uploadQueue.length > 0 && !kickedByPc) {
            if (!navigator.onLine) {
                markActiveUploadsOfflineWillResume();
                break;
            }
            const entry = uploadQueue.shift();
            await uploadSingleEntry(entry);
        }
    } finally {
        isUploading = false;
        activeTransferId = null;
        renderSpeedIndicator();
    }
}

function handleSelectedFiles(fileList) {
    if (kickedByPc) {
        showToast(blockedByPc ? t("status_blocked_pc") : t("status_disconnected_pc"), true);
        return;
    }
    const files = Array.from(fileList || []);
    if (files.length === 0) return;

    const reqId = "req-" + Date.now() + "-" + Math.random().toString(16).slice(2, 8);
    pendingBatches[reqId] = files;
    const totalCount = files.length;

    const metadata = files.map((file, idx) => {
        const category = inferCategory(file.name);
        const exactSize = Number(file.size) || 0;
        const pendingKey = `pending-${file.name}`;
        ensureTransferCard(
            pendingKey,
            file.name,
            exactSize,
            `${t("waiting_pc_approval")} (${formatBytes(exactSize)})`,
            null,
            category,
            null,
            idx + 1,
            totalCount
        );
        return {
            name: file.name,
            size: exactSize,
            category: category,
            file_index: idx,
            thumbnail: null
        };
    });

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: "transfer_request",
            target: "pc",
            request_id: reqId,
            files: metadata
        }));
    } else {
        delete pendingBatches[reqId];
        files.forEach((file) => setTransferStatusText(`pending-${file.name}`, file.name, t("failed_offline"), true));
    }
}

if (selectFilesBtn) {
    selectFilesBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        fileInput.click();
    });
}

if (dropZone) {
    dropZone.addEventListener("click", (e) => {
        if (e.target === selectFilesBtn) return;
        fileInput.click();
    });

    dropZone.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileInput.click();
        }
    });

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("drag-active");
    });

    dropZone.addEventListener("dragleave", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-active");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-active");

        if (e.dataTransfer && e.dataTransfer.items) {
            for (let i = 0; i < e.dataTransfer.items.length; i++) {
                const item = e.dataTransfer.items[i];
                if (typeof item.webkitGetAsEntry === "function") {
                    const entry = item.webkitGetAsEntry();
                    if (entry && entry.isDirectory) {
                        showToast(t("folder_drop_rejected"), true, 5000);
                        return;
                    }
                }
            }
        }

        if (e.dataTransfer && e.dataTransfer.files) {
            handleSelectedFiles(e.dataTransfer.files);
        }
    });
}

if (fileInput) {
    fileInput.addEventListener("change", (e) => {
        handleSelectedFiles(e.target.files);
        fileInput.value = "";
    });
}

async function init() {
    document.title = "ByteDrop";
    initAppearance();
    if (!TOKEN) {
        setConnectionState("no_token");
        return;
    }
    setConnectionState("connecting");
    await requestWakeLock();
    connectWebSocket();
}

init();
