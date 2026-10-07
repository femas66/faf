# 🤖 faf-agent: Autonomous AI Android Rooted Assistant via Telegram Bot

**faf-agent** adalah asisten kecerdasan buatan (AI) otonom yang berjalan langsung di perangkat fisik Android melalui lingkungan **Termux** (mendukung Non-Root via Termux:API & Superuser Root) dan dikendalikan sepenuhnya melalui antarmuka **Telegram Bot**.

Ditenagai oleh **LLM Function Calling (OpenAI-compatible)** dengan arsitektur asynchronous modern (`aiogram` v3 & `asyncio`), serta dipersenjatai dengan standar keamanan ketat: **Zero Trust User Whitelist**, **Destructive Guard (Inline Confirmation)**, **Anti Self-Termination (Process Immunity)**, **Anti-Prompt Injection**, dan **Realtime Subprocess Cancellation**.

---

## ⚡ Fitur Utama

- 📱 **100% Full Device Control (Android & Root)**:
  - Kontrol hardware: Senter (torch), WiFi, Data Seluler, Bluetooth, Volume, Kecerahan Layar, Mode DND.
  - Tangkapan layar (*screenshot*) dan foto kamera langsung (depan/belakang) yang otomatis dikirim ke chat Telegram.
  - Pasang Alarm jam tertentu, Timer hitung mundur, agenda Kalender, notifikasi pop-up, dan simpan Catatan cepat.
  - Buka aplikasi Android, cek status aplikasi, dan cari video di YouTube.
  - Manajemen proses (Top 10 CPU/RAM & kill process).
- 🛡️ **Standar Keamanan Absolut (Zero Trust & Process Immunity)**:
  - **User Whitelist**: Pesan dari user ID Telegram yang tidak terdaftar diabaikan seketika (*drop silently*).
  - **Destructive Guard**: Operasi shell berisiko tinggi (`rm`, `rm -rf`, `dd`, `mkfs`, `format`, `reboot`, `pm uninstall`, `pm clear`) dicegat dan memerlukan persetujuan tombol inline `[ ✅ Setujui ]` / `[ ❌ Tolak ]`.
  - **Process Immunity**: Kebal dari pembunuhan proses sendiri (`os.getpid()`), parent process, SSH (`sshd`), `tmux`, dan sesi Termux.
  - **Anti-Prompt Injection & Exfiltration**: Menolak kebocoran prompt internal dan memblokir akses ke berkas kredensial (`.env`, `id_rsa`, keystore, token).
- ⏱️ **Realtime Process Interruption**:
  - Batalkan eksekusi AI dan subprocess yang berjalan panjang seketika menggunakan `/cancel` atau tombol inline `[ ⎿ Batalkan ]`.
  - Mengembalikan status: `⎿ Interrupted · What should faf-agent do instead?`.
- ⚡ **Slash Commands Cepat**:
  - `/device` - Model HP, versi Android, RAM, & status Root.
  - `/battery` - Persentase baterai, status charging, suhu baterai.
  - `/top` - Ringkasan 10 proses teratas CPU & RAM.
  - `/apps` - Daftar aplikasi pihak ketiga terpasang.
  - `/wifi` & `/ping` - Status jaringan dan uji koneksi internet.
  - `/su <perintah>` - Eksekusi perintah root langsung tanpa LLM.
  - `/clear` - Bersihkan riwayat percakapan sesi AI.
  - `/help` - Panduan lengkap bot.

---

## 📂 Struktur Proyek

```text
faf-agent/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── README.md
├── main.py
├── src/
│   ├── __init__.py
│   ├── config.py             # Pydantic Settings & User Whitelist parsing
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── app.py            # Bot runner, Dispatcher, router setup
│   │   ├── handlers/
│   │   │   ├── commands.py   # Slash commands (/start, /device, /battery, /su, dll.)
│   │   │   └── chat.py       # Natural language agent loop & media sender
│   │   ├── middlewares/
│   │   │   └── auth.py       # Zero-trust whitelist authentication
│   │   └── ui/
│   │       ├── keyboards.py  # Inline confirmation & cancel keyboards
│   │       └── formatters.py # Markdown message formatters
│   ├── core/
│   │   ├── __init__.py
│   │   ├── agent.py          # FafAgent core loop, history, cancellation
│   │   ├── permissions.py    # Destructive guard, immunity, confirmation session
│   │   ├── android_bridge.py # Termux API & Root shell subprocess bridge
│   │   └── ai_client.py      # OpenAI-compatible API client wrapper
│   └── tools/                # Android Tools (Function Calling)
│       ├── __init__.py
│       ├── base.py           # BaseTool, ToolContext, ToolRegistry
│       ├── root_exec.py      # root_shell_exec tool
│       ├── system.py         # system_settings tool (wifi, torch, volume, dnd, dll.)
│       ├── productivity.py   # productivity_control tool (alarm, timer, note, dll.)
│       ├── reminder_mgr.py   # reminder_manager tool
│       ├── web_screenshot.py # web_screenshot tool (Chromium headless)
│       ├── media_downloader.py # media_downloader tool (yt-dlp)
│       ├── ocr.py            # ocr_extract tool (Tesseract / AI Vision)
│       └── file_mgr.py       # file_manager tool
├── skills/                   # Agent Skills (Troubleshooter, Humanizer, dll.)
│   ├── android-troubleshooter/
│   └── humanizer-id/
└── tests/
    ├── __init__.py
    ├── test_agent.py         # Test suite komprehensif
    └── test_ocr.py           # Test suite OCR tool
```

---

## 🚀 Panduan Instalasi di Termux (Android)

### 1. Prasyarat Lingkungan
Pastikan Termux dan paket pendukung telah terpasang di Android Anda:
```bash
# Update repository Termux
pkg update && pkg upgrade -y

# Pasang Python, Git, dan Termux-API
pkg install python git termux-api tsu -y

# Jika perangkat sudah di-root dengan Magisk / KernelSU / APatch, pastikan izin su aktif.
```
*Catatan: Pastikan aplikasi **Termux:API** dari F-Droid telah terpasang di Android dan seluruh izin aplikasi (Kamera, Notifikasi, Penyimpanan) telah diberikan.*

### 2. Kloning & Pengaturan Dependensi
```bash
# Masuk ke direktori kerja
cd ~/
git clone https://github.com/your-username/faf-agent.git
cd faf-agent

# Buat virtual environment Python
python -m venv .venv
source .venv/bin/activate

# Pasang dependensi
pip install -r requirements.txt
```

### 3. Konfigurasi Lingkungan (`.env`)
Salin file template `.env.example` ke `.env`:
```bash
cp .env.example .env
nano .env
```
Isi konfigurasi berikut:
```env
# Token bot Telegram dari @BotFather
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRstuVWXyz"

# ID Telegram Anda (dapat dicek via @userinfobot di Telegram)
ALLOWED_TELEGRAM_USER_IDS="987654321"

# LLM Provider (OpenAI, DeepSeek, Groq, OpenRouter, Ollama, dll.)
OPENAI_API_KEY="sk-..."
OPENAI_BASE_URL="https://api.openai.com/v1"
OPENAI_MODEL="gpt-4o"

# Pengaturan Keamanan
SECURITY_CONFIRMATION_TIMEOUT=60
ENABLE_ROOT_COMMANDS=true
COMMAND_TIMEOUT=30
```

### 4. Menjalankan Bot
```bash
# Menggunakan virtualenv yang aktif:
python main.py
```
Atau jalankan di background menggunakan `tmux` atau `nohup`:
```bash
tmux new -s faf-agent "python main.py"
```

---

## 🧪 Menjalankan Pengujian (Testing)

Proyek ini dilengkapi dengan test suite lengkap untuk memverifikasi keamanan dan eksekusi tools:
```bash
pytest -v
```

---

## 🔒 Standar Keamanan & Etika
Aplikasi ini dirancang khusus untuk administrasi dan otomasi perangkat pribadi milik pengguna sendiri. Semua perintah destruktif dipagari oleh konfirmasi manual pengguna, dan sistem dilengkapi proteksi anti-tamper untuk menjaga keutuhan sistem Android.
