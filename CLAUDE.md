# CLAUDE.md — Petunjuk Cepat Claude Code

> ⚠️ **PANDUAN UTAMA & ATURAN LENGKAP:**  
> Seluruh arsitektur, standar keamanan, invarian ketat, konvensi kode, dan daftar tool dipusatkan di **[AGENTS.md](AGENTS.md)**.  
> Setiap agen AI dan pengembang **WAJIB** membaca dan mematuhi isi `AGENTS.md` sebagai sumber kebenaran tunggal (*Single Source of Truth*).

---

## Ringkasan Proyek

`faf-agent` adalah asisten AI otonom untuk perangkat Android fisik yang berjalan di lingkungan Termux (mode non-root dan root) dan dikendalikan melalui Telegram Bot. Menggunakan LLM *function calling* untuk mengontrol hardware, menjalankan shell, mengelola file, dan otomasi lokal.

---

## Perintah Penting (Commands Reference)

```bash
# Menjalankan seluruh pengujian
pytest

# Menjalankan pengujian spesifik / verbose
pytest -v
pytest tests/test_agent.py -v
pytest -k "security or memory"

# Memeriksa dependensi sistem Termux & tools Android
python check_deps.py

# Menjalankan bot faf-agent
python main.py
```

### RTK (Rust Token Killer) CLI Proxy
Projek ini menggunakan hook otomatis RTK. Gunakan perintah meta berikut langsung:
```bash
rtk gain              # Tampilkan analitik penghematan token
rtk gain --history    # Riwayat perintah dan penghematan token
rtk discover          # Analisis riwayat Claude Code untuk peluang penghematan
rtk proxy <cmd>       # Eksekusi perintah mentah tanpa filtering
```

---

## Aturan Utama & Invarian Kritis (Non-Negotiables)

1. **Pure Python (Zero Maturin / Zero Rust):**  
   Dilarang keras menambah pustaka yang membutuhkan build compiler native/C/Rust (seperti Pydantic, pydantic-core, orjson) karena bot berjalan pada arsitektur ARM64 Termux. Gunakan standard library (`@dataclass`, `typing`, `pathlib`, `json`).
2. **Keamanan Daya & Perangkat (Power Guard):**  
   Dilarang keras mengeksekusi perintah mematikan/reboot ponsel (`shutdown`, `poweroff`, `reboot`, `sysrq-trigger`, `svc power`). Jangan membunuh proses inti sistem Android (`system_server`, `surfaceflinger`, `lmkd`, `init`).
3. **Format Chat Telegram (Mobile UX):**  
   Gunakan **Plain Text murni** untuk pesan obrolan. Dilarang menggunakan format markdown tebal/miring/codeblocks atau tabel markdown/ASCII (hancur di layar ponsel). Hanya buat markdown jika user eksplisit meminta file `.md`.
4. **Penanganan Ambiguitas (Proactive Clarification):**  
   Jangan pernah menebak path file yang tidak jelas, jam/alarm ambigu, atau kontak jamak. Ajukan pertanyaan singkat, padat, to-the-point dengan pilihan konkret (lihat `skills/ambiguity-handler/SKILL.md`).
5. **Keamanan Jaringan & Path:**  
   Patuhi proteksi SSRF (blokir IP privat/loopback/cloud metadata) dan larangan akses ke file kredensial (`.env`, `id_rsa`, token).

Untuk panduan mendalam tentang penambahan tool, struktur berkas, dan sistem memori, lihat **[AGENTS.md](AGENTS.md)**.
