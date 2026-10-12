# Playbook Deploy Website Python di Termux Android

Python sangat populer untuk backend API modern (FastAPI, Flask, Django). Di Termux, deployment Python membutuhkan isolasi virtual environment dan pemilihan ASGI/WSGI server yang efisien terhadap pemakaian memori perangkat.

---

## 1. Persiapan Lingkungan & Dependensi Sistem

Banyak paket Python (seperti Pydantic, Cryptography, Pillow) membutuhkan kompilasi C/C++. Pasang toolchain dasar:
```bash
pkg update
pkg install python python-pip clang libffi libcrypt make
```

### Isolasi Wajib: Virtual Environment
Hindari menginstal paket ke Python sistem Termux agar tidak terjadi konflik library:
```bash
mkdir -p ~/projects/my-py-web && cd ~/projects/my-py-web
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
```

---

## 2. Pilihan Framework & Server Produksi

### A. FastAPI (Modern & Asinkron - Sangat Direkomendasikan)
```bash
pip install fastapi "uvicorn[standard]"
```

Buat file `main.py`:
```python
from fastapi import FastAPI
import uvicorn
import datetime

app = FastAPI(title="Termux FastAPI Backend")

@app.get("/")
def read_root():
    return {
        "status": "online",
        "engine": "FastAPI on Android Termux",
        "timestamp": datetime.datetime.now().isoformat()
    }

if __name__ == "__main__":
    # Host 0.0.0.0 mengizinkan akses dari browser HP dan perangkat LAN Wi-Fi
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, workers=2)
```

Perintah menjalankan di terminal:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

### B. Flask (Microframework Klasik)
```bash
pip install flask gunicorn
```

Buat file `app.py`:
```python
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"message": "Hello dari Flask di Android!"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
```

Jalankan dengan Gunicorn untuk performa stabil:
```bash
gunicorn -w 2 -b 0.0.0.0:8000 "app:app"
```

### C. Django
```bash
pip install django gunicorn
django-admin startproject myproject .
python manage.py migrate
gunicorn myproject.wsgi:application --bind 0.0.0.0:8000 --workers 2
```

---

## 3. Aturan Emas Performa Python di Perangkat Android

1. **Batasi Worker (Maksimal 2 Worker)**:
   * Jangan gunakan formula standar server `workers = 2 * CPU + 1` (yang bisa menghasilkan 9 worker pada HP 8-core).
   * Menjalankan terlalu banyak worker Python akan memicu *Thermal Throttling* (HP panas) dan RAM cepat terkuras. Cukup gunakan **1 atau 2 workers**.
2. **Optimasi Database SQLite**:
   * Jika menggunakan SQLite lokal, aktifkan mode WAL (*Write-Ahead Logging*) agar pembacaan dan penulisan tidak saling mengunci:
     ```sql
     PRAGMA journal_mode=WAL;
     PRAGMA synchronous=NORMAL;
     ```
3. **Hindari Library C Berat Jika Tidak Diperlukan**:
   * Jika paket seperti `scipy` atau `numpy` bermasalah saat kompilasi di Termux, gunakan repo komunitas `tur-repo` (`pkg install tur-repo`) yang menyediakan binary pra-kompilasi.

---

## 4. Backgrounding & Supervisi dengan PM2

Pastikan path binary Python mengarah ke `.venv`:
```bash
# Jalankan via PM2 dengan virtual environment aktif
pm2 start ".venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2" --name "fastapi-service"
pm2 save
```

Pantau konsumsi RAM dan request log:
```bash
pm2 monit
pm2 logs fastapi-service
```
