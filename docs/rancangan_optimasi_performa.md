# Rancangan Peningkatan Performa & Response Time faf-agent

Dokumen ini berisi rancangan arsitektur dan peta jalan implementasi (implementation roadmap) untuk meningkatkan performa dan kecepatan respon (*response time*) AI Agent pada proyek **faf-agent**. Rancangan ini difokuskan untuk mencapai respon yang **sangat cepat (sub-detik / < 1 detik perceived latency)** tanpa mengorbankan kecerdasan model, akurasi *tool calling*, maupun aturan ketat proyek (*Pure-Python*, *Zero Native Build*, dan *Hard Security Guardrails*).

---

## 1. Analisis Profil Latensi Saat Ini (Root Causes & Baseline)

Berdasarkan inspeksi langsung pada kode sumber saat ini:

| Komponen | Kondisi Saat Ini | Dampak Latensi | Estimasi Waktu |
|---|---|---|---|
| **Input Token Bloat (Prefill)** | `SYSTEM_PROMPT` (~3.338 token) + 20 Skema Tools OpenAI (~10.753 token) + Memori (~500 token) = **~14.500+ token per request**. | TTFT (*Time To First Token*) sangat lama karena LLM harus membaca dan memproses 14.500 token bahkan hanya untuk membalas "Halo". | 2.0s – 5.0s |
| **Perceived Latency (Telegram)** | Mode *blocking*: bot hanya menampilkan indikator `typing...` dan menunggu seluruh iterasi agent selesai sebelum mengirim 1 balon teks. | Pengguna menatap layar kosong tanpa umpan balik nyata selama proses berlangsung. | 4.0s – 15.0s |
| **Eksekusi Tool Sekuensial** | Jika LLM memanggil beberapa tool sekaligus dalam 1 giliran (misal: cek baterai, cek wifi, cek memori), eksekusi dilakukan secara loop sekuensial (`for tc in message.tool_calls: await execute(...)`). | Latensi terakumulasi secara linier ($T_1 + T_2 + T_3$). | 1.5s – 6.0s |
| **Redundansi Deskripsi Tool** | `SYSTEM_PROMPT` di `agent.py` menulis ulang daftar 17 tool beserta fungsinya secara manual, padahal array skema JSON `tools` sudah mendefinisikan hal yang sama. | Pemborosan ~800 token input ganda pada setiap langkah LLM. | 200ms – 500ms |
| **Cache Miss pada MemoryStore** | `format_for_system_prompt()` mengeksekusi 3 query SQLite (`list_all_facts`, `list_episodes`, `list_all_relations`) setiap kali pesan masuk, tanpa in-memory caching. | I/O disk SQLite dan serialisasi string berulang pada setiap giliran chat. | 50ms – 150ms |
| **Model Tunggal (Single Tier)** | Bergantung pada 1 model default (misal: `gpt-4o`) untuk semua jenis permintaan (baik sapaan santai maupun tugas kompleks). | Model besar membutuhkan komputasi lebih lama dibandingkan model generasi cepat (*distilled/flash*). | 1.5s – 4.0s |

---

## 2. Prinsip Optimasi: Cepat Tanpa Menghilangkan Kecerdasan

1. **Intelligence Preservation (Kecerdasan Tetap Utuh):**
   - Tidak memangkas kemampuan penalaran (*reasoning*) model.
   - Jika perintah memerlukan analisis mendalam atau multi-step tool calls, model tetap memiliki akses penuh ke seluruh kapabilitas perangkat.
   - Aturan keamanan dan penanganan ambiguitas (`skills/ambiguity-handler`) tetap berjalan 100%.
2. **Zero Native Build & Pure-Python Invariant:**
   - Seluruh optimasi menggunakan pustaka standar Python (`asyncio`, `re`, `json`, `sqlite3`) dan pustaka murni yang sudah ada (`httpx`, `python-telegram-bot`).
   - Tidak menambahkan ekstensi C/Rust/Maturin yang dapat merusak portabilitas di Termux Android.
3. **Telegram UX Compliance:**
   - Mempertahankan aturan **Maksimal 2 Balon Chat** (1 balon teks bot + berkas media).
   - Fitur *streaming* diimplementasikan dengan mengedit balon pesan yang sama secara berkala (*in-place debounced message edit*), bukan membombardir pesan baru.

---

## 3. Enam Pilar Solusi Arsitektur

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             USER TELEGRAM CHAT                              │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ [PILAR 1] INTENT-BASED DYNAMIC TOOL PRUNING (ROUTER RINGAN PURE-PYTHON)     │
│ ├─ Sapaan / Chat Biasa   ──> 0 Tools (0 Token Overhead, Hemat 10.700 Token)  │
│ ├─ Kontrol Sistem & HP  ──> Subset Tools Sistem (system, time, productivity)│
│ ├─ Berkas & Dokumen      ──> Subset Tools Berkas (file_mgr, pdf_mgr)        │
│ └─ Ambigu / Kompleks    ──> Full Tools (Semua 20 Tools Siap Siaga)          │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ [PILAR 4 & 6] PROMPT CACHING & IN-MEMORY DIRTY-FLAG CACHING                 │
│ ├─ Static System Prompt Prefix (100% KV Cache Hit di Provider LLM)          │
│ └─ MemoryStore Prompt Block di-cache dalam RAM (0ms Disk I/O)               │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ [PILAR 5] DUAL-TIER MODEL ROUTING (FAST vs SMART MODEL)                     │
│ ├─ Fast Tier  : Model ultra-cepat (Gemini 2.5 Flash / GPT-4o-mini / Groq)   │
│ └─ Smart Tier : Model penalaran tinggi (GPT-4o / Claude 3.5 Sonnet)         │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ [PILAR 3] CONCURRENT TOOL EXECUTION (asyncio.gather)                        │
│ ├─ Eksekusi paralel jika LLM mengembalikan >1 Tool Call independen          │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ [PILAR 2] TELEGRAM PROGRESSIVE STREAMING & LIVE TOOL STATUS                 │
│ ├─ Streaming token via SSE (httpx streaming)                                │
│ ├─ In-place Edit Telegram Message (Throttle 1.0 - 1.5s, Anti-Error 429)     │
│ └─ Perceived Latency turun dari 8 detik menjadi < 500 ms                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### Pilar 1: Dynamic Tool Pruning & Intent Routing (Pengurangan Token 70% – 85%)

**Masalah:** Saat ini seluruh 20 tools (~10.753 token skema JSON) selalu dikirimkan ke LLM, bahkan untuk pesan seperti *"Halo"*, *"Siapa namamu?"*, atau *"Jelaskan tentang hukum gravitasi"*.

**Solusi:**
Buat mekanisme seleksi tool adaptif (*just-in-time tool pruning*) berbasis kategori dan deteksi intent:
1. **Cluster Kategori Tool:**
   - `CATEGORY_CONVERSATION`: `[ask_clarification]` (atau tanpa tools sama sekali).
   - `CATEGORY_SYSTEM`: `[system_settings, device_interaction, productivity_control, time_manager]`.
   - `CATEGORY_FILES`: `[file_manager, pdf_manager]`.
   - `CATEGORY_WEB_MEDIA`: `[web_search, media_downloader, web_screenshot, ocr_extract, media_control]`.
   - `CATEGORY_DEV_ADVANCED`: `[package_manager, process_manager, python_repl, root_shell_exec, cronjob]`.
   - `CATEGORY_MEMORY`: `[memory_manager]`.
2. **Intent Matcher Ringan (< 1ms):**
   - Menggunakan pencocokan kata kunci (*keyword heuristics*) dan regex cepat murni Python.
   - Jika pengguna menyapa santai / obrolan umum: kirim **0 tools** (hanya pesan teks biasa). Ukuran request turun dari 14.500 token menjadi ~1.500 token. LLM merespons secara instan (< 400ms).
   - Jika pengguna menyebut kata terkait sistem (misal: "baterai", "wifi", "senter", "volume"): kirim grup `CATEGORY_SYSTEM` (~2.000 token).
   - **Safety Fallback:** Jika intent tidak dapat dipastikan dengan yakin (ambigu), fallback otomatis memuat **semua tools** agar kecerdasan dan fleksibilitas agen tidak berkurang sedikitpun.

---

### Pilar 2: Telegram Progressive Streaming & Live Status Updates (Perceived Latency < 500ms)

**Masalah:** Telegram bot saat ini menahan seluruh teks sampai model selesai men-generate seluruh jawaban. Pada jawaban panjang, pengguna menunggu 5–10 detik.

**Solusi:**
1. **Aktifkan Streaming pada `AIClient`:**
   - Gunakan `client.stream("POST", url, json=payload)` pada `httpx.AsyncClient` dengan parser Server-Sent Events (SSE).
   - Jika response adalah teks langsung (bukan tool call), yield chunk token ke handler.
2. **In-Place Telegram Debounced Message Editing:**
   - Kirim satu pesan awal: `...` atau indikator status.
   - Kumpulkan token yang datang dan perbarui pesan (*edit_message_text*) setiap **1.2 detik** (untuk mematuhi batas rate-limit Telegram ~1 edit/detik per chat).
   - Dengan teknik ini, kata pertama muncul di layar ponsel pengguna dalam waktu **< 500ms** setelah tombol kirim ditekan.
3. **Live Status Indicator saat Menjalankan Tool:**
   - Saat agen memanggil tool yang memakan waktu (seperti OCR, download media, atau web search), perbarui balon chat dengan status real-time:
     - `⏳ Sedang membaca dokumen PDF...`
     - `🔍 Menelusuri informasi di internet...`
     - `⚙️ Mengatur setelan perangkat...`
   - Setelah selesai, timpa pesan status tersebut dengan teks jawaban akhir. Pengguna selalu mengetahui apa yang sedang dilakukan agen.

---

### Pilar 3: Parallel Tool Execution (Asyncio Concurrency)

**Masalah:** Saat LLM meminta informasi dari beberapa tool sekaligus (misalnya dalam 1 giliran model memanggil `system_settings(action="battery")` dan `system_settings(action="wifi")`), eksekusi saat ini berjalan sekuensial.

**Solusi:**
- Jika `len(message.tool_calls) > 1`, pisahkan tool call yang bersifat independen (read-only) dan jalankan secara bersamaan menggunakan `asyncio.gather(*tasks, return_exceptions=True)`.
- Mengurangi durasi eksekusi multi-tool dari $N \times T$ menjadi $\max(T_1, T_2, \dots, T_n)$.
- Tool yang bersifat interaktif (seperti `ask_clarification`) atau perintah konfirmasi destruktif tetap diprioritaskan dan dieksekusi secara terisolasi.

---

### Pilar 4: Prompt Optimization & Prefix Caching Alignment

**Masalah:**
- Redundansi: Bagian *ATURAN WAJIB PENGGUNAAN TOOLS ANDROID* di `SYSTEM_PROMPT` memuat ringkasan 17 tools yang memakan ~800 token, duplikat dengan skema JSON `tools`.
- Cache Busting: Menginjeksi memori yang berubah-ubah di tengah prompt dapat merusak *KV Prompt Cache* pada penyedia LLM (OpenAI, Gemini, OpenRouter, DeepSeek).

**Solusi:**
1. **Pangkas Redundansi `SYSTEM_PROMPT`:**
   - Hapus penjelasan deskriptif panjang per tool dari `SYSTEM_PROMPT` teks, serahkan deskripsi fungsi kepada atribut `description` di masing-masing class tool JSON Schema.
   - `SYSTEM_PROMPT` teks cukup memuat aturan perilaku, gaya bahasa santai, larangan markdown, dan guardrails keamanan.
2. **Struktur Ramah Prompt Caching:**
   - Pastikan teks awal (*prefix*) `SYSTEM_PROMPT` bernilai 100% statis.
   - Pindahkan blok memori dinamis (`[MEMORI PERMANEN & FAKTA PENGGUNA]`) ke bagian akhir dari system prompt atau sebagai pesan sistem terpisah berturut-turut, sehingga provider LLM mendapatkan 100% cache hit pada bagian aturan statis.

---

### Pilar 5: Dual-Tier Model Architecture (Fast / Smart Strategy)

**Masalah:** Menggunakan satu model besar serba guna untuk tugas-tugas mikro (seperti sapaan, klarifikasi singkat, atau toggle wifi sederhana) membebani biaya dan kecepatan respon.

**Solusi:**
1. **Konfigurasi Dua Model di `src/config.py`:**
   - `OPENAI_FAST_MODEL` (Default: model cepat seperti `gpt-4o-mini`, `gemini-2.5-flash`, atau model Llama-3.3-70B di Groq dengan kecepatan 300+ token/detik).
   - `OPENAI_SMART_MODEL` (Default: `gpt-4o` atau model reasoning tinggi).
2. **Pola Pemilihan Otomatis:**
   - Permintaan chat kasual, penjadwalan sederhana, atau kontrol hardware dialirkan ke `OPENAI_FAST_MODEL`.
   - Analisis mendalam (seperti pemecahan masalah rumit, eksekusi Python REPL, atau kueri multi-hop Knowledge Graph) dialirkan ke `OPENAI_SMART_MODEL`.
   - Tambahkan opsi perintah Telegram `/model fast` dan `/model smart` agar pengguna dapat memilih secara eksplisit jika diinginkan.

---

### Pilar 6: In-Memory Dirty-Flag Caching pada MemoryStore & Bridge

**Masalah:**
- `MemoryStore.format_for_system_prompt()` membaca disk SQLite pada setiap chat turn.
- `AndroidBridge` mengecek ketersediaan binary `su` dan properti hardware berulang kali.

**Solusi:**
1. **Dirty-Flag Caching di `MemoryStore`:**
   - Simpan hasil format string memori ke variabel instance `self._cached_prompt_block: str | None`.
   - Saat dipanggil, jika `_cached_prompt_block` ada, kembalikan langsung (0ms, 0 query).
   - Pasang flag *dirty* (set `_cached_prompt_block = None`) **hanya** ketika fungsi mutasi dipanggil: `store_fact()`, `delete_fact()`, `store_episode()`, atau `add_relation()`.
2. **Hardware Properties Caching di `AndroidBridge`:**
   - Cache hasil `is_root_available()` dan `get_prop("ro.product.model")` ke dalam memori proses setelah pembacaan pertama, karena properti fisik perangkat tidak pernah berubah selama sesi berjalan.

---

## 4. Rencana Kerja Implementasi Bertahap (Actionable Roadmap)

Rencana implementasi dibagi menjadi 5 fase modular yang dapat dikerjakan secara independen tanpa merusak kestabilan bot:

### Fase 1: Optimasi Prompt & In-Memory Caching (Paling Cepat, Dampak Langsung)
- [x] **Task 1.1:** Tambahkan *dirty-flag caching* pada `MemoryStore.format_for_system_prompt()` di `src/core/memory_store.py`.
- [x] **Task 1.2:** Cache properti statis hardware di `src/core/android_bridge.py`.
- [x] **Task 1.3:** Pangkas redundansi deskripsi tool pada `SYSTEM_PROMPT` di `src/core/agent.py` dan rapikan penempatan memori untuk memaksimalkan *LLM Prompt Caching*.
- [x] **Task 1.4:** Jalankan `pytest` untuk memastikan seluruh 165 unit test tetap lulus 100% (sekarang 167 unit test).

### Fase 2: Dynamic Tool Pruning / Intent-Based Tool Routing
- [x] **Task 2.1:** Buat modul router ringan `src/core/tool_router.py` untuk mengelompokkan tool ke dalam kategori (*system*, *files*, *web*, *dev*, *all*).
- [x] **Task 2.2:** Integrasikan `ToolRouter` ke dalam `FafAgent.run()` di `src/core/agent.py` sehingga request chat biasa mengirim 0 tools atau subset ringkas.
- [x] **Task 2.3:** Tulis unit test di `tests/test_tool_router.py` untuk menguji akurasi klasifikasi intent dan memastikan fallback *all-tools* aktif saat input ambigu.

### Fase 3: Concurrency pada Eksekusi Multi-Tool
- [x] **Task 3.1:** Perbarui blok pemrosesan `tool_calls` di `src/core/agent.py` untuk menggunakan `asyncio.gather` pada tool yang bersifat paralel.
- [x] **Task 3.2:** Pastikan penanganan tool spesial (seperti `ask_clarification`) tetap berjalan dengan aman mendahului tool lainnya.
- [x] **Task 3.3:** Uji skenario multi-tool di `tests/test_agent.py`.

### Fase 4: Telegram Progressive Streaming & In-Place Editing
- [x] **Task 4.1:** Tambahkan method `stream_chat_completion()` pada `src/core/ai_client.py` berbasis SSE streaming `httpx`.
- [x] **Task 4.2:** Perbarui `src/bot/handlers/chat.py` untuk mendukung *debounced message editing* (interval 1.0 – 1.2 detik) pada jawaban teks langsung.
- [x] **Task 4.3:** Tampilkan live status saat eksekusi tool sedang berlangsung (menggantikan indikator typing pasif).

### Fase 5: Konfigurasi Fast / Smart Dual-Model
- [x] **Task 5.1:** Tambahkan opsi `openai_fast_model` di `src/config.py` dan dokumentasikan di `.env.example`.
- [x] **Task 5.2:** Tambahkan logika pemilihan model di `FafAgent` berdasarkan kompleksitas tugas.
- [x] **Task 5.3:** Tambahkan perintah slash `/mode` di bot Telegram untuk memilih mode kecepatan secara manual jika diinginkan pengguna.

---

## 5. Estimasi Hasil dan Matriks Performa

| Metrik Performa | Kondisi Saat Ini (Baseline) | Target Setelah Optimasi | Peningkatan |
|---|---|---|---|
| **Token Prefill (Chat Biasa)** | ~14.500 token | ~1.500 token | **Hemat 89% token** |
| **Token Prefill (Perintah Sistem)** | ~14.500 token | ~3.500 token | **Hemat 75% token** |
| **Time To First Token (TTFT)** | 2.5s – 4.5s | 0.3s – 0.8s | **4x – 8x Lebih Cepat** |
| **Perceived Latency (Telegram)** | 5.0s – 12.0s | **< 0.5s** (Streaming) | **Hampir Instan** |
| **Multi-Tool Execution Time** | 3.0s – 6.0s (Sekuensial) | 1.0s – 2.0s (Paralel) | **2x – 3x Lebih Cepat** |
| **Overhead I/O SQLite per Turn** | 3 query disk per turn | 0 query (In-memory cache) | **100% I/O Saved** |

---

## 6. Rekomendasi Pemilihan Provider & Model untuk Kecepatan Maksimal

Jika Anda menginginkan respon agen yang benar-benar secepat kilat di perangkat fisik Termux:
1. **Groq (Llama-3.3-70B Versatile):** Kecepatan generasi mencapai **250–350 token/detik** dengan latency TTFT di bawah 300ms. Sangat cocok sebagai endpoint OpenAI-compatible (`OPENAI_BASE_URL="https://api.groq.com/openai/v1"`).
2. **Google Gemini Flash (gemini-2.5-flash / gemini-1.5-flash):** Sangat cepat, jendela konteks masif, dan akurasi *tool calling* luar biasa dengan harga sangat hemat.
3. **OpenAI GPT-4o-mini:** Model default terbaik untuk efisiensi seimbang antara kecerdasan bahasa dan kecepatan respon.
