# Networking, Background Daemons, & Reverse Proxy di Termux

Dokumen ini adalah panduan arsitektur level produksi untuk menjalankan web service di lingkungan Termux Android tanpa akses root.

---

## 1. Aturan Networking Android & Port Binding

### A. Pembatasan Port Non-Root (>= 1024)
* **Karakteristik Kernel Android**: Proses tanpa akses `root` dilarang melakukan `bind()` ke port privileged (< 1024) seperti port `80` (HTTP) dan `443` (HTTPS).
* **Solusi Standar**:
  * Gunakan port di atas 1024, misalnya:
    * `8080` (Standar Web / Reverse Proxy / PHP)
    * `8000` (Python FastAPI / Django / Flask)
    * `3000` (Node.js Next.js / Express)
    * `8081` atau `9000` (Golang / PHP-FPM)
  * Jika memerlukan akses port 80/443 dan perangkat memiliki akses **Root**, Anda dapat melakukan port redirection menggunakan iptables:
    ```bash
    su -c "iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080"
    su -c "iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 8443"
    ```

### B. Binding Address: `127.0.0.1` vs `0.0.0.0`
| Host Binding | Aksesibilitas | Kapan Digunakan |
|---|---|---|
| `127.0.0.1` (`localhost`) | Hanya dapat diakses oleh browser/aplikasi di dalam HP itu sendiri. | Development privat, backend di belakang Reverse Proxy. |
| `0.0.0.0` (Semua Interface) | Dapat diakses oleh HP sendiri **DAN** seluruh perangkat lain di jaringan Wi-Fi lokal yang sama. | Testing dari laptop/PC, presentasi demo lokal, web server LAN. |

### C. Menemukan Alamat IP LAN Android (Wi-Fi)
Untuk mengakses web dari laptop atau HP lain di satu Wi-Fi:
```bash
# Mengambil IP wlan0 secara otomatis
ip -4 addr show wlan0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}'
```
Contoh hasil: `192.168.1.50`. Website Anda dapat diakses di laptop via: `http://192.168.1.50:8080`.

---

## 2. Menjaga Service Tetap Hidup (Background Persistence & Anti-Doze)

Android memiliki mekanisme agresif penghemat baterai (*Doze Mode*) yang akan mematikan proses Termux saat layar mati atau aplikasi berada di latar belakang.

### A. Wajib: Termux Wake-Lock
Aktifkan CPU wake-lock agar prosesor tidak masuk mode sleep:
```bash
termux-wake-lock
```
*(Untuk mematikannya saat selesai: `termux-wake-unlock`)*

### B. Pengaturan Baterai Android
1. Buka **Settings** Android → **Apps** → **Termux**.
2. Pilih menu **Battery** / **Penggunaan Baterai**.
3. Ubah dari *Optimized* menjadi **Unrestricted** (Tidak Dibatasi / Tanpa Batasan).
4. Matikan fitur pembersih RAM otomatis (seperti *MIUI Battery Saver* atau *Device Care* Samsung) khusus untuk Termux.

---

## 3. Pilihan Process Supervisor (Tanpa systemd)

Termux **tidak menggunakan systemd**. Jangan jalankan `systemctl`. Gunakan salah satu dari 4 metode terbaik berikut:

### Metode 1: PM2 (Sangat Direkomendasikan untuk Semua Bahasa)
PM2 adalah process manager terbaik di Termux karena ringan, andal, memiliki auto-restart, dan log rotation.
```bash
# Pasang PM2 global
pkg install nodejs-lts
npm install -g pm2

# Menjalankan aplikasi (Node, Python, Go, PHP)
pm2 start server.js --name "node-api"
pm2 start "python main.py" --name "fastapi-app"
pm2 start ./go-server --name "golang-web"
pm2 start "php -S 0.0.0.0:8000 -t public" --name "php-app"

# Perintah esensial PM2
pm2 list                  # Daftar proses aktif
pm2 logs <nama|id>        # Pantau log realtime
pm2 restart <nama|id>     # Restart aplikasi
pm2 stop <nama|id>        # Hentikan aplikasi
pm2 delete <nama|id>      # Hapus dari manajemen
```

### Metode 2: Runit (`termux-services`)
Runit adalah init system resmi bawaan Termux:
```bash
pkg install termux-services

# Contoh mengaktifkan service nginx / php-fpm
sv-enable nginx
sv up nginx
sv status nginx
sv down nginx
```

### Metode 3: Tmux (Sesi Terminal Terisolasi)
Sangat berguna untuk proses development aktif yang ingin tetap berjalan di latar belakang:
```bash
pkg install tmux

# Buat session baru di background
tmux new-session -d -s webapp "python -m http.server 8080"

# Lampirkan kembali terminal jika ingin melihat langsung
tmux attach -t webapp

# Keluar dari tmux tanpa mematikan proses: Tekan Ctrl+B lalu D
```

### Metode 4: Standar Nohup & PID Tracking
Metode bawaan UNIX sederhana tanpa dependensi tambahan:
```bash
nohup ./my-app > app.log 2>&1 & echo $! > app.pid
# Mematikan service:
kill $(cat app.pid) && rm app.pid
```

---

## 4. Reverse Proxy & Web Server: Caddy vs Nginx

Menjalankan satu Reverse Proxy di port `8080` yang meneruskan traffic ke aplikasi upstream adalah praktik terbaik (Best Practice).

### Opsi Terbaik: Caddy (Sederhana & Modern)
Caddy ditulis dalam Go, berukuran satu binary, dan konfigurasi sangat ringkas:
```bash
pkg install caddy
```
Buat file `Caddyfile`:
```caddy
:8080 {
    # Reverse proxy ke upstream backend (misal FastAPI di port 8000)
    reverse_proxy localhost:8000

    # Kompresi otomatis
    encode gzip zstd

    # Logging akses
    log {
        output file caddy.log
    }
}
```
Menjalankan Caddy:
```bash
caddy run --config Caddyfile
# Atau jalankan di background:
caddy start --config Caddyfile
caddy stop
```

### Opsi Klasik: Nginx
Cocok jika mengintegrasikan PHP-FPM:
```bash
pkg install nginx
```
Konfigurasi file `$PREFIX/etc/nginx/nginx.conf`:
```nginx
events { worker_connections 1024; }
http {
    include mime.types;
    default_type application/octet-stream;
    sendfile on;

    server {
        listen 8080;
        server_name localhost;

        location / {
            proxy_pass http://127.0.0.1:3000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```
Kontrol Nginx:
```bash
nginx           # Menjalankan
nginx -s reload # Reload konfigurasi
nginx -s stop   # Menghentikan
```
