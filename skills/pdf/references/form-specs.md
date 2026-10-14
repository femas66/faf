# Format Spesifikasi JSON Dokumen & Formulir PDF (Form Specs)

Dokumen ini mendefinisikan skema JSON yang digunakan oleh `pdf_create.py`, `pdf_make_form.py`, dan validator tata letak `pdf_form_layout.py`.

---

## 1. Skema Dokumen (`pdf_create.py`)

Digunakan untuk membuat dokumen laporan, proposal, lembar fakta, atau surat resmi dari spesifikasi JSON terstruktur.

```json
{
  "title": "Laporan Kinerja Agen Q3",
  "author": "FAF Agent Intelligence",
  "subject": "Ringkasan Eksekutif",
  "page_size": "A4",
  "margins": {
    "left": 54,
    "right": 54,
    "top": 54,
    "bottom": 54
  },
  "header": "Laporan Rahasia - Halaman {page} dari {pages}",
  "footer": "Dicetak otomatis oleh FAF Assistant - {page} / {pages}",
  "elements": [
    {
      "type": "heading",
      "text": "Ringkasan Eksekutif Kuartal 3",
      "level": 1,
      "align": "center",
      "color": "#1E3A8A",
      "space_after": 12
    },
    {
      "type": "paragraph",
      "text": "Dokumen ini merangkum seluruh aktivitas otomatisasi sistem Android dan eksekusi tugas AI.",
      "font_size": 11,
      "color": "#334155",
      "align": "left",
      "space_after": 10
    },
    {
      "type": "hr",
      "thickness": 1.5,
      "color": "#CBD5E1",
      "space_after": 14
    },
    {
      "type": "table",
      "has_header": true,
      "header_bg": "#1E40AF",
      "header_color": "#FFFFFF",
      "striped": true,
      "stripe_bg": "#F8FAFC",
      "grid": true,
      "border_color": "#E2E8F0",
      "col_widths": [140, 180, 160],
      "data": [
        ["Komponen", "Metrik Pengujian", "Hasil Status"],
        ["Root Shell Engine", "150 perintah sukses", "Lolos (100%)"],
        ["Tool OCR Offline", "Tesseract ind+eng", "Lolos (99.2%)"],
        ["PDF Creation Tool", "Rendering JSON ke A4", "Lolos (100%)"]
      ],
      "space_after": 16
    },
    {
      "type": "list",
      "bullet_type": "bullet",
      "items": [
        "Semua proses dieksekusi secara aman tanpa membebani memori.",
        "Kompatibel penuh dengan perangkat Android yang di-root.",
        "Dukungan enkripsi AES-256 untuk keamanan data tingkat tinggi."
      ]
    },
    {
      "type": "page_break"
    },
    {
      "type": "heading",
      "text": "Lampiran & Detail Teknis",
      "level": 2
    }
  ]
}
```

### Elemen yang Didukung:
- `heading`: `level` (1, 2, atau 3), `text`, `align`, `color`, `space_after`.
- `paragraph`: `text` (mendukung tag HTML dasar `<b>`, `<i>`, `<u>`), `font_size`, `leading`, `align`, `color`, `space_after`.
- `spacer`: `height` (dalam points).
- `hr` / `divider`: `thickness`, `color`, `space_before`, `space_after`.
- `table`: `data` (matriks 2D), `has_header`, `col_widths`, `header_bg`, `header_color`, `grid`, `striped`, `stripe_bg`, `border_color`.
- `image`: `path`, `width`, `height`, `align` ("center", "left", "right").
- `list`: `items` (daftar teks), `bullet_type` ("bullet" atau "number").
- `page_break`: Pemisah halaman manual.

---

## 2. Skema Formulir Isian AcroForm (`pdf_make_form.py`)

Digunakan untuk membuat formulir digital interaktif (PDF forms) dengan field input teks, kotak centang (checkbox), dropdown/combobox, radio button, dan area tanda tangan.

```json
{
  "title": "Formulir Pendaftaran Pengguna",
  "page_size": "A4",
  "origin": "top-left",
  "pages": [
    {
      "page_number": 1,
      "drawings": [
        {
          "type": "heading",
          "text": "FORMULIR PENDAFTARAN ANGGOTA",
          "x": 50,
          "y": 60,
          "size": 16,
          "font": "helv-bold",
          "color": "#1E293B"
        },
        {
          "type": "text",
          "text": "Nama Lengkap:",
          "x": 50,
          "y": 105,
          "size": 10,
          "color": "#475569"
        },
        {
          "type": "text",
          "text": "Departemen:",
          "x": 50,
          "y": 155,
          "size": 10,
          "color": "#475569"
        },
        {
          "type": "line",
          "x0": 50,
          "y0": 75,
          "x1": 545,
          "y1": 75,
          "color": "#CBD5E1",
          "width": 1.5
        }
      ],
      "fields": [
        {
          "name": "full_name",
          "type": "text",
          "rect": [150, 90, 320, 24],
          "value": "",
          "label": "Nama Lengkap",
          "border_color": "#94A3B8",
          "fill_color": "#F8FAFC"
        },
        {
          "name": "department",
          "type": "choice",
          "rect": [150, 140, 220, 24],
          "options": ["Teknologi Informasi", "Operasional", "Keuangan", "Pemasaran"],
          "value": "Teknologi Informasi"
        },
        {
          "name": "agree_terms",
          "type": "checkbox",
          "rect": [50, 190, 18, 18],
          "value": false,
          "label": "Saya menyetujui syarat & ketentuan layanan"
        },
        {
          "name": "signature",
          "type": "signature",
          "rect": [50, 240, 250, 50]
        }
      ]
    }
  ]
}
```

### Format Rect & Koordinat
- Standard: `[x, y, width, height]`
- Default `origin`: `"top-left"` (di mana `x=0, y=0` adalah pojok kiri atas halaman, dan `y` bertambah ke bawah sesuai format web/UI modern).
- Jika dokumen lama menggunakan sistem koordinat standar PDF: tentukan `"origin": "bottom-left"`.

### Tipe Widget Formulir:
- `text` / `textarea`: Input teks bebas satu baris atau multi-baris (`multiline: true`).
- `checkbox`: Kotak centang boolean (`true` / `false`).
- `choice` / `combobox`: Menu pilihan tarik-turun (dropdown) dengan properti `options`.
- `radio`: Tombol opsi radio, gunakan atribut `group` atau `name` yang sama untuk opsi dalam satu kelompok.
- `signature`: Kotak area tanda tangan digital / basah.

---

## 3. Aturan Linting Tata Letak (`pdf_form_layout.py`)

Sebelum merender formulir PDF, jalankan linter untuk mencegah cacat desain:

1. **Collision / Overlap Detection**: Menemukan jika dua bounding box field saling bertumpukan atau bertubrukan pada halaman yang sama.
2. **Page Bounds Containment**: Memastikan seluruh bagian widget berada di dalam batas halaman (tidak terpotong di tepi margin).
3. **Target Sizing**:
   - Checkbox minimal 14x14 pt agar mudah ditekan di layar sentuh perangkat Android/mobile.
   - Text input minimal tinggi 18 pt agar nyaman dibaca.
4. **Duplicate Field Names**: Mendeteksi nama field duplikat yang tidak sengaja (kecuali tombol radio yang memang sengaja digrup).
