# AGENTS.md — Panduan & Standar Pengembang AI faf-agent

Dokumen ini adalah **sumber kebenaran tunggal (Single Source of Truth)** bagi agen AI koding (Claude Code, Antigravity, OpenAI Codex, Copilot, Cursor, Windsurf, dll.) dan pengembang manusia yang berkontribusi pada repositori `faf-agent`.

---

## 1. Ikhtisar & Arsitektur Proyek

`faf-agent` adalah asisten AI otonom yang dirancang khusus untuk perangkat fisik **Android** yang berjalan di lingkungan **Termux** (mendukung mode *non-root* dan *root/superuser*), dikendalikan sepenuhnya melalui antarmuka **Telegram Bot**. Agen ini memanfaatkan model LLM dengan kapabilitas *function calling* (OpenAI-compatible API) untuk mengontrol perangkat, membaca sensor, mengelola berkas, mengeksekusi automasi, dan menjalankan tugas sistem.

### Struktur Direktori Utama

```
faf-agent/
├── AGENTS.md                 # Standar dan aturan agen AI (dokumen ini)
├── CLAUDE.md                 # Petunjuk singkat untuk Claude Code (mengarahkan ke AGENTS.md)
├── README.md                 # Dokumentasi umum & panduan instalasi pengguna
├── audit_report.md           # Laporan audit arsitektur, keamanan, dan checklist perbaikan
├── check_deps.py             # Script CLI pemeriksa dependensi Termux & tools sistem
├── main.py                   # Entry point utama aplikasi bot
├── pyproject.toml            # Metadata proyek & konfigurasi build/pytest
├── requirements.txt          # Dependensi Python murni (Zero Maturin / Zero Rust)
├── docs/                     # Dokumen rencana arsitektur dan spesifikasi
├── skills/                   # Kumpulan panduan/skill operasional agen (ambiguity, troubleshooter, dll.)
│   ├── ambiguity-handler/    # Panduan klarifikasi proaktif untuk instruksi ambigu
│   ├── android-troubleshooter/ # Diagnostik baterai, thermal, dan konektivitas Android
│   ├── humanizer-id/         # Standar bahasa Indonesia alami & bebas AI buzzwords
│   ├── pdf/                  # Toolkit manipulasi & ekstraksi dokumen PDF
│   └── termux-web-deploy/    # Otomasi deployment web daemon di Termux
├── src/                      # Source code aplikasi
│   ├── config.py             # Settings berbasis Pure-Python (@dataclass + python-dotenv)
│   ├── bot/                  # Lapisan Telegram Bot
│   │   ├── app.py            # Lifecycle Application, single instance lock, shutdown handler
│   │   ├── handlers/         # Chat handler & slash command handlers (/start, /help, /su, dll.)
│   │   ├── middlewares/      # Whitelist otentikasi user ID Telegram
│   │   └── ui/               # Formatters teks & inline keyboard buttons
│   ├── core/                 # Komponen inti agen AI & interaksi sistem
│   │   ├── agent.py          # LLM loop, prompt injection guard, history trimmer, format sanitizer
│   │   ├── ai_client.py      # HTTP client asinkron (httpx) dengan connection pooling & lazy init
│   │   ├── android_bridge.py # Jembatan eksekusi shell, Termux:API, & proses background
│   │   ├── diagnostics.py    # Mesin inspeksi dependensi binary sistem Android & Python
│   │   ├── memory_store.py   # SQLite Cognitive Memory (Fakta permanen, episode, Graf RAG)
│   │   ├── path_security.py  # Wrapper re-export helper keamanan path
│   │   └── permissions.py    # Intersepsi perintah berbahaya, imunitas proses, konfirmasi user
│   └── tools/                # Registri tool yang dipanggil LLM (OpenAI Tool Calling)
│       ├── base.py           # BaseTool, ToolContext, ToolResult, ToolRegistry
│       ├── clarification.py  # Tool ask_clarification untuk klarifikasi terstruktur
│       ├── path_security.py  # Validasi traversal, SSRF, & proteksi kredensial
│       ├── file_mgr.py       # Manipulasi berkas aman (read/write/edit/tree/grep)
│       ├── pdf_mgr.py        # Ekstraksi dan pencarian teks dokumen PDF
│       ├── system.py         # Pengaturan perangkat (WiFi, Bluetooth, senter, volume, baterai)
│       ├── productivity.py   # Alarm fisik, timer, kalender, SMS, panggilan aman
│       ├── media.py          # Kamera, mikrofon, pemutar audio, text-to-speech
│       ├── package_mgr.py    # Manajemen aplikasi Android (pm, am, current app)
│       ├── process_mgr.py    # Monitor & kontrol proses Linux/Android
│       ├── device_interaction.py # Otomasi sentuhan layar (tap, swipe, keyevent, input text)
│       ├── reminder_mgr.py   # Pengingat pesan Telegram terjadwal
│       ├── cronjob_mgr.py    # Cron worker untuk automasi berkala & sensor watcher
│       ├── weather_mgr.py    # Prediksi cuaca & deteksi potensi hujan (Open-Meteo)
│       ├── web_search.py     # Penelusuran web & scraping bersih
│       ├── web_screenshot.py # Tangkapan layar web via headless Chromium
│       ├── media_downloader.py # Unduh media via yt-dlp/aria2c dengan guard anti-SSRF
│       ├── ocr.py            # OCR offline berbasis Tesseract
│       ├── memory_mgr.py     # Tool kontrol memori permanen & knowledge graph
│       ├── research_mgr.py   # Asisten riset paper (arXiv, Semantic Scholar, sitasi, perpustakaan)
│       ├── tech_digest.py    # Digest harian berita siber & teknologi (HN, GitHub, RSS)
│       ├── safe_http.py      # Helper HTTP anti-SSRF dengan batas ukuran & validasi redirect
│       ├── python_repl.py    # In-memory Python REPL untuk kalkulasi rumit
│       └── root_exec.py      # Fallback shell root (tsu/su) dengan konfirmasi keamanan
└── tests/                    # Pengujian otomatis berbasis pytest & pytest-asyncio
```

---

## 2. Invarian Arsitektur & Batasan Kritis (Strict Invariants)

Aturan-aturan berikut **TIDAK DAPAT DITAWAR** saat memodifikasi atau memperluas kode:

### A. Pure-Python & Zero Native Compilation (Zero Maturin / Zero Rust)
- Lingkungan target adalah **Termux pada Android fisik (ARM64)**.
- Di Termux, kompilasi binary C/Rust (seperti `pydantic-core`, `maturin`, `orjson`, `cryptography` dari source) sering kali gagal atau membutuhkan toolchain compiler yang sangat berat.
- **Dilarang keras** menambahkan dependensi yang membutuhkan kompilasi native atau Rust/Maturin.
- Gunakan `@dataclass` bawaan Python, `typing`, dan modul standar (`re`, `shlex`, `pathlib`, `json`, `sqlite3`, `fcntl`).
- Konfigurasi aplikasi harus tetap menggunakan `dataclass` murni di `src/config.py` yang membaca dari `os.environ` dan `python-dotenv`.

### B. Keamanan Perangkat & Batasan Fisik (Hard Security Guardrails)
1. **Proteksi Daya (Power Guard):**
   - **DILARANG KERAS** mengeksekusi perintah yang mematikan atau me-reboot perangkat (`reboot`, `shutdown`, `poweroff`, `halt`, `init 0`, `sysrq-trigger`, `svc power shutdown`, `battery set level 0`).
   - Mencegah ponsel mati di background **HANYA** melalui `termux-wake-lock` atau konfigurasi baterai Unrestricted, **BUKAN** membunuh proses manajemen daya Android.
2. **Imunitas Proses Inti (Process Immunity):**
   - Jangan pernah mengizinkan penghentian proses `faf-agent`, `python`, `sshd`, `tmux`, atau `com.termux`.
   - Jangan pernah membunuh proses sistem inti Android (`system_server`, `surfaceflinger`, `lmkd`, `servicemanager`, `init`). Membunuh proses ini akan memicu *Kernel Watchdog Panic* yang mematikan ponsel seketika.
3. **Pencegahan Eksfiltrasi Kredensial:**
   - Dilarang membaca atau mengirimkan berkas sensitif (`.env`, `id_rsa`, `id_ed25519`, `keystore`, token Telegram, API key) ke luar jaringan.
   - Semua path yang diakses berkas wajib divalidasi melalui helper `src/tools/path_security.py`.
4. **Pencegahan SSRF (Server-Side Request Forgery):**
   - Tool unduhan (`MediaDownloaderTool`) dan web scraping (`WebSearchTool`) **WAJIB** memvalidasi URL menggunakan `_check_url_safety`.
   - Tolak akses ke IP privat RFC1918 (`10.x`, `172.16.x`, `192.168.x`), loopback (`127.0.0.1`, `localhost`), dan metadata cloud (`169.254.169.254`).
5. **Proteksi Dialing USSD/MMI:**
   - Fitur telepon pada `ProductivityControlTool` menolak nomor yang memuat karakter `*` atau `#` untuk mencegah eksekusi kode MMI/USSD reset pabrik (seperti `*2767*3855#`).

### C. Antarmuka Obrolan Telegram & Persona Teks (Mobile Screen UX)
1. **Format Jawaban Plain Text Murni:**
   - Pengguna membaca tanggapan di layar smartphone.
   - Output percakapan **TIDAK BOLEH** menggunakan format markdown tebal (`**teks**`), miring (`*teks*`), backtick (` `teks` `), codeblocks (```), atau heading (`#`).
   - **DILARANG MENAMPILKAN TABEL DALAM BENTUK APAPUN** (baik tabel markdown `|` maupun tabel ASCII `+---+`). Tabel akan hancur dan tidak terbaca di layar HP.
   - Pengecualian tunggal: Format markdown hanya diperbolehkan jika pengguna secara eksplisit meminta membuat atau mengedit berkas dokumen `.md`.
2. **Gaya Bicara Alami & To-The-Point:**
   - Bersikap santai, ramah, dan manusiawi. Hindari gaya bahasa kaku seperti mesin customer service.
   - Jangan mengumbar menu fitur atau kemampuan bot kecuali diminta secara spesifik.
   - Jika disapa santai ("Halo", "P", "Pagi"), balas dengan santai dan singkat ("Halo! Ada yang bisa dibantu?").
3. **Maksimal 2 Balon Chat:**
   - Setiap interaksi pengguna idealnya menghasilkan 1 balon jawaban teks bot (didahului indikator `typing...`), ditambah berkas media jika memang ada foto/dokumen yang dihasilkan.

### D. Penanganan Ambiguitas & Klarifikasi Proaktif (`skills/ambiguity-handler`)
- **DILARANG MENEBAK PARAMETER ATAU MEMBUAT ASUMSI SEPIHAK.**
- Jika path penyimpanan tidak jelas (contoh: "buatkan file data.txt"), tanyakan folder tujuan (`~/`, `/sdcard/Documents/`, dll.).
- Jika waktu tidak spesifik (contoh: "pasang alarm jam 7"), tanyakan apakah jam 07:00 pagi atau 19:00 malam.
- Jika target jamak (contoh: "kirim SMS ke Budi"), tanyakan kontak mana yang dimaksud.
- Pertanyaan klarifikasi harus **singkat, padat, langsung ke inti**, tanpa basa-basi pembuka yang bertele-tele, disertai pilihan konkret.

### E. Siklus Hidup Koneksi & Konkurensi
1. **Single Instance Lock:**
   - `SingleInstanceLock` berbasis `fcntl.flock` memastikan hanya ada satu instance bot yang berjalan pada perangkat fisik untuk mencegah error `409 Conflict` dari Telegram polling.
2. **Connection Pooling pada AIClient:**
   - Gunakan instance `httpx.AsyncClient` tunggal yang di-reuse antar tool call. Jangan membuat instance baru pada setiap langkah loop agent.
   - Tutup klien secara aman pada callback `on_shutdown`.
3. **Manajemen Memori SQLite:**
   - Akses SQLite pada `MemoryStore` dilindungi oleh `threading.RLock` dan setiap koneksi wajib ditutup secara bersih (bebas dari file descriptor leaks).

---

## 3. Perintah Pengembangan & Verifikasi (CLI Reference)

Gunakan perintah-perintah berikut selama pengembangan:

### Menjalankan Pengujian
```bash
# Menjalankan seluruh test suite
pytest

# Menjalankan pengujian secara verbose
pytest -v

# Menjalankan test pada file tertentu
pytest tests/test_agent.py -v
pytest tests/test_path_security.py -v
pytest tests/test_pdf_mgr.py -v

# Menjalankan test berdasarkan kata kunci (filter)
pytest -k "security or memory" -v
```

### Memeriksa Dependensi & Kesiapan Perangkat
```bash
# Diagnostik kelengkapan tools di Termux/Android
python check_deps.py
```

### Menjalankan Bot
```bash
# Menjalankan bot secara lokal atau di Termux
python main.py
```

### Integrasi RTK (Rust Token Killer)
Sesuai aturan global pengguna, jika perintah git/shell dijalankan, RTK hook aktif secara otomatis:
```bash
rtk gain              # Menampilkan analitik penghematan token
rtk gain --history    # Riwayat perintah dengan penghematan
rtk discover          # Menganalisis peluang penghematan yang terlewat
rtk proxy <cmd>       # Eksekusi perintah mentah tanpa filter (untuk debugging)
```

---

## 4. Panduan Menambahkan Tool Baru

Untuk menambahkan tool baru ke dalam ekosistem `faf-agent`:

1. **Buat file modul tool di `src/tools/<nama_tool>.py`**:
   - Turunkan class dari `BaseTool` (`src/tools/base.py`).
   - Tentukan atribut `name`, `description`, dan skema `parameters` (mengikuti format JSON Schema OpenAI).
   - Implementasikan method `async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult`.
   - Pastikan mengembalikan `ToolResult(success=True/False, output="...", media_path=..., error=...)`.

2. **Daftarkan di `src/tools/__init__.py`**:
   - Import class tool dan daftarkan ke dalam `create_default_registry()`:
     ```python
     registry.register(NamaToolBaru())
     ```
   - Tambahkan nama class ke list `__all__`.

3. **Perbarui `SYSTEM_PROMPT` di `src/core/agent.py`**:
   - Berikan nomor dan deskripsi peran tool secara ringkas dan tegas agar LLM memahami kapan harus memanggil tool tersebut.

4. **Tulis Unit Test di `tests/test_<nama_tool>.py`**:
   - Uji skenario sukses, skenario kegagalan argumen, dan keamanan input.
   - Pastikan pengujian berjalan di `pytest`.

---

## 5. Konvensi Kode & Standar Penulisan

- **Python Versi:** Minimal Python 3.11+.
- **Type Annotations:** Wajib menggunakan *strict type hinting* modern (`from __future__ import annotations`, `str | None`, `list[dict[str, Any]]`).
- **Logging:** Gunakan logger terstandarisasi:
  ```python
  import logging
  logger = logging.getLogger("faf_agent.<submodul>")
  ```
- **Error Handling:** Jangan biarkan exception mentah membocorkan stack trace ke layar chat Telegram pengguna; tangkap dan bungkus dengan pesan penjelasan ramah manusia.
- **Asinkron & Pembatalan:** Selalu periksa `context.cancel_event.is_set()` pada loop panjang atau proses I/O agar perintah `/cancel` tetap responsif.
- **Path Resolution:** Selalu gunakan `pathlib.Path` atau helper di `src/tools/path_security.py` untuk menangani path absolut, path home (`~`), dan path kartu memori Android (`/sdcard/`).
