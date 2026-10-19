# faf-agent

> **Asisten AI Otonom untuk Android Fisik (Termux Root & Non-Root) via Telegram Bot**  
> *100% Pure Python · Zero Native Compilation · High-Performance Engine*

`faf-agent` adalah asisten AI otonom yang dirancang khusus untuk berjalan langsung pada perangkat fisik **Android** di lingkungan **Termux**. Dikendalikan penuh melalui antarmuka **Telegram Bot**, agen ini memanfaatkan kapabilitas *LLM Function Calling* (OpenAI-compatible protocol) untuk membaca sensor, mengelola berkas, mengontrol hardware, menjalankan otomasi, serta mengeksekusi perintah sistem root (superuser).

---

## ⚡ Keunggulan Arsitektur & Performa Terkini

`faf-agent` dibangun dengan arsitektur berkinerja tinggi yang telah dioptimalkan khusus untuk keterbatasan komputasi perangkat mobile:

1. **Pure-Python & Zero Native Compilation (Zero Rust/Maturin):**
   - Tidak memerlukan toolchain C/Rust berat seperti `pydantic-core` atau `maturin`. Kompatibel penuh dan instan di Termux ARM64.
2. **Intent Routing & Dynamic Tool Pruning (< 1ms):**
   - Pesan obrolan umum/sapaan memangkas 20 tools menjadi 0 tools, menghemat **~85% token prefill** dan merespons dalam waktu < 400ms.
   - Pilihan tool disesuaikan otomatis berdasarkan kategori (*System*, *Files*, *Web & Media*, *Dev & Advanced*, *Memory*).
3. **Progressive SSE Streaming & In-Place Editing:**
   - *Time To First Token (TTFT)* **< 500ms** di Telegram.
   - Menggunakan mekanisme *debounced message editing* (1.1 detik) yang halus dan mematuhi batas rate-limit Telegram API.
4. **Dual-Tier Model Architecture (Fast / Smart Strategy):**
   - Mendukung dua tier model sekaligus: `OPENAI_FAST_MODEL` (e.g. `gpt-4o-mini`, `gemini-2.5-flash`, atau Groq Llama-3.3-70B) untuk obrolan kasual dan aksi cepat, serta `OPENAI_SMART_MODEL` (e.g. `gpt-4o`, `claude-3-5-sonnet`) untuk tugas penalaran mendalam dan coding.
   - Pengguna dapat mengganti mode manual kapan saja lewat perintah `/mode [auto|fast|smart]`.
5. **Multi-Tool Concurrency:**
   - Eksekusi paralel untuk pemanggilan beberapa tool sekaligus via `asyncio.gather`.
6. **In-Memory Dirty-Flag Caching:**
   - Memori kognitif SQLite dan jembatan hardware memiliki KV-cache di memori RAM, menghasilkan 0 disk query per turn untuk data statis.
7. **Strict Mobile Screen UX Invariant:**
   - Format jawaban berupa **plain text bersih** (bebas tabel markdown/ASCII dan tanpa penebalan teks yang berantakan di layar ponsel).
   - Tepat **maksimal 2 balon chat** per interaksi (1 pesan pengguna + 1 respons bot).
8. **Keamanan Sistem Berlapis:**
   - **Anti-SSRF Protection:** Blokir akses ke IP privat RFC1918, metadata cloud, dan port sensitif.
   - **Path Traversal & Credential Guard:** Proteksi direktori sistem penting dan berkas kredensial (`.env`, `id_rsa`, keystore).
   - **Process & Power Immunity:** Mencegah penghentian proses kritis Android/Termux dan memblokir perintah shutdown/reboot tidak disengaja.
   - **Destructive Action Confirmation:** Tombol inline konfirmasi interaktif untuk perintah berisiko tinggi.

---

## 🛠️ Kemampuan & Toolset Lengkap (20 Tools Terintegrasi)

| Kategori | Tool Utama | Deskripsi Kemampuan |
|---|---|---|
| **⚙️ Sistem & Hardware** | `system_settings`, `device_interaction` | Kontrol WiFi, Bluetooth, senter, volume, info baterai, getaran, simulasi ketukan layar (*tap*), usapan (*swipe*), tombol fisik, dan input teks. |
| **📁 Berkas & Dokumen** | `file_manager`, `pdf_manager` | Membaca, menulis, mengedit, melihat struktur pohon direktori (*tree*), pencarian (*grep*), ekstraksi teks PDF, pencarian halaman PDF, penggabungan (*merge*), pembagian (*split*), dan pengisian formulir dokumen. |
| **📱 Aplikasi & Proses** | `package_manager`, `process_manager`, `root_shell_exec` | Membuka/menghentikan aplikasi Android (`am`/`pm`), daftar aplikasi terpasang, inspeksi proses sistem CPU/RAM (`top`), serta eksekusi shell root fallback (`tsu`/`su`). |
| **📷 Multimedia & OCR** | `media_control`, `ocr_extract` | Mengambil foto kamera depan/belakang, merekam mikrofon, memutar audio, Text-to-Speech (TTS), dan OCR teks gambar offline berbasis Tesseract. |
| **🌐 Web & Downloader** | `web_search`, `web_screenshot`, `media_downloader` | Penelusuran web cerdas, scraping konten bersih, tangkapan layar website via headless Chromium, dan unduhan video/audio/berkas via `yt-dlp` / `aria2c`. |
| **⏱️ Produktivitas & Jadwal** | `productivity_control`, `time_manager`, `reminder_manager`, `cronjob` | Pemasangan alarm fisik, timer, pengiriman SMS, panggilan telepon aman (anti kode MMI/USSD), pengingat Telegram terjadwal, dan cron worker berkala. |
| **🧠 Memori & Pengetahuan** | `memory_manager` | Penyimpanan memori fakta permanen pengguna, riwayat episode interaksi, dan Knowledge Graph RAG berbasis SQLite lokal. |
| **💻 Python REPL** | `python_repl` | Eksekusi kalkulasi rumit dan manipulasi data di sandbox Python in-memory. |

---

## 🚀 Panduan Instalasi di Termux (Android)

### 1. Persiapan Lingkungan Termux

Buka aplikasi **Termux** di perangkat fisik Android, lalu perbarui paket dan pasang dependensi dasar:

```bash
pkg update && pkg upgrade -y
pkg install python git termux-api tsu -y
```

> **PENTING:** Pastikan aplikasi pendamping **Termux:API** telah diinstal dari [F-Droid](https://f-droid.org/packages/com.termux.api/) dan semua izin Android (Penyimpanan, Kamera, Mikrofon, Notifikasi, Lokasi) telah diberikan pada setelan aplikasi Termux & Termux:API.

### 2. Kloning Repositori & Virtual Environment

```bash
cd ~
git clone https://github.com/femas66/faf.git faf-agent
cd faf-agent

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Diagnosis Kesiapan Tools Sistem

Jalankan script pemeriksa kesiapan alat untuk mengetahui dependensi sistem apa saja yang sudah atau belum terpasang:

```bash
python check_deps.py
```

Jika ada dependensi opsional yang ingin dipasang (seperti OCR atau pengunduh media):
```bash
# Dependensi media & OCR opsional:
pkg install yt-dlp aria2 tesseract -y
curl -L -o $PREFIX/share/tessdata/ind.traineddata https://github.com/tesseract-ocr/tessdata_fast/raw/main/ind.traineddata
```

### 4. Konfigurasi Lingkungan (`.env`)

Salin berkas contoh konfigurasi:

```bash
cp .env.example .env
nano .env
```

Sesuaikan nilai-nilai berikut:

```env
# Kredensial Bot Telegram
TELEGRAM_BOT_TOKEN="123456789:ABCDefGhIJKlmNoPQRstuVWXyz"
ALLOWED_TELEGRAM_USER_IDS="123456789"

# Konfigurasi LLM (OpenAI atau OpenAI-Compatible seperti Groq, OpenRouter, DeepSeek, Gemini)
OPENAI_API_KEY="sk-..."
OPENAI_BASE_URL="https://api.openai.com/v1"
OPENAI_MODEL="gpt-4o"

# Dual-Tier Model Strategy
OPENAI_FAST_MODEL="gpt-4o-mini"
OPENAI_SMART_MODEL="gpt-4o"

# Pengaturan Sistem & Keamanan
SECURITY_CONFIRMATION_TIMEOUT=60
ENABLE_ROOT_COMMANDS=true
COMMAND_TIMEOUT=30
LOG_LEVEL="WARNING"
```

### 5. Menjalankan Bot

```bash
python main.py
```

Untuk menjaga bot tetap berjalan di latar belakang saat Termux ditutup:
```bash
termux-wake-lock
tmux new -s faf
source .venv/bin/activate
python main.py
# Tekan Ctrl+B lalu D untuk detach dari tmux
```

---

## 💬 Daftar Perintah Slash (Telegram Bot Commands)

| Perintah | Deskripsi |
|---|---|
| `/start` | Sambutan awal dan perkenalan asisten. |
| `/help` | Panduan lengkap perintah cepat dan contoh bahasa alami. |
| `/mode` atau `/model` `[auto\|fast\|smart]` | Melihat atau mengubah mode kecepatan model AI (Fast: hemat & cepat, Smart: penalaran maksimal, Auto: otomatis adaptif). |
| `/doctor` atau `/check` | Memeriksa status instalasi dan kelengkapan tools di sistem Termux/Android. |
| `/device` | Menampilkan model perangkat, versi Android, RAM, dan status root. |
| `/battery` | Menampilkan persentase baterai, status pengisian daya, dan suhu. |
| `/time` atau `/jam` | Menampilkan waktu presisi, tanggal, hari, dan zona waktu lokal. |
| `/reminders` atau `/pengingat` | Menampilkan daftar pengingat dan cronjob yang sedang aktif. |
| `/top` | Menampilkan daftar proses sistem yang menggunakan CPU & RAM tertinggi. |
| `/apps` | Menampilkan daftar aplikasi pihak ketiga yang terpasang di perangkat. |
| `/wifi` | Memeriksa status koneksi WiFi aktif. |
| `/ping` | Menguji latensi koneksi internet ke 8.8.8.8. |
| `/su <perintah>` | Menjalankan perintah root shell langsung tanpa melalui penalaran LLM. |
| `/cancel` | Menghentikan paksa tugas AI yang sedang diproses. |
| `/clear` | Membersihkan riwayat percakapan sesi AI saat ini. |
| `/skills` | Menampilkan daftar custom skills yang terpasang dan statusnya. |
| `/skill_info <nama>` | Menampilkan detail parameter, izin yang diberikan, dan batas waktu skill. |
| `/skill_disable <nama>` | Menonaktifkan custom skill tertentu (mengubah status ke DEPRECATED). |
| `/skill_rollback <nama>` | Mengembalikan skill ke commit versi Git lokal sebelumnya (HEAD~1). |

---

## 📄 Penanganan Dokumen PDF Otomatis

Anda dapat mengirim berkas dokumen PDF secara langsung ke ruang obrolan Telegram bot:
- Bot otomatis menyimpan dokumen ke direktori `~/.faf_agent/documents/`.
- Sertakan teks pertanyaan/perintah pada caption dokumen (misal: *"Tolong ringkas poin penting pada bab 2 dokumen ini"*).
- Agen akan membaca, mencari bab relevan, atau menganalisis isinya secara cerdas menggunakan toolkit PDF murni Python.

---

## 🧩 Kemampuan Self-Extending Agent (Dynamic Custom Skills)

`faf-agent` dapat memperluas kapabilitasnya sendiri secara otonom saat menemui tugas atau otomasi perangkat yang belum didukung oleh tool bawaan, dengan **jaminan keamanan dan persetujuan pengguna**:

### 1. Prinsip Keamanan & Alur Kerja
1. **Deteksi & Pembuatan:** Saat pengguna meminta kemampuan baru, agen merancang modul skill Python terisolasi via tool `create_custom_skill`.
2. **Analisis Statis AST (Static Gate):** Kode diparsing untuk memblokir pemanggilan fungsi berbahaya (`eval`, `exec`, `compile`, `ctypes`, dunder reflection `__subclasses__`, serta akses file rahasia `.env`).
3. **Pengujian Terisolasi (Runner):** Script diuji otomatis pada subprocess terpisah (`python3 -I`) dengan *sanitized environment* (bebas dari API key/token), batas memori (256MB), batas output (64KB), dan timeout ketat.
4. **Self-Correction:** Jika terjadi kegagalan uji runtime atau pelanggaran AST, agen melakukan iterasi perbaikan mandiri hingga maksimal 3 kali.
5. **Persetujuan Eksplisit Pengguna (Human-in-the-Loop):** Skill **TIDAK PERNAH** aktif secara otomatis. Pengguna menerima ringkasan izin dan hasil uji di chat Telegram.
   - Ketik **`Ya`** untuk menyetujui dan mengaktifkan (berlaku 5 menit).
   - Ketik **`Tidak`** untuk membatalkan.
   - Ketik **`Lihat Kode`** untuk memeriksa seluruh kode sumber.
6. **Versioning Git Lokal:** Setiap skill yang disetujui di-commit secara otomatis ke Git lokal `custom_skills/` dan dicatat ke log audit `custom_skills/audit.jsonl`.

### 2. Struktur Modul Skill (`custom_skills/<nama_skill>/`)
```
custom_skills/<nama_skill>/
├── manifest.json   # Metadata, parameter JSON schema, izin deklaratif, status
├── main.py         # Entry point: def run(params: dict) -> dict
├── tests.json      # Minimal 3 kasus uji (input -> expected output)
└── CHANGELOG.md    # Catatan riwayat versi dan perubahan
```

---

## 🔒 Batas Keamanan Terbuka (Known Limitations & Security Boundaries)

Bekerja di lingkungan Android Termux tanpa root (*non-root*) memiliki batasan arsitektur fisik yang perlu dipahami secara transparan:

1. **Ketiadaan Kernel Network Namespaces:**
   - Tanpa root / `CAP_SYS_ADMIN`, Linux Android tidak mengizinkan pemanggilan `unshare(CLONE_NEWNET)`. Isolasi jaringan antar-proses ditegakkan pada tingkat aplikasi (AST static analyzer melarang modul `socket`, `urllib`, `requests` jika izin `network` kosong) dan verifikasi domain anti-SSRF, bukan firewall level kernel per-PID.
2. **Batas Memori Virtual vs Native Heap:**
   - `resource.setrlimit(RLIMIT_AS)` membatasi ruang alamat virtual, namun lonjakan alokasi memori drastis pada library native C dapat memicu *Low Memory Killer* (LMK) Android sebelum proses anak menerima sinyal SIGSEGV. Batas waktu eksekusi singkat (5–15 detik) dan pembatasan buffer output 64KB menjadi jaring pengaman utama.
3. **Paket Eksternal (Pip):**
   - Skill kustom dilarang melakukan instalasi paket pihak ketiga secara otomatis (`pip install`). Skill harus mengandalkan modul Python standar aman atau dependensi yang sudah terpasang.

---

## 🧭 Saran Langkah Pengembangan Berikutnya

1. **Dashboard CLI Lokal:** Membuat perintah pembantu `python -m src.custom_skills.cli` untuk menginspeksi atau mengaudit skill langsung dari terminal Termux tanpa membuka Telegram.
2. **Integrasi Root Execution Terpisah:** Untuk perangkat yang memiliki akses superuser (*rooted*), runner dapat diperluas dengan opsi isolasi namespace mount (`unshare -m`) untuk sandboxing filesystem tingkat kernel.
3. **Penyimpanan Metrik Penggunaan:** Mencatat frekuensi pemanggilan tiap custom skill dan latensi rata-rata ke tabel SQLite untuk rekomendasi deprecation skill yang jarang digunakan.

---

## 🧪 Pengujian Otomatis (Unit Testing)

Repositori ini dilengkapi dengan 230 unit test otomatis yang mencakup keamanan path, routing intent, isolasi REPL, mitigasi SSRF, progressive streaming, dual-tier model, analisis statis AST, subprocess runner sandbox, dan pipeline custom skills:

```bash
# Menjalankan seluruh test suite
pytest

# Menjalankan dengan laporan detail (verbose)
pytest -v

# Menjalankan suite custom skills
pytest tests/test_custom_skills_foundation.py -v
pytest tests/test_custom_skills_security_runner.py -v
pytest tests/test_custom_skills_pipeline.py -v
```

---

## 🔒 Lisensi

Didistribusikan di bawah lisensi MIT. Lihat berkas `LICENSE` jika tersedia untuk informasi lebih lanjut.
