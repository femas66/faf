# Troubleshooting & Jebakan Umum Deployment di Termux Android

Menjalankan web server di Android Termux berbeda dengan server Linux konvensional (seperti Ubuntu VPS) karena arsitektur keamanan Android, kernel Bionic libc, dan manajemen daya baterai. Berikut adalah solusi untuk masalah yang paling sering ditemui.

---

## 1. Jebakan Lokasi Storage: Error `EPERM` / `symlink` di `/sdcard`

### Gejala Masalah:
* Saat `npm install` muncul error: `npm ERR! code EPERM: operation not permitted, symlink ...`
* File binary tidak bisa dieksekusi (`bash: ./server: Permission denied`) meskipun sudah di-`chmod +x`.
* Database SQLite / Git repository korup atau permission error.

### Akar Masalah:
Direktori `/sdcard` atau `/storage/emulated/0` adalah shared storage Android yang di-mount dengan flag `noexec` dan filesystem FUSE/FAT32 tanpa dukungan kepemilikan Unix UID/GID dan symbolic link.

### Solusi Permanen:
**JANGAN PERNAH** menaruh source code, repositori git, virtual environment (`.venv`), atau `node_modules` di dalam `/sdcard`.
Pindahkan seluruh folder project Anda ke direktori internal Termux:
```bash
# Path yang benar:
cd /data/data/com.termux/files/home/projects
# atau gunakan shortcut:
cd ~/projects
```

---

## 2. Error Binding Port: `EACCES: permission denied` / Port Privileged

### Gejala Masalah:
* Mencoba menjalankan web server di port 80 atau 443 menghasilkan error `bind: permission denied` atau crash saat startup.

### Akar Masalah:
Linux kernel Android melarang proses non-root mengikat (*bind*) soket TCP/UDP ke port bernomor di bawah 1024.

### Solusi:
Gunakan port alternatif:
* Port 80 diganti menjadi **8080** atau **8000**
* Port 443 diganti menjadi **8443**
Akses di browser dengan menyertakan port: `http://localhost:8080`.

---

## 3. Server Tiba-tiba Mati Saat Layar HP Mati (Android Doze Kill)

### Gejala Masalah:
Server berjalan normal saat aplikasi Termux dibuka di layar, tetapi begitu layar dikunci atau didiamkan beberapa menit, koneksi dari laptop terputus (*Connection Timed Out*).

### Akar Masalah:
Android mengaktifkan CPU sleep state dan menangguhkan thread proses latar belakang aplikasi (*Doze Mode & App Standby*).

### Solusi Bertingkat:
1. **Jalankan Wake-Lock**:
   ```bash
   termux-wake-lock
   ```
2. **Kecualikan Termux dari Penghemat Baterai**:
   * Buka **Pengaturan Android** → **Aplikasi** → **Termux** → **Baterai**.
   * Ubah menjadi **Tidak Dibatasi (Unrestricted)**.
3. **Kunci Aplikasi Termux di Recent Apps**:
   * Buka Recent Apps di Android, tahan ikon Termux, pilih ikon **Gembok (Lock)** agar tidak terhapus saat membersihkan RAM.

---

## 4. Error `Address already in use` (`EADDRINUSE`)

### Gejala Masalah:
Server gagal start dengan pesan: `listen tcp 0.0.0.0:8080: bind: address already in use`.

### Akar Masalah:
Instance server sebelumnya masih aktif di background atau menjadi zombie process.

### Solusi Cepat:
Gunakan script pembantu bawaan skill ini:
```bash
bash skills/termux-web-deploy/scripts/termux-web-ctl.sh kill-port 8080
```
Atau manual:
```bash
fuser -k 8080/tcp
# Atau dengan lsof:
kill -9 $(lsof -ti :8080)
```

---

## 5. Website Hanya Bisa Dibuka di HP Sendiri, Tidak Bisa Dibuka dari Laptop

### Gejala Masalah:
Bisa dibuka via `http://localhost:8080` di browser HP, tapi saat dibuka di laptop via IP Wi-Fi (`http://192.168.1.50:8080`), muncul pesan `ERR_CONNECTION_REFUSED`.

### Akar Masalah:
Web server Anda melakukan listen hanya ke loopback interface `127.0.0.1` bukan ke seluruh interface `0.0.0.0`.

### Solusi:
Ubah konfigurasi listen host kode Anda:
* **Python**: `uvicorn main:app --host 0.0.0.0`
* **Node.js**: `app.listen(3000, '0.0.0.0')` atau `fastify.listen({ port: 3000, host: '0.0.0.0' })`
* **PHP**: `php -S 0.0.0.0:8080`
* **Golang**: `http.ListenAndServe("0.0.0.0:8080", nil)`

Pastikan juga HP dan Laptop terhubung ke jaringan Wi-Fi yang sama (tanpa fitur *AP Client Isolation* di router).

---

## 6. Proses Tiba-tiba "Killed" (Android Low Memory Killer / LMK)

### Gejala Masalah:
Terminal hanya menampilkan pesan satu kata: `Killed`.

### Akar Masalah:
Pemakaian RAM melebihi alokasi yang diizinkan kernel Android, sehingga proses Termux dipaksa mati oleh Android LMK.

### Langkah Pencegahan:
* **Node.js**: Batasi heap V8 memory:
  ```bash
  node --max-old-space-size=384 server.js
  ```
* **Python**: Batasi worker Uvicorn/Gunicorn menjadi 1 atau maksimal 2 worker:
  ```bash
  uvicorn main:app --workers 1
  ```
* **Build Step**: Hindari menjalankan `npm run build` yang sangat berat langsung di HP jika RAM < 4 GB. Lakukan build di laptop, lalu salin folder dist/build ke Termux.
