# faf-agent

faf-agent adalah asisten AI otonom untuk perangkat Android yang berjalan di lingkungan Termux (mendukung non-root dan root) dan dikendalikan melalui Telegram Bot. Agen ini memanfaatkan LLM function calling untuk mengontrol perangkat, menjalankan perintah sistem, mengelola berkas, dan menjalankan otomasi lokal.

## Panduan Instalasi

### 1. Prasyarat di Termux

Jalankan perintah berikut di Termux:

```bash
pkg update && pkg upgrade -y
pkg install python git termux-api tsu -y
```

Pastikan aplikasi Termux:API dari F-Droid sudah terpasang di perangkat serta izin sistem (kamera, notifikasi, penyimpanan) telah diberikan.

### 2. Kloning Repositori dan Dependensi

```bash
cd ~
git clone https://github.com/femas66/faf.git faf-agent
cd faf-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Konfigurasi (.env)

Salin berkas contoh konfigurasi:

```bash
cp .env.example .env
```

Isi nilai variabel penting di dalam berkas `.env`:

```env
TELEGRAM_BOT_TOKEN="token_bot_anda"
ALLOWED_TELEGRAM_USER_IDS="id_telegram_anda"
OPENAI_API_KEY="api_key_anda"
OPENAI_BASE_URL="https://api.openai.com/v1"
OPENAI_MODEL="gpt-4o"
```

### 4. Menjalankan Bot

```bash
python main.py
```
