/**
 * ByteDrop v1.0.0 Desktop UI Controller (/ui/desktop/desktop.js)
 * Connects pywebview.api and server events to the glassmorphic desktop interface.
 */
(function () {
    "use strict";

    const Fmt = window.ByteDropFormat;
    const I18n = window.ByteDropDesktopI18n;
    const formatBytes = Fmt.formatBytes;
    const formatSpeed = Fmt.formatSpeed;
    const formatDuration = Fmt.formatDuration;
    const formatTransferRowDetail = Fmt.formatTransferRowDetail;
    const formatPromptSummary = Fmt.formatPromptSummary;
    const summarizeActivity = Fmt.summarizeActivity;
    const ACCENT_PALETTES = Fmt.ACCENT_PALETTES;

    const syncTextarea = document.getElementById("sync-textarea");
    const permModal = document.getElementById("perm-modal");
    const permDesc = document.getElementById("perm-desc");
    const permFileList = document.getElementById("perm-file-list");
    const permExpandBtn = document.getElementById("perm-expand-btn");
    const permDiskWarn = document.getElementById("perm-disk-warn");
    const permThumbs = document.getElementById("perm-thumbs");
    const acceptBtn = document.getElementById("accept-btn");
    const rejectBtn = document.getElementById("reject-btn");

    const dropCard = document.getElementById("drop-card");
    const qrImg = document.getElementById("qr-img");
    const qrBtnLocal = document.getElementById("qr-btn-local");
    const qrBtnCloud = document.getElementById("qr-btn-cloud");
    const qrBtnHotspot = document.getElementById("qr-btn-hotspot");
    const openHotspotSettingsBtn = document.getElementById("open-hotspot-settings-btn");
    const statusBadge = document.getElementById("status-badge");
    const cloudStatePill = document.getElementById("cloud-state-pill");
    const devicesListEl = document.getElementById("devices-list");
    const blockedSectionEl = document.getElementById("blocked-section");
    const blockedListEl = document.getElementById("blocked-list");
    const sharedPcListEl = document.getElementById("shared-pc-list");
    const activeTransfersBox = document.getElementById("active-transfers-box");
    const speedIndicator = document.getElementById("speed-indicator");
    const activeCountSub = document.getElementById("active-count-sub");
    const cancelAllBtn = document.getElementById("cancel-all-btn");
    const confirmCancelAllModal = document.getElementById("confirm-cancel-all-modal");
    const dismissCancelAllBtn = document.getElementById("dismiss-cancel-all-btn");
    const confirmCancelAllBtn = document.getElementById("confirm-cancel-all-btn");
    const cloudSlowBanner = document.getElementById("cloud-slow-banner");
    const dismissCloudHintBtn = document.getElementById("dismiss-cloud-hint-btn");

    const settingsModal = document.getElementById("settings-modal");
    const openSettingsBtn = document.getElementById("open-settings-btn");
    const closeSettingsBtn = document.getElementById("close-settings-btn");
    const themeDarkBtn = document.getElementById("theme-dark-btn");
    const themeLightBtn = document.getElementById("theme-light-btn");
    const langEnBtn = document.getElementById("lang-en-btn");
    const langArBtn = document.getElementById("lang-ar-btn");
    const settingsDirLabel = document.getElementById("settings-dir-label");
    const changeDirBtn = document.getElementById("change-dir-btn");
    const preferredIpSelect = document.getElementById("preferred-ip-select");
    const cloudAutoToggle = document.getElementById("cloud-auto-toggle");
    const cloudRestartBtn = document.getElementById("cloud-restart-btn");
    const autoAcceptToggle = document.getElementById("auto-accept-toggle");
    const maxFolderGbInput = document.getElementById("max-folder-gb-input");
    const trayModeToggle = document.getElementById("tray-mode-toggle");
    const startMinToggle = document.getElementById("start-min-toggle");
    const autostartToggle = document.getElementById("autostart-toggle");
    const muteNotifToggle = document.getElementById("mute-notif-toggle");
    const regenSessionBtn = document.getElementById("regen-session-btn");
    const openLogsBtn = document.getElementById("open-logs-btn");
    const copyDiagBtn = document.getElementById("copy-diag-btn");

    const clearHistoryBtn = document.getElementById("clear-history-btn");
    const confirmClearModal = document.getElementById("confirm-clear-modal");
    const cancelClearBtn = document.getElementById("cancel-clear-btn");
    const confirmClearBtn = document.getElementById("confirm-clear-btn");

    const copyLocalBtn = document.getElementById("copy-local-btn");
    const copyPublicBtn = document.getElementById("copy-public-btn");
    const copyBtn = document.getElementById("copy-btn");
    const clipToggleBtn = document.getElementById("clip-toggle-btn");

    const bootCfg = window.__BYTEDROP_CONFIG__ || {};
    let local_url = (document.getElementById("url-box") && document.getElementById("url-box").textContent.trim()) || "";
    let cloud_url = "";
    let hotspot_url = "";

    const qrCache = {
        local: qrImg ? qrImg.getAttribute("src") : "",
        cloud: "",
        hotspot_link: ""
    };
    let activeQrMode = "local";

    let connectedCount = 0;
    let connectedDevicesModel = [];
    let blockedDevicesModel = [];
    let sharedPcFilesModel = [];
    let lastTunnelStatus = { state: "Starting", reason: "" };
    let lastHotspotStatus = { detected: false, active: false };
    let candidateIpsModel = [];
    let preferredIpModel = "";

    const activeTransfersMap = new Map();
    const preparingMap = new Map();
    const rowRemovalTimers = new Map();
    const disconnectingDevices = new Map();
    let lastActivitySummary = { state: "idle", speed_bps: 0, eta_seconds: null, active_count: 0 };
    let cloudHintDismissed = false;
    let corruptToastShown = false;
    let interruptedCountdownTimer = null;

    let requestQueue = [];
    let isProcessingRequest = false;
    let currentRequest = null;
    let promptExpanded = false;
    let isPywebviewBound = false;
    let dragDepth = 0;
    let syncDebounceTimer = null;

    let currentTheme = bootCfg.theme || "dark";
    let currentAccent = bootCfg.accent || "blue";
    let currentLanguage = bootCfg.language || "en";
    let cloudAutoStart = bootCfg.cloud_auto_start !== false;
    let clipboardAutoSync = Boolean(bootCfg.clipboard_sync_enabled);
    let autoAcceptLocal = Boolean(bootCfg.auto_accept_local);
    let trayModeEnabled = Boolean(bootCfg.tray_mode_enabled);
    let startMinimized = Boolean(bootCfg.start_minimized);
    let startWithWindows = Boolean(bootCfg.autostart_windows);
    let notificationsEnabled = bootCfg.notifications_enabled !== false;

    const MAX_ACTIVITY_ROWS = 120;

    function tCategory(cat) {
        const key = `cat_${cat || "File"}`;
        return I18n.t(key);
    }

    function getSafeRowId(prefix, rawId) {
        const hex = Array.from(new TextEncoder().encode(String(rawId)))
            .map((b) => b.toString(16).padStart(2, "0"))
            .join("");
        return `${prefix}-${hex}`;
    }

    async function persistPreferences(themeVal, accentVal, langVal) {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_ui_preferences) {
            try {
                await window.pywebview.api.set_ui_preferences(themeVal, accentVal, langVal);
            } catch (e) {
                console.error("set_ui_preferences failed:", e);
            }
        }
    }

    function applyTheme(theme, saveToDisk = false) {
        const isLight = theme === "light";
        currentTheme = isLight ? "light" : "dark";
        document.body.classList.toggle("light-mode", isLight);
        if (themeDarkBtn) themeDarkBtn.classList.toggle("active", !isLight);
        if (themeLightBtn) themeLightBtn.classList.toggle("active", isLight);
        if (saveToDisk) {
            persistPreferences(currentTheme, currentAccent, currentLanguage);
        }
    }

    function applyAccent(accentName, saveToDisk = false) {
        const validName = ACCENT_PALETTES[accentName] ? accentName : "blue";
        currentAccent = validName;
        const p = ACCENT_PALETTES[validName];
        const root = document.documentElement;
        root.style.setProperty("--accent-from", p.from);
        root.style.setProperty("--accent-to", p.to);
        root.style.setProperty("--accent-light", p.light);
        root.style.setProperty("--accent-rgb", p.rgb);
        root.style.setProperty("--accent-dark-rgb", p.darkRgb);

        document.querySelectorAll("#accent-swatch-group .color-swatch").forEach((btn) => {
            btn.classList.toggle("active", btn.dataset.accent === validName);
        });
        if (saveToDisk) {
            persistPreferences(currentTheme, currentAccent, currentLanguage);
        }
    }

    function renderDynamicStaticButtons() {
        if (copyLocalBtn) copyLocalBtn.textContent = I18n.t("copy_btn");
        if (copyPublicBtn) copyPublicBtn.textContent = I18n.t("copy_btn");
        if (copyBtn) copyBtn.textContent = I18n.t("clip_send_btn");
        if (clipToggleBtn) {
            ByteDropFormat.setButtonLabel(clipToggleBtn, clipboardAutoSync ? I18n.t("clip_auto_on") : I18n.t("clip_auto_off"));
            clipToggleBtn.classList.toggle("active", clipboardAutoSync);
        }
        renderToggleButton(cloudAutoToggle, cloudAutoStart, I18n.t("toggle_on"), I18n.t("toggle_off"));
        renderToggleButton(autoAcceptToggle, autoAcceptLocal, I18n.t("toggle_on"), I18n.t("toggle_off"));
        renderToggleButton(trayModeToggle, trayModeEnabled, I18n.t("tray_on"), I18n.t("tray_off"));
        renderToggleButton(startMinToggle, startMinimized, I18n.t("min_on"), I18n.t("min_off"));
        renderToggleButton(autostartToggle, startWithWindows, I18n.t("win_on"), I18n.t("win_off"));
        renderToggleButton(muteNotifToggle, notificationsEnabled, I18n.t("alerts_on"), I18n.t("alerts_muted"));
        if (copyDiagBtn) copyDiagBtn.textContent = I18n.t("copy_diag_btn");
    }

    function applyLanguage(lang, saveToDisk = false) {
        currentLanguage = I18n.setLanguage(lang);
        const isAr = currentLanguage === "ar";
        if (langEnBtn) langEnBtn.classList.toggle("active", !isAr);
        if (langArBtn) langArBtn.classList.toggle("active", isAr);

        renderDynamicStaticButtons();
        renderStatusBadgeFromModel();
        updateTunnelStatus(lastTunnelStatus);
        renderHotspotLabels(lastHotspotStatus);
        renderConnectedDevices(connectedDevicesModel);
        renderBlockedDevices(blockedDevicesModel);
        renderSharedPcFiles(sharedPcFilesModel);
        populateCandidateIps(candidateIpsModel, preferredIpModel);
        renderAllActiveTransferRows();
        renderSpeedIndicator(lastActivitySummary);
        if (currentRequest) {
            renderCurrentPromptItems();
        }

        if (saveToDisk) {
            persistPreferences(currentTheme, currentAccent, currentLanguage);
        }
    }

    function renderToggleButton(btn, isActive, onLabel, offLabel) {
        if (!btn) return;
        btn.classList.toggle("active", isActive);
        btn.textContent = isActive ? onLabel : offLabel;
    }

    if (openSettingsBtn) openSettingsBtn.onclick = () => settingsModal.classList.add("active");
    if (closeSettingsBtn) closeSettingsBtn.onclick = () => settingsModal.classList.remove("active");
    if (settingsModal) {
        settingsModal.addEventListener("click", (e) => {
            if (e.target === settingsModal) settingsModal.classList.remove("active");
        });
    }

    if (themeDarkBtn) themeDarkBtn.onclick = () => applyTheme("dark", true);
    if (themeLightBtn) themeLightBtn.onclick = () => applyTheme("light", true);
    if (langEnBtn) langEnBtn.onclick = () => applyLanguage("en", true);
    if (langArBtn) langArBtn.onclick = () => applyLanguage("ar", true);

    document.querySelectorAll("#accent-swatch-group .color-swatch").forEach((btn) => {
        btn.onclick = () => applyAccent(btn.dataset.accent, true);
    });

    /* ---------------- F1: Pure Connection Status Badge Rendering ---------------- */
    function renderStatusBadgeFromModel() {
        if (!statusBadge) return;
        const rendered = I18n.renderConnectionStatus({ count: connectedCount }, currentLanguage);
        statusBadge.textContent = rendered.text;
        statusBadge.className = rendered.cssClass;
    }

    function flashStatusMessage(msg) {
        if (!statusBadge) return;
        statusBadge.textContent = msg;
        statusBadge.classList.add("warn");
        setTimeout(() => {
            statusBadge.classList.remove("warn");
            renderStatusBadgeFromModel();
        }, 2200);
    }
    window.flashStatusMessage = flashStatusMessage;

    /* ---------------- Section 2: Speed / Time-Left Indicator ---------------- */
    function computeLocalSummaryFallback() {
        const items = [];
        activeTransfersMap.forEach((tr) => items.push(tr));
        preparingMap.forEach((p) => items.push({
            id: p.id,
            request_id: p.request_id,
            name: p.name,
            state: "preparing",
            preparing: true,
            progress: p.progress
        }));
        return summarizeActivity(items);
    }

    function updateCancelAllButtonVisibility() {
        if (!cancelAllBtn) return;
        const nonTerminalCount = activeTransfersMap.size + preparingMap.size;
        const show = nonTerminalCount >= 2;
        cancelAllBtn.style.display = show ? "inline-block" : "none";
        cancelAllBtn.classList.toggle("hidden", !show);
    }

    function updateCloudSlowBanner() {
        if (!cloudSlowBanner) return;
        let hasLargeCloudTransfer = false;
        if (!cloudHintDismissed) {
            activeTransfersMap.forEach((tr) => {
                const st = String(tr.state || "");
                const isNonTerminal = st === "Uploading" || st === "Downloading" || st === "Waiting" || st === "Paused" || st === "Interrupted";
                if (isNonTerminal && tr.via === "Cloud" && Number(tr.size || 0) > 100 * 1024 * 1024) {
                    hasLargeCloudTransfer = true;
                }
            });
        }
        cloudSlowBanner.style.display = hasLargeCloudTransfer ? "flex" : "none";
        cloudSlowBanner.classList.toggle("hidden", !hasLargeCloudTransfer);
    }
    window.updateCloudSlowBanner = updateCloudSlowBanner;

    function renderSpeedIndicator(summaryOverride = null) {
        updateCancelAllButtonVisibility();
        updateCloudSlowBanner();
        if (!speedIndicator) return;
        let summary = summaryOverride;
        if (!summary || (summary.state === "idle" && (activeTransfersMap.size > 0 || preparingMap.size > 0))) {
            summary = computeLocalSummaryFallback();
        }
        lastActivitySummary = summary;

        const st = String(summary.state || "idle").toLowerCase();
        speedIndicator.className = `speed-pill ${st}`;

        let labelHtml = "";
        if (st === "active") {
            const spdStr = formatSpeed(summary.speed_bps || 0);
            const hasEta = summary.eta_seconds !== null && summary.eta_seconds !== undefined && Number.isFinite(Number(summary.eta_seconds));
            const etaText = hasEta
                ? I18n.t("eta_left", { eta: formatDuration(summary.eta_seconds) })
                : I18n.t("eta_calculating");
            labelHtml = `<bdi dir="ltr">${spdStr}</bdi> • <bdi dir="ltr">${etaText}</bdi>`;
        } else if (st === "waiting") {
            labelHtml = `<bdi dir="auto">${I18n.t("status_waiting_phone")}</bdi>`;
        } else if (st === "paused") {
            labelHtml = `<bdi dir="auto">${I18n.t("status_paused")}</bdi>`;
        } else if (st === "stalled") {
            labelHtml = `<bdi dir="auto">${I18n.t("status_stalled")}</bdi>`;
        } else if (st === "preparing") {
            labelHtml = `<bdi dir="auto">${I18n.t("status_preparing")}</bdi>`;
        } else {
            labelHtml = `<bdi dir="auto">${I18n.t("status_idle")}</bdi>`;
        }
        speedIndicator.innerHTML = labelHtml;

        if (activeCountSub) {
            const cnt = Number(summary.active_count || 0);
            if (cnt > 1 && st !== "idle") {
                activeCountSub.style.display = "inline-block";
                activeCountSub.textContent = I18n.t("active_count_label", { count: cnt });
            } else {
                activeCountSub.style.display = "none";
                activeCountSub.textContent = "";
            }
        }
    }

    async function fetchQrForText(textPayload) {
        if (!textPayload) return "";
        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.generate_qr) {
                return (await window.pywebview.api.generate_qr(textPayload)) || "";
            }
        } catch (e) {
            console.error("generate_qr failed:", e);
        }
        return "";
    }

    function safeThumb(src) {
        return typeof src === "string" && src.startsWith("data:image/") ? src : "";
    }

    function applyQrImageWithTransition(dataUri) {
        if (!dataUri || !qrImg) return;
        qrImg.classList.add("qr-swap");
        setTimeout(() => {
            qrImg.src = dataUri;
            qrImg.classList.remove("qr-swap");
        }, 140);
    }

    async function switchQrMode(mode) {
        if (mode === "local") {
            if (!local_url) return;
            activeQrMode = "local";
            if (qrBtnLocal) qrBtnLocal.classList.add("active");
            if (qrBtnCloud) qrBtnCloud.classList.remove("active");
            if (qrBtnHotspot) qrBtnHotspot.classList.remove("active");
            if (!qrCache.local) {
                qrCache.local = await fetchQrForText(local_url);
            }
            applyQrImageWithTransition(qrCache.local);
        } else if (mode === "cloud") {
            if (!cloud_url) return;
            activeQrMode = "cloud";
            if (qrBtnLocal) qrBtnLocal.classList.remove("active");
            if (qrBtnCloud) qrBtnCloud.classList.add("active");
            if (qrBtnHotspot) qrBtnHotspot.classList.remove("active");
            if (!qrCache.cloud) {
                qrCache.cloud = await fetchQrForText(cloud_url);
            }
            applyQrImageWithTransition(qrCache.cloud);
        } else if (mode === "hotspot") {
            if (!hotspot_url && !qrCache.hotspot_link) return;
            activeQrMode = "hotspot";
            if (qrBtnLocal) qrBtnLocal.classList.remove("active");
            if (qrBtnCloud) qrBtnCloud.classList.remove("active");
            if (qrBtnHotspot) qrBtnHotspot.classList.add("active");
            if (!qrCache.hotspot_link && hotspot_url) {
                qrCache.hotspot_link = await fetchQrForText(hotspot_url);
            }
            applyQrImageWithTransition(qrCache.hotspot_link);
        }
    }

    if (qrBtnLocal) qrBtnLocal.onclick = () => switchQrMode("local");
    if (qrBtnCloud) qrBtnCloud.onclick = () => switchQrMode("cloud");
    if (qrBtnHotspot) qrBtnHotspot.onclick = () => switchQrMode("hotspot");

    function setConnectedCount(count, devices = null, blocked = null) {
        connectedCount = count || 0;
        renderStatusBadgeFromModel();
        if (Array.isArray(devices)) {
            const activeIds = new Set(devices.map((d) => String(d.id)));
            for (const [devId, timerId] of disconnectingDevices.entries()) {
                if (!activeIds.has(devId)) {
                    clearTimeout(timerId);
                    disconnectingDevices.delete(devId);
                }
            }
            connectedDevicesModel = devices;
            renderConnectedDevices(devices);
        }
        if (Array.isArray(blocked)) {
            blockedDevicesModel = blocked;
            renderBlockedDevices(blocked);
        }
    }

    function renderConnectedDevices(devices) {
        if (!devicesListEl) return;
        devicesListEl.innerHTML = "";
        devices.forEach((dev) => {
            const devId = String(dev.id);
            const row = document.createElement("div");
            row.className = "device-row";
            row.dataset.deviceId = devId;
            const meta = document.createElement("span");
            meta.className = "device-row-meta";
            const viaTranslated = I18n.t(dev.via === "Cloud" ? "via_cloud" : "via_wifi");
            const bdi = document.createElement("bdi");
            bdi.dir = "ltr";
            bdi.textContent = `${dev.name} (${dev.ip} • ${viaTranslated})`;
            meta.appendChild(bdi);
            meta.title = `${dev.name} - ${dev.ip} (${viaTranslated})`;

            const isDisconnecting = disconnectingDevices.has(devId);
            const kickBtn = document.createElement("button");
            kickBtn.type = "button";
            kickBtn.className = "btn-danger";
            kickBtn.style.padding = "3px 8px";
            kickBtn.style.fontSize = "0.64rem";
            kickBtn.disabled = isDisconnecting;
            ByteDropFormat.setButtonLabel(kickBtn, isDisconnecting ? I18n.t("disconnecting_btn") : I18n.t("disconnect_btn"));
            kickBtn.onclick = async () => {
                if (disconnectingDevices.has(devId)) return;
                kickBtn.disabled = true;
                ByteDropFormat.setButtonLabel(kickBtn, I18n.t("disconnecting_btn"));
                const timeoutId = setTimeout(() => {
                    disconnectingDevices.delete(devId);
                    const stillConnected = connectedDevicesModel.some((d) => String(d.id) === devId);
                    if (stillConnected) {
                        renderConnectedDevices(connectedDevicesModel);
                        flashStatusMessage(I18n.t("disconnect_timeout_err"));
                    }
                }, 5000);
                disconnectingDevices.set(devId, timeoutId);

                if (window.pywebview && window.pywebview.api && window.pywebview.api.kick_device) {
                    try {
                        await window.pywebview.api.kick_device(devId);
                    } catch (e) {
                        clearTimeout(timeoutId);
                        disconnectingDevices.delete(devId);
                        kickBtn.disabled = false;
                        ByteDropFormat.setButtonLabel(kickBtn, I18n.t("disconnect_btn"));
                        flashStatusMessage(I18n.t("disconnect_timeout_err"));
                    }
                }
            };
            row.appendChild(meta);
            row.appendChild(kickBtn);
            devicesListEl.appendChild(row);
        });
    }

    function renderBlockedDevices(blocked) {
        if (!blockedSectionEl || !blockedListEl) return;
        blockedListEl.innerHTML = "";
        if (!blocked || blocked.length === 0) {
            blockedSectionEl.classList.remove("visible");
            return;
        }
        blockedSectionEl.classList.add("visible");
        blocked.forEach((b) => {
            const row = document.createElement("div");
            row.className = "device-row";
            const meta = document.createElement("span");
            meta.className = "device-row-meta";
            const bdi = document.createElement("bdi");
            bdi.dir = "ltr";
            bdi.textContent = `${b.name} (${b.ip})`;
            meta.appendChild(bdi);
            const allowBtn = document.createElement("button");
            allowBtn.className = "btn-secondary";
            allowBtn.style.padding = "2px 7px";
            allowBtn.style.fontSize = "0.64rem";
            allowBtn.textContent = I18n.t("allow_btn");
            allowBtn.onclick = async () => {
                allowBtn.disabled = true;
                if (window.pywebview && window.pywebview.api && window.pywebview.api.unblock_device) {
                    await window.pywebview.api.unblock_device(b.device_id);
                }
            };
            row.appendChild(meta);
            row.appendChild(allowBtn);
            blockedListEl.appendChild(row);
        });
    }

    function renderSharedPcFiles(files) {
        if (!sharedPcListEl) return;
        sharedPcFilesModel = Array.isArray(files) ? files : [];
        sharedPcListEl.innerHTML = "";
        if (sharedPcFilesModel.length === 0) {
            const empty = document.createElement("div");
            empty.className = "activity-item";
            empty.style.justifyContent = "center";
            empty.style.color = "var(--text-muted)";
            empty.textContent = I18n.t("no_shared_files");
            sharedPcListEl.appendChild(empty);
            return;
        }
        sharedPcFilesModel.forEach((f) => {
            const row = document.createElement("div");
            row.className = "activity-item";
            row.dataset.shareId = f.id || "";
            const left = document.createElement("div");
            left.className = "activity-item-left";
            const label = document.createElement("span");
            const isFolderPending = Boolean((f.is_folder || f.is_dir) && !f.archive_ready && (!f.size || Number(f.size) <= 0));
            const sizeStr = isFolderPending ? I18n.t("status_preparing") : formatBytes(f.size);
            label.innerHTML = `<bdi dir="auto"></bdi> (<bdi dir="ltr"></bdi>)`;
            const bdis = label.querySelectorAll("bdi");
            bdis[0].textContent = f.name;
            bdis[1].textContent = sizeStr;
            label.title = `${f.name} (${sizeStr})`;
            left.appendChild(label);

            const delBtn = document.createElement("button");
            delBtn.className = "btn-danger";
            delBtn.style.padding = "3px 8px";
            delBtn.style.fontSize = "0.64rem";
            delBtn.textContent = I18n.t("remove_btn");
            delBtn.onclick = async () => {
                if (window.pywebview && window.pywebview.api && window.pywebview.api.remove_share) {
                    await window.pywebview.api.remove_share(f.id);
                }
            };
            row.appendChild(left);
            row.appendChild(delBtn);
            sharedPcListEl.appendChild(row);
        });
    }

    /* ---------------- F3: Queued Log & size_updated Handling ---------------- */
    function formatQueuedSpanText(category, name, sizeLabel) {
        return I18n.t("log_queued", {
            category: tCategory(category),
            name: name,
            size: sizeLabel
        });
    }

    function addQueuedLogs(items) {
        if (!Array.isArray(items)) return;
        const list = document.getElementById("activity-list");
        if (!list) return;
        items.forEach((item) => {
            if (typeof item === "string") {
                addActivityRow(item);
                return;
            }
            const row = document.createElement("div");
            row.className = "activity-item";
            const left = document.createElement("div");
            left.className = "activity-item-left";
            const span = document.createElement("span");
            const isFolder = Boolean(item.is_folder || item.is_dir);
            const isReady = item.archive_ready !== false && (!isFolder || Number(item.size) > 0);
            const szLabel = (!isReady && isFolder) ? I18n.t("status_preparing") : formatBytes(item.size || 0);

            span.dataset.queued = "true";
            span.dataset.shareId = item.id || "";
            span.dataset.requestId = item.request_id || "";
            span.dataset.fileIndex = String(item.file_index ?? "");
            span.dataset.filename = item.name || "";
            span.dataset.category = item.category || "File";
            span.dataset.isFolder = isFolder ? "true" : "false";
            span.dataset.sizelabel = szLabel;
            span.textContent = formatQueuedSpanText(item.category || "File", item.name || "", szLabel);
            span.title = span.textContent;
            left.appendChild(span);
            row.appendChild(left);
            list.prepend(row);
        });
        while (list.children.length > MAX_ACTIVITY_ROWS) {
            list.lastElementChild.remove();
        }
    }
    window.addQueuedLogs = addQueuedLogs;

    function handleSizeUpdated(data) {
        if (!data) return;
        const newSizeBytes = Number(data.size || 0);
        const newSizeLabel = formatBytes(newSizeBytes);
        const shareId = String(data.share_id || data.id || "");
        const reqId = String(data.request_id || "");
        const fIndex = String(data.file_index ?? "");
        const name = String(data.name || "");

        // 1. Update activity log rows (both still-queued and already-accepted)
        const allSpans = Array.from(document.querySelectorAll("#activity-list span[data-filename]"));
        allSpans.forEach((el) => {
            const matchShare = shareId && el.dataset.shareId === shareId;
            const matchReqIdx = reqId && el.dataset.requestId === reqId && (el.dataset.fileIndex === fIndex || el.dataset.filename === name);
            if (matchShare || matchReqIdx) {
                el.dataset.sizelabel = newSizeLabel;
                const statusKind = el.dataset.statusKind || "queued";
                if (statusKind === "Accepted") {
                    el.textContent = I18n.t("log_accepted", { name: el.dataset.filename || name, size: newSizeLabel });
                } else if (statusKind === "Declined") {
                    el.textContent = I18n.t("log_declined", { name: el.dataset.filename || name, size: newSizeLabel });
                } else if (statusKind === "Expired") {
                    el.textContent = I18n.t("log_expired", { name: el.dataset.filename || name, size: newSizeLabel });
                } else {
                    el.textContent = formatQueuedSpanText(el.dataset.category || "Archives", el.dataset.filename || name, newSizeLabel);
                }
                el.title = el.textContent;
            }
        });

        // 2. Update Shared From PC model & DOM
        let sharedChanged = false;
        sharedPcFilesModel.forEach((f) => {
            if ((shareId && f.id === shareId) || (reqId && f.request_id === reqId && f.name === name)) {
                f.size = newSizeBytes;
                f.archive_ready = true;
                sharedChanged = true;
            }
        });
        if (sharedChanged) {
            renderSharedPcFiles(sharedPcFilesModel);
        }

        // 3. Remove preparing row if finished
        if (shareId && preparingMap.has(shareId)) {
            removePreparingRow(shareId);
        }
        if (reqId && preparingMap.has(reqId)) {
            removePreparingRow(reqId);
        }
    }

    function addActivityRow(text, thumbUrl = null) {
        const list = document.getElementById("activity-list");
        if (!list) return;
        const row = document.createElement("div");
        row.className = "activity-item";
        const left = document.createElement("div");
        left.className = "activity-item-left";
        const safeSrc = safeThumb(thumbUrl);
        if (safeSrc) {
            const img = document.createElement("img");
            img.src = safeSrc;
            left.appendChild(img);
        }
        const span = document.createElement("span");
        span.textContent = text;
        span.title = text;
        left.appendChild(span);
        row.appendChild(left);
        list.prepend(row);
        while (list.children.length > MAX_ACTIVITY_ROWS) {
            list.lastElementChild.remove();
        }
    }

    function formatStatusLogLine(statusKind, name, szLabel) {
        if (statusKind === "Accepted") {
            return szLabel ? I18n.t("log_accepted", { name, size: szLabel }) : I18n.t("log_accepted_nosize", { name });
        }
        if (statusKind === "Expired") {
            return szLabel ? I18n.t("log_expired", { name, size: szLabel }) : I18n.t("log_expired_nosize", { name });
        }
        return szLabel ? I18n.t("log_declined", { name, size: szLabel }) : I18n.t("log_declined_nosize", { name });
    }

    function updateQueuedStatus(requestId, files, statusKind) {
        const cls = statusKind === "Accepted" ? "log-accepted" : "log-declined";
        const pendingSpans = Array.from(document.querySelectorAll("span[data-queued='true']"));

        if (Array.isArray(files) && files.length > 0) {
            files.forEach((f, idx) => {
                const fIndex = String(f.file_index ?? idx);
                const name = (f.name || f || "").trim();
                let el = pendingSpans.find((s) =>
                    s.dataset.queued === "true" &&
                    s.dataset.requestId === String(requestId || "") &&
                    s.dataset.fileIndex === fIndex
                );
                if (!el && requestId) {
                    el = pendingSpans.find((s) =>
                        s.dataset.queued === "true" &&
                        s.dataset.requestId === String(requestId) &&
                        s.dataset.filename === name
                    );
                }
                if (el) {
                    const isFolderPending = Boolean((f.is_folder || f.is_dir) && !f.archive_ready && (!f.size || Number(f.size) <= 0));
                    const szLabel = (!isFolderPending && typeof f.size === "number" && f.size > 0)
                        ? formatBytes(f.size)
                        : (el.dataset.sizelabel || "");
                    el.dataset.sizelabel = szLabel;
                    el.dataset.statusKind = statusKind;
                    el.textContent = formatStatusLogLine(statusKind, name, szLabel);
                    el.title = el.textContent;
                    el.classList.remove("log-accepted", "log-declined");
                    el.classList.add(cls);
                    delete el.dataset.queued;
                }
            });
        } else if (requestId) {
            pendingSpans
                .filter((s) => s.dataset.requestId === String(requestId))
                .forEach((el) => {
                    const name = el.dataset.filename || "";
                    const szLabel = el.dataset.sizelabel || "";
                    el.dataset.statusKind = statusKind;
                    el.textContent = formatStatusLogLine(statusKind, name, szLabel);
                    el.title = el.textContent;
                    el.classList.remove("log-accepted", "log-declined");
                    el.classList.add(cls);
                    delete el.dataset.queued;
                });
        }
    }

    /* ---------------- F2 & Section 2.3: Idempotent Per-File & Preparing Rows ---------------- */
    function normalizeTransferDto(raw) {
        const fileObj = raw.file || {};
        const rawState = String(raw.state || "active").toLowerCase();
        const direction = String(raw.direction || "");
        let normState = direction === "pc_to_phone" ? "Downloading" : "Uploading";
        if (rawState === "done" || rawState === "completed") normState = "Completed";
        else if (rawState === "paused") normState = "Paused";
        else if (rawState === "interrupted") normState = "Interrupted";
        else if (rawState === "cancelled") normState = "Cancelled";
        else if (rawState === "rejected") normState = "Rejected";
        else if (rawState === "expired" || rawState === "failed") normState = "Cancelled";
        else if (rawState === "pending" || rawState === "accepted" || rawState === "waiting") normState = "Waiting";

        const sizeNum = Number(raw.size ?? raw.total ?? fileObj.size ?? 0);
        const offsetNum = Number(raw.bytes_done ?? raw.offset ?? raw.received ?? 0);
        if ((rawState === "active" || rawState === "uploading" || rawState === "downloading") && offsetNum === 0 && Number(raw.speed ?? raw.speed_bps ?? 0) === 0 && direction === "pc_to_phone") {
            normState = "Waiting";
        }
        const computedPct = sizeNum > 0 ? Math.min(100, Math.floor((offsetNum / sizeNum) * 100)) : (normState === "Completed" ? 100 : 0);

        const interruptedAt = raw.interrupted_at !== undefined && raw.interrupted_at !== null ? Number(raw.interrupted_at) : null;
        let interruptedRemSec = raw.interrupted_remaining_sec !== undefined ? Number(raw.interrupted_remaining_sec) : null;
        if (normState === "Interrupted" && interruptedRemSec === null) {
            const elapsedInt = interruptedAt ? Math.max(0, (Date.now() / 1000) - interruptedAt) : 0;
            interruptedRemSec = Math.max(0, Math.round(600 - elapsedInt));
        }

        return {
            id: raw.transfer_id || raw.id || fileObj.name || raw.name || "tx",
            request_id: raw.request_id || "",
            name: raw.name || raw.filename || fileObj.name || "file",
            size: sizeNum,
            offset: offsetNum,
            bytes_done: offsetNum,
            resumed_offset: Number(raw.resumed_offset ?? 0),
            progress: raw.progress !== undefined ? Number(raw.progress) : computedPct,
            state: normState,
            direction: direction,
            via: raw.via || "Wi-Fi",
            cancelled_by: raw.cancelled_by || "",
            interrupted_at: interruptedAt,
            interrupted_remaining_sec: interruptedRemSec,
            speed_bps: Number(raw.speed ?? raw.speed_bps ?? 0),
            avg_speed_bps: Number(raw.avg_speed ?? raw.avg_speed_bps ?? 0),
            eta_seconds: raw.eta !== undefined ? raw.eta : raw.eta_seconds,
            duration_sec: raw.elapsed !== undefined ? raw.elapsed : raw.duration_sec,
            stalled: Boolean(raw.stalled) && offsetNum > 0,
            waiting_for_phone: Boolean(raw.waiting_for_phone) && offsetNum > 0,
            connection_lost: Boolean(raw.connection_lost) && offsetNum > 0,
            batch_index: Number(raw.batch_index || 1),
            batch_size: Number(raw.batch_size || 1),
            saved_as: raw.saved_as || fileObj.name,
            category: raw.category || fileObj.category || "Others",
            thumbnail: raw.thumbnail || fileObj.thumbnail
        };
    }

    function ensureInterruptedCountdownTimer() {
        if (interruptedCountdownTimer) return;
        interruptedCountdownTimer = setInterval(() => {
            let hasInterrupted = false;
            activeTransfersMap.forEach((tr) => {
                if (tr.state === "Interrupted") {
                    hasInterrupted = true;
                    updatePerFileTransferRow(tr);
                }
            });
            if (!hasInterrupted) {
                clearInterval(interruptedCountdownTimer);
                interruptedCountdownTimer = null;
            }
        }, 1000);
    }

    function ensureRowElement(rowId, isWaiting = false) {
        let row = document.getElementById(rowId);
        if (!row) {
            row = document.createElement("div");
            row.id = rowId;
            row.className = "transfer-row-item" + (isWaiting ? " waiting-row" : "");
            row.innerHTML = `
                <div class="transfer-row-top">
                    <div class="transfer-row-left">
                        <span class="cat-tag"></span>
                        <span class="via-tag" style="display:none;"></span>
                        <span class="pos-tag" style="display:none;" dir="ltr"></span>
                        <span class="transfer-row-text"><bdi dir="auto"></bdi></span>
                    </div>
                    <span class="transfer-row-detail"><bdi dir="ltr"></bdi></span>
                    <div class="transfer-row-actions">
                        <button type="button" class="btn-secondary tx-pause-btn" style="padding:2px 7px; font-size:0.62rem;"></button>
                        <button type="button" class="btn-danger tx-cancel-btn" style="padding:2px 7px; font-size:0.62rem;"></button>
                    </div>
                </div>
                <div class="progress-track"><div class="progress-fill"></div></div>
            `;
            if (isWaiting) {
                activeTransfersBox.appendChild(row);
            } else {
                const firstWaiting = activeTransfersBox.querySelector(".waiting-row");
                if (firstWaiting) {
                    activeTransfersBox.insertBefore(row, firstWaiting);
                } else {
                    activeTransfersBox.prepend(row);
                }
            }
        } else {
            const wasWaiting = row.classList.contains("waiting-row");
            row.classList.toggle("waiting-row", isWaiting);
            if (wasWaiting && !isWaiting) {
                const firstWaiting = activeTransfersBox.querySelector(".waiting-row");
                if (firstWaiting && firstWaiting !== row) {
                    activeTransfersBox.insertBefore(row, firstWaiting);
                }
            }
        }
        return row;
    }

    function updatePreparingArchiveRow(data) {
        if (!activeTransfersBox || !data) return;
        const key = String(data.share_id || data.id || data.request_id || data.name || "prep");
        const name = String(data.filename || data.name || "Folder.zip");
        const pct = Math.max(0, Math.min(100, Number(data.progress ?? 0)));
        const reqId = String(data.request_id || key);

        preparingMap.set(key, { id: key, request_id: reqId, name, progress: pct });

        const rowId = getSafeRowId("prep", key);
        const row = ensureRowElement(rowId, false);
        const catEl = row.querySelector(".cat-tag");
        const viaEl = row.querySelector(".via-tag");
        const posEl = row.querySelector(".pos-tag");
        const nameBdi = row.querySelector(".transfer-row-text bdi");
        const textSpan = row.querySelector(".transfer-row-text");
        const detailBdi = row.querySelector(".transfer-row-detail bdi");
        const fillEl = row.querySelector(".progress-fill");
        const pauseBtn = row.querySelector(".tx-pause-btn");
        const cancelBtn = row.querySelector(".tx-cancel-btn");

        if (catEl) catEl.textContent = tCategory("Archives");
        if (viaEl) viaEl.style.display = "none";
        if (posEl) posEl.style.display = "none";
        const label = I18n.t("preparing_archive_row", { name, progress: pct });
        if (nameBdi) nameBdi.textContent = label;
        if (textSpan) textSpan.title = label;
        if (detailBdi) detailBdi.textContent = `${pct}%`;
        if (fillEl) fillEl.style.width = `${pct}%`;

        if (pauseBtn) pauseBtn.style.display = "none";
        if (cancelBtn) {
            cancelBtn.style.display = "inline-block";
            cancelBtn.textContent = I18n.t("cancel_btn");
            cancelBtn.onclick = async () => {
                if (window.pywebview && window.pywebview.api && window.pywebview.api.cancel_prepare && reqId) {
                    await window.pywebview.api.cancel_prepare(reqId);
                }
                removePreparingRow(key);
            };
        }

        if (pct >= 100) {
            setTimeout(() => removePreparingRow(key), 600);
        }
        renderSpeedIndicator();
    }

    function removePreparingRow(key) {
        if (!key) return;
        const keysToRemove = [String(key)];
        for (const [k, v] of preparingMap.entries()) {
            if (v && (v.id === key || v.request_id === key || v.share_id === key)) {
                if (!keysToRemove.includes(k)) keysToRemove.push(k);
            }
        }
        keysToRemove.forEach((k) => {
            preparingMap.delete(k);
            const rowId = getSafeRowId("prep", k);
            const row = document.getElementById(rowId);
            if (row) row.remove();
        });
        renderSpeedIndicator();
    }

    function scheduleTransferRowExit(rowId, delayMs = 3000) {
        if (rowRemovalTimers.has(rowId)) {
            clearTimeout(rowRemovalTimers.get(rowId));
        }
        const timer = setTimeout(() => {
            rowRemovalTimers.delete(rowId);
            const r = document.getElementById(rowId);
            if (r) {
                r.classList.add("row-exiting");
                setTimeout(() => {
                    if (r.parentNode) r.remove();
                }, 240);
            }
        }, delayMs);
        rowRemovalTimers.set(rowId, timer);
    }

    function updatePerFileTransferRow(raw) {
        if (!activeTransfersBox || !raw) return;
        const existingData = activeTransfersMap.get(String(raw.transfer_id || raw.id || ""));
        const mergedRaw = existingData ? Object.assign({}, existingData, raw) : raw;
        const data = normalizeTransferDto(mergedRaw);
        const tid = String(data.id);
        const rowId = getSafeRowId("tx", tid);

        if (data.state === "Cancelled" || data.state === "Rejected") {
            activeTransfersMap.delete(tid);
            const existingRow = document.getElementById(rowId);
            if (existingRow) {
                existingRow.classList.remove("waiting-row");
                const detailBdi = existingRow.querySelector(".transfer-row-detail bdi");
                const actions = existingRow.querySelector(".transfer-row-actions");
                if (actions) actions.style.display = "none";
                if (detailBdi) {
                    if (data.state === "Rejected") {
                        detailBdi.textContent = I18n.t("status_rejected");
                    } else if (data.cancelled_by === "phone") {
                        detailBdi.textContent = I18n.t("status_cancelled_phone");
                    } else {
                        detailBdi.textContent = I18n.t("status_cancelled");
                    }
                }
                scheduleTransferRowExit(rowId, 3000);
            }
            renderSpeedIndicator();
            return;
        }

        activeTransfersMap.set(tid, data);
        updateCloudSlowBanner();
        if (rowRemovalTimers.has(rowId) && data.state !== "Completed") {
            clearTimeout(rowRemovalTimers.get(rowId));
            rowRemovalTimers.delete(rowId);
        }

        const isWaitingRow = data.state === "Waiting";
        const row = ensureRowElement(rowId, isWaitingRow);
        row.classList.remove("row-exiting");

        const catEl = row.querySelector(".cat-tag");
        const viaEl = row.querySelector(".via-tag");
        const posEl = row.querySelector(".pos-tag");
        const nameBdi = row.querySelector(".transfer-row-text bdi");
        const textSpan = row.querySelector(".transfer-row-text");
        const detailBdi = row.querySelector(".transfer-row-detail bdi");
        const fillEl = row.querySelector(".progress-fill");
        const pauseBtn = row.querySelector(".tx-pause-btn");
        const cancelBtn = row.querySelector(".tx-cancel-btn");
        const actions = row.querySelector(".transfer-row-actions");

        if (catEl) {
            catEl.textContent = tCategory(data.category);
            catEl.style.display = "inline-block";
        }

        if (viaEl) {
            viaEl.textContent = I18n.t(data.via === "Cloud" ? "via_cloud" : "via_wifi");
            viaEl.style.display = "inline-block";
        }

        if (posEl) {
            if (data.batch_size > 1) {
                posEl.textContent = I18n.t("batch_pos_tag", { index: data.batch_index, total: data.batch_size });
                posEl.style.display = "inline-block";
            } else {
                posEl.style.display = "none";
            }
        }

        if (nameBdi) nameBdi.textContent = data.name;
        const detailText = formatTransferRowDetail(data, I18n.t);
        if (detailBdi) detailBdi.textContent = detailText;
        if (textSpan) textSpan.title = `${data.name} • ${detailText}`;

        const pct = data.state === "Completed" ? 100 : (data.progress !== undefined ? data.progress : 0);
        if (fillEl) fillEl.style.width = `${pct}%`;

        if (data.state === "Interrupted") {
            ensureInterruptedCountdownTimer();
        }

        if (tid && data.state !== "Completed") {
            if (actions) actions.style.display = "flex";
            const isPaused = data.state === "Paused";
            const isWaitingOrInterrupted = data.state === "Waiting" || data.state === "Interrupted";
            const tooltipText = data.direction === "pc_to_phone" ? I18n.t("browser_download_tooltip") : "";
            if (pauseBtn) {
                if (isWaitingOrInterrupted) {
                    pauseBtn.style.display = "none";
                } else {
                    pauseBtn.style.display = "inline-block";
                    ByteDropFormat.setButtonLabel(pauseBtn, isPaused ? I18n.t("resume_btn") : I18n.t("pause_btn"));
                    pauseBtn.title = tooltipText;
                    pauseBtn.onclick = async () => {
                        if (!window.pywebview || !window.pywebview.api) return;
                        const updated = isPaused
                            ? await window.pywebview.api.resume_transfer(tid)
                            : await window.pywebview.api.pause_transfer(tid);
                        if (updated) updatePerFileTransferRow(updated);
                    };
                }
            }
            if (cancelBtn) {
                cancelBtn.style.display = "inline-block";
                cancelBtn.textContent = I18n.t("cancel_btn");
                cancelBtn.title = tooltipText;
                cancelBtn.onclick = async () => {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.cancel_transfer) {
                        await window.pywebview.api.cancel_transfer(tid);
                    }
                    updatePerFileTransferRow(Object.assign({}, data, { state: "cancelled", cancelled_by: "pc" }));
                };
            }
        } else if (actions) {
            actions.style.display = "none";
        }

        if (data.state === "Completed" || pct >= 100) {
            activeTransfersMap.delete(tid);
            scheduleTransferRowExit(rowId, 3200);
        }

        updateCloudSlowBanner();
        renderSpeedIndicator();
    }

    function renderAllActiveTransferRows() {
        activeTransfersMap.forEach((tr) => updatePerFileTransferRow(tr));
        preparingMap.forEach((p) => updatePreparingArchiveRow(p));
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
        if (window.pywebview && window.pywebview.api && window.pywebview.api.cancel_all_transfers) {
            try {
                await window.pywebview.api.cancel_all_transfers();
            } catch (e) {
                console.error("cancel_all_transfers failed:", e);
            }
        }
        const ids = Array.from(activeTransfersMap.keys());
        ids.forEach((tid) => {
            const tr = activeTransfersMap.get(tid);
            if (tr) {
                updatePerFileTransferRow(Object.assign({}, tr, { state: "cancelled", cancelled_by: "pc" }));
            }
        });
        const prepKeys = Array.from(preparingMap.keys());
        prepKeys.forEach((k) => removePreparingRow(k));
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

    /* ---------------- F7 & G1: Translated Tunnel & Passive Hotspot States ---------------- */
    function updateTunnelStatus(status) {
        if (!status) return;
        lastTunnelStatus = status;
        const box = document.getElementById("public-url-box");
        const state = status.state || "Disabled";
        const reason = status.reason || "";

        if (cloudStatePill) {
            if (state === "Downloading" && typeof status.download_progress === "number") {
                cloudStatePill.textContent = I18n.t("tunnel_downloading", { progress: status.download_progress });
            } else if (state === "Failed") {
                cloudStatePill.textContent = I18n.t("tunnel_failed", { reason: reason || I18n.t("tunnel_unavailable") });
            } else if (state === "Starting") {
                cloudStatePill.textContent = I18n.t("tunnel_starting");
            } else if (state === "Reconnecting") {
                cloudStatePill.textContent = I18n.t("tunnel_reconnecting");
            } else if (state === "Online") {
                cloudStatePill.textContent = I18n.t("tunnel_online");
            } else {
                cloudStatePill.textContent = I18n.t("tunnel_disabled");
            }
        }

        if (state === "Online" && status.public_url) {
            cloud_url = status.public_url;
            if (box) box.textContent = cloud_url;
            qrCache.cloud = status.cloud_qr || "";
            if (qrBtnCloud) qrBtnCloud.disabled = false;
            if (activeQrMode === "cloud" && qrCache.cloud) {
                applyQrImageWithTransition(qrCache.cloud);
            }
        } else {
            cloud_url = "";
            qrCache.cloud = "";
            if (qrBtnCloud) qrBtnCloud.disabled = true;
            if (box) {
                if (state === "Downloading") {
                    box.textContent = I18n.t("tunnel_downloading_box");
                } else if (state === "Starting") {
                    box.textContent = I18n.t("tunnel_starting_box");
                } else if (state === "Reconnecting") {
                    box.textContent = I18n.t("tunnel_reconnecting_box");
                } else if (state === "Failed") {
                    box.textContent = I18n.t("tunnel_failed", { reason: reason || I18n.t("tunnel_unavailable") });
                } else {
                    box.textContent = I18n.t("tunnel_disabled_box");
                }
            }
            if (activeQrMode === "cloud") {
                switchQrMode("local");
            }
        }
    }

    function renderHotspotLabels(res) {
        const lbl = document.getElementById("hotspot-label");
        if (!lbl) return;
        const detected = Boolean(res && (res.detected || res.active));
        if (detected) {
            lbl.textContent = I18n.t("hotspot_detected");
        } else {
            lbl.textContent = I18n.t("hotspot_help");
        }
    }

    async function updateHotspotState(res) {
        lastHotspotStatus = res || { detected: false, active: false };
        renderHotspotLabels(lastHotspotStatus);
        const detected = Boolean(res && (res.detected || res.active));
        if (detected) {
            hotspot_url = res.hotspot_url || res.url || "";
            qrCache.hotspot_link = res.link_qr || res.hotspot_qr || res.qr || await fetchQrForText(hotspot_url) || "";
            if (qrBtnHotspot) qrBtnHotspot.disabled = false;
            if (activeQrMode === "hotspot" && qrCache.hotspot_link) {
                applyQrImageWithTransition(qrCache.hotspot_link);
            }
        } else {
            hotspot_url = "";
            qrCache.hotspot_link = "";
            if (qrBtnHotspot) qrBtnHotspot.disabled = true;
            if (activeQrMode === "hotspot") {
                await switchQrMode("local");
            }
        }
    }

    async function copyToClipboardWithSync(text, btnElement, triggerSync = false, restoreKey = "copy_btn") {
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
        } catch (err) {
            const temp = document.createElement("textarea");
            temp.value = text;
            document.body.appendChild(temp);
            temp.select();
            document.execCommand("copy");
            temp.remove();
        }
        if (triggerSync && window.pywebview && window.pywebview.api) {
            window.pywebview.api.send_text(text);
        }
        if (btnElement) {
            ByteDropFormat.setButtonLabel(btnElement, I18n.t("copied_btn"));
            setTimeout(() => {
                ByteDropFormat.setButtonLabel(btnElement, I18n.t(restoreKey));
            }, 1400);
        }
    }

    /* ---------------- Section 3.1 Incoming Prompt Rendering ---------------- */
    function renderCurrentPromptItems() {
        if (!currentRequest) return;
        const files = currentRequest.files || [];
        const senderName = currentRequest.device_name || "Phone";
        const summary = formatPromptSummary(files, senderName, I18n.t);

        if (permDesc) permDesc.textContent = summary.headerText;
        if (!permFileList || !permExpandBtn) return;
        permFileList.innerHTML = "";

        if (summary.isSingle) {
            permFileList.style.display = "none";
            permExpandBtn.style.display = "none";
        } else {
            permFileList.style.display = "flex";
            const itemsToShow = promptExpanded
                ? summary.visibleItems.concat(summary.hiddenItems)
                : summary.visibleItems;
            itemsToShow.forEach((line) => {
                const div = document.createElement("div");
                const bdi = document.createElement("bdi");
                bdi.dir = "ltr";
                bdi.textContent = `• ${line}`;
                div.appendChild(bdi);
                permFileList.appendChild(div);
            });
            if (summary.moreCount > 0) {
                permExpandBtn.style.display = "inline-block";
                permExpandBtn.textContent = promptExpanded
                    ? I18n.t("show_less_btn")
                    : I18n.t("show_more_btn", { count: summary.moreCount });
            } else {
                permExpandBtn.style.display = "none";
            }
        }
    }

    function processNextRequest() {
        if (isProcessingRequest || requestQueue.length === 0) return;
        isProcessingRequest = true;
        currentRequest = requestQueue.shift();
        promptExpanded = false;

        renderCurrentPromptItems();

        const dw = currentRequest.disk_check || currentRequest.disk_warning;
        if (dw && dw.warning) {
            permDiskWarn.textContent = dw.warning;
            permDiskWarn.classList.add("visible");
            acceptBtn.textContent = dw.check_failed ? I18n.t("accept_btn") : I18n.t("accept_anyway_btn");
        } else {
            permDiskWarn.textContent = "";
            permDiskWarn.classList.remove("visible");
            acceptBtn.textContent = I18n.t("accept_btn");
        }

        permThumbs.innerHTML = "";
        (currentRequest.files || []).forEach((f) => {
            const safeSrc = safeThumb(f.thumbnail);
            if (safeSrc) {
                const img = document.createElement("img");
                img.src = safeSrc;
                permThumbs.appendChild(img);
            }
        });
        permModal.classList.add("active");
    }

    if (permExpandBtn) {
        permExpandBtn.onclick = () => {
            promptExpanded = !promptExpanded;
            renderCurrentPromptItems();
        };
    }

    window.addEventListener("dragenter", (e) => {
        e.preventDefault();
        dragDepth++;
        if (dropCard) dropCard.classList.add("drag-active");
    });

    window.addEventListener("dragover", (e) => {
        e.preventDefault();
    });

    window.addEventListener("dragleave", (e) => {
        e.preventDefault();
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0 && dropCard) {
            dropCard.classList.remove("drag-active");
        }
    });

    window.addEventListener("drop", (e) => {
        e.preventDefault();
        dragDepth = 0;
        if (dropCard) dropCard.classList.remove("drag-active");
    });

    if (copyLocalBtn) {
        copyLocalBtn.onclick = () => {
            copyToClipboardWithSync(document.getElementById("url-box").textContent, copyLocalBtn, false, "copy_btn");
        };
    }

    if (copyPublicBtn) {
        copyPublicBtn.onclick = () => {
            const text = document.getElementById("public-url-box").textContent;
            if (text && text.startsWith("http")) {
                copyToClipboardWithSync(text, copyPublicBtn, false, "copy_btn");
            }
        };
    }

    if (clipToggleBtn) {
        clipToggleBtn.onclick = async () => {
            clipboardAutoSync = !clipboardAutoSync;
            ByteDropFormat.setButtonLabel(clipToggleBtn, clipboardAutoSync ? I18n.t("clip_auto_on") : I18n.t("clip_auto_off"));
            clipToggleBtn.classList.toggle("active", clipboardAutoSync);
            if (window.pywebview && window.pywebview.api) {
                await window.pywebview.api.set_clipboard_sync(clipboardAutoSync);
            }
        };
    }

    if (copyBtn) {
        copyBtn.onclick = () => {
            copyToClipboardWithSync(syncTextarea.value, copyBtn, true, "clip_send_btn");
        };
    }

    if (acceptBtn) {
        acceptBtn.onclick = () => {
            if (currentRequest && window.pywebview && window.pywebview.api) {
                window.pywebview.api.respond_transfer(currentRequest.request_id, true);
            }
            permModal.classList.remove("active");
            currentRequest = null;
            isProcessingRequest = false;
            processNextRequest();
        };
    }

    if (rejectBtn) {
        rejectBtn.onclick = () => {
            if (currentRequest && window.pywebview && window.pywebview.api) {
                window.pywebview.api.respond_transfer(currentRequest.request_id, false);
            }
            permModal.classList.remove("active");
            currentRequest = null;
            isProcessingRequest = false;
            processNextRequest();
        };
    }

    if (clearHistoryBtn) clearHistoryBtn.onclick = () => confirmClearModal.classList.add("active");
    if (cancelClearBtn) cancelClearBtn.onclick = () => confirmClearModal.classList.remove("active");
    if (confirmClearBtn) {
        confirmClearBtn.onclick = async () => {
            confirmClearModal.classList.remove("active");
            if (window.pywebview && window.pywebview.api && window.pywebview.api.clear_history) {
                await window.pywebview.api.clear_history();
                document.getElementById("activity-list").innerHTML = "";
            }
        };
    }

    function populateCandidateIps(candidates, preferredIp) {
        candidateIpsModel = Array.isArray(candidates) ? candidates : [];
        preferredIpModel = preferredIp || "";
        if (!preferredIpSelect) return;
        preferredIpSelect.innerHTML = "";
        const defaultOpt = document.createElement("option");
        defaultOpt.value = "";
        defaultOpt.textContent = I18n.t("auto_detect_opt");
        preferredIpSelect.appendChild(defaultOpt);

        candidateIpsModel.forEach((c) => {
            const ipVal = typeof c === "string" ? c : c.ip;
            const ifaceVal = typeof c === "string" ? "LAN" : (c.iface || "LAN");
            const opt = document.createElement("option");
            opt.value = ipVal;
            opt.textContent = `${ipVal} (${ifaceVal})`;
            if (ipVal === preferredIpModel) opt.selected = true;
            preferredIpSelect.appendChild(opt);
        });
    }

    function updateSyncedText(content) {
        if (syncTextarea && syncTextarea.value !== content) {
            syncTextarea.value = content;
        }
    }
    window.updateSyncedText = updateSyncedText;

    function applySnapshotState(state) {
        if (!state) return;
        const cfg = state.settings || state;
        if (cfg.theme) applyTheme(cfg.theme, false);
        if (cfg.accent) applyAccent(cfg.accent, false);
        if (cfg.language) applyLanguage(cfg.language, false);
        if ((cfg.corrupt_config_recovered || state.corrupt_config_recovered) && !corruptToastShown) {
            corruptToastShown = true;
            flashStatusMessage(I18n.t("corrupt_config_reset"));
            addActivityRow(I18n.t("corrupt_config_reset"));
        }

        if (state.local_url) {
            local_url = state.local_url;
            const urlBox = document.getElementById("url-box");
            if (urlBox) urlBox.textContent = local_url;
        }
        if (state.local_qr && qrImg) {
            qrCache.local = state.local_qr;
            if (activeQrMode === "local") qrImg.src = qrCache.local;
        }
        if (typeof state.connected_count === "number") {
            setConnectedCount(state.connected_count, state.devices || [], state.blocked_devices || []);
        }
        if (state.tunnel) {
            updateTunnelStatus(state.tunnel);
        }
        if (state.hotspot) {
            updateHotspotState(state.hotspot);
        }
        if (cfg.upload_dir || cfg.download_dir) {
            const d = cfg.upload_dir || cfg.download_dir;
            if (settingsDirLabel) {
                settingsDirLabel.textContent = d;
                settingsDirLabel.title = d;
            }
        }
        if (state.candidate_ips) {
            populateCandidateIps(state.candidate_ips, cfg.preferred_ip || "");
        }
        if (typeof cfg.cloud_auto_start === "boolean") {
            cloudAutoStart = cfg.cloud_auto_start;
        }
        if (typeof cfg.clipboard_sync_enabled === "boolean") {
            clipboardAutoSync = cfg.clipboard_sync_enabled;
        }
        if (typeof cfg.auto_accept_local === "boolean") {
            autoAcceptLocal = cfg.auto_accept_local;
        }
        if (typeof cfg.max_folder_gb === "number" && maxFolderGbInput) {
            maxFolderGbInput.value = String(cfg.max_folder_gb);
        }
        if (typeof cfg.tray_mode_enabled === "boolean") {
            trayModeEnabled = cfg.tray_mode_enabled;
        }
        if (typeof cfg.start_minimized === "boolean") {
            startMinimized = cfg.start_minimized;
        }
        if (typeof cfg.autostart_windows === "boolean") {
            startWithWindows = cfg.autostart_windows;
        }
        if (typeof cfg.notifications_enabled === "boolean") {
            notificationsEnabled = cfg.notifications_enabled;
        }
        renderDynamicStaticButtons();

        if (Array.isArray(state.shares)) {
            renderSharedPcFiles(state.shares);
        }
        if (Array.isArray(state.transfers)) {
            const seenIds = new Set();
            state.transfers.forEach((tr) => {
                const tid = tr.id || tr.transfer_id;
                const st = String(tr.state || "").toLowerCase();
                if (st === "active" || st === "paused" || st === "interrupted" || st === "accepted" || st === "pending" || st === "waiting") {
                    if (tid) seenIds.add(tid);
                    updatePerFileTransferRow(tr);
                } else if (tid) {
                    activeTransfersModel.delete(tid);
                }
            });
            for (const existingId of Array.from(activeTransfersModel.keys())) {
                if (!seenIds.has(existingId)) {
                    activeTransfersModel.delete(existingId);
                    const row = document.getElementById(getTransferRowId(existingId));
                    if (row) row.remove();
                }
            }
            updateCloudSlowBanner();
        }
        if (Array.isArray(state.preparing_items)) {
            state.preparing_items.forEach((prep) => updatePreparingArchiveRow(prep));
        }
        if (state.activity_summary) {
            renderSpeedIndicator(state.activity_summary);
        } else {
            renderSpeedIndicator();
        }
        if (Array.isArray(state.history)) {
            const list = document.getElementById("activity-list");
            if (list) {
                list.innerHTML = "";
                state.history.slice().reverse().forEach((r) => {
                    const dirLabel = I18n.t(`dir_${r.direction || "INCOMING"}`);
                    addActivityRow(I18n.t("log_history_item", {
                        category: tCategory(r.category),
                        direction: dirLabel,
                        name: r.filename,
                        size: formatBytes(r.size || 0),
                        timestamp: r.timestamp
                    }));
                });
            }
        }
    }

    function bindPywebviewButtons() {
        if (isPywebviewBound) return;
        if (!window.pywebview || !window.pywebview.api) return;
        isPywebviewBound = true;

        const browseBtn = document.getElementById("browse-btn");
        if (browseBtn) {
            browseBtn.onclick = async () => {
                if (connectedCount === 0) {
                    flashStatusMessage(I18n.t("connect_first_warn"));
                    return;
                }
                await window.pywebview.api.browse_files();
            };
        }

        const browseFolderBtn = document.getElementById("browse-folder-btn");
        if (browseFolderBtn) {
            browseFolderBtn.onclick = async () => {
                if (connectedCount === 0) {
                    flashStatusMessage(I18n.t("connect_first_warn"));
                    return;
                }
                await window.pywebview.api.browse_folders();
            };
        }

        const dlBtn = document.getElementById("downloads-btn");
        if (dlBtn) {
            dlBtn.onclick = () => {
                window.pywebview.api.open_downloads();
            };
        }

        if (openHotspotSettingsBtn) {
            openHotspotSettingsBtn.onclick = async () => {
                if (window.pywebview.api.open_hotspot_settings) {
                    await window.pywebview.api.open_hotspot_settings();
                }
            };
        }

        if (changeDirBtn) {
            changeDirBtn.onclick = async () => {
                if (window.pywebview.api.choose_download_dir) {
                    const res = await window.pywebview.api.choose_download_dir();
                    if (res && res.path && settingsDirLabel) {
                        settingsDirLabel.textContent = res.path;
                        settingsDirLabel.title = res.path;
                    }
                }
            };
        }

        if (preferredIpSelect) {
            preferredIpSelect.onchange = async () => {
                preferredIpModel = preferredIpSelect.value;
                if (window.pywebview.api.set_preferred_ip) {
                    const res = await window.pywebview.api.set_preferred_ip(preferredIpSelect.value);
                    if (res && res.local_url) {
                        local_url = res.local_url;
                        document.getElementById("url-box").textContent = local_url;
                        qrCache.local = res.qr_data_uri || await fetchQrForText(local_url);
                        if (activeQrMode === "local") applyQrImageWithTransition(qrCache.local);
                    }
                }
            };
        }

        if (cloudAutoToggle) {
            cloudAutoToggle.onclick = async () => {
                cloudAutoStart = !cloudAutoStart;
                renderToggleButton(cloudAutoToggle, cloudAutoStart, I18n.t("toggle_on"), I18n.t("toggle_off"));
                if (window.pywebview.api.set_cloud_auto_start) {
                    const st = await window.pywebview.api.set_cloud_auto_start(cloudAutoStart);
                    updateTunnelStatus(st);
                }
            };
        }

        if (cloudRestartBtn) {
            cloudRestartBtn.onclick = async () => {
                if (window.pywebview.api.restart_cloud_link) {
                    const st = await window.pywebview.api.restart_cloud_link();
                    updateTunnelStatus(st);
                }
            };
        }

        if (autoAcceptToggle) {
            autoAcceptToggle.onclick = async () => {
                autoAcceptLocal = !autoAcceptLocal;
                renderToggleButton(autoAcceptToggle, autoAcceptLocal, I18n.t("toggle_on"), I18n.t("toggle_off"));
                if (window.pywebview.api.update_settings) {
                    await window.pywebview.api.update_settings({ auto_accept_local: autoAcceptLocal });
                }
            };
        }

        if (maxFolderGbInput) {
            maxFolderGbInput.onchange = async () => {
                const val = Math.max(1, Math.min(100, Number(maxFolderGbInput.value) || 20));
                maxFolderGbInput.value = String(val);
                if (window.pywebview.api.update_settings) {
                    await window.pywebview.api.update_settings({ max_folder_gb: val });
                }
            };
        }

        if (trayModeToggle) {
            trayModeToggle.onclick = async () => {
                trayModeEnabled = !trayModeEnabled;
                renderToggleButton(trayModeToggle, trayModeEnabled, I18n.t("tray_on"), I18n.t("tray_off"));
                if (window.pywebview.api.update_settings) {
                    await window.pywebview.api.update_settings({ tray_mode_enabled: trayModeEnabled });
                }
            };
        }

        if (startMinToggle) {
            startMinToggle.onclick = async () => {
                startMinimized = !startMinimized;
                renderToggleButton(startMinToggle, startMinimized, I18n.t("min_on"), I18n.t("min_off"));
                if (window.pywebview.api.update_settings) {
                    await window.pywebview.api.update_settings({ start_minimized: startMinimized });
                }
            };
        }

        if (autostartToggle) {
            autostartToggle.onclick = async () => {
                startWithWindows = !startWithWindows;
                renderToggleButton(autostartToggle, startWithWindows, I18n.t("win_on"), I18n.t("win_off"));
                if (window.pywebview.api.update_settings) {
                    await window.pywebview.api.update_settings({ autostart_windows: startWithWindows });
                }
            };
        }

        if (muteNotifToggle) {
            muteNotifToggle.onclick = async () => {
                notificationsEnabled = !notificationsEnabled;
                renderToggleButton(muteNotifToggle, notificationsEnabled, I18n.t("alerts_on"), I18n.t("alerts_muted"));
                if (window.pywebview.api.update_settings) {
                    await window.pywebview.api.update_settings({ notifications_enabled: notificationsEnabled });
                }
            };
        }

        if (regenSessionBtn) {
            regenSessionBtn.onclick = async () => {
                if (window.pywebview.api.regenerate_session) {
                    const res = await window.pywebview.api.regenerate_session();
                    if (res && res.local_url) {
                        local_url = res.local_url;
                        document.getElementById("url-box").textContent = local_url;
                        qrCache.local = res.local_qr || "";
                        if (activeQrMode === "local") applyQrImageWithTransition(qrCache.local);
                        if (res.tunnel) updateTunnelStatus(res.tunnel);
                        if (res.hotspot) updateHotspotState(res.hotspot);
                        addActivityRow(I18n.t("log_session_regenerated"));
                    }
                }
            };
        }

        if (openLogsBtn) {
            openLogsBtn.onclick = async () => {
                if (window.pywebview.api.open_log_folder) {
                    await window.pywebview.api.open_log_folder();
                }
            };
        }

        if (copyDiagBtn) {
            copyDiagBtn.onclick = async () => {
                if (window.pywebview.api.get_diagnostics) {
                    const res = await window.pywebview.api.get_diagnostics();
                    const text = (res && typeof res === "object") ? res.diagnostics : String(res || "");
                    if (text) {
                        await copyToClipboardWithSync(text, copyDiagBtn, false, "copy_diag_btn");
                    }
                }
            };
        }

        if (syncTextarea) {
            syncTextarea.oninput = () => {
                clearTimeout(syncDebounceTimer);
                syncDebounceTimer = setTimeout(() => {
                    if (window.pywebview && window.pywebview.api) {
                        window.pywebview.api.send_text(syncTextarea.value);
                    }
                }, 180);
            };
        }

        if (window.pywebview.api.get_initial_state) {
            window.pywebview.api.get_initial_state().then((state) => {
                applySnapshotState(state);
            });
        }
    }

    applyTheme(currentTheme, false);
    applyAccent(currentAccent, false);
    applyLanguage(currentLanguage, false);

    window.addEventListener("pywebviewready", bindPywebviewButtons);
    if (window.pywebview && window.pywebview.api) bindPywebviewButtons();

    function handleServerEvent(data) {
        if (!data || typeof data !== "object") return;
        if (data.type === "snapshot") {
            applySnapshotState(data);
        } else if (data.type === "devices_updated" || data.type === "client_connected" || data.type === "client_disconnected") {
            setConnectedCount(data.connected_count ?? data.count ?? 0, data.devices || null, data.blocked_devices || null);
        } else if (data.type === "network_changed") {
            if (data.local_url) {
                local_url = data.local_url;
                document.getElementById("url-box").textContent = local_url;
            }
            if (data.qr_data_uri || data.local_qr) {
                qrCache.local = data.qr_data_uri || data.local_qr;
                if (activeQrMode === "local") applyQrImageWithTransition(qrCache.local);
            }
            if (data.candidate_ips) {
                populateCandidateIps(data.candidate_ips, preferredIpSelect ? preferredIpSelect.value : "");
            }
        } else if (data.type === "session_regenerated") {
            if (data.local_url) {
                local_url = data.local_url;
                document.getElementById("url-box").textContent = local_url;
            }
            if (data.local_qr) {
                qrCache.local = data.local_qr;
                if (activeQrMode === "local") applyQrImageWithTransition(qrCache.local);
            }
            if (data.tunnel) updateTunnelStatus(data.tunnel);
            if (data.hotspot) updateHotspotState(data.hotspot);
            setConnectedCount(0, data.devices || [], data.blocked_devices || []);
        } else if (data.type === "tunnel_status") {
            updateTunnelStatus(data);
        } else if (data.type === "stage_result") {
            if (Array.isArray(data.queued) && data.queued.length > 0) {
                addQueuedLogs(data.queued);
            }
            if (Array.isArray(data.rejected)) {
                data.rejected.forEach((rej) => {
                    addActivityRow(I18n.t("log_rejected_item", { name: rej.name, detail: rej.detail }));
                });
            }
            renderSpeedIndicator();
        } else if (data.type === "scan_progress") {
            updatePreparingArchiveRow({
                id: data.share_id || data.request_id || data.name,
                request_id: data.request_id,
                name: `${data.name}.zip`,
                progress: 0
            });
        } else if (data.type === "zip_progress") {
            updatePreparingArchiveRow(data);
        } else if (data.type === "size_updated") {
            handleSizeUpdated(data);
            renderSpeedIndicator();
        } else if (data.type === "activity_summary") {
            renderSpeedIndicator(data);
        } else if (data.type === "transfer_updated" || data.type === "progress" || data.type === "download_progress" || data.type === "download_complete") {
            const payload = data.transfer || data;
            updatePerFileTransferRow(payload);
            const norm = normalizeTransferDto(payload);
            if (norm.state === "Completed" && (payload.direction === "phone_to_pc" || data.type === "progress")) {
                addActivityRow(I18n.t("log_received", {
                    category: tCategory(norm.category),
                    name: norm.saved_as,
                    size: formatBytes(norm.size)
                }), norm.thumbnail);
            }
        } else if (data.type === "transfer_cancelled") {
            if (data.transfer) updatePerFileTransferRow(Object.assign({}, data.transfer, { cancelled_by: data.cancelled_by || data.transfer.cancelled_by || "" }));
            else if (data.transfer_id) updatePerFileTransferRow({ id: data.transfer_id, state: "cancelled", cancelled_by: data.cancelled_by || "" });
            if (data.id) removePreparingRow(data.id);
            if (data.share_id) removePreparingRow(data.share_id);
            if (data.request_id) removePreparingRow(data.request_id);
            if (data.transfer_id) removePreparingRow(data.transfer_id);
            if (data.request_id) {
                requestQueue = requestQueue.filter((r) => r.request_id !== data.request_id);
                if (currentRequest && currentRequest.request_id === data.request_id) {
                    permModal.classList.remove("active");
                    currentRequest = null;
                    isProcessingRequest = false;
                    processNextRequest();
                }
            }
            if (Array.isArray(data.shares)) renderSharedPcFiles(data.shares);
            renderSpeedIndicator();
        } else if (data.type === "transfer_request" && data.target === "pc") {
            requestQueue.push(data);
            processNextRequest();
        } else if (data.type === "transfer_accepted") {
            if (data.auto_accepted && data.direction === "phone_to_pc") {
                const count = (data.files || []).length;
                addActivityRow(I18n.t("log_auto_accepted", {
                    device: data.device_name || "Phone",
                    count: count
                }));
            } else if (data.target === "pc") {
                updateQueuedStatus(data.request_id, data.files, "Accepted");
                if (Array.isArray(data.shares)) {
                    renderSharedPcFiles(data.shares);
                }
            }
            if (Array.isArray(data.transfers)) {
                data.transfers.forEach((tr) => updatePerFileTransferRow(tr));
            }
            renderSpeedIndicator();
        } else if (data.type === "transfer_rejected") {
            if (data.target === "pc") {
                updateQueuedStatus(data.request_id, data.files, "Declined");
            }
            if (data.request_id) removePreparingRow(data.request_id);
            if (data.share_id) removePreparingRow(data.share_id);
            if (Array.isArray(data.files)) {
                data.files.forEach((f) => {
                    if (f && f.id) removePreparingRow(f.id);
                });
            }
            if (data.request_id) {
                requestQueue = requestQueue.filter((r) => r.request_id !== data.request_id);
                if (currentRequest && currentRequest.request_id === data.request_id) {
                    permModal.classList.remove("active");
                    currentRequest = null;
                    isProcessingRequest = false;
                    processNextRequest();
                }
            }
            renderSpeedIndicator();
        } else if (data.type === "transfer_expired") {
            updateQueuedStatus(data.request_id, data.files, "Expired");
            if (data.request_id) removePreparingRow(data.request_id);
            const expiredIds = Array.isArray(data.transfer_ids) ? data.transfer_ids.slice() : [];
            if (data.transfer_id && !expiredIds.includes(data.transfer_id)) {
                expiredIds.push(data.transfer_id);
            }
            if (data.request_id) {
                activeTransfersMap.forEach((tr, tid) => {
                    if (tr.request_id === data.request_id && !expiredIds.includes(tid)) {
                        expiredIds.push(tid);
                    }
                });
            }
            expiredIds.forEach((tid) => {
                activeTransfersMap.delete(String(tid));
                const rowId = getSafeRowId("tx", String(tid));
                const row = document.getElementById(rowId);
                if (row) row.remove();
            });
            if (data.reason === "waiting_timeout") {
                flashStatusMessage(I18n.t("transfer_expired_phone"));
                addActivityRow(I18n.t("transfer_expired_phone"));
            }
            if (data.request_id) {
                requestQueue = requestQueue.filter((r) => r.request_id !== data.request_id);
                if (currentRequest && currentRequest.request_id === data.request_id) {
                    permModal.classList.remove("active");
                    currentRequest = null;
                    isProcessingRequest = false;
                    processNextRequest();
                }
            }
            renderSpeedIndicator();
        } else if (data.type === "share_removed") {
            if (Array.isArray(data.shares)) renderSharedPcFiles(data.shares);
        } else if (data.type === "text_sync") {
            if (typeof data.content === "string") updateSyncedText(data.content);
        } else if (data.type === "history_cleared") {
            document.getElementById("activity-list").innerHTML = "";
        } else if (data.type === "ui_error") {
            flashStatusMessage(data.message || I18n.t("log_error", { message: "" }));
            addActivityRow(I18n.t("log_error", { message: data.message || "" }));
        } else if (data.type === "hotspot_status") {
            updateHotspotState(data);
        }
    }
    window.handleServerEvent = handleServerEvent;
    window.__onServerEvent = handleServerEvent;
    window.__flashWarning = flashStatusMessage;
})();
