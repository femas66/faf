---
title: "FAF Agent — Autonomous Android AI Assistant"
subtitle: "Asisten AI otonom di lingkungan Termux Android yang dikendalikan penuh lewat Telegram Bot"
description: "Asisten AI otonom berbasis Pure Python untuk perangkat fisik Android (Termux Root & Non-Root) dengan 24+ tools sistem, asisten riset paper ilmiah, tech digest harian, dan memori kognitif lokal oleh Femas Akbar Faturrohim."
image: "/projects/faf-agent.webp"
tags: ["Python", "AI Agent", "LLM Function Calling", "Termux", "Android Root", "Telegram Bot", "SQLite"]
date: "Oktober 2026"
role: "AI & Systems Engineer"
order: 7
github: "https://github.com/femas66/faf"
---

## Latar Belakang Masalah

Perangkat Android yang jarang digunakan secara langsung sebenarnya memiliki potensi besar sebagai server mini yang hemat daya dan selalu terhubung ke internet. Namun, mengoperasikan ponsel dari jarak jauh atau menjalankan asisten AI di lingkungan **Termux ARM64** punya dua kendala utama:

1. **Keterbatasan Kompilasi Native di Termux:** Banyak framework AI modern bergantung pada library C/Rust seperti `pydantic-core`, `maturin`, atau `orjson` yang sering gagal dikompilasi di lingkungan Android ARM64.
2. **Kontrol Sistem & Produktivitas dari Satu Antarmuka:** Mengelola perangkat fisik, mencari literatur riset kuliah, memantau berita keamanan siber, hingga menjalankan otomasi sistem membutuhkan jembatan yang ringan dan bisa diakses kapan saja lewat aplikasi chat seperti Telegram.

**FAF Agent** dibangun untuk menjawab kebutuhan tersebut: asisten AI otonom yang berjalan 100% di atas **Pure Python (Zero Native Compilation)** langsung di perangkat Android fisik dan dikendalikan sepenuhnya melalui **Telegram Bot**.

---

## Arsitektur & Cara Kerja

FAF Agent menggabungkan protokol **OpenAI-Compatible Function Calling** dengan jembatan eksekusi sistem Android (`AndroidBridge` via Termux:API dan akses Superuser/`su`).

1. **Intent Router & Dynamic Tool Pruning (< 1ms):**
   Sebelum memanggil LLM, pesan pengguna dianalisis oleh router berbasis kata kunci dan konteks untuk memilih klaster tool yang relevan (*System*, *Files*, *Web & Media*, *Dev & Advanced*, *Memory*, atau *Research*). Untuk obrolan santai, 0 tool dikirimkan sehingga menghemat **~85% token prefill** dan mempercepat waktu respons.
2. **Dual-Tier Model Strategy (Fast vs. Smart):**
   Menggunakan model cepat dan ringan (`OPENAI_FAST_MODEL`) untuk obrolan kasual atau perintah sistem sederhana, serta otomatis beralih ke model penalaran tinggi (`OPENAI_SMART_MODEL`) saat menangani analisis PDF, riset akademik, penulisan kode, atau eksekusi multi-tool.
3. **Progressive SSE Streaming di Telegram:**
   Respons dikirim secara *real-time* menggunakan *Server-Sent Events (SSE)* dengan mekanisme *debounced in-place message editing* yang mematuhi batas *rate-limit* Telegram.
4. **Cognitive Memory & Knowledge Graph Lokal:**
   Dilengkapi penyimpanan berbasis **SQLite** dengan `threading.RLock` dan *in-memory dirty-flag caching* untuk mengingat fakta permanen pengguna, riwayat episodik, serta relasi entitas (*Knowledge Graph RAG*).

---

## Fitur Utama (24+ Tools Terintegrasi)

### 1. Asisten Riset Paper Ilmiah (`research_paper`)
Dirancang untuk mendukung kegiatan kuliah dan riset literatur langsung dari ruang obrolan Telegram:
- Mencari paper secara paralel dari **arXiv API** dan **Semantic Scholar API** lengkap dengan deduplikasi otomatis berbasis DOI/arXiv ID.
- Mengunduh dokumen PDF *open-access*, mengekstrak teks, dan memilih bagian kunci (*Abstract*, *Introduction*, *Conclusion*) untuk diringkas secara terstruktur (masalah, metode, hasil, keterbatasan).
- Menghasilkan sitasi siap pakai dalam format **BibTeX**, **APA**, dan **IEEE** (melalui *DOI content negotiation* maupun pemformatan lokal).
- Menyimpan paper ke perpustakaan SQLite pribadi beserta catatan/tag dan mengekspornya ke berkas `.bib`.

### 2. Tech & Cybersecurity Digest Harian (`tech_digest`)
Kurator berita otomatis yang berjalan setiap pagi menggunakan *cron worker* bawaan:
- Mengambil berita secara paralel dari **Hacker News (Algolia API)**, **GitHub Trending** (dengan fallback otomatis ke GitHub Search API), dan belasan sumber **RSS/Atom** keamanan siber & teknologi (The Hacker News, BleepingComputer, Krebs on Security, Project Zero, CISA Advisories, Ars Technica, dll.).
- Menyaring berita menggunakan filter kualitas (poin minimum HN & bintang harian GitHub) dan sistem skoring berbasis bobot minat, dengan prioritas khusus untuk peringatan kerentanan kritis (*zero-day* / *actively exploited*).
- Mencatat riwayat URL ter-normalisasi di SQLite agar berita yang sama tidak pernah dikirim berulang.

### 3. Kontrol Perangkat Fisik & Hardware Android
- **Sistem & Sensor:** Mengatur WiFi, Bluetooth, senter, volume, kecerahan layar, membaca status baterai/suhu, lokasi GPS, dan membaca notifikasi aktif (termasuk ekstraksi OTP).
- **Interaksi Layar & Aplikasi:** Simulasi sentuhan layar (*tap*, *swipe*, *keyevent*, *input text*), manajemen paket aplikasi (`pm`/`am`), serta pemantauan proses Linux/Android (`top`, tekanan memori PSI, dan imunisasi proses `oom_score_adj`).
- **Multimedia & OCR Offline:** Mengambil foto dari kamera depan/belakang, merekam audio mikrofon, *Text-to-Speech (TTS)*, serta ekstraksi teks dari gambar menggunakan **Tesseract OCR**.

### 4. Produktivitas, Dokumen, & Utilitas Developer
- **Manipulasi Berkas & PDF:** Operasi berkas aman (`read`, `write`, `edit`, `tree`, `grep`), ekstraksi dan pencarian isi dokumen PDF, hingga pembuatan gambar potongan kode bergaya **VS Code Dark+** (`code_to_image`).
- **Self-Extending Custom Skills:** Kemampuan bagi agen untuk menulis, menguji di sandbox terisolasi, dan mendaftarkan modul skill Python baru secara mandiri dengan persetujuan pengguna.
- **Penjadwalan Otonom:** Pengingat pesan satu kali (`reminder_manager`) dan *cronjob* berkala (`cronjob`) yang mendukung zona waktu lokal dan kondisi pemicu dinamis.

---

## Keamanan Berlapis (Security Guardrails)

Karena berjalan di perangkat fisik dengan akses *root*, FAF Agent menerapkan pengamanan ketat pada level kode:

- **Power & Process Immunity Guard:** Memblokir semua variasi perintah yang dapat mematikan atau me-reboot ponsel (`reboot`, `shutdown`, `poweroff`, `sysrq-trigger`) serta mencegah penghentian proses kritis Android (`system_server`, `surfaceflinger`, `lmkd`, `init`) maupun proses Termux itu sendiri.
- **Anti-SSRF & Safe HTTP Helper:** Memvalidasi setiap URL dan setiap hop *redirect* untuk menolak akses ke IP privat RFC1918 (`10.x`, `172.16.x`, `192.168.x`), `localhost`, dan metadata cloud (`169.254.169.254`), disertai batas ukuran streaming dan penolakan deklarasi XML `<!ENTITY>`.
- **Path Traversal & Credential Guard:** Memblokir akses baca/eksfiltrasi terhadap berkas kredensial sensitif (`.env`, kunci SSH `id_rsa`/`id_ed25519`, keystore) dan partisi sistem terproteksi.
- **Interactive Confirmation Gate:** Perintah shell berisiko tinggi otomatis ditahan dan membutuhkan persetujuan eksplisit pengguna melalui tombol *Inline Keyboard* di Telegram.

---

## Teknologi yang Digunakan

- **Bahasa & Runtime:** Python 3.11+ (100% Pure Python, Zero Rust/Maturin)
- **Antarmuka Bot:** `python-telegram-bot` (Asyncio Polling, Inline Keyboards, SSE Streaming)
- **Jaringan & Integrasi API:** `httpx` (Async Connection Pooling), OpenAI-Compatible Chat Completions & Tool Calling, arXiv Atom API, Semantic Scholar Graph API, Hacker News Algolia API, Open-Meteo API
- **Penyimpanan & Dokumen:** SQLite3 (`threading.RLock`), `pypdf`
- **Lingkungan Sistem:** Termux Android (ARM64), Termux:API, Superuser (`tsu`/`su`), Tesseract OCR, Headless Chromium, `yt-dlp`, `aria2c`
- **Pengujian:** `pytest` & `pytest-asyncio` (300+ unit & security tests)
