# Laporan Audit Kode & Rencana Perbaikan — faf-agent

> **Tanggal Audit:** 13 Oktober 2026  
> **Peran Peninjau:** Senior AI Agent Architect & DevSecOps Engineer  
> **Target Proyek:** `faf-agent` (Android/Termux Autonomous AI Agent via Telegram)  
> **Status Akhir:** REQUEST CHANGES (Terdapat 2 isu kritis keamanan & performa, 4 isu penting)

---

## Ringkasan Eksekutif

Basis kode `faf-agent` memiliki arsitektur awal yang sangat baik: implementasi *pure-Python* (zero binary compilation/maturin dependencies), isolasi proses REPL berbasis duplikasi file descriptor dan pengalihan ke `/dev/null`, serta penjagaan terhadap prompt injection.

Namun, audit menyeluruh dari hulu ke hilir menemukan beberapa titik kritis yang harus diperbaiki:
1. **SSRF & Vektor Eksfiltrasi Data Lokal** pada `MediaDownloaderTool` (URL lokal/privat dapat diunduh dan diteruskan otomatis ke Telegram).
2. **Koneksi HTTP Socket Churn** pada `AIClient` (membuat `AsyncClient` baru pada tiap iterasi *tool call*).
3. **Inkonsistensi Field Dataclass** pada `Settings` (`temp_media_dir` tidak terdaftar di skema).
4. **Ketiadaan Pelacakan Konsumsi Token** (`usage` dibuang dari respons LLM).
5. **Path Penyimpanan Relatif** pada `ReminderStore` dan `CronJobStore`.
6. **Potensi Eksekusi Kode USSD/MMI Berbahaya** pada fitur telepon.

---

## Daftar Tugas Perbaikan (Actionable Tasks)

### Task 1: Proteksi SSRF & Validasi Keamanan URL pada `MediaDownloaderTool`

- **Tingkat Urgensi:** 🔴 Kritis (Security)
- **File Target:**
  - Ubah: `src/tools/media_downloader.py`
  - Tambah Uji: `tests/test_agent.py`
- **Permasalahan:**
  Pada metode `_download_direct` dan `_download_via_ytdlp`, parameter `url` langsung diserahkan ke engine eksternal (`aria2c`, `curl`, `wget`, `yt-dlp`, atau `urllib.request`) tanpa pengecekan apakah URL mengarah ke alamat lokal/privat. Jika agen dieksploitasi untuk mengunduh `http://127.0.0.1:8000/keys` atau `http://192.168.1.1/backup.cfg`, berkas yang berukuran <= 50MB akan langsung dikirim ke chat Telegram pengguna.
- **Rekomendasi Perbaikan:**
  1. Integrasikan fungsi `_check_url_safety(url)` dari `src/tools/web_search.py` ke `src/tools/media_downloader.py`.
  2. Tolak unduhan sebelum engine dijalankan jika mendeteksi loopback (`127.0.0.1`, `localhost`), IP privat RFC1918 (`10.x`, `172.16.x`, `192.168.x`), cloud metadata (`169.254.169.254`), atau port non-web terlarang.
  3. Kembalikan `ToolResult(success=False, error="Akses ditolak: URL mengarah ke jaringan privat/lokal (ancaman SSRF).")`.

---

### Task 2: Refactor Lifecycle & Connection Pooling pada `AIClient`

- **Tingkat Urgensi:** 🔴 Kritis (Performa & Arsitektur)
- **File Target:**
  - Ubah: `src/core/ai_client.py`
  - Ubah: `src/bot/app.py`
- **Permasalahan:**
  Di `src/core/ai_client.py` baris 81, kode menggunakan:
  ```python
  async with httpx.AsyncClient(timeout=60.0) as client:
      res = await client.post(url, headers=headers, json=payload)
  ```
  Pada agen otonom dengan hingga 15 langkah per giliran, membuka dan menutup socket TLS berulang kali menimbulkan latensi handshake yang tinggi, *socket exhaustion*, dan mematikan fitur HTTP Keep-Alive.
- **Rekomendasi Perbaikan:**
  1. Simpan klien di instance: `self._client: httpx.AsyncClient | None = None`.
  2. Sediakan method `_get_client()` dengan lazy initialization:
     ```python
     async def _get_client(self) -> httpx.AsyncClient:
         if self._client is None or self._client.is_closed:
             limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
             self._client = httpx.AsyncClient(timeout=60.0, limits=limits)
         return self._client
     ```
  3. Sediakan method `async def close(self) -> None` dan panggil pada callback `on_shutdown` di `src/bot/app.py`.

---

### Task 3: Token Usage Observability & Sinkronisasi Dataclass `Settings`

- **Tingkat Urgensi:** 🟡 Penting (Observability & Integrity)
- **File Target:**
  - Ubah: `src/config.py`
  - Ubah: `src/core/ai_client.py`
  - Ubah: `src/core/agent.py`
- **Permasalahan:**
  1. Di `src/config.py`, `temp_media_dir` di-assign di `__init__` tetapi tidak dideklarasikan sebagai field pada class `@dataclass class Settings`. Hal ini merusak introspeksi tipe dan fungsi `dataclasses.asdict()`.
  2. Di `src/core/ai_client.py`, field `usage` dari respons OpenAI API dibuang, sehingga bot tidak memantau konsumsi token dan limit jendela konteks.
- **Rekomendasi Perbaikan:**
  1. Tambahkan deklarasi field pada `Settings`:
     ```python
     temp_media_dir: str = "/data/data/com.termux/files/home/faf_media"
     ```
  2. Tambahkan `usage: dict[str, int] = field(default_factory=dict)` pada `LLMResponse`.
  3. Tangkap data token:
     ```python
     raw_usage = data.get("usage", {})
     return LLMResponse(choices=[LLMChoice(message=msg_obj)], usage=raw_usage)
     ```
  4. Catat `usage` pada log di `src/core/agent.py`.

---

### Task 4: Standarisasi Lokasi Penyimpanan State Persisten (`reminders` & `cronjobs`)

- **Tingkat Urgensi:** 🟡 Penting (Stabilitas & Reliabilitas)
- **File Target:**
  - Ubah: `src/tools/reminder_mgr.py`
  - Ubah: `src/tools/cronjob_mgr.py`
  - Ubah: `src/tools/path_security.py`
- **Permasalahan:**
  `ReminderStore` dan `CronJobStore` memakai nilai default relatif `"data/reminders.json"` dan `"data/cronjobs.json"`. Jika bot dipicu melalui Termux:Boot, systemd, atau skrip cron dari direktori lain, folder `data/` akan tercipta di lokasi yang tidak konsisten.
- **Rekomendasi Perbaikan:**
  1. Tentukan path absolut berbasis root direktori proyek atau home pengguna (misal: `os.path.expanduser("~/.faf_agent/data/")`).
  2. Gunakan helper `validate_cron_state_path()` dari `src/tools/path_security.py` sebelum membaca atau menulis ke berkas JSON tersebut.

---

### Task 5: Proteksi USSD Dialing & Pembersihan Redundansi

- **Tingkat Urgensi:** 🟢 Perbaikan Kualitas & Keamanan Tambahan
- **File Target:**
  - Ubah: `src/tools/productivity.py`
  - Ubah: `src/tools/media.py`
  - Ubah: `src/tools/weather_mgr.py`
  - Ubah: `src/core/memory_store.py`
- **Permasalahan & Rekomendasi Perbaikan:**
  1. **Proteksi Dialing:** Di `src/tools/productivity.py` aksi `make_call`, tolak atau mintakan konfirmasi jika nomor telepon diawali atau memuat karakter `*` atau `#` (mencegah eksekusi kode MMI/USSD pemformatan ponsel seperti `*2767*3855#`).
  2. **Shell Quoting Konsisten:** Di `src/tools/media.py`, ganti single quote manual `'{filepath}'` menjadi `{shlex.quote(filepath)}` pada perintah `termux-camera-photo` dan `termux-microphone-record`.
  3. **Hapus Fungsi Duplikat:** Di `src/tools/weather_mgr.py`, hapus definisi ganda fungsi `_format_readable_dt` pada baris 84 yang menimpa baris 41.
  4. **Re-entrant Lock:** Di `src/core/memory_store.py`, ganti `self._lock = threading.Lock()` dengan `threading.RLock()` untuk mencegah potensi *self-deadlock* pada traversal graf bertingkat.

---

## Checklist Eksekusi Perbaikan

- [x] **Task 1:** Validasi SSRF & loopback guard pada `MediaDownloaderTool`.
- [x] **Task 2:** Client connection pool & graceful shutdown pada `AIClient`.
- [x] **Task 3:** Pendaftaran field `temp_media_dir` & tracking `usage` token LLM.
- [x] **Task 4:** Path absolut deterministik untuk `reminders.json` dan `cronjobs.json`.
- [x] **Task 5:** Proteksi kode USSD pada dialer & pembersihan duplikasi `_format_readable_dt`.
