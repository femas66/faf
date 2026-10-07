from __future__ import annotations

from typing import Any


def format_device_info(info: dict[str, Any]) -> str:
    """Format device information into clean plain text for mobile screens."""
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
        "Informasi Perangkat Android:\n\n"
        f"• Model: {mfg} {model}\n"
        f"• Versi Android: {android_ver} (SDK {sdk_ver})\n"
        f"• Status Root: {is_root}\n"
        f"• Lingkungan: {is_termux}\n"
        f"• RAM Total: {ram_total} MB\n"
        f"• RAM Tersedia: {ram_avail} MB ({ram_used_pct}% terpakai)"
    )


def format_battery_info(info: dict[str, Any]) -> str:
    """Format battery information into clean plain text."""
    pct = info.get("percentage", "N/A")
    status = info.get("status", "Unknown")
    temp = info.get("temperature", "N/A")
    plugged = info.get("plugged", "Unknown")

    temp_str = f"{temp} °C" if temp != "N/A" else "N/A"

    return (
        "Status Baterai:\n\n"
        f"• Persentase: {pct}%\n"
        f"• Status Pengisian: {status}\n"
        f"• Sumber Daya: {plugged}\n"
        f"• Suhu Baterai: {temp_str}"
    )


def format_help_message() -> str:
    """Generate help guide in clean plain text."""
    return (
        "faf-agent: Panduan Perintah & Kemampuan\n\n"
        "Perintah Cepat (Slash Commands):\n"
        "• /time - Waktu, tanggal, hari, dan zona waktu lengkap saat ini\n"
        "• /device - Info model perangkat, versi Android, RAM, & status root\n"
        "• /battery - Status persentase baterai, charger, & suhu\n"
        "• /top - Daftar proses sistem teratas\n"
        "• /apps - Daftar aplikasi pihak ketiga yang terpasang\n"
        "• /wifi - Status koneksi WiFi aktif\n"
        "• /ping - Tes koneksi internet ke 8.8.8.8\n"
        "• /su <perintah> - Eksekusi perintah root langsung tanpa LLM\n"
        "• /cancel - Batalkan tugas AI yang sedang berjalan\n"
        "• /clear - Bersihkan riwayat percakapan sesi AI saat ini\n"
        "• /help - Tampilkan panduan ini\n\n"
        "Perintah Bahasa Alami (Chat Langsung):\n"
        "• Ambil foto dengan kamera depan/belakang dan kirimkan ke saya\n"
        "• Rekam suara selama 5 detik lewat mikrofon dan kirimkan rekaman\n"
        "• Ucapkan 'Halo bos' dengan suara lantang lewat speaker ponsel\n"
        "• Ambil screenshot layar sekarang\n"
        "• Nyalakan senter, pindai jaringan WiFi sekitar, dan aktifkan hotspot\n"
        "• Pasang alarm besok jam 07:00 dan buat catatan belanja baru\n"
        "• Ketuk koordinat layar (tap 500 800) atau usap layar ke atas (swipe)\n"
        "• Tekan tombol home, buka aplikasi WhatsApp, dan putar musik\n"
        "• Kirim SMS ke 0812345678 atau cari nomor telepon di kontak\n"
        "• Baca file /sdcard/Notes/todo.txt baris 5 sampai 15\n"
        "• Edit atau ganti baris tertentu dalam berkas kode script.py\n"
        "• Cari file yang mengandung kata tertentu di direktori ini\n\n"
        "Catatan Keamanan:\n"
        "Setiap perintah berbahaya (hapus partisi, format, hapus folder, uninstall, reboot) akan memicu tombol konfirmasi persetujuan terlebih dahulu."
    )


def format_start_message(user_name: str) -> str:
    """Welcome greeting message in clean plain text."""
    return (
        f"Halo, {user_name}!\n\n"
        "Saya adalah faf-agent, asisten otonom untuk perangkat Android fisik Anda.\n"
        "Saya memiliki kendali penuh atas sistem Android (Termux API & Superuser Root).\n\n"
        "Ketik pesan apa saja atau gunakan perintah /help untuk melihat daftar instruksi."
    )
