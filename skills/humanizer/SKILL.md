---
name: humanizer
description: |
  Humanizer Bahasa Indonesia: Mengubah teks buatan AI agar terdengar alami seperti tulisan manusia asli tanpa mengubah inti informasi dan fakta.
  Gunakan otomatis saat pengguna meminta membuat, menyusun, merapikan, atau mengedit tugas kuliah/sekolah, laporan kerja/praktikum, makalah, esai, artikel, atau tulisan profesional.
  Menghilangkan 26 tanda tulisan AI (Wikipedia Signs of AI writing versi Indonesia: bukan X melainkan Y, kalimat penutup dramatis, basa-basi panggung, trias paksa, kata klise AI Indonesia, dll.).
license: MIT
metadata:
  version: "1.0.0"
---

# Humanizer Bahasa Indonesia: Menghapus Pola Tulisan AI

Ubah teks berbahasa Indonesia yang terdengar seperti hasil AI (kaku, klise, dramatis, atau monoton) agar terbaca seperti ditulis oleh manusia sungguhan yang berpikir jernih. Pertahankan seluruh informasi faktual, data, dan klaim asli. Jangan mengarang fakta baru.

## Mengapa Teks AI Terdengar Kaku dan Tertebak

Model bahasa besar (LLM) memilih kata yang secara statistik paling mungkin muncul berikutnya berdasarkan miliaran data latih. Akibatnya, AI selalu memilih gaya rata-rata umum yang aman bagi semua topik. Manusia sebaliknya: menulis untuk satu topik tertentu dan untuk pembaca tertentu, dengan variasi kalimat yang tidak seragam dan lugas.

Pola teks AI dalam bahasa Indonesia umumnya terbagi ke dalam enam penyakit struktural:
1. **Panggung alih-alih Fakta (Staging):** Melebih-lebihkan bobot kalimat dengan sanggahan palsu ("Bukan hanya sekadar X, tapi Y") atau kalimat penutup dramatis satu baris ("Camkan itu.", "Inilah kunci sesungguhnya.").
2. **Ritme Rumus Kaku (Rhythm by rule):** Selalu memasang tiga kata beruntun ("efektif, efisien, dan terukur") dan menabur tanda pisah (—) di setiap kalimat.
3. **Pembengkakan Fakta (Inflation):** Membumbui hal biasa dengan pujian muluk ("menjadi tonggak bersejarah", "bukti nyata", "lanskap", "memainkan peran krusial").
4. **Format Berlebihan (Formatting by rule):** Menabur huruf tebal (bold) di setiap label dan menempelkan emoji di setiap subjudul.
5. **Residu Chatbot (Leftovers):** Basa-basi pembuka ("Tentu! Ini laporannya...") dan penutup ("Semoga membantu ya!").
6. **Salah Pembaca (Wrong reader):** Menjelaskan ulang hal mendasar yang sudah dipahami pembaca sebelum masuk ke inti jawaban.

---

## Cara Kerja (Alur Humanizer)

1. **Kenali Pola (Identifikasi Tells):** Pindai teks untuk menemukan tanda-tanda AI, terutama 5 tanda terkuat (§1 sampai §5) dan kata-kata klise khas AI Indonesia (§12).
2. **Tulis Ulang Langsung ke Inti (Direct Rewrite):** Tulis ulang kalimat dengan struktur baru yang wajar. Hilangkan kalimat pembuka panggung, potong bumbu dramatis, dan variasikan panjang kalimat (kombinasikan kalimat pendek dan sedang).
3. **Verifikasi Keutuhan Fakta:** Pastikan tidak ada angka, data statistik, nama, kutipan, atau argumen inti yang hilang atau tertukar. Jangan menambahkan fakta baru yang tidak bersumber dari pengguna atau teks asli.
4. **Periksa Nada Suara (Voice):**
   - **Tugas / Makalah / Laporan Akademik:** Nada objektif, lugas, baku, berbasis penalaran logis, tanpa bunga bahasa klise.
   - **Laporan Kerja / Profesional:** Nada ringkas, berorientasi hasil, langsung menyajikan data dan kesimpulan.
   - **Esai / Opini Pribadi:** Nada personal, mengalir, membawa perspektif penulis yang wajar.

---

## 26 Pola Tulisan AI Bahasa Indonesia

Pola diurutkan dari yang paling mencolok dan sering muncul. Pola §1 sampai §5 adalah tanda terkuat yang harus segera dihilangkan pada kemunculan pertama.

### A. Panggung alih-alih Menyatakan Fakta

#### 1. Bukan X melainkan Y (Not X but Y)
- **Ciri:** "Bukan hanya sekadar X, melainkan Y", "Ini bukan tentang X, tapi tentang Y", "Hal ini tidak berarti X, melainkan Y", "..., tanpa keraguan".
- **Masalah:** Menggunakan sanggahan terhadap hal yang tidak dibantah siapa pun demi membuat klaim positif terdengar lebih megah.
- **Sebelum:** "Inovasi ini bukan hanya sekadar pembaruan aplikasi, melainkan sebuah transformasi digital yang mendasar bagi organisasi."
- **Sesudah:** "Pembaruan aplikasi ini mempercepat proses administrasi di seluruh divisi."

#### 2. Penutup Satu Baris Dramatis (One-line closers & dramatic fragments)
- **Ciri:** Kalimat satu baris terpisah di akhir paragraf: "Camkan itu.", "Renungkanlah hal ini.", "Inilah kemenangan yang sesungguhnya.", "Pesan moralnya sangat jelas:", rentetan kata pendek ("Tanpa henti. Tanpa kompromi.").
- **Masalah:** Memaksa pembaca terkesima alih-alih menambah informasi.
- **Sebelum:** "Tim berhasil menyelesaikan migrasi database tepat waktu. Tanpa kesalahan. Tanpa hambatan. Dan itulah bukti dedikasi yang nyata."
- **Sesudah:** "Migrasi database selesai tepat waktu tanpa kendala pada data transaksi."

#### 3. Pepatah dan Filosofi Sok Dalam (Sayings that sound deep)
- **Ciri:** "Pada hakikatnya...", "Di era digital yang serba cepat ini...", "Pada intinya yang paling mendasar...", "X adalah bahasa dari Y", "X menjadi cermin dari Y".
- **Masalah:** Mengemas hal lumrah seolah-olah penemuan filosofis tersembunyi.
- **Sebelum:** "Di era transformasi digital yang dinamis ini, pada hakikatnya komunikasi adalah jembatan kepercayaan antara atasan dan bawahan."
- **Sesudah:** "Komunikasi rutin antara manajer dan anggota tim membantu mencegah salah paham dalam pekerjaan."

#### 4. Awalan Berbasa-basi Panggung (Staged run-up before the point)
- **Ciri:** "Mari kita selami...", "Mari kita bahas secara mendalam...", "Jujur saja?", "Begini duduk perkaranya...", "Tanpa berlama-lama lagi...", "Berikut yang perlu Anda ketahui:".
- **Masalah:** Mengumumkan apa yang akan dibahas alih-alih langsung membahasnya.
- **Sebelum:** "Mari kita bedah cara kerja algoritma sorting ini. Berikut beberapa poin penting yang perlu Anda pahami."
- **Sesudah:** "Algoritma quicksort bekerja dengan membagi larik (array) menggunakan elemen poros (pivot)."

#### 5. Berdebat dengan Hantu / Sanggahan Tanpa Lawan (Arguing with no one)
- **Ciri:** "Saya tidak bermaksud mengatakan bahwa X, tetapi...", "Sebagian orang mungkin berpikir bahwa X, padahal...", "Bisa saja kita tergoda untuk...", "Tentu ini bukan berarti X...".
- **Masalah:** Menjawab bantahan khayalan yang tidak pernah diajukan pembaca.
- **Sebelum:** "Bukan berarti metode manual tidak memiliki kelebihan, namun dalam konteks ini sistem otomatis jauh lebih unggul."
- **Sesudah:** "Sistem otomatis memproses data lebih cepat daripada pencatatan manual."

---

### B. Ritme Berdasarkan Rumus Kaku

#### 6. Trias Paksa / Tiga Serangkai (Forced triads)
- **Ciri:** Selalu menjejalkan 3 kata sifat atau kata benda beruntun: "inovatif, inspiratif, dan transformatif", "efektif, efisien, dan akuntabel", "memberikan kemudahan, fleksibilitas, dan kenyamanan".
- **Masalah:** Memaksakan ritme 3 kata padahal maknanya hanya butuh 1 atau 2 poin nyata.
- **Sebelum:** "Pelatihan ini bertujuan mencetak lulusan yang cerdas, tangguh, dan berintegritas tinggi."
- **Sesudah:** "Pelatihan ini fokus pada peningkatan keterampilan teknis dan etika kerja peserta."

#### 7. Pengulangan Kata Pembuka Kalimat (Repeated sentence openings)
- **Ciri:** Tiga kalimat berturut-turut diawali subjek yang sama: "Peneliti mencatat... Peneliti kemudian... Peneliti menemukan...".
- **Masalah:** Struktur kalimat monoton mekanis. Gabungkan kalimat atau variasikan letak predikat/objek.
- **Sebelum:** "Sistem mencatat transaksi. Sistem kemudian memverifikasi saldo. Sistem lalu mengirimkan notifikasi."
- **Sesudah:** "Setelah memverifikasi saldo dan mencatat transaksi, sistem mengirimkan notifikasi ke pengguna."

#### 8. Tanda Pisah (Em-Dash) Berlebihan (Dashes everywhere)
- **Ciri:** Menabur tanda pisah (— atau – atau ` -- `) di hampir setiap kalimat untuk menyisipkan keterangan tambahan.
- **Masalah:** Terlalu banyak tanda pisah membuat tulisan bahasa Indonesia terasa seperti terjemahan bahasa Inggris mentah. Ganti dengan koma, titik, atau restrukturisasi kalimat.
- **Sebelum:** "Kebijakan baru tersebut — yang dirumuskan tanpa konsultasi publik — menuai protes keras dari para karyawan."
- **Sesudah:** "Kebijakan baru yang dirumuskan tanpa konsultasi publik itu menuai protes keras dari para karyawan."

#### 9. Kualifikasi Bertumpuk (Stacked qualifiers)
- **Ciri:** "Bisa jadi kemungkinan besar secara potensial dapat dikatakan bahwa...", "Tampaknya patut diduga...".
- **Masalah:** Menumpuk kata ragu demi menghindari risiko klaim.
- **Sebelum:** "Bisa jadi kemungkinan kebijakan ini berpotensi memberikan dampak terhadap kenaikan omzet."
- **Sesudah:** "Kebijakan ini diperkirakan dapat menaikkan omzet penjualan."

#### 10. Penggunaan 'Di Mana' / 'Yang Mana' Tidak Baku
- **Ciri:** Menerjemahkan klausa penjelas "where/which" menjadi "di mana" atau "yang mana" di tengah kalimat.
- **Masalah:** Kesalahan struktur tata bahasa Indonesia.
- **Sebelum:** "Perusahaan menerapkan sistem absensi baru di mana karyawan wajib melakukan pemindaian wajah."
- **Sesudah:** "Perusahaan menerapkan sistem absensi baru yang mewajibkan karyawan memindai wajah."

#### 11. Kalimat Pasif Mengaburkan Pelaku (Passive voice and missing subjects)
- **Ciri:** "Diharapkan agar dapat dilakukan peninjauan ulang terhadap...", "Telah diselesaikan pengujian...".
- **Masalah:** Mengaburkan siapa yang bertanggung jawab melakukan aksi.
- **Sebelum:** "Diharapkan agar laporan ini dapat segera disetujui oleh pihak manajemen."
- **Sesudah:** "Manajemen diharapkan segera menyetujui laporan ini."

---

### C. Pembengkakan & Kewibawaan Pinjaman

#### 12. Kata-Kata Klise Khas AI Bahasa Indonesia (Overused AI words)
- **Daftar Kata/Frasa yang Wajib Dihindari:**
  - "Tak bisa dipungkiri" / "Tidak dapat dipungkiri"
  - "Perlu digarisbawahi" / "Perlu dicatat bahwa"
  - "Merupakan bukti nyata" / "Bukti konkret"
  - "Menjadi saksi bisu"
  - "Menjadi tonggak sejarah" / "Tonggak penting"
  - "Lanskap" (secara metafora abstrak: "lanskap bisnis", "lanskap teknologi")
  - "Menyelami" / "Menelusuri lebih dalam"
  - "Menghadirkan" (alih-alih "memiliki", "menyediakan", "menyebabkan")
  - "Berperan krusial" / "Memainkan peran penting"
  - "Menawarkan" (berulang kali pada deskripsi produk/fitur)
  - "Harmonisasi", "Sinergi", "Ekosistem" (secara metafora berlebihan)
  - "Komprehensif", "Holistik", "Signifikan" (jika bukan analisis statistik matematis)
- **Sebelum:** "Tak bisa dipungkiri bahwa AI memainkan peran krusial dalam mengubah lanskap pendidikan modern, menghadirkan solusi komprehensif bagi proses belajar."
- **Sesudah:** "Penggunaan AI di bidang pendidikan membantu pengajar menyusun bahan ajar dan memeriksa tugas secara lebih cepat."

#### 13. Signifikansi yang Digembungkan (Inflated significance)
- **Ciri:** Mengklaim hal kecil sebagai "pembuka era baru", "warisan abadi", "langkah revolusioner", "masa depan yang cerah".
- **Masalah:** Melebih-lebihkan fakta tanpa bukti pendukung.
- **Sebelum:** "Peluncuran modul login baru ini menandai era baru dalam sejarah keamanan data perusahaan."
- **Sesudah:** "Modul login baru ini menambahkan verifikasi dua langkah (2FA) untuk meningkatkan keamanan akun."

#### 14. Keterkaitan Samar (Vague connection)
- **Ciri:** "Terkait erat dengan...", "Memiliki kaitan tak terpisahkan...", "Berhubungan dengan...".
- **Masalah:** Menyatakan ada hubungan tanpa menjelaskan bentuk hubungannya.
- **Sebelum:** "Angka penjualan kuartal ini terkait erat dengan dinamika pasar global."
- **Sesudah:** "Penjualan kuartal ini turun 12 persen karena kenaikan biaya impor bahan baku."

#### 15. Ekor Kalimat Berimbuhan 'Menjadikan/Mencerminkan' (Shallow -ing riders)
- **Ciri:** Menempelkan frasa gerund di ujung kalimat: "...menjadikannya bukti nyata...", "...sekaligus mencerminkan komitmen mendalam...".
- **Masalah:** Frasa tempelan penghias yang tidak menambah fakta.
- **Sebelum:** "Gedung ini menggunakan panel surya di atapnya, mencerminkan komitmen mendalam perusahaan terhadap pelestarian lingkungan."
- **Sesudah:** "Gedung ini menggunakan panel surya di atapnya untuk menghemat konsumsi listrik PLN sekitar 20 persen."

#### 16. Bahasa Brosur Promosi dalam Tulisan Formal (Sales language)
- **Ciri:** "Terletak anggun di tengah keasrian...", "Menawarkan pesona luar biasa...", "Karya spektakuler yang memikat".
- **Masalah:** Menggunakan bahasa iklan pada tugas, makalah, atau laporan resmi.
- **Sebelum:** "Laboratorium biologi kampus ini menawarkan fasilitas canggih nan memukau bagi para peneliti muda."
- **Sesudah:** "Laboratorium biologi kampus ini dilengkapi mikroskop elektron dan inkubator steril."

#### 17. Kewibawaan Pinjaman Tanpa Sumber Riil (Borrowed authority)
- **Ciri:** "Para ahli sepakat bahwa...", "Banyak kalangan menilai...", "Berdasarkan berbagai sumber tepercaya...".
- **Masalah:** Mengatasnamakan pakar tanpa menyebut nama ahli, institusi, atau tahun penelitian.
- **Sebelum:** "Para ahli meyakini bahwa konsumsi gula berlebih memicu gangguan metabolisme."
- **Sesudah:** "Penelitian WHO (2023) menunjukkan konsumsi gula harian di atas 50 gram meningkatkan risiko diabetes tipe 2."

#### 18. Menghindari Kata Kerja Sederhana 'Adalah' & 'Memiliki'
- **Ciri:** Mengganti kata kerja biasa dengan "berfungsi sebagai", "hadir sebagai", "merepresentasikan", "menampilkan ragam".
- **Sebelum:** "Dokumen ini berfungsi sebagai panduan teknis bagi teknisi lapangan."
- **Sesudah:** "Dokumen ini adalah panduan teknis untuk teknisi lapangan."

---

### D. Format Berdasarkan Pola Kaku

#### 19. Huruf Tebal (Bold) Berhamburan
- **Ciri:** Setiap istilah diberi cetak tebal tanpa alasan, atau membuat daftar dengan label tebal berulang (**Fitur:** ..., **Keunggulan:** ...).
- **Solusi:** Hapus cetak tebal dekoratif. Tuliskan dalam bentuk paragraf mengalir yang rapi.

#### 20. Judul Berhias Emoji dan Gaya Klikbait
- **Ciri:** "🚀 Tahap Peluncuran", "💡 Poin Kunci:", "Bab 1: Menguak Rahasia Sistem".
- **Solusi:** Gunakan judul deskriptif lugas tanpa emoji anak-anak: "1. Metodologi Penelitian", "2. Hasil Pengujian".

#### 21. Tanda Petik Terjemahan Mesin
- **Ciri:** Tanda petik ganda bengkok atau penempatan tanda baca di luar/dalam petik yang tidak konsisten dengan kaidah PUEBI/EYD.

---

### E. Residu Percakapan Chatbot & Draf

#### 22. Residu Chatbot (Chatbot residue)
- **Ciri:** "Tentu! Berikut adalah laporannya:", "Pertanyaan yang sangat bagus!", "Semoga penjelasan ini membantu ya!", "Jika ada yang ingin ditanyakan lagi, silakan kabari saya."
- **Solusi:** Hapus seluruh kalimat pembuka dan penutup obrolan tersebut. Sajikan langsung isi dokumennya.

#### 23. Pernyataan Batas Pengetahuan AI (Disclaimers & guesses)
- **Ciri:** "Berdasarkan data yang tersedia hingga pembaruan terakhir saya...", "Meskipun informasinya terbatas, kemungkinan besar...".
- **Solusi:** Jangan berspekulasi. Tuliskan hanya fakta yang valid atau nyatakan secara lugas data mana yang belum diperoleh.

#### 24. Judul Diulang pada Kalimat Pertama
- **Ciri:** Judul bab langsung diulang di kalimat pembuka paragraf pertama tanpa membawa konteks baru.
- **Sebelum:** "## Keandalan Server\nKeandalan server adalah aspek krusial."
- **Sesudah:** "## Keandalan Server\nUptime server selama semester pertama mencapai 99,8 persen."

#### 25. Menulis Tentang Dokumen Alih-alih Isinya
- **Ciri:** "Laporan ini disusun untuk menjelaskan...", "Tabel berikut menyajikan perbandingan antara...".
- **Solusi:** Langsung bahas topik dan temuannya.

---

### F. Menulis untuk Pembaca yang Salah

#### 26. Menjelaskan Ulang Hal yang Sudah Diketahui Pembaca
- **Ciri:** Menjelaskan ulang teori pengantar dasar panjang lebar ketika dosen atau manajer hanya meminta hasil evaluasi atau rekomendasi praktis.
- **Solusi:** Awali langsung dengan kesimpulan atau keputusan utama, lalu sertakan bukti relevan.

---

## Contoh Lengkap Transformasi: Tugas & Laporan

### Contoh 1: Laporan Praktikum / Analisis Sistem

**Sebelum (Gaya Khas AI):**
> Tak bisa dipungkiri bahwa di era transformasi digital saat ini, sistem basis data bukan hanya sekadar tempat penyimpanan data, melainkan pilar fundamental yang memainkan peran krusial dalam keberlanjutan operasional perusahaan. Melalui implementasi indexing yang inovatif, komprehensif, dan adaptif, sistem dapat menghadirkan peningkatan performa yang sangat signifikan. Hal ini menjadi bukti nyata bahwa optimasi query adalah kunci utama. Perlu digarisbawahi bahwa indeks B-Tree berfungsi sebagai solusi andal dalam mereduksi waktu eksekusi. Camkan bahwa arsitektur data yang kokoh adalah cerminan dari kematangan teknologi organisasi.

**Sesudah (Gaya Humanizer Alami):**
> Penambahan indeks B-Tree pada kolom tanggal transaksi memangkas waktu pencarian data dari 1,8 detik menjadi 45 milidetik pada tabel berukuran 2 juta baris. Optimasi ini juga menurunkan utilisasi CPU server database saat jam sibuk dari rata-rata 82 persen menjadi 34 persen.

### Contoh 2: Pendahuluan Makalah / Tugas Kuliah

**Sebelum (Gaya Khas AI):**
> Dalam lanskap pendidikan kontemporer yang sarat akan tantangan dan dinamika, pembelajaran daring hadir sebagai sebuah terobosan revolusioner yang tak terelakkan. Bukan hanya sekadar alternatif di masa krisis, pembelajaran jarak jauh telah menjadi simbol kemajuan peradaban ilmiah. Para ahli meyakini bahwa integrasi platform digital menawarkan peluang tanpa batas untuk memperkaya wawasan mahasiswa. Kendati demikian, terdapat berbagai tantangan yang membentang di hadapan kita. Namun demikian, masa depan pendidikan tinggi tetap memancarkan optimisme yang luar biasa.

**Sesudah (Gaya Humanizer Alami):**
> Pembelajaran daring selama tiga tahun terakhir memperluas akses materi kuliah bagi mahasiswa di luar pulau Jawa. Namun, survei internal kampus pada semester ganjil 2025 menunjukkan 42 persen mahasiswa masih terkendala kestabilan koneksi internet saat ujian praktikum berbasis video, sehingga ujian daring membutuhkan penyesuaian format tugas mandiri.
