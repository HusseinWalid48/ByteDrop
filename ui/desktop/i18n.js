/**
 * ByteDrop v1.0.0 Desktop UI Bilingual Strings (English + Arabic with RTL)
 */
(function (root) {
    "use strict";

    const DICT = {
        en: {
            brand_sub: "Local & Cloud File Transfer • v1.0.0",
            qr_local: "Local",
            qr_cloud: "Cloud",
            qr_hotspot: "Hotspot",
            qr_wifi: "Wi-Fi",
            qr_app_link: "App Link",
            local_link_lbl: "Local Wi-Fi Link",
            cloud_link_lbl: "Public Cloud Link",
            cloud_link_warning: "Anyone with this link can send you file requests. Use Regenerate Session to revoke it.",
            copy_btn: "Copy",
            copied_btn: "Copied!",
            open_hotspot_settings: "Open Windows Hotspot settings",
            hotspot_detected: "Hotspot detected",
            hotspot_help: "Turn on Mobile hotspot in Windows, then scan the Hotspot QR.",
            hotspot_settings_error: "Could not open Windows Hotspot settings.",
            devices_zero: "0 Devices Connected",
            devices_n: "{count} Device(s) Connected",
            status_connecting: "Connecting...",
            status_reconnecting: "Reconnecting...",
            status_online: "Online",
            status_offline: "Offline",
            status_disconnected_pc: "Disconnected by the PC",
            status_blocked_pc: "Blocked by the PC",
            connect_first_warn: "Connect a device first!",
            disconnect_btn: "Disconnect",
            disconnecting_btn: "Disconnecting...",
            blocked_devices_title: "Blocked Devices",
            allow_btn: "Allow",
            drop_title: "Drag & Drop Files or Folders Here",
            drop_sub: "Instant Metadata Prompt • Chunk Streaming • Auto-Zips Folders",
            browse_files_btn: "Browse PC Files",
            browse_folders_btn: "Browse Folders",
            active_transfers_title: "Active Transfers",
            transfers_idle: "No active transfers",
            status_idle: "Idle",
            status_paused: "Paused",
            status_stalled: "Stalled",
            status_preparing: "Preparing...",
            status_waiting_phone: "Waiting for phone",
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
            disconnect_timeout_err: "Could not disconnect device. Try again.",
            corrupt_config_reset: "Settings file was corrupted and has been reset",
            state_cancelled: "Cancelled",
            status_cancelled: "Cancelled",
            status_cancelled_phone: "Cancelled by the phone",
            status_rejected: "Declined",
            cancelled_by_pc: "Cancelled by the PC",
            cancel_all_btn: "Cancel all",
            cancel_all_confirm: "Cancel all active and waiting transfers?",
            cancel_all_modal_title: "Cancel All Transfers",
            cancel_all_modal_desc: "Are you sure you want to cancel all active and waiting transfers?",
            browser_download_tooltip: "Your browser's download list may show this as interrupted.",
            via_cloud: "Cloud",
            via_wifi: "Wi-Fi",
            cloud_slow_hint: "Using the Cloud link (slower). Use the Wi-Fi link for faster transfers.",
            cloud_large_file_hint: "Large file over the internet link — for faster speed, connect both devices to the same Wi-Fi or a PC hotspot.",
            eta_calculating: "calculating...",
            eta_left: "{eta} left",
            active_count_label: "{count} active",
            batch_pos_tag: "{index}/{total}",
            preparing_archive: "Preparing archive",
            preparing_archive_row: "Preparing archive: {name} ({progress}%)",
            state_paused: "Paused",
            state_stalled: "Stalled",
            state_waiting: "Waiting",
            row_done_in: "Done in {duration} (avg {avg})",
            pause_btn: "Pause",
            resume_btn: "Resume",
            cancel_btn: "Cancel",
            clipboard_title: "Clipboard Sync",
            clip_auto_on: "Auto: On",
            clip_auto_off: "Auto: Off",
            clip_send_btn: "Copy & Send",
            clip_placeholder: "Plain text syncs between PC and connected phones...",
            history_title: "Transfer History & Live Feed",
            clear_history_btn: "Clear History",
            clear_history_modal_title: "Clear Transfer History",
            clear_history_modal_desc: "Are you sure you want to permanently clear the transfer history log?",
            clear_all_btn: "Clear All",
            open_downloads_btn: "Open Downloads",
            shared_pc_title: "Shared From PC",
            no_shared_files: "No shared files",
            no_activity: "No transfer activity yet",
            remove_btn: "Remove",
            incoming_title: "Incoming Mobile Transfer",
            prompt_wants_single: "{sender} wants to send {item}",
            prompt_wants_many: "{sender} wants to send {count} files",
            show_more_btn: "+{count} more",
            show_less_btn: "Show less",
            reject_btn: "Reject",
            accept_btn: "Accept",
            accept_anyway_btn: "Accept Anyway",
            settings_title: "ByteDrop Settings",
            done_btn: "Done",
            settings_theme_title: "Appearance Theme & Language",
            settings_theme_sub: "Saved to %APPDATA%\\ByteDrop\\config.json",
            theme_dark: "Dark",
            theme_light: "Light",
            settings_accent_title: "Accent Color",
            settings_accent_sub: "Customize UI glass accent palette",
            settings_dir_title: "Download Save Directory",
            change_folder_btn: "Change Folder",
            settings_ip_title: "Preferred LAN Network Adapter",
            settings_ip_sub: "Select IPv4 address used for local QR code",
            auto_detect_opt: "Auto-Detect",
            settings_cloud_title: "Cloud Link Auto-Start",
            settings_cloud_sub: "Start public cloud tunnel automatically on launch",
            restart_btn: "Restart",
            settings_auto_accept_title: "Auto-Accept Local Transfers",
            settings_auto_accept_sub: "Skip prompt for trusted local Wi-Fi devices",
            settings_max_folder_title: "Max Folder Share Size (GB)",
            settings_max_folder_sub: "Safety cap when zipping shared folders",
            settings_tray_title: "System Tray & Startup",
            settings_tray_sub: "Tray close behavior, start minimized, Windows login",
            settings_notif_title: "OS Toast Notifications & Session",
            settings_notif_sub: "Desktop alerts & instant session token rotation",
            regen_session_btn: "Regenerate Session",
            settings_diag_title: "Diagnostics & Logs",
            settings_diag_sub: "Inspect logs or copy support summary (tokens redacted)",
            open_logs_btn: "Open Log Folder",
            copy_diag_btn: "Copy Diagnostics",
            toggle_on: "On",
            toggle_off: "Off",
            tray_on: "Tray: On",
            tray_off: "Tray: Off",
            min_on: "Min: On",
            min_off: "Min: Off",
            win_on: "Win: On",
            win_off: "Win: Off",
            alerts_on: "Alerts: On",
            alerts_muted: "Alerts: Muted",
            tunnel_starting: "Starting",
            tunnel_starting_box: "Starting cloud tunnel...",
            tunnel_reconnecting: "Reconnecting",
            tunnel_reconnecting_box: "Reconnecting cloud tunnel...",
            tunnel_downloading: "Downloading ({progress}%)",
            tunnel_downloading_box: "Downloading cloudflared...",
            tunnel_online: "Online",
            tunnel_failed: "Failed ({reason})",
            tunnel_disabled: "Disabled",
            tunnel_disabled_box: "Cloud link disabled",
            tunnel_unavailable: "unavailable",
            log_queued: "Queued [{category}]: {name} ({size})",
            log_accepted: "Accepted: {name} ({size})",
            log_accepted_nosize: "Accepted: {name}",
            log_declined: "Declined: {name} ({size})",
            log_declined_nosize: "Declined: {name}",
            log_expired: "Expired: {name} ({size})",
            log_expired_nosize: "Expired: {name}",
            log_received: "Received [{category}]: {name} ({size})",
            log_rejected_item: "Rejected: {name} — {detail}",
            log_auto_accepted: "Auto-Accepted Local Transfer from {device} ({count} file(s))",
            log_session_regenerated: "Session token regenerated. Connected devices must re-scan QR.",
            log_error: "Error: {message}",
            log_history_item: "[{category}] {direction}: {name} ({size} • {timestamp})",
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
            brand_sub: "نقل الملفات المحلي والسحابي • v1.0.0",
            qr_local: "محلي",
            qr_cloud: "سحابي",
            qr_hotspot: "نقطة اتصال",
            qr_wifi: "واي فاي",
            qr_app_link: "رابط التطبيق",
            local_link_lbl: "رابط الواي فاي المحلي",
            cloud_link_lbl: "الرابط السحابي العام",
            cloud_link_warning: "يمكن لأي شخص لديه هذا الرابط إرسال طلبات نقل ملفات إليك. استخدم تجديد الجلسة لإلغائه.",
            copy_btn: "نسخ",
            copied_btn: "تم النسخ!",
            open_hotspot_settings: "فتح إعدادات نقطة اتصال ويندوز",
            hotspot_detected: "تم اكتشاف نقطة الاتصال",
            hotspot_help: "قم بتشغيل نقطة الاتصال في ويندوز، ثم امسح رمز QR الخاص بها.",
            hotspot_settings_error: "تعذر فتح إعدادات نقطة اتصال ويندوز.",
            devices_zero: "لا توجد أجهزة متصلة",
            devices_n: "{count} أجهزة متصلة",
            status_connecting: "جاري الاتصال...",
            status_reconnecting: "جاري إعادة الاتصال...",
            status_online: "متصل",
            status_offline: "غير متصل",
            status_disconnected_pc: "تم الفصل بواسطة الكمبيوتر",
            status_blocked_pc: "محظور بواسطة الكمبيوتر",
            connect_first_warn: "يرجى توصيل جهاز أولاً!",
            disconnect_btn: "فصل",
            disconnecting_btn: "جاري الفصل...",
            blocked_devices_title: "الأجهزة المحظورة",
            allow_btn: "سماح",
            drop_title: "اسحب وأفلت الملفات أو المجلدات هنا",
            drop_sub: "إشعار فوري • بث مقسم عالي السرعة • ضغط تلقائي للمجلدات",
            browse_files_btn: "تصفح الملفات",
            browse_folders_btn: "تصفح المجلدات",
            active_transfers_title: "عمليات النقل النشطة",
            transfers_idle: "لا توجد عمليات نقل نشطة",
            status_idle: "خامل",
            status_paused: "متوقف مؤقتاً",
            status_stalled: "متعثر",
            status_preparing: "جاري التحضير...",
            status_waiting_phone: "بانتظار الهاتف",
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
            disconnect_timeout_err: "تعذر فصل الجهاز. حاول مرة أخرى.",
            corrupt_config_reset: "ملف الإعدادات كان تالفاً وتمت إعادة ضبطه",
            state_cancelled: "ملغى",
            status_cancelled: "ملغى",
            status_cancelled_phone: "تم الإلغاء بواسطة الهاتف",
            status_rejected: "مرفوض",
            cancelled_by_pc: "تم الإلغاء بواسطة الكمبيوتر",
            cancel_all_btn: "إلغاء الكل",
            cancel_all_confirm: "هل أنت متأكد من إلغاء جميع عمليات النقل النشطة والمنتظرة؟",
            cancel_all_modal_title: "إلغاء جميع عمليات النقل",
            cancel_all_modal_desc: "هل أنت متأكد من إلغاء جميع عمليات النقل النشطة والمنتظرة؟",
            browser_download_tooltip: "قد تظهر قائمة تنزيلات المتصفح هذا التنزيل كمنقطع.",
            via_cloud: "سحابي",
            via_wifi: "واي فاي",
            cloud_slow_hint: "يتم استخدام الرابط السحابي (أبطأ). استخدم رابط الواي فاي لنقل أسرع.",
            cloud_large_file_hint: "ملف كبير عبر رابط الإنترنت — لسرعة أعلى، وصّل الجهازين بنفس شبكة الواي فاي أو نقطة اتصال الكمبيوتر.",
            eta_calculating: "جاري الحساب...",
            eta_left: "متبقي {eta}",
            active_count_label: "{count} نشط",
            batch_pos_tag: "{index}/{total}",
            preparing_archive: "جاري تحضير الأرشيف",
            preparing_archive_row: "جاري تحضير الأرشيف: {name} ({progress}%)",
            state_paused: "متوقف مؤقتاً",
            state_stalled: "متعثر",
            state_waiting: "بانتظار الموافقة",
            row_done_in: "اكتمل في {duration} (بمتوسط {avg})",
            pause_btn: "إيقاف مؤقت",
            resume_btn: "استئناف",
            cancel_btn: "إلغاء",
            clipboard_title: "مزامنة الحافظة",
            clip_auto_on: "تلقائي: مفعل",
            clip_auto_off: "تلقائي: متوقف",
            clip_send_btn: "نسخ وإرسال",
            clip_placeholder: "مزامنة النصوص بين الكمبيوتر والهواتف المتصلة...",
            history_title: "سجل النقل والنشاط المباشر",
            clear_history_btn: "مسح السجل",
            clear_history_modal_title: "مسح سجل النقل",
            clear_history_modal_desc: "هل أنت متأكد من مسح سجل عمليات النقل نهائياً؟",
            clear_all_btn: "مسح الكل",
            open_downloads_btn: "فتح التنزيلات",
            shared_pc_title: "ملفات مشاركة من الكمبيوتر",
            no_shared_files: "لا توجد ملفات مشاركة",
            no_activity: "لا يوجد نشاط نقل بعد",
            remove_btn: "حذف",
            incoming_title: "طلب نقل وارد من الهاتف",
            prompt_wants_single: "يرغب {sender} بإرسال {item}",
            prompt_wants_many: "يرغب {sender} بإرسال {count} ملفات",
            show_more_btn: "+{count} أخرى",
            show_less_btn: "عرض أقل",
            reject_btn: "رفض",
            accept_btn: "قبول",
            accept_anyway_btn: "قبول على أي حال",
            settings_title: "إعدادات بايت دروب",
            done_btn: "تم",
            settings_theme_title: "المظهر واللغة",
            settings_theme_sub: "محفوظة في %APPDATA%\\ByteDrop\\config.json",
            theme_dark: "داكن",
            theme_light: "فاتح",
            settings_accent_title: "اللون المميز",
            settings_accent_sub: "تخصيص ألوان الواجهة الزجاجية",
            settings_dir_title: "مجلد حفظ التنزيلات",
            change_folder_btn: "تغيير المجلد",
            settings_ip_title: "محول الشبكة المحلية المفضل",
            settings_ip_sub: "اختر عنوان IPv4 المستخدم لرمز QR المحلي",
            auto_detect_opt: "اكتشاف تلقائي",
            settings_cloud_title: "بدء الرابط السحابي تلقائياً",
            settings_cloud_sub: "تشغيل النفق السحابي تلقائياً عند فتح البرنامج",
            restart_btn: "إعادة تشغيل",
            settings_auto_accept_title: "قبول تلقائي للنقل المحلي",
            settings_auto_accept_sub: "تخطي نافذة التأكيد لأجهزة الواي فاي المحلية",
            settings_max_folder_title: "الحد الأقصى لحجم المجلد المشترك (GB)",
            settings_max_folder_sub: "سقف الأمان عند ضغط المجلدات المشتركة",
            settings_tray_title: "شريط النظام وبدء التشغيل",
            settings_tray_sub: "التصغير إلى الشريط، البدء مصغراً، والتشغيل مع ويندوز",
            settings_notif_title: "إشعارات النظام والجلسة",
            settings_notif_sub: "تنبيهات سطح المكتب وتجديد رمز الجلسة الفوري",
            regen_session_btn: "تجديد الجلسة",
            settings_diag_title: "التشخيص والسجلات",
            settings_diag_sub: "عرض ملفات السجل أو نسخ ملخص التشخيص (مع إخفاء الرموز)",
            open_logs_btn: "فتح مجلد السجلات",
            copy_diag_btn: "نسخ بيانات التشخيص",
            toggle_on: "مفعل",
            toggle_off: "متوقف",
            tray_on: "الشريط: مفعل",
            tray_off: "الشريط: متوقف",
            min_on: "مصغر: مفعل",
            min_off: "مصغر: متوقف",
            win_on: "ويندوز: مفعل",
            win_off: "ويندوز: متوقف",
            alerts_on: "التنبيهات: مفعلة",
            alerts_muted: "التنبيهات: مكتومة",
            tunnel_starting: "جاري البدء",
            tunnel_starting_box: "جاري بدء النفق السحابي...",
            tunnel_reconnecting: "إعادة الاتصال",
            tunnel_reconnecting_box: "جاري إعادة اتصال النفق السحابي...",
            tunnel_downloading: "جاري التنزيل ({progress}%)",
            tunnel_downloading_box: "جاري تنزيل cloudflared...",
            tunnel_online: "متصل",
            tunnel_failed: "فشل ({reason})",
            tunnel_disabled: "معطل",
            tunnel_disabled_box: "الرابط السحابي معطل",
            tunnel_unavailable: "غير متاح",
            log_queued: "في الانتظار [{category}]: {name} ({size})",
            log_accepted: "مقبول: {name} ({size})",
            log_accepted_nosize: "مقبول: {name}",
            log_declined: "مرفوض: {name} ({size})",
            log_declined_nosize: "مرفوض: {name}",
            log_expired: "منتهي الصلاحية: {name} ({size})",
            log_expired_nosize: "منتهي الصلاحية: {name}",
            log_received: "تم استلام [{category}]: {name} ({size})",
            log_rejected_item: "مرفوض: {name} — {detail}",
            log_auto_accepted: "قبول تلقائي لنقل محلي من {device} ({count} ملفات)",
            log_session_regenerated: "تم تجديد رمز الجلسة. يجب على الأجهزة إعادة مسح رمز QR.",
            log_error: "خطأ: {message}",
            log_history_item: "[{category}] {direction}: {name} ({size} • {timestamp})",
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
        const lang = langOverride && DICT[langOverride] ? langOverride : currentLang;
        const table = DICT[lang] || DICT.en;
        let str = table[key] !== undefined ? table[key] : (DICT.en[key] || key);
        if (vars && typeof vars === "object") {
            Object.keys(vars).forEach((k) => {
                str = str.replace(new RegExp(`\\{${k}\\}`, "g"), String(vars[k]));
            });
        }
        return str;
    }

    function setLanguage(lang) {
        currentLang = DICT[lang] ? lang : "en";
        const isAr = currentLang === "ar";
        if (typeof document !== "undefined" && document.documentElement) {
            document.documentElement.lang = currentLang;
            document.documentElement.dir = isAr ? "rtl" : "ltr";
            if (document.body) {
                document.body.classList.toggle("rtl-mode", isAr);
            }
            document.querySelectorAll("[data-i18n]").forEach((el) => {
                if (el.hasAttribute("data-dynamic")) return;
                const k = el.getAttribute("data-i18n");
                if (k) el.textContent = t(k);
            });
            document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
                if (el.hasAttribute("data-dynamic")) return;
                const k = el.getAttribute("data-i18n-placeholder");
                if (k) el.setAttribute("placeholder", t(k));
            });
        }
        return currentLang;
    }

    function renderConnectionStatus(model, lang) {
        const l = lang && DICT[lang] ? lang : currentLang;
        const m = model && typeof model === "object" ? model : { state: String(model || "offline"), count: 0 };
        const rawCount = typeof m.deviceCount === "number" ? m.deviceCount : m.count;
        if (typeof rawCount === "number" && !m.state) {
            const count = rawCount || 0;
            return {
                text: count > 0 ? t("devices_n", { count }, l) : t("devices_zero", {}, l),
                cssClass: count > 0 ? "status-badge online" : "status-badge"
            };
        }
        const st = String(m.state || "offline").toLowerCase();
        if (st === "connecting") {
            return { text: t("status_connecting", {}, l), cssClass: "status-badge connecting" };
        }
        if (st === "reconnecting") {
            return { text: t("status_reconnecting", {}, l), cssClass: "status-badge connecting" };
        }
        if (st === "kicked") {
            return { text: t("status_disconnected_pc", {}, l), cssClass: "status-badge warn" };
        }
        if (st === "blocked") {
            return { text: t("status_blocked_pc", {}, l), cssClass: "status-badge warn" };
        }
        if (st === "online") {
            const count = typeof rawCount === "number" ? rawCount : 1;
            return {
                text: count > 0 ? t("devices_n", { count }, l) : t("status_online", {}, l),
                cssClass: "status-badge online"
            };
        }
        return {
            text: typeof rawCount === "number" ? t("devices_zero", {}, l) : t("status_offline", {}, l),
            cssClass: "status-badge"
        };
    }

    const api = {
        DICT,
        dictionaries: DICT,
        t,
        setLanguage,
        getLanguage: () => currentLang,
        renderConnectionStatus
    };
    root.ByteDropDesktopI18n = api;
    if (typeof window !== "undefined") {
        window.ByteDropDesktopI18n = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : window);
