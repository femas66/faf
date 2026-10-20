---
name: code-to-image
description: |
  Ubah kode atau teks pemrograman menjadi gambar PNG tangkapan layar VS Code (tema Dark+).
  Gunakan saat pengguna meminta membuat screenshot kode, gambar kode, CodeSnap, konversi snippet teks/kode jadi gambar beresolusi tinggi, atau membagikan kode secara visual.
tags:
  - codesnap
  - vscode
  - syntax-highlighting
  - image-generation
  - developer-tools
  - python
metadata:
  version: "1.0.0"
---

# Code to Image (VS Code Dark+ Style)

Skill ini memberdayakan AI agent dan pengembang untuk mengubah teks atau berkas kode menjadi gambar tangkapan layar PNG yang sangat otentik bergaya **Visual Studio Code (tema Dark+)**, mirip dengan ekstensi CodeSnap.

Gambar yang dihasilkan memiliki palet warna persis VS Code Dark+, breadcrumb navigator, tab file dengan ikon bahasa, nomor baris yang dapat disesuaikan (`--start-line`), sorot baris (`--highlight`), kursor aktif (`--cursor`), soft wrap (`--wrap`), serta dukungan multi-bahasa termasuk file Jupyter Notebook (`.ipynb`).

---

## 1. Dependensi & Instalasi

Tool ini dibangun menggunakan dependensi Pure-Python yang ringan dan kompatibel penuh dengan lingkungan Android Termux:

```bash
# Di Termux (Android)
pkg install python-pillow
pip install pygments

# Di macOS / Linux umum
pip install pillow pygments
```

---

## 2. Parameter & Opsi CLI (`code_to_image.py`)

Skrip mandiri `code_to_image.py` tersedia di root proyek dan dapat dijalankan langsung melalui shell atau pipe stdin:

```bash
python code_to_image.py [OPSI]
```

| Parameter | Opsi Singkat | Tipe | Default | Deskripsi |
|---|---|---|---|---|
| `--file` | `-f` | Path | `None` | Path berkas kode sumber yang akan dibaca |
| `--text` | `-t` | String | `None` | Teks kode yang akan dirender langsung via CLI |
| `stdin` | - | Stream | - | Kode dapat dialirkan via pipe (`cat file.py \| python code_to_image.py`) |
| `--lang` | `-l` | String | Otomatis | Bahasa kode (`python`, `golang`, `php`, `html`, `js`, `ts`, `bash`, `sql`, `css`, `json`, `ipynb`, dll.) |
| `--name` | `-n` | String | Otomatis | Nama file di tab VS Code (otomatis disesuaikan dengan bahasa jika kosong) |
| `--path` | `-p` | String | Nilai `--name` | Isi jalur breadcrumb di atas editor (contoh: `src/utils/main.py`) |
| `--frame` | - | Enum | `tab` | Gaya frame: `tab` (default, tanpa status bar), `full` (+ title bar & status bar), `none` (kode saja) |
| `--os` | - | `win` \| `mac` | `mac` (di Mac) / `win` | Gaya title bar jendela untuk frame `full` |
| `--project` | - | String | `faf-agent` | Nama folder/project di title bar |
| `--branch` | - | String | `main` | Nama branch Git di status bar |
| `--highlight` | - | String | `None` | Sorot baris tertentu (contoh: `3,5-7` atau `42,45-48`) |
| `--cursor` | - | String | `None` | Posisi kursor & baris aktif dengan format `baris:kolom` (contoh: `12:5`) |
| `--wrap` | - | Integer | `None` | Soft wrap pada N kolom agar gambar tidak terlalu lebar (contoh: `80`) |
| `--start-line` | `-s` | Integer | `1` | Nomor baris awal pada gutter (contoh: `40` untuk mulai baris 40) |
| `--scale` | - | Float | `2.0` | Skala resolusi gambar (2 = tajam Retina/HiDPI) |
| `--output` | `-o` | Path | `code.png` | Lokasi berkas PNG keluaran |
| `--font` | - | Path | `None` | Path berkas font monospace custom (`.ttf`, `.otf`, `.ttc`) |
| `--font-dir` | - | Folder | `.fonts` | Folder font kustom (default mencari di folder `.fonts/` lokal atau `~/.fonts`) |
| `--no-status-bar`| - | Flag | `False` | Sembunyikan status bar bahkan ketika `--frame full` digunakan |

---

## 3. Dukungan Bahasa Pemrograman Lengkap

Tool ini mendukung sintaks hampir semua bahasa pemrograman populer dengan badge ikon tab dan pewarnaan Dark+ otentik:

| Kategori | Bahasa | Ekstensi Berkas | Ikon Tab & Warna |
|---|---|---|---|
| **Backend & Systems** | **Golang** | `.go` | `GO` (Cyan `#00ADD8`) |
| | **PHP** | `.php`, `.phtml` | `PHP` (Ungu `#777BB4`, auto-inline) |
| | **Python** | `.py`, `.pyw`, `.pyx` | `PY` (Biru `#3572A5`) |
| | **Rust** | `.rs` | `RS` (Cokelat `#DEA584`) |
| | **C / C++** | `.c`, `.h`, `.cpp`, `.hpp`, `.cc` | `C` / `C++` (Biru `#00599C`) |
| | **C#** | `.cs` | `C#` (Hijau `#178600`) |
| | **Java / Kotlin**| `.java`, `.kt`, `.kts` | `JV` / `KT` (Oranye `#B07219`) |
| **Web & Frontend** | **HTML** | `.html`, `.htm`, `.xhtml` | `<>` (Oranye `#E34F26`) |
| | **JavaScript** | `.js`, `.mjs`, `.cjs` | `JS` (Kuning `#F7DF1E`) |
| | **TypeScript** | `.ts`, `.mts`, `.cts` | `TS` (Biru `#3178C6`) |
| | **React JSX/TSX**| `.jsx`, `.tsx` | `JSX` / `TSX` (Cyan `#61DAFB`) |
| | **CSS / SCSS** | `.css`, `.scss`, `.sass`, `.less` | `#` (Ungu `#563D7C`) |
| **Database & Query** | **SQL** | `.sql`, `.pgsql`, `.mysql`, `.sqlite` | `SQL` (Emas `#E38C00`) |
| | **Prisma** | `.prisma` | `▲` (Dark `#2D3748`) |
| **Shell & DevOps** | **Bash / Shell** | `.sh`, `.bash`, `.zsh`, `.ksh`, `.fish` | `$_` (Hijau `#4EAA25`) |
| | **PowerShell** | `.ps1` | `PS` (Biru Navy `#012456`) |
| | **Docker** | `Dockerfile`, `.dockerignore` | `🐳` (Biru Tua `#384D54`) |
| | **Makefile** | `Makefile`, `gnumakefile` | `MK` (Hijau Zaitun `#427819`) |
| **Data & Notebook** | **Jupyter** | `.ipynb` | `NB` (Oranye `#F37626`, rich card) |
| | **JSON / YAML** | `.json`, `.yaml`, `.yml`, `.toml` | `{ }` / `YM` / `TO` |
| | **Markdown** | `.md`, `.markdown` | `MD` (Biru `#083FA1`) |
| | **Config / Env** | `.env`, `.ini`, `.cfg`, `.conf` | `⚙` (Abu-abu `#6D8086`) |

---

## 4. Contoh Penggunaan CLI

### A. Format Standar (Frame Tab, Tanpa Status Bar)
```bash
python code_to_image.py \
  --file src/config.py \
  --name config.py \
  --path src/config.py \
  --start-line 1 \
  --highlight 5,10-14 \
  -o config_preview.png
```

### B. Mulai Baris Tertentu & Posisi Kursor
```bash
python code_to_image.py \
  --text "def calculate_total(items: list[dict]) -> float:
    subtotal = sum(item['price'] * item['qty'] for item in items)
    tax = subtotal * 0.11
    return subtotal + tax
" \
  --name calc.py \
  --path services/billing/calc.py \
  --start-line 40 \
  --highlight 41-42 \
  --cursor 43:12 \
  -o billing.png
```

### C. Jendela Penuh VS Code (Frame Full + Title Bar Mac)
```bash
python code_to_image.py \
  --file main.go \
  --name main.go \
  --lang go \
  --frame full \
  --os mac \
  --project "ecommerce-api" \
  --branch "feature/payment" \
  -o full_mac.png
```

### D. Jendela Penuh VS Code (Frame Full + Title Bar Windows)
```bash
python code_to_image.py \
  --text "<?php
namespace App\Http\Controllers;

class AuthController extends Controller {
    public function login(Request \$request) {
        return response()->json(['token' => 'xyz']);
    }
}
" \
  --name AuthController.php \
  --lang php \
  --frame full \
  --os win \
  --project "laravel-backend" \
  --branch "develop" \
  -o full_win.png
```

### E. Jupyter Notebook (.ipynb)
Mendukung rendering cell kode dan cell markdown secara elegan dengan container terpisah:
```bash
python code_to_image.py \
  --file notebook.ipynb \
  --name analysis.ipynb \
  --frame tab \
  -o jupyter.png
```

### F. Query SQL & Script Bash
```bash
# SQL Query
python code_to_image.py \
  --text "SELECT u.id, u.name, COUNT(o.id) AS total_orders
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
WHERE u.status = 'active'
GROUP BY u.id
ORDER BY total_orders DESC;" \
  --lang sql \
  -o sql_preview.png

# Bash Script
python code_to_image.py \
  --text "#!/bin/bash
set -euo pipefail
echo 'Starting deployment...'
rsync -avz --delete ./dist/ server:/var/www/html/
echo 'Deployment finished successfully!'" \
  --lang bash \
  -o bash_preview.png
```

### G. Pipe Melalui Stdin & Soft Wrap
```bash
git diff | python code_to_image.py --lang diff --name diff.patch --wrap 80 -o diff.png
```

---

## 5. Kustomisasi Font

Pengguna dapat meletakkan font TrueType/OpenType monospace favorit mereka (seperti Cascadia Code, JetBrains Mono, Fira Code, atau Menlo) ke dalam folder `.fonts/`:

```
faf-agent/
├── .fonts/
│   ├── JetBrainsMono-Regular.ttf
│   └── FiraCode-Regular.ttf
└── code_to_image.py
```

`code_to_image.py` secara otomatis memprioritaskan font yang berada di `.fonts/`, lalu memeriksa font sistem Termux (`~/.termux/font.ttf`), font sistem Android (`/system/fonts/DroidSansMono.ttf`), atau font sistem macOS/Linux.

---

## 6. Integrasi Tool Agen AI (`CodeToImageTool`)

Tool ini terdaftar di registri bawaan `faf-agent` dengan nama `code_to_image`. Agen AI dapat memanggil tool ini secara otomatis saat pengguna Telegram meminta gambar kodingan:

```json
{
  "name": "code_to_image",
  "arguments": {
    "text": "console.log('Halo dunia!');",
    "name": "app.js",
    "lang": "javascript",
    "start_line": 1,
    "highlight": "1",
    "frame": "tab"
  }
}
```

Tool akan mengembalikan berkas foto (`media_path` dan `media_type="photo"`) sehingga bot Telegram langsung mengirimkan foto screenshot tersebut ke layar obrolan pengguna.
