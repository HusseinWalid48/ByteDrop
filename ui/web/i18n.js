/**
 * ByteDrop v1.0.0 Mobile/Web UI Bilingual Dictionary (English & Modern Standard Arabic with RTL)
 */
(function (root) {
    "use strict";

    const DICTIONARIES = {
        en: {
            app_title: "ByteDrop",
            status_connecting: "Connecting...",
            status_reconnecting: "Reconnecting...",
            status_online: "Online",
            status_offline: "Offline",
            status_no_token: "No token - re-scan QR",
            status_disconnected_pc: "Disconnected by the PC",
            status_blocked_pc: "Blocked by the PC",
            reconnect_btn: "Reconnect",
            cannot_reach_pc: "Cannot reach PC server",
            upload_title: "Tap or Drop Files to Send",
            upload_sub: "Chunked Streaming • Smart Resume",
            select_files_btn: "Select Files",
            folder_hint: "To send a folder, zip it first or send it from the PC.",
            folder_drop_rejected: "Folders cannot be dropped from a browser. Zip the folder first or send it from the PC.",
            clipboard_title: "Live Clipboard",
            copy_btn: "Copy",
            copied_btn: "Copied!",
            clipboard_placeholder: "Plain text syncs with PC clipboard...",
            active_transfers_title: "Active Transfers",
            transfers_idle: "No active transfers",
            status_idle: "Idle",
            status_paused: "Paused",
            status_stalled: "Stalled",
            status_preparing: "Preparing...",
            status_waiting_phone: "Waiting",
            status_waiting: "Waiting",
            waiting_for_phone: "Waiting for the phone to start saving",
            waiting_for_phone_upload: "Waiting for the phone",
            offline_will_resume: "Offline, will resume",
            waiting_to_start_row: "Waiting to start • {size}",
            transfer_expired_phone: "Transfer expired: the phone did not start downloading",
            transfer_expired_waiting: "Transfer expired (never started): {name}",
            connection_lost_waiting: "Connection lost — waiting to resume ({remaining} left)",
            interrupted_waiting_row: "Interrupted — waiting for browser to resume ({remaining})",
            connection_lost_retry_browser: "Connection lost. Retry from your browser's downloads",
            cancelled_by_pc: "Cancelled by the PC",
            cancel_all_btn: "Cancel all",
            cancel_all_confirm: "Cancel all active and waiting transfers?",
            browser_download_tooltip: "Your browser's download list may show this as interrupted.",
            via_cloud: "Cloud",
            via_wifi: "Wi-Fi",
            cloud_slow_hint: "Using the Cloud link (slower). Use the Wi-Fi link for faster transfers.",
            cloud_large_file_hint: "Large file over the internet link — for faster speed, connect both devices to the same Wi-Fi or a PC hotspot.",
            status_calculating: "calculating...",
            eta_calculating: "calculating...",
            eta_left: "{eta} left",
            active_count_label: "{count} active",
            batch_pos_tag: "{index}/{total}",
            preparing_archive: "Preparing archive",
            preparing_archive_named: "Preparing archive: {name}",
            preparing_archive_row: "Preparing archive: {name} ({progress}%)",
            state_paused: "Paused",
            state_stalled: "Stalled",
            state_waiting: "Waiting",
            state_cancelled: "Cancelled",
            status_cancelled: "Cancelled",
            status_cancelled_pc: "Cancelled by the PC",
            status_cancelled_phone: "Cancelled by the phone",
            status_rejected: "Declined",
            status_accepted: "Accepted",
            starting_upload: "Starting upload...",
            declined_by_pc: "Declined by PC",
            waiting_pc_approval: "Waiting for PC approval",
            failed_offline: "Failed (Offline)",
            upload_failed: "Upload failed",
            show_less: "Show less",
            more_items: "+{count} more",
            state_declined_pc: "Declined by PC",
            state_failed_offline: "Failed (Offline)",
            state_accepted_starting: "Accepted • Starting upload...",
            state_waiting_pc: "Waiting for PC approval ({size})...",
            row_done_in: "Done in {duration} (avg {avg})",
            pause_btn: "Pause",
            resume_btn: "Resume",
            cancel_btn: "Cancel",
            shared_pc_title: "Shared From PC",
            no_shared_files: "No files shared yet",
            download_btn: "Download",
            stream_btn: "Stream",
            remove_btn: "Remove",
            close_btn: "Close",
            media_stream_title: "Media Stream",
            downloading_first_toast: "Downloading {name}. Tap Download on remaining files when ready.",
            upload_failed_msg: "Upload failed",
            history_title: "Transfer History",
            no_history: "No transfer history",
            incoming_pc_title: "Incoming PC Share",
            prompt_wants_single: "{sender} wants to send {item}",
            prompt_wants_many: "{sender} wants to send {count} files",
            show_more_btn: "+{count} more",
            show_less_btn: "Show less",
            reject_btn: "Reject",
            accept_btn: "Accept",
            settings_title: "Settings",
            done_btn: "Done",
            theme_title: "Theme Mode",
            theme_sub: "Glassmorphic Dark or Light",
            theme_dark: "Dark",
            theme_light: "Light",
            language_title: "Language / اللغة",
            language_sub: "Interface language and direction",
            accent_title: "Accent Color",
            accent_sub: "Primary glass highlight",
            transfer_expired_msg: "Transfer request expired or is no longer available.",
            error_rate_limited: "Too many failed authentication attempts. Please wait 5 minutes.",
            error_unauthorized: "Session unauthorized. Please re-scan the QR code.",
            cat_Images: "Images",
            cat_Videos: "Videos",
            cat_Docs: "Docs",
            cat_Audio: "Audio",
            cat_Archives: "Archives",
            cat_Others: "Others",
            cat_File: "File",
            dir_INCOMING: "INCOMING",
            dir_OUTGOING: "OUTGOING"
        },
        ar: {
            app_title: "بايت دروب (ByteDrop)",
            status_connecting: "جاري الاتصال...",
            status_reconnecting: "جاري إعادة الاتصال...",
            status_online: "متصل",
            status_offline: "غير متصل",
            status_no_token: "لا يوجد رمز - أعد مسح QR",
            status_disconnected_pc: "تم الفصل بواسطة الكمبيوتر",
            status_blocked_pc: "محظور بواسطة الكمبيوتر",
            reconnect_btn: "إعادة الاتصال",
            cannot_reach_pc: "تعذر الوصول إلى خادم الكمبيوتر",
            upload_title: "اضغط أو اسحب الملفات للإرسال",
            upload_sub: "بث مقسم عالي السرعة • استئناف ذكي",
            select_files_btn: "اختيار ملفات",
            folder_hint: "لإرسال مجلد، قم بضغطه بصيغة ZIP أولاً أو أرسله من الكمبيوتر.",
            folder_drop_rejected: "لا يمكن إفلات المجلدات من المتصفح. قم بضغط المجلد أولاً أو أرسله من الكمبيوتر.",
            clipboard_title: "مزامنة الحافظة",
            copy_btn: "نسخ",
            copied_btn: "تم النسخ!",
            clipboard_placeholder: "مزامنة النصوص مع حافظة الكمبيوتر...",
            active_transfers_title: "عمليات النقل النشطة",
            transfers_idle: "لا توجد عمليات نقل نشطة",
            status_idle: "خامل",
            status_paused: "متوقف مؤقتاً",
            status_stalled: "متعثر",
            status_preparing: "جاري التحضير...",
            status_waiting_phone: "بانتظار البدء",
            status_waiting: "بانتظار البدء",
            waiting_for_phone: "بانتظار بدء حفظ الملف على الهاتف",
            waiting_for_phone_upload: "بانتظار الهاتف",
            offline_will_resume: "غير متصل، سيتم الاستئناف تلقائياً",
            waiting_to_start_row: "بانتظار البدء • {size}",
            transfer_expired_phone: "انتهت صلاحية النقل: لم يبدأ الهاتف التنزيل",
            transfer_expired_waiting: "انتهت صلاحية النقل (لم يبدأ): {name}",
            connection_lost_waiting: "انقطع الاتصال — بانتظار الاستئناف (متبقي {remaining})",
            interrupted_waiting_row: "انقطع الاتصال — بانتظار استئناف المتصفح ({remaining})",
            connection_lost_retry_browser: "انقطع الاتصال. أعد المحاولة من قائمة تنزيلات المتصفح",
            cancelled_by_pc: "تم الإلغاء بواسطة الكمبيوتر",
            cancel_all_btn: "إلغاء الكل",
            cancel_all_confirm: "هل أنت متأكد من إلغاء جميع عمليات النقل النشطة والمنتظرة؟",
            browser_download_tooltip: "قد تظهر قائمة تنزيلات المتصفح هذا التنزيل كمنقطع.",
            via_cloud: "سحابي",
            via_wifi: "واي فاي",
            cloud_slow_hint: "يتم استخدام الرابط السحابي (أبطأ). استخدم رابط الواي فاي لنقل أسرع.",
            cloud_large_file_hint: "ملف كبير عبر رابط الإنترنت — لسرعة أعلى، وصّل الجهازين بنفس شبكة الواي فاي أو نقطة اتصال الكمبيوتر.",
            status_calculating: "جاري الحساب...",
            eta_calculating: "جاري الحساب...",
            eta_left: "متبقي {eta}",
            active_count_label: "{count} نشط",
            batch_pos_tag: "{index}/{total}",
            preparing_archive: "جاري تحضير الأرشيف",
            preparing_archive_named: "جاري تحضير الأرشيف: {name}",
            preparing_archive_row: "جاري تحضير الأرشيف: {name} ({progress}%)",
            state_paused: "متوقف مؤقتاً",
            state_stalled: "متعثر",
            state_waiting: "بانتظار الموافقة",
            state_cancelled: "ملغى",
            status_cancelled: "ملغى",
            status_cancelled_pc: "تم الإلغاء بواسطة الكمبيوتر",
            status_cancelled_phone: "تم الإلغاء بواسطة الهاتف",
            status_rejected: "مرفوض",
            status_accepted: "مقبول",
            starting_upload: "جاري بدء الرفع...",
            declined_by_pc: "تم الرفض من الكمبيوتر",
            waiting_pc_approval: "بانتظار موافقة الكمبيوتر",
            failed_offline: "فشل (غير متصل)",
            upload_failed: "فشل الرفع",
            show_less: "عرض أقل",
            more_items: "+{count} أخرى",
            state_declined_pc: "تم الرفض من الكمبيوتر",
            state_failed_offline: "فشل (غير متصل)",
            state_accepted_starting: "تم القبول • جاري بدء الرفع...",
            state_waiting_pc: "بانتظار موافقة الكمبيوتر ({size})...",
            row_done_in: "اكتمل في {duration} (بمتوسط {avg})",
            pause_btn: "إيقاف مؤقت",
            resume_btn: "استئناف",
            cancel_btn: "إلغاء",
            shared_pc_title: "ملفات مشاركة من الكمبيوتر",
            no_shared_files: "لا توجد ملفات مشاركة بعد",
            download_btn: "تنزيل",
            stream_btn: "بث مباشر",
            remove_btn: "حذف",
            close_btn: "إغلاق",
            media_stream_title: "بث الوسائط",
            downloading_first_toast: "جاري تنزيل {name}. اضغط تنزيل على بقية الملفات عند الجاهزية.",
            upload_failed_msg: "فشل الرفع",
            history_title: "سجل النقل",
            no_history: "لا يوجد سجل نقل",
            incoming_pc_title: "ملفات واردة من الكمبيوتر",
            prompt_wants_single: "يرغب {sender} بإرسال {item}",
            prompt_wants_many: "يرغب {sender} بإرسال {count} ملفات",
            show_more_btn: "+{count} أخرى",
            show_less_btn: "عرض أقل",
            reject_btn: "رفض",
            accept_btn: "قبول",
            settings_title: "الإعدادات",
            done_btn: "تم",
            theme_title: "مظهر الواجهة",
            theme_sub: "الوضع الداكن أو الفاتح الزجاجي",
            theme_dark: "داكن",
            theme_light: "فاتح",
            language_title: "اللغة / Language",
            language_sub: "لغة الواجهة واتجاه النص",
            accent_title: "اللون المميز",
            accent_sub: "تخصيص لون الواجهة الزجاجية",
            transfer_expired_msg: "انتهت صلاحية طلب النقل أو لم يعد متاحاً.",
            error_rate_limited: "محاولات تحقق خاطئة كثيرة. يرجى الانتظار 5 دقائق.",
            error_unauthorized: "الجلسة غير مصرح لها. يرجى إعادة مسح رمز QR.",
            cat_Images: "صور",
            cat_Videos: "فيديو",
            cat_Docs: "مستندات",
            cat_Audio: "صوتيات",
            cat_Archives: "أرشيف",
            cat_Others: "أخرى",
            cat_File: "ملف",
            dir_INCOMING: "وارد",
            dir_OUTGOING: "صادر"
        }
    };

    let currentLang = "en";

    function t(key, vars, langOverride) {
        const lang = langOverride && DICTIONARIES[langOverride] ? langOverride : currentLang;
        const dict = DICTIONARIES[lang] || DICTIONARIES.en;
        let str = dict[key] !== undefined ? dict[key] : (DICTIONARIES.en[key] || key);
        if (vars && typeof vars === "object") {
            Object.keys(vars).forEach((k) => {
                str = str.replace(new RegExp(`\\{${k}\\}`, "g"), String(vars[k]));
            });
        }
        return str;
    }

    function setLanguage(lang) {
        currentLang = DICTIONARIES[lang] ? lang : "en";
        if (typeof document !== "undefined" && document.documentElement) {
            document.documentElement.lang = currentLang;
            document.documentElement.dir = currentLang === "ar" ? "rtl" : "ltr";
            if (document.body) {
                document.body.classList.toggle("rtl-mode", currentLang === "ar");
            }
            document.querySelectorAll("[data-i18n]").forEach((el) => {
                if (el.hasAttribute("data-dynamic")) return;
                const key = el.getAttribute("data-i18n");
                const translated = t(key);
                if (translated) el.textContent = translated;
            });
            document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
                if (el.hasAttribute("data-dynamic")) return;
                const key = el.getAttribute("data-i18n-placeholder");
                const translated = t(key);
                if (translated) el.setAttribute("placeholder", translated);
            });
        }
        return currentLang;
    }

    function renderConnectionStatus(model, lang) {
        const l = lang && DICTIONARIES[lang] ? lang : currentLang;
        const stateStr = typeof model === "string" ? model : String((model && model.state) || "connecting");
        const st = stateStr.toLowerCase();

        if (st === "online" || st === "connected") {
            return { text: t("status_online", {}, l), cssClass: "badge connected" };
        }
        if (st === "connecting") {
            return { text: t("status_connecting", {}, l), cssClass: "badge connecting" };
        }
        if (st === "reconnecting") {
            return { text: t("status_reconnecting", {}, l), cssClass: "badge connecting" };
        }
        if (st === "kicked") {
            return { text: t("status_disconnected_pc", {}, l), cssClass: "badge kicked" };
        }
        if (st === "blocked") {
            return { text: t("status_blocked_pc", {}, l), cssClass: "badge kicked" };
        }
        if (st === "no_token") {
            return { text: t("status_no_token", {}, l), cssClass: "badge disconnected" };
        }
        return { text: t("status_offline", {}, l), cssClass: "badge disconnected" };
    }

    const api = {
        DICTIONARIES,
        dictionaries: DICTIONARIES,
        setLanguage,
        getLanguage: () => currentLang,
        t,
        renderConnectionStatus
    };
    root.ByteDropI18n = api;
    if (typeof window !== "undefined") {
        window.ByteDropI18n = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : window);
