from __future__ import annotations

import logging
import re
from typing import Any

from src.tools.base import ToolRegistry
from src.tools import default_registry

logger = logging.getLogger("faf_agent.router")

# Tool category cluster names
CATEGORY_CONVERSATION = "conversation"
CATEGORY_SYSTEM = "system"
CATEGORY_FILES = "files"
CATEGORY_WEB_MEDIA = "web_media"
CATEGORY_DEV_ADVANCED = "dev_advanced"
CATEGORY_MEMORY = "memory"
CATEGORY_RESEARCH = "research"
CATEGORY_ALL = "all"

TOOL_CLUSTERS: dict[str, set[str]] = {
    CATEGORY_SYSTEM: {
        "system_settings",
        "device_interaction",
        "productivity_control",
        "time_manager",
        "reminder_manager",
        "weather_forecast",
        "ask_clarification",
    },
    CATEGORY_FILES: {
        "file_manager",
        "pdf_manager",
        "code_to_image",
        "media_downloader",
        "ask_clarification",
    },
    CATEGORY_WEB_MEDIA: {
        "web_search",
        "browser_agent",
        "media_downloader",
        "web_screenshot",
        "ocr_extract",
        "media_control",
        "code_to_image",
        "ask_clarification",
    },
    CATEGORY_DEV_ADVANCED: {
        "package_manager",
        "process_manager",
        "python_repl",
        "root_shell_exec",
        "cronjob",
        "code_to_image",
        "ask_clarification",
    },
    CATEGORY_MEMORY: {
        "memory_manager",
        "ask_clarification",
    },
    CATEGORY_RESEARCH: {
        "research_paper",
        "tech_digest",
        "browser_agent",
        "pdf_manager",
        "web_search",
        "ask_clarification",
    },
}

CASUAL_PATTERNS = [
    r"^(halo|hai|hei|helo|hello|hi|p|tes|test|ping)(\s+(faf|bot|min|kawan|bro|sob|teman|assisten|asisten|ya|kak|bang|mas|mbak|gan))?[\s!\.?]*$",
    r"^(selamat\s+)?(pagi|siang|sore|malam)(\s+(faf|bot|min|kawan|bro|sob|teman|assisten|asisten|ya|kak|bang|mas|mbak|gan))?[\s!\.?]*$",
    r"^(assalamu['\s]?alaikum(\s+wr\s+wb)?|sampurasun)[\s!\.?]*$",
    r"^(terima\s+kasih|makasih|makasi|thanks|thank\s+you|syukron|maturnuwun)(\s+(ya|faf|bot|kawan|bro|sob|kak|bang|mas|mbak|gan|banyak))?[\s!\.?]*$",
    r"^(ok|oke|okee|sip|siap|mantap|yoi|baik|bagus|sipp)(\s+(ya|siap|faf|bot|kawan|bro|sob|kak|bang|mas|mbak|gan|deh|dong))?[\s!\.?]*$",
    r"^(siapa\s+(kamu|dirimu|anda|namamu)|kamu\s+siapa|nama\s+kamu\s+siapa)[\s!\.?]*$",
    r"^(siapa\s+yang\s+(membuatmu|menciptakanmu|develop))[\s!\.?]*$",
    r"^(apa\s+kabar|gimana\s+kabarnya|how\s+are\s+you)[\s!\.?]*$",
    r"^(dadah|bye|selamat\s+tinggal|sampai\s+jumpa)(\s+(faf|bot|kawan|bro|sob|kak|bang))?[\s!\.?]*$",
]

INFO_CREATIVE_PREFIXES = [
    r"^(buatkan|tuliskan|bikin)\s+(puisi|pantun|cerita|dongeng|lirik|surat|esai)",
    r"^(jelaskan|terangkan|ceritakan|apa\s+arti|apa\s+makna)\s+",
    r"^(apa\s+itu|apakah\s+yang\s+dimaksud|siapakah)\s+",
    r"^(kenapa|mengapa|bagaimana\s+cara\s+kerja)\s+",
    r"^(terjemahkan|translate)\s+",
]

ACTION_VERBS = {
    "jalankan", "eksekusi", "lakukan", "buka", "tutup", "nyalakan", "matikan",
    "atur", "aturkan", "ubah", "ganti", "hapus", "buat", "buatkan", "bikin",
    "simpan", "kirim", "ambil", "cek", "periksa", "pasang", "install",
    "uninstall", "restart", "reboot", "stop", "start", "run", "do", "execute",
    "open", "close", "set", "change", "delete", "create", "save", "send",
    "check", "inspect", "play", "unduh", "download", "scan",
}

SYSTEM_KEYWORDS = {
    "baterai", "battery", "batre", "daya", "charger", "cas", "charging",
    "wifi", "wi-fi", "hotspot", "tethering", "seluler", "cellular", "roaming", "sinyal",
    "bluetooth", "bt", "nfc", "gps", "lokasi", "koordinat",
    "senter", "torch", "flashlight",
    "volume", "audio", "suara", "hening", "silent", "dering", "ringtone", "mute", "unmute", "dnd",
    "kecerahan", "brightness", "layar", "screen", "rotasi", "landscape", "potret", "portrait", "resolusi", "getar", "vibrate",
    "jam", "waktu", "tanggal", "uptime", "countdown", "timer", "stopwatch", "kalender",
    "alarm", "bangunkan", "jadwal", "pengingat", "ingatkan", "reminder", "agenda",
    "cuaca", "hujan", "weather", "suhu", "temperatur", "ramalan", "mendung", "prakiraan",
    "sms", "telepon", "panggilan", "call", "kontak", "bts", "clipboard",
    "tap", "tekan", "sentuh", "swipe", "scroll", "geser", "ketik", "back", "home", "recents", "notifikasi",
    "notif", "baca notifikasi", "otp", "inspect ui", "elemen layar", "hierarki ui", "tombol layar",
}

FILE_KEYWORDS = {
    "file", "berkas", "folder", "direktori", "directory", "path", "dokumen",
    "txt", "log", "csv", "json", "xml", "zip", "tar", "gz", "pdf", "ipynb", "notebook", "jupyter",
    "py", "go", "php", "sql", "html", "css", "js", "ts", "sh", "rs", "cpp", "java",
    "baca file", "tulis file", "edit file", "hapus file", "cari file", "buat file",
    "simpan file", "salin file", "pindah file", "list file", "baca pdf", "cari teks",
    "/sdcard", "/data", "/storage", "~/", "documents", "download",
    "downloadkan", "mendownload", "unduh", "mengunduh", "diunduh", "unduhkan",
    "font", "fonts", "nerd font", "nerdfont", "jetbrains", "fira code", "hack font", "cascadia",
    "huruf", "tipografi", "ttf", "otf", "woff", "arsip", "ekstrak",
}

WEB_MEDIA_KEYWORDS = {
    "cari web", "cari di web", "cari internet", "gugling", "googling", "riset",
    "web search", "search web", "browsing", "internet", "website", "url", "situs", "link", "tautan", "http", "https",
    "browser", "browser agent", "buka web", "klik web", "klik tombol", "isi form", "web pdf", "simpan pdf web", "scroll web",
    "download", "unduh", "downloadkan", "mendownload", "mengunduh", "diunduh", "unduhkan",
    "unduh font", "download font", "downloadkan font",
    "font", "fonts", "nerd font", "nerdfont", "jetbrains", "fira code", "hack font", "cascadia",
    "huruf", "tipografi", "ttf", "otf", "video", "youtube", "yt", "tiktok", "instagram", "ig", "twitter", "x.com",
    "yt-dlp", "aria2", "torrent", "magnet", "mp3", "mp4",
    "screenshot", "screenshot web", "tangkapan layar", "tangkapan layar web", "web screenshot",
    "screenshot kode", "code to image", "code_to_image", "codesnap", "gambar kode", "teks jadi gambar",
    "vscode", "vs code", "dark+", "render kode", "render gambar", "ubah jadi gambar", "jadikan gambar",
    "golang", "php", "sql", "html", "bash", "typescript", "javascript",
    "ocr", "ekstrak teks", "baca gambar", "tesseract", "scan teks", "foto dokumen",
    "musik", "lagu", "play", "pause", "kamera", "foto", "fotonya", "gambar", "gambarnya", "jepret",
    "rekam suara", "mikrofon", "tts", "bicara",
}

DEV_ADVANCED_KEYWORDS = {
    "app", "aplikasi", "apk", "package", "install", "uninstall", "force stop", "current app",
    "running app", "buka aplikasi", "tutup aplikasi", "daftar aplikasi", "pm", "am",
    "process", "proses", "pid", "top cpu", "cpu", "ram", "memori linux", "kill", "ps",
    "bersihkan ram", "clean ram", "memory pressure", "tekanan memori", "oom", "zram", "swap", "drop caches",
    "python", "repl", "eksekusi kode", "script", "hitung", "kalkulasi", "evaluasi",
    "ipynb", "notebook", "jupyter",
    "golang", "go", "php", "sql", "html", "css", "bash", "shell", "javascript", "js", "typescript", "ts", "rust", "c++", "java",
    "screenshot kode", "screenshot", "code to image", "code_to_image", "codesnap", "gambar kode",
    "teks jadi gambar", "vscode", "vs code", "dark+",
    "root", "su", "tsu", "shell", "terminal", "command", "perintah shell", "dmesg", "logcat",
    "cron", "cronjob", "watcher", "pemantauan", "berkala", "otomasi", "tick", "sensor watcher",
}

MEMORY_KEYWORDS = {
    "ingat", "catat", "preferensi", "simpan preferensi", "nama saya", "saya suka", "hobi saya",
    "makanan favorit", "rutinitas", "fakta tentang saya", "fakta", "memori permanen",
    "graf pengetahuan", "knowledge graph", "relasi entitas", "episode", "riwayat tugas",
}

RESEARCH_KEYWORDS = {
    "paper", "jurnal", "journal", "arxiv", "semantic scholar", "sitasi", "citation", "bibtex", "literatur",
    "doi", "perpustakaan paper", "library paper", "referensi ilmiah", "publikasi ilmiah",
    "digest", "tech digest", "berita teknologi", "berita tech", "berita siber", "tech news", "hacker news",
    "github trending", "rss", "sumber rss", "topik digest", "ringkasan berita",
}


def _matches_any_keyword(text: str, keywords: set[str]) -> bool:
    """Check if text contains any of the given keywords or phrases safely."""
    for kw in keywords:
        if " " in kw or "/" in kw or "-" in kw or "." in kw:
            if kw in text:
                return True
        else:
            if re.search(rf"\b(meng|peng|men|pen|me|di|pe|ter)?{re.escape(kw)}(kan|i|an|nya)?\b", text):
                return True
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return True
    return False


class ToolRouter:
    """Lightweight pure-Python intent matcher and dynamic tool pruner (< 1ms).

    Reduces token prefill from ~14.500 to ~1.500 tokens for casual chats (0 tools)
    and ~2.500 - 3.500 tokens for domain-specific tasks.
    Falls back to ALL tools whenever ambiguity or multi-domain intent is detected.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        custom_skill_registry: Any = None,
    ) -> None:
        self.registry = registry or default_registry
        self.custom_skill_registry = custom_skill_registry

    def classify_categories(
        self,
        message: str,
        history: list[dict[str, Any]] | None = None,
    ) -> set[str]:
        """Classify message into set of tool categories."""
        text = message.strip().lower()
        if not text:
            return {CATEGORY_CONVERSATION}

        matched: set[str] = set()
        if _matches_any_keyword(text, SYSTEM_KEYWORDS):
            matched.add(CATEGORY_SYSTEM)
        if _matches_any_keyword(text, FILE_KEYWORDS) or re.search(r"(\.txt|\.pdf|\.log|\.json|\.csv|\/sdcard|\/data|~\/)", text):
            matched.add(CATEGORY_FILES)
        if _matches_any_keyword(text, WEB_MEDIA_KEYWORDS) or re.search(r"https?://|www\.", text):
            matched.add(CATEGORY_WEB_MEDIA)
        if _matches_any_keyword(text, DEV_ADVANCED_KEYWORDS):
            matched.add(CATEGORY_DEV_ADVANCED)
        if _matches_any_keyword(text, MEMORY_KEYWORDS):
            matched.add(CATEGORY_MEMORY)
        if _matches_any_keyword(text, RESEARCH_KEYWORDS):
            matched.add(CATEGORY_RESEARCH)

        # Context-aware fallback: check recent history if message is short or clarifying
        if history and len(history) > 1:
            last_assistant = None
            for prev in reversed(history):
                if prev.get("role") == "assistant":
                    last_assistant = prev
                    break
            # If previous assistant asked a question or called a tool
            if last_assistant and last_assistant.get("tool_calls"):
                for tc in last_assistant.get("tool_calls", []):
                    tc_fn = tc.get("function", {}).get("name", "")
                    for cat, tools in TOOL_CLUSTERS.items():
                        if tc_fn in tools:
                            matched.add(cat)

        if matched:
            return matched

        # If no domain keyword matched:
        # 1. Check if casual / greeting
        for pat in CASUAL_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return {CATEGORY_CONVERSATION}

        # 2. Check if general knowledge / creative writing
        for prefix in INFO_CREATIVE_PREFIXES:
            if re.search(prefix, text, re.IGNORECASE):
                return {CATEGORY_CONVERSATION}

        # 3. Fallback to ALL tools for any unrecognized or ambiguous intent
        return {CATEGORY_ALL}

    def get_tool_names(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
    ) -> set[str] | None:
        """Return the set of tool names needed for user_message.

        Returns:
            set[str]: specific subset of tool names.
            set(): empty set if 0 tools needed (pure conversation).
            None: all tools should be provided (fallback).
        """
        categories = self.classify_categories(user_message, history=history)

        if CATEGORY_ALL in categories:
            return None

        if CATEGORY_CONVERSATION in categories:
            return set()

        tool_names: set[str] = set()
        for cat in categories:
            tool_names.update(TOOL_CLUSTERS.get(cat, set()))

        return tool_names

    def get_tools_for_message(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]] | None:
        """Return list of OpenAI tool schemas filtered for the message.

        Returns:
            list[dict]: tool schemas for OpenAI function calling.
            None: when 0 tools are needed (LLM call will omit 'tools' payload).
        """
        registry = self.registry or default_registry
        tool_names = self.get_tool_names(user_message, history=history)

        # Retrieve relevant active custom skills (top-k) to prevent token bloat
        try:
            csr = self.custom_skill_registry
            if csr is None:
                from src.custom_skills.registry import custom_skill_registry as global_csr
                csr = global_csr
            matched_custom_skills = csr.get_top_k(user_message, k=3)
            custom_schemas = [s.to_openai_tool() for s in matched_custom_skills]
        except Exception as e:
            logger.debug(f"Could not load custom skills for routing: {e}")
            custom_schemas = []

        if tool_names is None:
            # Fallback to all registered tools
            all_tools = registry.get_openai_tools()
            existing_names = {t["function"]["name"] for t in all_tools if "function" in t}
            for cs in custom_schemas:
                if cs.get("function", {}).get("name") not in existing_names:
                    all_tools.append(cs)
            return all_tools

        if len(tool_names) == 0:
            # Pure conversation (greetings, smalltalk, creative writing): 0 tools
            return None

        # Filter registry tools and append matched custom skills
        selected_tools = [tool.to_openai_tool() for tool in registry.get_all() if tool.name in tool_names]
        selected_names = {t["function"]["name"] for t in selected_tools if "function" in t}
        for cs in custom_schemas:
            if cs.get("function", {}).get("name") not in selected_names:
                selected_tools.append(cs)

        return selected_tools


# Singleton default router
tool_router = ToolRouter()
