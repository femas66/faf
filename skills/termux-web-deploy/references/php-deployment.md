# Playbook Deploy Website PHP di Termux Android

PHP di Termux memiliki ekosistem yang sangat matang. Anda dapat menjalankan aplikasi PHP Native, CodeIgniter, Laravel, hingga WordPress baik menggunakan built-in CLI server maupun arsitektur PHP-FPM + Caddy/Nginx.

---

## 1. Persiapan & Instalasi Paket PHP

```bash
pkg update
pkg install php php-fpm composer php-apache php-sqlite php-curl php-pgsql
php -v
composer --version
```

Pastikan direktori proyek berada di `$HOME/projects/...`:
```bash
mkdir -p ~/projects/my-php-web/public
cd ~/projects/my-php-web
```

---

## 2. Metode Deployment

### Metode A: PHP Built-in Server (Cepat & Praktis)
Cocok untuk pengembangan lokal, dashboard pribadi, atau testing cepat:

1. Buat file `public/index.php`:
```php
<?php
header('Content-Type: application/json');
echo json_encode([
    'status' => 'success',
    'runtime' => 'PHP ' . PHP_VERSION,
    'platform' => 'Android Termux',
    'time' => date('Y-m-d H:i:s')
]);
```

2. Jalankan server dengan bind ke `0.0.0.0`:
```bash
php -S 0.0.0.0:8080 -t public
```

---

### Metode B: Arsitektur Produksi (PHP-FPM + Caddy Web Server)
Metode ini adalah standar industri terbaik untuk performa tinggi, konkurensi stabil, dan penanganan file statis (CSS/JS/Gambar) tanpa membebani thread PHP:

1. **Jalankan PHP-FPM**:
PHP-FPM di Termux secara default mendengarkan di socket atau port `127.0.0.1:9000`:
```bash
php-fpm
```

2. **Pasang Caddy & Buat Konfigurasi**:
```bash
pkg install caddy
```
Buat file `Caddyfile` di root project:
```caddy
:8080 {
    # Path absolut direktori publik website Anda di Termux
    root * /data/data/com.termux/files/home/projects/my-php-web/public

    # Forward request PHP ke PHP-FPM daemon
    php_fastcgi 127.0.0.1:9000

    # Sajikan file statis langsung
    file_server

    encode gzip zstd
}
```

3. **Jalankan Caddy**:
```bash
caddy start --config Caddyfile
```

---

## 3. Deployment Framework: Laravel di Termux

Laravel dapat berjalan mulus di Termux dengan penyesuaian berikut:

1. **Install dependensi & setup environment**:
```bash
cd ~/projects/laravel-app
composer install --no-dev --optimize-autoloader
cp .env.example .env
php artisan key:generate
```

2. **Gunakan SQLite untuk Database Ringan**:
Edit file `.env`:
```env
DB_CONNECTION=sqlite
# Kosongkan DB_HOST, DB_PORT, DB_USERNAME, DB_PASSWORD
```
Buat database SQLite kosong:
```bash
touch database/database.sqlite
php artisan migrate --force
```

3. **Optimasi Cache Laravel**:
```bash
php artisan config:cache
php artisan route:cache
php artisan view:cache
```

4. **Jalankan Laravel**:
* Untuk dev:
  ```bash
  php artisan serve --host=0.0.0.0 --port=8000
  ```
* Untuk background dengan PM2:
  ```bash
  pm2 start "php artisan serve --host=0.0.0.0 --port=8000" --name "laravel-app"
  ```

---

## 4. Optimasi Ekstra: OPcache di Termux

Buka file konfigurasi PHP `$PREFIX/lib/php.ini` (atau buat jika belum ada):
```ini
[opcache]
zend_extension=opcache.so
opcache.enable=1
opcache.enable_cli=1
opcache.memory_consumption=64
opcache.interned_strings_buffer=8
opcache.max_accelerated_files=4000
opcache.revalidate_freq=60
```
Mengaktifkan OPcache memangkas waktu load script PHP hingga 70% di prosesor mobile!
