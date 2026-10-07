# Troubleshooting: Boot, Layar, Touch, Update & Sistem

## Tidak bisa menyala / mati total
1. Charge ≥ 30 menit dengan charger dan kabel orisinil (baterai bisa benar-benar kosong, indikator baru muncul setelah beberapa menit).
2. Force restart: tahan Power ~10-15 detik (sebagian: Power + Volume Bawah).
3. Cek port charger (kotor/longgar), coba charger lain.
4. Pernah jatuh/kena air? Jangan dinyalakan atau di-charge, keringkan (jangan pakai beras sebagai jaminan), bawa ke service center.
5. Jika ada getar/lampu LED tetapi layar hitam: kemungkinan masalah layar/backlight → service center.

## Bootloop / stuck di logo
| Kondisi | Tindakan |
|---|---|
| Setelah update OS | Masuk recovery, **Wipe cache partition** (tidak menghapus data) |
| Setelah pasang aplikasi/modifikasi | Boot ke **Safe mode**, uninstall aplikasi terakhir |
| Tetap loop | Backup tidak mungkin → **Factory reset** via recovery (data hilang, peringatkan keras) |
| Setelah root/custom ROM | Flash ulang firmware resmi |
| Tetap loop setelah reset | Kerusakan storage/mainboard → service center |

Masuk recovery (umum): matikan HP → tahan Power + Volume Atas (Samsung lama: + Home; Pixel: Power + Volume Bawah → pilih Recovery). Kombinasi bervariasi per merek, cari spesifik model.

## Layar & Touch
| Gejala | Penyebab / tindakan |
|---|---|
| Touch tidak responsif sebagian | Pelindung layar kotor/retak, tangan basah, restart, safe mode, update, kalibrasi (kode servis), kerusakan digitizer |
| Ghost touch (menyentuh sendiri) | Pelindung layar murahan, charger tidak orisinil (noise), layar rusak → cabut charger & lepas pelindung, jika tetap ada → ganti layar |
| Layar berkedip | Mode PWM/refresh rate, kecerahan rendah di OLED, aplikasi tertentu → matikan adaptive brightness/refresh rate, safe mode |
| Garis/bercak/warna hijau-pink | Kerusakan panel (hardware) → service center, backup data segera |
| Burn-in | Ganti wallpaper/pola, aktifkan auto-rotate/timeout, tidak bisa dihapus |
| Layar redup sendiri | Adaptive brightness, mode hemat baterai, suhu panas (thermal) |
| Layar hitam tapi HP hidup | Tekan tombol power, coba force restart, sambungkan ke monitor (USB-C DP) untuk cek apakah OS hidup |

## Update OS gagal / bermasalah
- Gagal unduh/pasang: pastikan storage ≥ 5GB, baterai > 50%, koneksi stabil, hapus cache Google Play Services, restart.
- Setelah update boros/lemot: tunggu 1-3 hari, wipe cache partition, jika perlu factory reset.
- Update tidak tersedia: perangkat sudah EOL (end of life), pertimbangkan alternatif aman (jangan flash sembarangan).

## Suara, kamera, sensor
- Speaker/mic tidak bunyi: cek volume/mode senyap, bersihkan lubang speaker, Bluetooth tersambung tanpa disadari, restart/safe mode. Kecil kemungkinan hardware jika ada perubahan mendadak setelah update.
- Kamera error "Gagal terhubung ke kamera": hapus cache & data aplikasi kamera, restart, safe mode (aplikasi lain menahan kamera), hardware bila tetap.
- Sensor (rotasi/proximity/sidik jari): kalibrasi, lepas pelindung layar, daftarkan ulang sidik jari.

## Keamanan & anomali
- Iklan pop-up, aplikasi tidak dikenal, kuota habis sendiri, panas saat idle → curigai adware/malware: Play Protect, hapus aplikasi tidak dikenal, cek Admin perangkat & Aksesibilitas, safe mode, reset bila perlu. Ubah password akun penting.
- Perangkat lupa pola/PIN: gunakan Find My Device / akun Google / layanan merek. Reset akan menghapus data.

## Eskalasi (service center)
Kerusakan fisik, kena air, panel rusak, bootloop setelah reset, reboot sendiri berulang, baterai menggembung, tidak ada sinyal/IMEI hilang.
