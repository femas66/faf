from __future__ import annotations

from typing import Any


def format_device_info(info: dict[str, Any]) -> str:
    """Format device information into clean Markdown."""
    mfg = info.get("manufacturer", "Unknown")
    model = info.get("model", "Unknown")
    android_ver = info.get("android_version", "Unknown")
    sdk_ver = info.get("sdk_version", "N/A")
    is_root = "Aktif (Superuser)" if info.get("root_available") else "Tidak Aktif"
    is_termux = "Ya (Termux)" if info.get("is_termux") else "Bukan Termux"

    ram_total = info.get("total_ram_mb", 0)
    ram_avail = info.get("available_ram_mb", 0)
    ram_used_pct = info.get("used_ram_percent", 0)

    return (
        f"📱 **Informasi Perangkat Android**\n\n"
        f"• **Model:** `{mfg} {model}`\n"
        f"• **Versi Android:** `{android_ver}` (SDK `{sdk_ver}`)\n"
        f"• **Status Root:** `{is_root}`\n"
        f"• **Environment:** `{is_termux}`\n"
        f"• **RAM Total:** `{ram_total} MB`\n"
        f"• **RAM Tersedia:** `{ram_avail} MB` (Terpakai `{ram_used_pct}%`)\n"
    )


def format_battery_info(info: dict[str, Any]) -> str:
    """Format battery information into clean Markdown."""
    pct = info.get("percentage", "N/A")
    status = info.get("status", "Unknown")
    temp = info.get("temperature", "N/A")
    plugged = info.get("plugged", "Unknown")

    temp_str = f"{temp} °C" if temp != "N/A" else "N/A"

    return (
        f"🔋 **Status Baterai**\n\n"
        f"• **Persentase:** `{pct}%`\n"
        f"• **Status Pengisian:** `{status}`\n"
        f"• **Sumber Daya:** `{plugged}`\n"
        f"• **Suhu Baterai:** `{temp_str}`\n"
    )


def format_help_message() -> str:
    """Generate help guide with all available slash commands and tool capabilities."""
    return (
        "🤖 **faf-agent: Panduan Perintah & Kemampuan**\n\n"
        "**Perintah Cepat (Slash Commands):**\n"
        "• `/device` - Info model perangkat, versi Android, RAM, & root.\n"
        "• `/battery` - Status persentase baterai, charger, & suhu.\n"
        "• `/top` - Ringkasan proses CPU & RAM tertinggi.\n"
        "• `/apps` - Daftar aplikasi pihak ketiga terpasang.\n"
        "• `/wifi` - Status koneksi WiFi aktif.\n"
        "• `/ping` - Cek latensi koneksi internet (8.8.8.8).\n"
        "• `/su <perintah>` - Eksekusi perintah root langsung tanpa LLM.\n"
        "• `/cancel` - Batalkan tugas AI / subprocess yang sedang berjalan.\n"
        "• `/clear` - Bersihkan riwayat percakapan sesi AI saat ini.\n"
        "• `/help` - Tampilkan panduan ini.\n\n"
        "**Perintah Bahasa Alami (Natural Language):**\n"
        "Anda dapat meminta faf-agent melakukan apa saja di HP Anda, contoh:\n"
        "- *\"Ambil foto dengan kamera depan dan kirimkan ke saya\"*\n"
        "- *\"Ambil screenshot layar sekarang\"*\n"
        "- *\"Nyalakan senter dan pasang alarm besok jam 07:00\"*\n"
        "- *\"Buka aplikasi WhatsApp dan putar musik\"*\n"
        "- *\"Cari video tutorial Python di YouTube\"*\n"
        "- *\"Simpan catatan: beli kopi dan gula\"*\n\n"
        "🛡️ *Setiap perintah destruktif (hapus partisi, format, reboot) akan memicu tombol konfirmasi manual.*"
    )


def format_start_message(user_name: str) -> str:
    """Welcome greeting message."""
    return (
        f"👋 Halo, **{user_name}**!\n\n"
        "Saya adalah **faf-agent**, asisten otonom untuk perangkat Android fisik Anda.\n"
        "Saya memiliki kendali penuh atas sistem Android (Termux API & Superuser Root).\n\n"
        "Ketik pesan apa saja atau gunakan perintah `/help` untuk melihat daftar instruksi."
    )
