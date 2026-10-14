# Lembar Contekan CLI Script PDF (CLI Cheatsheet)

Semua script pembantu PDF berada di dalam folder `scripts/` (atau `skills/pdf/scripts/`) dan dapat dijalankan langsung melalui terminal. Setiap script dilengkapi dengan panduan bawaan via `--help`.

---

## 1. Pembuatan Dokumen & Formulir

### Membangun Dokumen PDF dari JSON Spec
```bash
python scripts/pdf_create.py spec.json -o out.pdf
python scripts/pdf_create.py spec.json -o out.pdf --page-size LETTER
```

### Membuat Formulir Isian AcroForm dari JSON Spec
```bash
python scripts/pdf_make_form.py formspec.json -o form.pdf
```

### Linting Tata Letak Formulir Sebelum Membangun
```bash
# Validasi batas dan collision tanpa render
python scripts/pdf_form_layout.py formspec.json

# Validasi sekaligus render visualisasi bounding box
python scripts/pdf_form_layout.py formspec.json --render-overlay boxes.png

# Render overlay di atas PDF yang sudah jadi
python scripts/pdf_form_layout.py formspec.json --render-overlay boxes.png --pdf form.pdf
```

---

## 2. Pembacaan & Ekstraksi Data

### Ekstraksi Teks Per Halaman (JSON atau Raw)
```bash
# Hasil terstruktur JSON dengan metadata karakter dan dimensi
python scripts/pdf_read.py doc.pdf --text

# Simpan ke berkas JSON
python scripts/pdf_read.py doc.pdf --text -o output.json

# Teks mentah langsung ke terminal
python scripts/pdf_read.py doc.pdf --text --raw
```

### Ekstraksi Tabel dan Export ke CSV
```bash
# Ekstraksi tabel dalam format JSON
python scripts/pdf_read.py doc.pdf --tables

# Ekstraksi tabel dan otomatis simpan tiap tabel ke CSV
python scripts/pdf_read.py doc.pdf --tables --csv-dir ./hasil_tabel/
```

### Inspeksi Metadata & Deteksi Dokumen Pindaian (Scanned PDF)
```bash
python scripts/pdf_read.py doc.pdf --meta
```

### Memeriksa Field Formulir AcroForm
```bash
python scripts/pdf_read.py form.pdf --fields
```

---

## 3. Manipulasi Halaman & Penggabungan

### Menggabungkan Beberapa Berkas PDF
```bash
# Gabungkan dengan outline/daftar isi berdasarkan nama berkas
python scripts/pdf_merge.py bab1.pdf bab2.pdf bab3.pdf -o buku.pdf --bookmarks
```

### Memotong / Mengekstrak Halaman PDF
```bash
# Ekstrak halaman tertentu dengan rotasi
python scripts/pdf_split.py doc.pdf --pages 1-3,7 -o bagian.pdf --rotate 90

# Ekstrak tiap halaman menjadi berkas terpisah
python scripts/pdf_split.py doc.pdf --pages 1-5 -o "halaman_{page}.pdf"
```

---

## 4. Pengisian Formulir & Keamanan

### Mengisi Formulir PDF (AcroForm)
```bash
# Mengisi field dari berkas JSON
python scripts/pdf_fill_form.py form.pdf --fields-json values.json -o filled.pdf

# Mengisi field sekaligus membekukan (flatten) agar tidak bisa diedit lagi
python scripts/pdf_fill_form.py form.pdf --fields-json values.json -o filled.pdf --flatten

# Mengisi field cepat secara langsung dari CLI
python scripts/pdf_fill_form.py form.pdf --field username="JohnDoe" --field status="Active" -o filled.pdf
```

### Enkripsi & Dekripsi Kata Sandi (AES-256)
```bash
# Enkripsi dokumen dengan kata sandi
python scripts/pdf_secure.py doc.pdf --encrypt -o enc.pdf --user-password rahasia123

# Dekripsi dokumen terenkripsi
python scripts/pdf_secure.py enc.pdf --decrypt -o dec.pdf --password rahasia123
```

---

## 5. Watermark, Stempel, & Gambar

### Menerapkan Watermark / Cap PDF
```bash
# Watermark di atas konten (overlay foreground)
python scripts/pdf_watermark.py doc.pdf --stamp mark.pdf -o stamped.pdf

# Watermark di belakang konten (background underlay)
python scripts/pdf_watermark.py doc.pdf --stamp mark.pdf -o stamped.pdf --under
```

### Menempelkan Stempel Teks / Gambar Kustom
```bash
# Stempel teks miring transparan ("DRAFT")
python scripts/pdf_stamp.py doc.pdf -o out.pdf --text "DRAFT" --x 150 --y 400 \
    --font-size 60 --rotation 45 --opacity 0.3 --color "#cc0000" --pages 1-3

# Stempel gambar tanda tangan di pojok
python scripts/pdf_stamp.py doc.pdf -o out.pdf --image tanda_tangan.png --x 400 --y 60 --width 120
```

### Mengonversi Halaman PDF Menjadi Gambar
```bash
python scripts/pdf_page_image.py doc.pdf --pages 1-3 --dpi 150 --out-dir imgs/
```

---

## 6. Metadata & Lampiran Berkas (Attachments)

### Mengubah Metadata Dokumen
```bash
python scripts/pdf_meta.py doc.pdf --set-meta --title "Laporan Tahunan" --author "Tim AI" -o out.pdf
```

### Menyematkan Lampiran ke Dalam PDF
```bash
python scripts/pdf_meta.py doc.pdf --attach data_rekap.csv -o out.pdf
```

### Melihat & Mengekstrak Lampiran
```bash
# Lihat daftar lampiran di dalam berkas PDF
python scripts/pdf_meta.py out.pdf --list-attachments

# Ekstrak seluruh lampiran ke folder tujuan
python scripts/pdf_meta.py out.pdf --extract-attachments ./lampiran_ekstrak/
```
