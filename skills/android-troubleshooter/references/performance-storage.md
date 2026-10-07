# Troubleshooting: Lemot, Lag, RAM, Storage, Aplikasi Crash

## Penyebab umum lemot (urut dari paling sering)

1. **Storage hampir penuh** (> 90%). Android butuh ruang kosong untuk cache, swap, dan update. Ideal sisa ≥ 15%.
2. **Terlalu banyak aplikasi di latar belakang / autostart.**
3. **RAM kecil** (≤ 3GB) untuk Android modern + aplikasi berat. Tekanan memori tinggi → aplikasi sering dimuat ulang.
4. **Thermal throttling** (HP panas → CPU diturunkan). Lihat [overheating.md](overheating.md).
5. **Aplikasi bermasalah / versi buggy**, terutama setelah update.
6. **OS belum dioptimasi setelah update** atau sudah tidak mendapat patch.
7. **Animasi/launcher berat**, widget live berlebihan, wallpaper animasi.
8. **Storage lama/aus** (eMMC/UFS lambat setelah bertahun-tahun, penuh).
9. **Malware/adware** (iklan pop-up, browser berubah sendiri).

## Data yang dicek (ADB)

```bash
bash skills/android-troubleshooter/scripts/diagnose.sh memory
bash skills/android-troubleshooter/scripts/diagnose.sh storage
bash skills/android-troubleshooter/scripts/diagnose.sh cpu
bash skills/android-troubleshooter/scripts/diagnose.sh crash
```
Perhatikan: persen storage /data, MemAvailable vs MemTotal, swap terpakai, aplikasi pemakai RAM/CPU terbesar, aplikasi terbesar di storage, riwayat crash/ANR terakhir.

## Penanganan: Lemot / RAM
1. Restart HP (bersihkan proses macet). Lakukan rutin seminggu sekali.
2. Tutup aplikasi berat yang tidak digunakan. **Jangan** sering "clear all" tiap saat, itu justru memaksa muat ulang dan boros baterai.
3. Setting → Aplikasi: matikan/hapus bloatware & aplikasi yang tidak dipakai. Batasi autostart (Xiaomi: Keamanan → Izin → Autostart; Oppo/Vivo: Manajer startup; Samsung: Baterai → Batas penggunaan latar belakang).
4. Opsi Pengembang: kurangi skala animasi ke 0.5x atau off (menghemat kesan lag). Jangan aktifkan "Batas proses latar belakang" kecuali paham dampaknya.
5. Hapus widget/wallpaper animasi, ganti launcher berat.
6. Update OS dan aplikasi. Bila lag muncul setelah update aplikasi tertentu, rollback via uninstall update (aplikasi sistem) atau tunggu patch.
7. Safe mode: bila lancar di safe mode, penyebabnya aplikasi pihak ketiga.
8. Backup, factory reset sebagai pilihan terakhir.
9. Perangkat lama RAM ≤ 3GB: pakai versi "Lite" aplikasi (Facebook Lite, dsb.), batasi multitasking.

## Penanganan: Storage penuh
1. Setting → Penyimpanan: lihat kategori terbesar.
2. Google Files / Files by Google: hapus file besar, duplikat, unduhan lama.
3. WhatsApp/Telegram: Kelola penyimpanan → hapus media besar, matikan auto-download. Folder media WhatsApp sering puluhan GB.
4. Foto/video: backup ke Google Photos/PC lalu "Bebaskan ruang". Pindahkan ke microSD bila ada.
5. Bersihkan cache aplikasi besar (Setting → Aplikasi → [app] → Penyimpanan → Hapus cache). **Jangan** "Hapus data" kecuali pengguna paham akan kehilangan login/data.
6. Uninstall game/aplikasi yang jarang dipakai. Cek aplikasi besar dengan script storage.
7. Jangan bersihkan folder `Android/data` atau `Android/obb` secara manual.

## Penanganan: Aplikasi crash / force close / ANR
| Gejala | Tindakan |
|---|---|
| Satu aplikasi crash | Update ke versi terbaru → hapus cache → uninstall & install ulang (peringatkan data lokal) |
| Banyak aplikasi crash | Update "Android System WebView" dan "Google Play Services", cek storage/RAM, periksa tanggal & jam otomatis |
| "Aplikasi tidak merespons" (ANR) | Biasanya CPU/RAM/storage kewalahan. Tutup aplikasi lain, bebaskan storage |
| Crash setelah update OS | Tunggu patch aplikasi, update aplikasi, hapus cache partisi (recovery) bila tersedia |
| Crash saat dibuka (langsung tertutup) | Hapus cache, hapus data (bila aman), cek kompatibilitas versi Android |
| Play Store error/download gagal | Hapus cache & data Play Store dan Play Services, cek tanggal-jam, sisa storage, login ulang akun |

Log crash dari `diagnose.sh crash` menunjukkan nama paket, exception (mis. `OutOfMemoryError`, `NullPointerException`, `SecurityException`), dan waktu kejadian. `OutOfMemoryError` mengarah ke RAM/storage, exception lain biasanya bug aplikasi → update atau lapor developer.

## Eskalasi
Lag parah tetap ada setelah factory reset, storage lambat/error baca-tulis, reboot sendiri berulang, "Storage corrupted". Kemungkinan hardware (memori internal).
