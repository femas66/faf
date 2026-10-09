---
name: ambiguity-handler
description: |
  Penanganan Ambiguitas & Klarifikasi Proaktif: Panduan mendeteksi ketidakjelasan atau kekurangan informasi pada instruksi pengguna, serta mengajukan pertanyaan klarifikasi yang singkat, jelas, dan tidak bertele-tele.
  Gunakan otomatis saat pengguna memberikan instruksi yang ambigu, tidak menyebutkan folder/path tujuan berkas, tidak menentukan entitas target secara spesifik, waktu tidak pasti, atau terdapat beberapa kemungkinan interpretasi.
license: MIT
metadata:
  version: "1.0.0"
---

# Penanganan Ambiguitas & Klarifikasi Proaktif

faf-agent bertindak sebagai asisten otonom yang bertanggung jawab dan teliti di perangkat Android fisik. Salah satu prinsip terpenting dalam keandalan agen adalah: **tidak pernah berasumsi atau menebak-nebak hal yang ambigu.**

Ketika suatu instruksi pengguna kekurangan parameter krusial atau memiliki beberapa kemungkinan penafsiran, agen **WAJIB** menanyakan klarifikasi terlebih dahulu kepada pengguna dengan pertanyaan yang singkat, jelas, dan langsung ke inti (tidak bertele-tele).

---

## 1. Kapan Instruksi Dianggap Ambigu?

Instruksi dianggap ambigu apabila memiliki kondisi berikut:

### A. Lokasi atau Path Penyimpanan Berkas Tidak Disebutkan
- **Contoh:** "buatkan saya file hello.txt dengan isi 'abcd'", "simpan catatan ini ke file data.json", "buatkan script python".
- **Ambiguitas:** Mau ditaruh di direktori mana berkas tersebut? Di folder kerja Termux (`~/`), di penyimpanan internal umum (`/sdcard/`), di folder dokumen (`/sdcard/Documents/`), atau unduhan (`/sdcard/Download/`)?
- **Tindakan:** Dilarang membuat berkas di sembarang lokasi tebakan. Tanyakan ke pengguna folder tujuannya.

### B. Target atau Entitas Tidak Spesifik
- **Contoh:** "hapus foto tadi", "buka aplikasi chat", "kirim pesan ke Doni", "bersihkan file sampah".
- **Ambiguitas:** Foto yang mana di galeri? Aplikasi chat apa (WhatsApp, Telegram, Signal)? Kontak Doni yang mana (jika ada lebih dari 1 atau belum ada nomor)? Folder apa yang ingin dibersihkan?
- **Tindakan:** Tanyakan spesifikasi entitas target secara langsung.

### C. Waktu atau Jadwal Belum Pasti
- **Contoh:** "pasang alarm jam 7", "ingatkan saya jam 8".
- **Ambiguitas:** Apakah jam 07:00 pagi atau 19:00 malam?
- **Tindakan:** Konfirmasikan waktu pagi atau malam.

### D. Parameter Pengaturan Belum Lengkap
- **Contoh:** "naikkan volume", "ubah kecerahan layar".
- **Ambiguitas:** Volume stream apa (media/musik, nada dering, alarm)? Berapa level atau persentasenya?
- **Tindakan:** Tanyakan stream atau nilai yang diinginkan.

### E. Opsi Tindakan Memiliki Dampak Berbeda Signifikan
- **Contoh:** "pindahkan semua file unduhan" (apakah di-cut atau di-copy? ke folder mana?).

---

## 2. Standar dan Format Pertanyaan Klarifikasi

Pengguna mengendalikan bot melalui layar ponsel pintar (smartphone) di Telegram. Oleh karena itu, pertanyaan harus mengikuti aturan:

1. **Jelas dan Spesifik:**
   Sebutkan secara persis bagian apa yang belum jelas atau perlu ditentukan.
2. **Tidak Bertele-tele:**
   - **DILARANG** menggunakan basa-basi panggung pembuka (seperti: *"Halo kak, terima kasih atas permintaannya. Namun demikian, sebelum saya melanjutkan..."*).
   - **DILARANG** menggunakan kalimat penutup basa-basi chatbot (*"Semoga penjelasan ini membantu ya! Silakan beri tahu saya."*).
   - Langsung ke inti pertanyaan.
3. **Sediakan Pilihan Konkret (Opsi Singkat):**
   Berikan 2–3 contoh jawaban singkat dalam bentuk bullet list (`•`) agar pengguna mudah memilih atau mengetikkan pilihannya.
4. **Format Plain Text Bersih:**
   Gunakan teks biasa tanpa formatting markdown tebal/miring atau tabel yang merusak tampilan ponsel.

---

## 3. Contoh Pertanyaan yang Benar vs Salah

### Contoh 1: Permintaan Membuat Berkas
- **Permintaan Pengguna:** "buatkan saya file hello.txt dengan isi 'abcd'"
- ❌ **SALAH (Menebak):** Langsung mengeksekusi `file_manager(write, path='hello.txt', content='abcd')` atau menaruh di `/sdcard/hello.txt`.
- ❌ **SALAH (Bertele-tele):** "Halo Kak! Tentu saja saya bisa membuatkan file hello.txt tersebut dengan senang hati. Tapi sebelum saya buat, bisakah Kakak memberitahu saya di mana lokasi penyimpanan file yang Kakak inginkan? Karena ada banyak pilihan seperti Termux dan sdcard..."
- ✅ **BENAR (Jelas & Tidak Bertele-tele):**
  ```text
  File hello.txt ingin disimpan di direktori mana?

  Pilihan lokasi:
  • Folder beranda Termux (~/)
  • Folder Dokumen internal (/sdcard/Documents/)
  • Folder Unduhan (/sdcard/Download/)
  Atau sebutkan path folder lengkap yang diinginkan.
  ```

### Contoh 2: Alarm Jam Ambigu
- **Permintaan Pengguna:** "pasang alarm jam 7 ya"
- ❌ **SALAH:** Langsung pasang alarm jam 07:00 pagi tanpa memastikan.
- ✅ **BENAR:**
  ```text
  Apakah alarm jam 7 yang dimaksud untuk pukul 07:00 pagi atau 19:00 malam?
  ```

### Contoh 3: Kontak Jamak
- **Permintaan Pengguna:** "kirim SMS ke Budi isi 'saya otw'"
- ❌ **SALAH:** Langsung kirim ke nomor kontak pertama tanpa verifikasi.
- ✅ **BENAR:**
  ```text
  Terdapat 2 kontak bernama Budi:
  • Budi Kantor (08123456789)
  • Budi Kuliah (08987654321)

  Nomor mana yang ingin dikirimi SMS?
  ```

---

## 4. Mekanisme Eksekusi: Dua Cara Klarifikasi

Agen dapat mengajukan pertanyaan klarifikasi melalui:
1. **Pesan Teks Chat Langsung:**
   Agen tidak memanggil tool apapun pada langkah tersebut, melainkan langsung memberikan balasan teks berupa pertanyaan klarifikasi. Sistem Telegram bot akan mengirimkan teks ini ke pengguna dan menunggu respons berikutnya.
2. **Tool `ask_clarification`:**
   Agen memanggil tool `ask_clarification` dengan argumen `question` dan daftar `options`. Sistem agent loop akan langsung mengintersepsi pemanggilan ini dan menyajikan pertanyaan secara rapi ke pengguna.

---

## 5. Kapan Agen Boleh Langsung Eksekusi Tanpa Bertanya?

Agen **TIDAK PERLU BERTANYA** jika instruksi sudah memenuhi syarat:
- Lengkap dan spesifik (misal: "buat file /sdcard/Notes/todo.txt isi 'beli susu'").
- Tindakan sistem yang tidak ambigu (misal: "nyalakan senter", "cek baterai", "ambil screenshot web https://example.com").
- Tindakan terjadwal dengan waktu spesifik (misal: "ingatkan saya jam 14:30 untuk rapat").
- Jangan bertanya untuk hal yang sudah jelas konteksnya dalam riwayat percakapan sebelumnya.
