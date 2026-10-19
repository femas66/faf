# Panduan & Lembar Uji Percakapan faf-agent (Testing Cheatsheet)

Dokumen ini berisi daftar lengkap perintah chat natural language dan slash commands untuk menguji seluruh fitur yang ada di `faf-agent` melalui antarmuka Telegram Bot, lengkap dengan ekspektasi keluaran (*expected output*) bot.

> **Catatan Format:** Sesuai standar desain antarmuka `faf-agent` (layar ponsel), seluruh keluaran teks bot disajikan dalam format *plain text* bersih tanpa tabel ASCII/markdown dan tanpa format tebal (*bold*) yang berlebihan.

---

## 1. Perintah Cepat (Slash Commands)

Perintah langsung berbasis slash command untuk inspeksi instan tanpa pemanggilan LLM:

### 1.1 Status Bot & Diagnostik
- **Perintah Chat:** `/start`
  - **Ekspektasi Output:**
    ```text
    Halo! Saya faf-agent, asisten kecerdasan buatan otonom untuk perangkat Android fisik via Termux.

    Gunakan /help untuk melihat panduan perintah, atau langsung ketik instruksi Anda.
    ```
- **Perintah Chat:** `/doctor` atau `/check`
  - **Ekspektasi Output:**
    ```text
    Laporan Diagnostik Sistem & Dependensi faf-agent:
    • Termux Environment: Terdeteksi (ARM64)
    • Termux:API Binary: Terpasang (OK)
    • Superuser (Root / tsu): Tersedia
    • Tesseract OCR: Terpasang (ind+eng)
    • Chromium (Headless): Terpasang
    • yt-dlp & aria2c: Terpasang
    • SQLite FTS5 (MemoryStore): Aktif
    Semua komponen inti siap digunakan!
    ```
- **Perintah Chat:** `/ping`
  - **Ekspektasi Output:**
    ```text
    Pong! Bot aktif.
    Uptime sistem: 2 hari, 4 jam, 12 menit.
    ```

### 1.2 Status Perangkat & Baterai
- **Perintah Chat:** `/device`
  - **Ekspektasi Output:**
    ```text
    Status Perangkat Android:
    • Model: Xiaomi Redmi Note 10 Pro
    • Android OS: Versi 13 (SDK 33)
    • CPU: 8 Cores (Snapdragon 732G)
    • RAM: 2.1 GB bebas dari total 5.8 GB
    • Baterai: 78% (Tidak mengisi daya)
    • Suhu Baterai: 32.4°C
    ```
- **Perintah Chat:** `/battery`
  - **Ekspektasi Output:**
    ```text
    Status Baterai Detail:
    • Persentase: 78%
    • Status: Discharging
    • Kesehatan: Good
    • Suhu: 32.4°C
    • Tegangan: 4050 mV
    • Arus: -350 mA
    ```

### 1.3 Pemilihan Model AI
- **Perintah Chat:** `/mode` atau `/model`
  - **Ekspektasi Output:**
    ```text
    Mode Model AI Saat Ini:
    • Mode Aktif: FAST (gpt-4o-mini)
    • Model Cerdas: SMART (gpt-4o)

    Ketik /mode fast atau /mode smart untuk beralih mode.
    ```

---

## 2. Fitur Baru: Notifikasi, Inspeksi Layar, & RAM Optimizer

Fitur unggulan hasil audit yang baru ditambahkan:

### 2.1 Pembacaan Notifikasi Masuk Android (`termux-notification-list`)
- **Perintah Chat:** `baca notifikasi yang ada di status bar sekarang`
  - **Tool Dipicu:** `productivity_control` (action: `list_notifications`)
  - **Ekspektasi Output:**
    ```text
    Daftar Notifikasi Aktif (3 ditemukan):
    • [Whatsapp] Budi Santoso: Besok jadi rapat jam 10 pagi? (23:15)
    • [Messaging] Bank BCA: Kode OTP Anda: 829104. Jangan bagikan kepada siapa pun. (23:14)
    • [Gojek] Driver: Pesanan Anda sedang diantar menuju lokasi. (23:10)
    ```
- **Perintah Chat:** `cek apakah ada notifikasi atau OTP dari bank`
  - **Tool Dipicu:** `productivity_control` (action: `list_notifications`, `search_query`: `OTP`)
  - **Ekspektasi Output:**
    ```text
    Daftar Notifikasi Aktif (1 ditemukan):
    • [Messaging] Bank BCA: Kode OTP Anda: 829104. Jangan bagikan kepada siapa pun. (23:14)
    ```

### 2.2 Inspeksi Hierarki UI & Auto-Tap (`uiautomator dump`)
- **Perintah Chat:** `inspeksi elemen apa saja yang ada di layar HP sekarang`
  - **Tool Dipicu:** `device_interaction` (action: `inspect_ui`)
  - **Ekspektasi Output:**
    ```text
    Elemen Antarmuka Layar Terdeteksi (8 elemen):
    • Check In Harian (Button) [dapat diklik] -> Koordinat: (540, 720)
    • Riwayat Transaksi (TextView) [dapat diklik] -> Koordinat: (540, 950)
    • Beranda (ImageView) [dapat diklik] -> Koordinat: (120, 2200)
    • Profil Saya (ImageView) [dapat diklik] -> Koordinat: (960, 2200)
    ```
- **Perintah Chat:** `klik tombol Check In Harian di layar`
  - **Tool Dipicu:** `device_interaction` (action: `inspect_ui`, `search_text`: `Check In Harian`, `auto_tap`: `True`)
  - **Ekspektasi Output:**
    ```text
    Elemen 'Check In Harian' ditemukan pada posisi (540, 720) dan berhasil diketuk (tap otomatis).
    ```

### 2.3 Manajemen RAM & Proteksi OOM (Device 6GB Class)
- **Perintah Chat:** `bersihkan RAM HP sekarang`
  - **Tool Dipicu:** `process_mgr` (action: `clean_ram`)
  - **Ekspektasi Output:**
    ```text
    Pembersihan Memori RAM Berhasil (termasuk drop_caches sistem via root):
    • Memori Total Perangkat: 5859 MB
    • Memori Tersedia: 1420 MB -> 2210 MB (+790 MB dibebaskan)
    • Memori Bebas: 310 MB -> 1150 MB
    • Catatan: Proses background yang menganggur telah dihentikan secara aman via 'am kill-all'.
    ```
- **Perintah Chat:** `cek laporan tekanan memori RAM dan swap`
  - **Tool Dipicu:** `process_mgr` (action: `memory_pressure`)
  - **Ekspektasi Output:**
    ```text
    Laporan Tekanan Memori & RAM Perangkat (6GB Class):
    • Total RAM Fisik: 5859 MB
    • RAM Digunakan: 3649 MB (62.3%)
    • RAM Tersedia: 2210 MB
    • RAM Bebas Murni: 1150 MB
    • Page Cache & Buffers: 850 MB
    • Swap / zRAM: 1200 MB / 3000 MB (40.0%)
    • Indikator Tekanan PSI (Memory Stall):
      - some avg10=0.00 avg60=0.12 avg300=0.08 total=124021
      - full avg10=0.00 avg60=0.00 avg300=0.00 total=21034
    ```

---

## 3. Kontrol Sistem & Hardware Android

### 3.1 Senter & Layar
- **Perintah Chat:** `tolong nyalakan senter HP`
  - **Ekspektasi Output:** `Senter (torch) berhasil diatur ke: ON.`
- **Perintah Chat:** `matikan senter`
  - **Ekspektasi Output:** `Senter (torch) berhasil diatur ke: OFF.`
- **Perintah Chat:** `atur kecerahan layar ke 180`
  - **Ekspektasi Output:** `Kecerahan layar berhasil diatur ke nilai: 180 (70.6%).`
- **Perintah Chat:** `ambil tangkapan layar HP`
  - **Ekspektasi Output:** Mengirimkan berkas gambar hasil screenshot layar langsung ke chat Telegram.

### 3.2 Volume, Dering, & Suara
- **Perintah Chat:** `atur volume musik ke 12`
  - **Ekspektasi Output:** `Volume stream 'music' berhasil diatur ke level: 12.`
- **Perintah Chat:** `ubah mode dering ke hening`
  - **Ekspektasi Output:** `Mode dering ponsel berhasil diubah ke: SILENT.`
- **Perintah Chat:** `cek pengaturan volume HP saat ini`
  - **Ekspektasi Output:**
    ```text
    Daftar Level Volume Suara Ponsel:
    • Music: 12 / 15
    • Ring: 8 / 15
    • Notification: 7 / 15
    • Alarm: 10 / 15
    • Call: 5 / 5
    • System: 6 / 15
    ```

### 3.3 Konektivitas (WiFi, Bluetooth, Hotspot, GPS)
- **Perintah Chat:** `cek status koneksi wifi sekarang`
  - **Ekspektasi Output:**
    ```text
    Status Koneksi WiFi:
    • SSID: Rumah_Fiber_5G
    • IP Address: 192.168.1.45
    • Kekuatan Sinyal (RSSI): -52 dBm
    • Kecepatan Tautan: 433 Mbps
    • BSSID: ac:84:c6:12:34:56
    ```
- **Perintah Chat:** `pindai jaringan wifi di sekitar`
  - **Ekspektasi Output:**
    ```text
    Hasil Pindai Jaringan WiFi (4 AP ditemukan):
    • SSID: Rumah_Fiber_5G | Sinyal: -52 dBm | Frekuensi: 5180 MHz
    • SSID: Tetangga_Sebelah | Sinyal: -78 dBm | Frekuensi: 2412 MHz
    • SSID: Warkop_Free_WiFi | Sinyal: -85 dBm | Frekuensi: 2437 MHz
    ```
- **Perintah Chat:** `nyalakan hotspot wifi HP`
  - **Ekspektasi Output:** `Hotspot WiFi berhasil diaktifkan.`
- **Perintah Chat:** `cek perangkat bluetooth yang terpasang`
  - **Ekspektasi Output:**
    ```text
    Daftar Perangkat Bluetooth Terpasang (Bonded):
    • TWS Wireless Earbuds (Connected)
    • Smartwatch Fit 2 (Connected)
    ```

---

## 4. Produktivitas, Komunikasi, & Pengorganisasian

### 4.1 Alarm, Timer, & Notifikasi Pop-up
- **Perintah Chat:** `pasang alarm jam 05:30 pagi`
  - **Ekspektasi Output:** `Alarm berhasil disetel pada jam 05:30.`
- **Perintah Chat:** `pasang timer 10 menit untuk rendam cucian`
  - **Ekspektasi Output:** `Timer hitung mundur berhasil disetel selama 600 detik (10 menit) dengan label 'rendam cucian'.`
- **Perintah Chat:** `munculkan pesan toast 'Halo dari faf-agent'`
  - **Ekspektasi Output:** `Pesan toast berhasil ditampilkan di layar: 'Halo dari faf-agent'.`

### 4.2 Kontak, Telepon, & SMS
- **Perintah Chat:** `cari kontak nama Budi`
  - **Ekspektasi Output:**
    ```text
    Daftar Kontak (2 ditemukan):
    • Budi Kantor: +6281234567890
    • Budi Santoso: +6285678901234
    ```
- **Perintah Chat:** `baca 3 SMS masuk terakhir`
  - **Ekspektasi Output:**
    ```text
    Daftar SMS (3 SMS):
    • Dari Telkomsel: Paket kuota internet Anda tersisa 14.5 GB. (17-10-2026 18:20)
    • Dari Bank Mandiri: Transaksi berhasil senilai Rp 50.000. (17-10-2026 14:10)
    • Dari Tokopedia: Pesanan Anda telah tiba di tujuan. (17-10-2026 11:05)
    ```
- **Perintah Chat:** `kirim SMS ke 08123456789 pesan 'Saya sudah di lokasi ya'`
  - **Ekspektasi Output:** `SMS berhasil dikirim ke nomor 08123456789.`
- **Perintah Chat:** `telepon nomor 08123456789`
  - **Ekspektasi Output:** `Panggilan telepon ke nomor 08123456789 berhasil diinisialisasi.`

### 4.3 Clipboard (Papan Klip)
- **Perintah Chat:** `salin teks 'TOKEN-SECRET-XYZ-99' ke clipboard HP`
  - **Ekspektasi Output:** `Teks berhasil disalin ke papan klip (clipboard) perangkat.`
- **Perintah Chat:** `baca isi clipboard HP sekarang`
  - **Ekspektasi Output:**
    ```text
    Isi Papan Klip (Clipboard):
    TOKEN-SECRET-XYZ-99
    ```

---

## 5. Multimedia, Kamera, & Suara

### 5.1 Kamera & Perekaman
- **Perintah Chat:** `ambil foto menggunakan kamera belakang`
  - **Ekspektasi Output:** Mengirimkan foto asli hasil tangkapan kamera belakang perangkat langsung ke chat Telegram.
- **Perintah Chat:** `rekam audio mikrofon selama 5 detik`
  - **Ekspektasi Output:** Mengirimkan berkas rekaman suara (.m4a) dari mikrofon fisik HP ke Telegram.

### 5.2 Text-to-Speech (Bicara Keras di HP)
- **Perintah Chat:** `ucapkan 'Halo, jangan lupa istirahat makan siang' lewat speaker HP`
  - **Ekspektasi Output:** `Teks berhasil diucapkan lewat speaker ponsel fisik via TTS.` *(Suara sintesis berbunyi langsung dari speaker fisik ponsel).*

### 5.3 Pemutar Musik & YouTube
- **Perintah Chat:** `putar musik di HP`
  - **Ekspektasi Output:** `Perintah pemutar media 'play_pause' berhasil dikirim ke sistem.`
- **Perintah Chat:** `cari video lo-fi coding di youtube`
  - **Ekspektasi Output:** `Aplikasi YouTube berhasil dibuka dengan pencarian 'lo-fi coding'.`

---

## 6. Pengelolaan Aplikasi & Proses Sistem

### 6.1 Manajemen Aplikasi Android
- **Perintah Chat:** `aplikasi apa yang sedang terbuka di layar saat ini?`
  - **Ekspektasi Output:**
    ```text
    Aplikasi yang Sedang Terbuka di Layar:
    • Nama Paket: com.whatsapp
    • Activity: com.whatsapp.HomeActivity
    ```
- **Perintah Chat:** `buka aplikasi chrome`
  - **Ekspektasi Output:** `Aplikasi 'com.android.chrome' berhasil diluncurkan ke layar.`
- **Perintah Chat:** `hentikan paksa aplikasi tiktok`
  - **Ekspektasi Output:** `Aplikasi 'com.zhiliaoapp.musically' berhasil dihentikan paksa (force stop).`

### 6.2 Monitoring Beban Sistem
- **Perintah Chat:** `tampilkan 5 proses yang paling banyak memakan RAM`
  - **Ekspektasi Output:**
    ```text
    Daftar Proses Sistem (Urut berdasarkan Penggunaan RAM):
    • system_server (PID 1450) - RAM: 320 MB - User: system
    • com.android.chrome (PID 12402) - RAM: 245 MB - User: u0_a124
    • com.whatsapp (PID 8912) - RAM: 185 MB - User: u0_a92
    • python main.py (PID 21045) - RAM: 94 MB - User: u0_a245
    • surfaceflinger (PID 820) - RAM: 82 MB - User: system
    ```
- **Perintah Chat:** `/top` atau `ringkasan beban sistem saat ini`
  - **Ekspektasi Output:**
    ```text
    Ringkasan Beban Sistem & Proses:
    • Beban Rata-rata (Load Average): 1.45 (1m), 1.62 (5m), 1.50 (15m)
    • Total Proses Terdeteksi: 412 proses
    • RAM Terpakai Terbesar: system_server (320 MB), com.android.chrome (245 MB)
    ```

---

## 7. Pengingat (Reminders) & Cronjob Terjadwal

### 7.1 Pengingat Telegram Otomatis
- **Perintah Chat:** `ingatkan saya jam 14:00 untuk meeting evaluasi tim`
  - **Ekspektasi Output:** `Pengingat berhasil dijadwalkan untuk hari ini jam 14:00: 'meeting evaluasi tim'.` *(Saat jam 14:00 tiba, bot akan mengirimkan pesan otomatis ke chat Telegram).*
- **Perintah Chat:** `daftar pengingat saya` atau `/reminders`
  - **Ekspektasi Output:**
    ```text
    Daftar Pengingat Aktif:
    • [ID: rem-1a2b] Jam 14:00 (dalam 2 jam 15 menit): meeting evaluasi tim
    • [ID: rem-3c4d] Harian Jam 07:00: Minum vitamin dan olahraga pagi
    ```

### 7.2 Otomasi Cronjob Berkala
- **Perintah Chat:** `jadwalkan cek suhu dan baterai setiap 4 jam kirim ke telegram`
  - **Ekspektasi Output:**
    ```text
    Cronjob berhasil dibuat:
    • Job ID: monitor-baterai-suhu
    • Jadwal: every 4h
    • Saluran Kirim: Telegram
    • Target: Chat Aktif
    ```
- **Perintah Chat:** `daftar cronjob aktif`
  - **Ekspektasi Output:**
    ```text
    Daftar Cronjob Aktif:
    • monitor-baterai-suhu | every 4h | Eksekusi prompt agen | Aktif
    ```

---

## 8. Cuaca & Penelusuran Web

### 8.1 Cuaca & Ramalan Hujan
- **Perintah Chat:** `bagaimana cuaca hari ini di Jakarta?`
  - **Ekspektasi Output:**
    ```text
    Prakiraan Cuaca Jakarta (Hari Ini):
    • Cuaca: Berawan Sebagian
    • Suhu Saat Ini: 31.2°C (Terasa seperti 36.0°C)
    • Kelembapan: 72%
    • Kecepatan Angin: 12 km/jam
    • Potensi Hujan: Rendah (15%)
    ```
- **Perintah Chat:** `apakah nanti sore atau malam ada potensi hujan?`
  - **Ekspektasi Output:**
    ```text
    Analisis Potensi Hujan:
    • Sore (15:00 - 18:00): Hujan ringan diprediksi mulai pukul 16:30 dengan probabilitas 65%.
    • Malam: Berawan tebal, kemungkinan hujan reda.
    Saran: Siapkan payung atau jas hujan jika bepergian sore ini.
    ```

### 8.2 Pencarian Web & Riset Cepat
- **Perintah Chat:** `cari info tentang terminal ghostty apa keunggulannya`
  - **Tool Dipicu:** `web_search`
  - **Ekspektasi Output:**
    ```text
    Ghostty adalah emulator terminal lintas platform (macOS & Linux) yang dikembangkan oleh Mitchell Hashimoto (kreator HashiCorp/Vagrant) menggunakan bahasa pemrograman Zig.

    Keunggulan utamanya:
    • Rendering Berbasis GPU: Memanfaatkan Metal (macOS) dan OpenGL (Linux) sehingga latensi ketikan sangat rendah mendekati nol.
    • Performa Ekstrem: Jauh lebih ringan dan responsif dibanding iTerm2 atau Hyper, serta lebih kaya fitur dibanding Alacritty murni.
    • Tipografi Halus: Dukungan rendering teks subpixel, ligature, dan emoji yang tajam tanpa artefak visual.
    • Tab dan Windowing Natif: Menggunakan windowing natif sistem operasi tanpa bloat framework web.
    ```

---

## 9. Memori Kognitif Hermes (Penyimpanan Fakta Permanen)

- **Perintah Chat:** `ingat ya bahwa nama panggilan saya adalah Alex dan saya suka minum kopi hitam tanpa gula`
  - **Tool Dipicu:** `memory_manager` (action: `store`)
  - **Ekspektasi Output:** `Baik Alex, saya sudah mencatat dan mengingat preferensi kopi hitam tanpa gula Anda ke dalam memori permanen.`
- **Perintah Chat:** `kamu masih ingat kopi kesukaan saya apa?`
  - **Ekspektasi Output:** `Tentu Alex, Anda menyukai kopi hitam tanpa gula.`

---

## 10. Pengelolaan Dokumen PDF & REPL Python

### 10.1 Dokumen PDF
- **Aksi Uji:** Kirim berkas dokumen PDF langsung ke chat bot Telegram.
  - **Ekspektasi Output:**
    ```text
    Dokumen 'laporan_keuangan.pdf' (12 halaman) berhasil disimpan ke perpustakaan dokumen.
    Anda dapat menanyakan isi, ringkasan, atau mencari topik di dalam dokumen ini kapan saja!
    ```
- **Perintah Chat:** `ringkas poin penting dari dokumen laporan keuangan yang barusan saya kirim`
  - **Ekspektasi Output:** Menghasilkan ringkasan per bab/poin penting dari isi PDF tersebut.

### 10.2 Kalkulasi Rumit Python REPL
- **Perintah Chat:** `hitung berapa nilai 2 pangkat 64 dibagi 1337 dengan presisi penuh menggunakan python`
  - **Tool Dipicu:** `python_repl`
  - **Ekspektasi Output:**
    ```text
    Hasil Perhitungan Python:
    Nilai 2**64 // 1337 adalah 13797063462991097 dengan sisa bagi 1145.
    ```
