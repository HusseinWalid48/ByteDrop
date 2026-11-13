/**
 * ByteDrop v1.0.0 Shared Formatting & Speed/ETA Engine (/ui/shared/format.js)
 * Used by both Desktop UI (/ui/desktop) and Phone/Web UI (/ui/web) as well as Node tests.
 * Enforces:
 *   - Section 3.1 (no "total" text, sizes shown once)
 *   - Section 3.2 (EWMA speed & clamped ETA)
 *   - Section 2 (summarizeActivity single source of truth & per-file row without speed/ETA)
 *   - F3 (folder items show "Preparing..." before size_updated)
 *   - F5 (row detail without repeating file name)
 */
(function (root, factory) {
    const api = factory();
    if (typeof globalThis !== "undefined") {
        globalThis.ByteDropFormat = api;
    }
    if (typeof root !== "undefined") {
        root.ByteDropFormat = api;
    }
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    const ACCENT_PALETTES = {
        blue: { from: "#1d4ed8", to: "#3b82f6", light: "#60a5fa", rgb: "59, 130, 246", darkRgb: "29, 78, 216" },
        purple: { from: "#6d28d9", to: "#8b5cf6", light: "#a78bfa", rgb: "139, 92, 246", darkRgb: "109, 40, 217" },
        green: { from: "#047857", to: "#10b981", light: "#34d399", rgb: "16, 185, 129", darkRgb: "4, 120, 87" },
        cyan: { from: "#0e7490", to: "#06b6d4", light: "#22d3ee", rgb: "6, 182, 212", darkRgb: "14, 116, 144" },
        rose: { from: "#be123c", to: "#f43f5e", light: "#fb7185", rgb: "244, 63, 94", darkRgb: "190, 18, 60" }
    };

    const CATEGORY_EXTENSIONS = {
        Images: [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic"],
        Videos: [".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"],
        Docs: [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".md", ".json", ".xml"],
        Audio: [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
        Archives: [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"]
    };

    const EXT_TO_CATEGORY = {};
    Object.keys(CATEGORY_EXTENSIONS).forEach((cat) => {
        CATEGORY_EXTENSIONS[cat].forEach((ext) => {
            EXT_TO_CATEGORY[ext] = cat;
        });
    });

    function inferCategory(filename) {
        if (!filename || typeof filename !== "string") return "Others";
        const idx = filename.lastIndexOf(".");
        const ext = idx !== -1 ? filename.slice(idx).toLowerCase() : "";
        return EXT_TO_CATEGORY[ext] || "Others";
    }

    function formatBytes(bytes) {
        const num = Number(bytes);
        if (!Number.isFinite(num) || num <= 0) return "0 B";
        const k = 1024;
        const sizes = ["B", "KB", "MB", "GB", "TB"];
        const i = Math.min(sizes.length - 1, Math.floor(Math.log(num) / Math.log(k)));
        if (i === 0) return `${Math.round(num)} B`;
        return `${(num / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
    }

    function formatSpeed(bps) {
        const num = Number(bps);
        if (!Number.isFinite(num) || num <= 0) return "0.0 KB/s";
        const kb = num / 1024;
        if (kb < 1024) {
            return `${kb.toFixed(1)} KB/s`;
        }
        const mb = kb / 1024;
        if (mb < 1024) {
            return `${mb.toFixed(1)} MB/s`;
        }
        const gb = mb / 1024;
        return `${gb.toFixed(2)} GB/s`;
    }

    function formatDuration(seconds) {
        if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds)) || Number(seconds) < 0) {
            return "--:--";
        }
        const total = Math.max(0, Math.round(Number(seconds)));
        const hours = Math.floor(total / 3600);
        const rem = total % 3600;
        const mins = Math.floor(rem / 60);
        const secs = rem % 60;
        if (hours > 0) {
            return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
        }
        return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }

    function formatEta(seconds, trFn) {
        if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds)) || Number(seconds) < 0) {
            return typeof trFn === "function" ? trFn("eta_calculating") : "calculating...";
        }
        const dur = formatDuration(seconds);
        return typeof trFn === "function" ? trFn("eta_left", { eta: dur }) : `${dur} left`;
    }

    /**
     * Section 3.1 & F3: Transfer prompt summary formatter.
     * Single item: shows `name (size)` once — never an aggregated "total".
     * Folder items before size_updated (is_folder/is_dir && !archive_ready && size === 0) show Preparing... instead of a size.
     */
    function formatPromptSummary(files, senderLabel = "Device", translateFn = null) {
        const list = Array.isArray(files) ? files : [];
        const prepWord = typeof translateFn === "function" ? translateFn("status_preparing") : "Preparing...";
        const formattedItems = list.map((f) => {
            const name = String((f && f.name) || "file");
            const isFolderPending = Boolean(f && (f.is_folder || f.is_dir) && !f.archive_ready && (!f.size || Number(f.size) <= 0));
            const sizeLabel = isFolderPending ? prepWord : formatBytes((f && f.size) || 0);
            return `${name} (${sizeLabel})`;
        });
        if (formattedItems.length === 0) {
            const header0 = typeof translateFn === "function"
                ? translateFn("prompt_wants_many", { sender: senderLabel, count: 0 })
                : `${senderLabel} wants to send 0 files`;
            return {
                isSingle: false,
                count: 0,
                headerText: header0,
                visibleItems: [],
                hiddenItems: [],
                moreCount: 0
            };
        }
        if (formattedItems.length === 1) {
            const header1 = typeof translateFn === "function"
                ? translateFn("prompt_wants_single", { sender: senderLabel, item: formattedItems[0] })
                : `${senderLabel} wants to send ${formattedItems[0]}`;
            return {
                isSingle: true,
                count: 1,
                headerText: header1,
                visibleItems: [formattedItems[0]],
                hiddenItems: [],
                moreCount: 0
            };
        }
        const visibleItems = formattedItems.slice(0, 4);
        const hiddenItems = formattedItems.slice(4);
        const headerMany = typeof translateFn === "function"
            ? translateFn("prompt_wants_many", { sender: senderLabel, count: formattedItems.length })
            : `${senderLabel} wants to send ${formattedItems.length} files`;
        return {
            isSingle: false,
            count: formattedItems.length,
            headerText: headerMany,
            visibleItems: visibleItems,
            hiddenItems: hiddenItems,
            moreCount: hiddenItems.length
        };
    }

    /**
     * Section 2.3 & F5: Per-file row detail formatter (without repeating file name, and no speed/ETA in active rows).
     * Active: "340.2 MB / 1.1 GB • 28%"
     * Paused/Stalled/Waiting: "340.2 MB / 1.1 GB • 28% • Paused"
     * Completed: "Done in 03:12 (avg 9.8 MB/s)"
     */
    function formatTransferRowDetail(t, translateFn = null, opts = null) {
        const tr = (key, vars, fallback) => {
            if (typeof translateFn === "function") {
                const res = translateFn(key, vars);
                if (res && res !== key) return res;
            }
            return fallback;
        };

        const size = Math.max(0, Number((t && (t.size ?? t.total)) || 0));
        const offset = Math.max(0, Math.min(size || Infinity, Number((t && (t.offset ?? t.received ?? t.bytes_done)) || 0)));
        const stateRaw = String((t && t.state) || "Uploading");
        const stateLower = stateRaw.toLowerCase();
        const isDone = stateLower === "completed" || stateLower === "done" || (size > 0 && offset >= size && stateLower !== "uploading" && stateLower !== "downloading" && stateLower !== "active" && stateLower !== "interrupted" && stateLower !== "paused" && stateLower !== "cancelled");
        const pct = isDone ? 100 : (size > 0 ? Math.min(99, Math.floor((offset / size) * 100)) : 0);

        if (isDone) {
            const dur = formatDuration(t && (t.duration_sec ?? t.elapsed) !== undefined ? (t.duration_sec ?? t.elapsed) : 0);
            const avg = formatSpeed(t && (t.avg_speed_bps ?? t.avg_speed) !== undefined ? (t.avg_speed_bps ?? t.avg_speed) : 0);
            return tr("row_done_in", { duration: dur, avg: avg }, `Done in ${dur} (avg ${avg})`);
        }

        if (stateLower === "preparing" || (t && t.preparing)) {
            const prepPct = Math.max(0, Math.min(100, Number((t && t.progress) || 0)));
            const prepLabel = tr("preparing_archive", {}, "Preparing archive");
            return `${prepLabel} • ${prepPct}%`;
        }

        const baseProgress = `${formatBytes(offset)} / ${formatBytes(size)} • ${pct}%`;

        if (stateLower === "cancelled") {
            if (t && t.cancelled_by === "pc" && (t.direction === "pc_to_phone" || t.isDownload)) {
                const byPc = tr("cancelled_by_pc", {}, "Cancelled by the PC");
                return `${baseProgress} • ${byPc}`;
            }
            const cancWord = tr("state_cancelled", {}, "Cancelled");
            return `${baseProgress} • ${cancWord}`;
        }

        if (t && t.offline_will_resume) {
            const offResume = tr("offline_will_resume", {}, "Offline, will resume");
            return `${baseProgress} • ${offResume}`;
        }

        if (stateLower === "interrupted" || (t && t.connection_lost)) {
            if ((t && t.isPhoneView) || (opts && opts.isPhone)) {
                const retryMsg = tr("connection_lost_retry_browser", {}, "Connection lost. Retry from your browser's downloads");
                return `${baseProgress} • ${retryMsg}`;
            }
            const remSec = (t && t.interrupted_remaining_sec !== undefined && t.interrupted_remaining_sec !== null)
                ? Math.max(0, Number(t.interrupted_remaining_sec))
                : 600;
            const remStr = formatDuration(remSec);
            const waitResume = tr(
                "connection_lost_waiting",
                { remaining: remStr },
                `Connection lost — waiting to resume (${remStr} left)`
            );
            return `${baseProgress} • ${waitResume}`;
        }

        if (stateLower === "paused" || (t && t.paused)) {
            const pausedWord = tr("state_paused", {}, "Paused");
            return `${baseProgress} • ${pausedWord}`;
        }

        const isPcToPhone = Boolean(t && (t.direction === "pc_to_phone" || t.isDownload));
        if (isPcToPhone && offset === 0 && (stateLower === "accepted" || stateLower === "waiting" || stateLower === "pending" || stateLower === "queued" || stateLower === "active" || stateLower === "downloading")) {
            const waitPhone = tr("waiting_for_phone", {}, "Waiting for the phone to start saving");
            return `${baseProgress} • ${waitPhone}`;
        }

        if (t && t.waiting_for_phone && !isPcToPhone && offset > 0) {
            const waitPhoneUpload = tr("waiting_for_phone_upload", {}, "Waiting for the phone");
            return `${baseProgress} • ${waitPhoneUpload}`;
        }

        if (t && t.stalled && offset > 0) {
            const stalledWord = tr("state_stalled", {}, "Stalled");
            return `${baseProgress} • ${stalledWord}`;
        }

        if (stateLower === "waiting" || stateLower === "pending" || stateLower === "queued" || stateLower === "accepted") {
            const waitingWord = tr("state_waiting", {}, "Waiting");
            return `${baseProgress} • ${waitingWord}`;
        }

        return baseProgress;
    }

    /**
     * Section 2.3: Per-file active transfer row formatter (includes name once, no speed/ETA when active).
     */
    function formatTransferRowText(t, translateFn = null) {
        const name = String((t && t.name) || (t && t.filename) || "file");
        const detail = formatTransferRowDetail(t, translateFn);
        return `${name} • ${detail}`;
    }

    /**
     * Section 3.2: EWMA Speed & Clamped ETA Estimator (4 Hz sampling, 3 s window).
     */
    class SpeedEstimator {
        constructor(totalBytes, resumedOffset = 0, nowSec = null) {
            const now = nowSec !== null ? nowSec : Date.now() / 1000;
            this.totalBytes = Math.max(0, Number(totalBytes) || 0);
            this.resumedOffset = Math.max(0, Number(resumedOffset) || 0);
            this.currentOffset = this.resumedOffset;

            this.startTime = now;
            this.lastSampleTime = now;
            this.lastByteTime = now;
            this.pausedAt = null;
            this.totalPausedSec = 0;

            this.samples = [[now, this.resumedOffset]];
            this.smoothedSpeed = 0;
            this.lastEta = null;
            this.isPaused = false;

            this.SAMPLE_INTERVAL_SEC = 0.25;
            this.WINDOW_SEC = 3.0;
            this.EWMA_ALPHA = 0.3;
            this.ETA_MIN_ELAPSED_SEC = 1.5;
            this.ETA_MIN_BYTES = 64 * 1024;
            this.ETA_MAX_CHANGE_RATIO = 0.20;
            this.STALL_THRESHOLD_SEC = 5.0;
            this.CONNECTION_LOST_SEC = 15.0;
            this.UPLOAD_WAITING_PHONE_SEC = 45.0;
        }

        resetForResume(resumedOffset, nowSec = null) {
            const now = nowSec !== null ? nowSec : Date.now() / 1000;
            this.resumedOffset = Math.max(0, Number(resumedOffset) || 0);
            this.currentOffset = this.resumedOffset;
            this.startTime = now;
            this.lastSampleTime = now;
            this.lastByteTime = now;
            this.pausedAt = null;
            this.totalPausedSec = 0;
            this.samples = [[now, this.resumedOffset]];
            this.smoothedSpeed = 0;
            this.lastEta = null;
            this.isPaused = false;
        }

        pause(nowSec = null) {
            const now = nowSec !== null ? nowSec : Date.now() / 1000;
            if (!this.isPaused) {
                this.isPaused = true;
                this.pausedAt = now;
                this.smoothedSpeed = 0;
            }
        }

        resume(currentOffset = null, nowSec = null) {
            const now = nowSec !== null ? nowSec : Date.now() / 1000;
            if (this.isPaused) {
                if (this.pausedAt !== null) {
                    this.totalPausedSec += Math.max(0, now - this.pausedAt);
                }
                this.pausedAt = null;
                this.isPaused = false;
                if (currentOffset !== null && currentOffset !== undefined) {
                    this.currentOffset = Math.max(0, Number(currentOffset) || 0);
                }
                this.lastSampleTime = now;
                this.lastByteTime = now;
                this.samples = [[now, this.currentOffset]];
            }
        }

        activeElapsed(nowSec = null) {
            const now = nowSec !== null ? nowSec : Date.now() / 1000;
            let pausedExtra = 0;
            if (this.isPaused && this.pausedAt !== null) {
                pausedExtra = Math.max(0, now - this.pausedAt);
            }
            return Math.max(0.001, (now - this.startTime) - (this.totalPausedSec + pausedExtra));
        }

        update(currentOffset, force = false, nowSec = null) {
            const now = nowSec !== null ? nowSec : Date.now() / 1000;
            const offset = Math.max(this.resumedOffset, Number(currentOffset) || 0);
            if (offset > this.currentOffset) {
                this.lastByteTime = now;
            }
            this.currentOffset = offset;

            if (this.isPaused) {
                return this.snapshot(now);
            }

            if (!force && (now - this.lastSampleTime) < this.SAMPLE_INTERVAL_SEC) {
                return this.snapshot(now);
            }

            this.lastSampleTime = now;
            this.samples.push([now, offset]);

            const cutoff = now - this.WINDOW_SEC;
            while (this.samples.length > 2 && this.samples[0][0] < cutoff) {
                this.samples.shift();
            }

            if (this.samples.length >= 2) {
                const [t0, b0] = this.samples[0];
                const dt = now - t0;
                const db = Math.max(0, offset - b0);
                if (dt > 0.01) {
                    const windowSpeed = db / dt;
                    if (this.smoothedSpeed <= 0) {
                        this.smoothedSpeed = windowSpeed;
                    } else {
                        this.smoothedSpeed = this.EWMA_ALPHA * windowSpeed + (1 - this.EWMA_ALPHA) * this.smoothedSpeed;
                    }
                }
            }
            return this.snapshot(now);
        }

        snapshot(nowSec = null, direction = null) {
            const now = nowSec !== null ? nowSec : Date.now() / 1000;
            const elapsed = this.activeElapsed(now);
            const newBytes = Math.max(0, this.currentOffset - this.resumedOffset);
            const avgSpeed = elapsed > 0 ? newBytes / elapsed : 0;

            const idleSec = Math.max(0, now - this.lastByteTime);
            const isIncomplete = this.currentOffset > 0 && (this.totalBytes === 0 || this.currentOffset < this.totalBytes);
            const connectionLost = !this.isPaused && isIncomplete && direction === "pc_to_phone" && idleSec >= this.CONNECTION_LOST_SEC;
            const waitingForPhone = !this.isPaused && isIncomplete && direction === "phone_to_pc" && idleSec >= this.UPLOAD_WAITING_PHONE_SEC;

            // G2 & H2: Stalled ONLY when currentOffset > 0 and no new bytes for >= 5 s (before connection_lost/waiting_for_phone)
            const stalled = !this.isPaused && !connectionLost && !waitingForPhone && isIncomplete && idleSec >= this.STALL_THRESHOLD_SEC;
            const speedBps = (this.isPaused || stalled || connectionLost || waitingForPhone) ? 0 : this.smoothedSpeed;

            let etaSec = null;
            const remaining = Math.max(0, this.totalBytes - this.currentOffset);
            if (remaining === 0) {
                etaSec = 0;
            } else if (!this.isPaused && !stalled && !connectionLost && !waitingForPhone && elapsed >= this.ETA_MIN_ELAPSED_SEC && newBytes >= this.ETA_MIN_BYTES && speedBps > 1) {
                const rawEta = remaining / speedBps;
                if (this.lastEta !== null && this.lastEta > 0) {
                    const low = this.lastEta * (1 - this.ETA_MAX_CHANGE_RATIO);
                    const high = this.lastEta * (1 + this.ETA_MAX_CHANGE_RATIO);
                    etaSec = Math.max(low, Math.min(high, rawEta));
                } else {
                    etaSec = rawEta;
                }
                this.lastEta = etaSec;
            }

            return {
                speed_bps: Math.round(speedBps * 10) / 10,
                avg_speed_bps: Math.round(avgSpeed * 10) / 10,
                eta_seconds: etaSec !== null ? Math.round(etaSec * 10) / 10 : null,
                elapsed_sec: Math.round(elapsed * 100) / 100,
                new_bytes: newBytes,
                stalled: stalled,
                connection_lost: connectionLost,
                waiting_for_phone: waitingForPhone,
                paused: this.isPaused
            };
        }
    }

    /**
     * Section 2.2, G2 & G4: Pure function summarizeActivity(transfers, nowSec, prevEta)
     * Returns {state: 'idle'|'waiting'|'active'|'paused'|'stalled'|'preparing', speed_bps, eta_seconds, active_count}.
     * - Waiting for phone: accepted/waiting or active with bytes_done === 0 and speed === 0. Not stalled, not in active_count.
     * - Interrupted: treated as paused by the activity summary indicator.
     * - Stalled: only when bytes_done > 0 and no new bytes for >= 5 s.
     */
    function summarizeActivity(transfers, nowSec = null, prevEta = null, opts = null) {
        const now = nowSec !== null && nowSec !== undefined ? Number(nowSec) : Date.now() / 1000;
        const list = Array.isArray(transfers) ? transfers : [];
        const connLostSec = (opts && Number.isFinite(Number(opts.connection_lost_sec))) ? Number(opts.connection_lost_sec) : 15.0;
        const waitPhoneSec = (opts && Number.isFinite(Number(opts.upload_waiting_phone_sec))) ? Number(opts.upload_waiting_phone_sec) : 45.0;

        const activeMoving = [];
        const stalledList = [];
        const pausedList = [];
        const preparingList = [];
        const waitingList = [];

        for (let i = 0; i < list.length; i++) {
            const item = list[i];
            if (!item || typeof item !== "object") continue;

            const rawState = String(item.state || "").toLowerCase();
            if (
                rawState === "done" ||
                rawState === "completed" ||
                rawState === "cancelled" ||
                rawState === "rejected" ||
                rawState === "expired" ||
                rawState === "failed"
            ) {
                continue;
            }

            if (rawState === "preparing" || rawState === "scanning" || rawState === "zipping" || item.preparing) {
                preparingList.push(item);
                continue;
            }

            if (
                rawState === "paused" ||
                rawState === "interrupted" ||
                item.paused ||
                item.connection_lost ||
                item.waiting_for_phone ||
                item.offline_will_resume ||
                (item.estimator && item.estimator.isPaused)
            ) {
                pausedList.push(item);
                continue;
            }

            if (rawState === "accepted" || rawState === "queued" || rawState === "waiting" || rawState === "pending") {
                waitingList.push(item);
                continue;
            }

            if (rawState === "active" || rawState === "uploading" || rawState === "downloading" || rawState === "") {
                const direction = String(item.direction || (rawState === "downloading" ? "pc_to_phone" : "phone_to_pc"));
                let snap = null;
                if (item.estimator && typeof item.estimator.snapshot === "function") {
                    snap = item.estimator.snapshot(now, direction);
                }

                const fObj = item.file || {};
                const totalBytes = Math.max(0, Number(item.size ?? item.total ?? fObj.size ?? (item.estimator ? item.estimator.totalBytes : 0)) || 0);
                const bytesDone = Math.max(0, Number(item.offset ?? item.bytes_done ?? item.received ?? (item.estimator ? item.estimator.currentOffset : 0)) || 0);
                const resumedOffset = Math.max(0, Number(item.resumed_offset ?? item.resumedOffset ?? (item.estimator ? item.estimator.resumedOffset : 0)) || 0);
                const spd = snap
                    ? Number(snap.speed_bps || 0)
                    : Math.max(0, Number(item.speed_bps ?? item.speed ?? 0) || 0);

                // G2: If no bytes have flowed yet and speed is 0, classify as waiting (never stalled or 0.0 KB/s active)
                if (bytesDone <= 0 && spd <= 0) {
                    waitingList.push(item);
                    continue;
                }

                const lastByteAt = item.last_byte_time ?? item.lastByteTime ?? item.updated_at;
                let idleSec = 0;
                if (bytesDone > 0 && lastByteAt !== undefined && lastByteAt !== null && Number.isFinite(Number(lastByteAt))) {
                    idleSec = Math.max(0, now - Number(lastByteAt));
                }

                const isConnLost = Boolean((snap && snap.connection_lost) || (direction === "pc_to_phone" && bytesDone > 0 && (totalBytes === 0 || bytesDone < totalBytes) && idleSec >= connLostSec));
                const isWaitPhone = Boolean((snap && snap.waiting_for_phone) || (direction === "phone_to_pc" && bytesDone > 0 && (totalBytes === 0 || bytesDone < totalBytes) && idleSec >= waitPhoneSec));
                if (isConnLost || isWaitPhone) {
                    pausedList.push(item);
                    continue;
                }

                let isStalled = Boolean((item.stalled || (snap && snap.stalled)) && bytesDone > 0);
                if (!isStalled && bytesDone > 0 && idleSec >= 5.0 && (totalBytes === 0 || bytesDone < totalBytes)) {
                    isStalled = true;
                }

                if (isStalled) {
                    stalledList.push(item);
                } else {
                    let elapsed = snap
                        ? Number(snap.elapsed_sec || 0)
                        : Number(item.elapsed_sec ?? item.elapsed ?? 0);
                    if ((!elapsed || elapsed <= 0) && item.started_at !== undefined && item.started_at !== null) {
                        elapsed = Math.max(0, now - Number(item.started_at));
                    }
                    const newBytes = snap
                        ? Number(snap.new_bytes || 0)
                        : Math.max(0, bytesDone - resumedOffset);
                    const itemPrevEta = item.prev_eta ?? item.last_eta ?? (snap ? item.estimator.lastEta : null);
                    const itemEta = snap ? snap.eta_seconds : (item.eta_seconds ?? item.eta ?? null);

                    activeMoving.push({
                        raw: item,
                        speed_bps: spd,
                        total_bytes: totalBytes,
                        bytes_done: bytesDone,
                        resumed_offset: resumedOffset,
                        new_bytes: newBytes,
                        elapsed_sec: elapsed,
                        request_id: item.request_id || item.batch_id || "",
                        prev_eta: itemPrevEta,
                        item_eta: itemEta
                    });
                }
            }
        }

        if (activeMoving.length > 0) {
            let speedSum = 0;
            let remainingBytes = 0;
            let maxElapsed = 0;
            let totalNewBytes = 0;
            const activeBatchIds = new Set();

            for (let i = 0; i < activeMoving.length; i++) {
                const m = activeMoving[i];
                speedSum += Math.max(0, m.speed_bps);
                remainingBytes += Math.max(0, m.total_bytes - m.bytes_done);
                totalNewBytes += Math.max(0, m.new_bytes);
                if (m.elapsed_sec > maxElapsed) {
                    maxElapsed = m.elapsed_sec;
                }
                if (m.request_id) {
                    activeBatchIds.add(m.request_id);
                }
            }

            // Include accepted-but-not-started files of the same batch (or all queued if batch id is unset)
            for (let j = 0; j < waitingList.length; j++) {
                const q = waitingList[j];
                const qState = String(q.state || "").toLowerCase();
                if (qState === "pending") continue;
                const qBatch = q.request_id || q.batch_id || "";
                if (activeBatchIds.size === 0 || !qBatch || activeBatchIds.has(qBatch)) {
                    const qFile = q.file || {};
                    const qSize = Math.max(0, Number(q.size ?? q.total ?? qFile.size ?? 0) || 0);
                    const qDone = Math.max(0, Number(q.offset ?? q.bytes_done ?? q.received ?? 0) || 0);
                    remainingBytes += Math.max(0, qSize - qDone);
                }
            }

            let etaSeconds = null;
            const hasEnoughHistory = (maxElapsed >= 1.5 && totalNewBytes >= 64 * 1024) ||
                (activeMoving.length === 1 && activeMoving[0].item_eta !== null && activeMoving[0].item_eta !== undefined && waitingList.length === 0);

            if (remainingBytes === 0 && speedSum > 0) {
                etaSeconds = 0;
            } else if (hasEnoughHistory && speedSum > 1) {
                const rawEta = remainingBytes / speedSum;
                const clampRef = (prevEta !== null && prevEta !== undefined && Number.isFinite(Number(prevEta)) && Number(prevEta) > 0)
                    ? Number(prevEta)
                    : (activeMoving.length === 1 && Number.isFinite(Number(activeMoving[0].prev_eta)) && Number(activeMoving[0].prev_eta) > 0
                        ? Number(activeMoving[0].prev_eta)
                        : null);
                if (clampRef !== null) {
                    const low = clampRef * 0.80;
                    const high = clampRef * 1.20;
                    etaSeconds = Math.max(low, Math.min(high, rawEta));
                } else {
                    etaSeconds = rawEta;
                }
                etaSeconds = Math.round(etaSeconds * 10) / 10;
            }

            return {
                state: "active",
                speed_bps: Math.round(speedSum * 10) / 10,
                eta_seconds: etaSeconds,
                active_count: activeMoving.length,
                waiting_count: waitingList.length
            };
        }

        if (preparingList.length > 0) {
            return {
                state: "preparing",
                speed_bps: 0,
                eta_seconds: null,
                active_count: preparingList.length,
                waiting_count: waitingList.length
            };
        }

        if (stalledList.length > 0) {
            return {
                state: "stalled",
                speed_bps: 0,
                eta_seconds: null,
                active_count: stalledList.length,
                waiting_count: waitingList.length
            };
        }

        if (pausedList.length > 0) {
            return {
                state: "paused",
                speed_bps: 0,
                eta_seconds: null,
                active_count: pausedList.length,
                waiting_count: waitingList.length
            };
        }

        if (waitingList.length > 0) {
            return {
                state: "waiting",
                speed_bps: 0,
                eta_seconds: null,
                active_count: 0,
                waiting_count: waitingList.length
            };
        }

        return {
            state: "idle",
            speed_bps: 0,
            eta_seconds: null,
            active_count: 0,
            waiting_count: 0
        };
    }

    /**
     * Dynamic button label: the button smoothly resizes to its new label while the text swaps with a short
     * rise-and-fade. Falls back to a plain text change when there is no layout or reduced motion is requested.
     */
    function setButtonLabel(btn, text) {
        if (!btn) return;
        const next = String(text === null || text === undefined ? "" : text);
        if (btn.textContent === next) return;
        const canAnimate = typeof document !== "undefined" && typeof window !== "undefined" &&
            btn.isConnected && typeof btn.getBoundingClientRect === "function";
        const reduce = canAnimate && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const from = canAnimate ? btn.getBoundingClientRect().width : 0;
        if (!canAnimate || reduce || !from) {
            btn.textContent = next;
            return;
        }
        if (btn.__dynTimer) {
            clearTimeout(btn.__dynTimer);
            btn.__dynTimer = null;
        }
        btn.classList.add("dyn-btn");
        btn.style.boxSizing = "border-box";
        btn.style.width = from + "px";
        btn.textContent = "";
        const label = document.createElement("span");
        label.className = "dyn-label";
        label.textContent = next;
        btn.appendChild(label);

        const savedTransition = btn.style.transition;
        btn.style.transition = "none";
        btn.style.width = "auto";
        const to = btn.getBoundingClientRect().width;
        btn.style.width = from + "px";
        void btn.offsetWidth;
        btn.style.transition = savedTransition;
        btn.style.width = to + "px";
        btn.__dynTimer = setTimeout(() => {
            btn.style.width = "";
            btn.style.boxSizing = "";
            btn.__dynTimer = null;
        }, 340);
    }

    return {
        ACCENT_PALETTES,
        CATEGORY_EXTENSIONS,
        EXT_TO_CATEGORY,
        inferCategory,
        formatBytes,
        formatSpeed,
        formatDuration,
        formatEta,
        formatPromptSummary,
        formatTransferRowDetail,
        formatTransferRowText,
        SpeedEstimator,
        summarizeActivity,
        setButtonLabel
    };
});
