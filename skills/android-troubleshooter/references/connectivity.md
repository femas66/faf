# Troubleshooting: Konektivitas (WiFi, Data Seluler, Bluetooth, GPS)

## Langkah pertama: isolasi lokasi masalah
Selalu tentukan dulu apakah masalah di **HP** atau di **jaringan**:
- Perangkat lain di WiFi/provider yang sama bermasalah juga? → router/ISP/provider, bukan HP.
- Hanya HP ini? → lanjut ke langkah di bawah.
- Hanya satu aplikasi tidak bisa online? → izin data latar belakang, Data Saver, VPN/DNS, atau server aplikasi down.

## WiFi
| Gejala | Penyebab / tindakan |
|---|---|
| Tidak bisa terhubung ("autentikasi gagal") | Password salah, lupakan jaringan lalu sambungkan ulang; router MAC filtering |
| Terhubung tapi tanpa internet | Router/ISP bermasalah, DNS salah. Coba DNS Pribadi `dns.google` atau `one.one.one.one`, restart router; captive portal belum login |
| Sering putus | Jarak/sinyal lemah, band 5GHz jangkauan pendek, Penghemat daya WiFi, "Beralih ke data seluler otomatis" |
| Lambat | Router padat, kanal bentrok, banyak perangkat, VPN aktif, proses unduh latar belakang |
| Tidak mau menyala | Reset setelan jaringan; bug setelah update; hardware bila tetap gagal |

Tindakan: toggle WiFi → lupakan & sambung ulang → restart HP & router → matikan VPN/proxy → Setting → Sistem → Reset → **Reset WiFi, seluler & Bluetooth** (peringatkan password WiFi tersimpan hilang) → update OS.

## Data seluler / sinyal
| Gejala | Tindakan |
|---|---|
| "Tidak ada layanan" / tanpa sinyal | Mode pesawat on/off, keluarkan & pasang kartu SIM, cek pulsa/masa aktif, coba SIM di HP lain, pilih operator manual |
| Sinyal ada tapi data tidak jalan | Cek APN (Setting → Jaringan seluler → APN → Reset ke default), kuota habis/FUP, "Data roaming", Data Saver |
| Sinyal naik-turun | Lokasi buruk, 5G tidak stabil → paksa LTE/4G, lepas casing logam |
| Hanya di satu SIM (dual SIM) | Cek SIM default untuk data, volte/VoWiFi |
| Panggilan putus | Aktifkan VoLTE (atau matikan bila bermasalah), update OS |
| IMEI hilang / "IMEI tidak valid" | Kerusakan software/hardware modem, ke service center |

## Bluetooth
- Tidak terhubung: hapus pairing di kedua perangkat, pair ulang; matikan-nyalakan Bluetooth; jauhkan dari interferensi; cek baterai perangkat; Reset setelan jaringan.
- Audio putus-putus: jarak, WiFi 2.4GHz bentrok, codec (Opsi pengembang), update firmware headset.
- Tidak bisa dideteksi: perangkat lain mode pairing? Izin lokasi/Perangkat di sekitar untuk aplikasi.

## GPS / Lokasi
- Lokasi tidak akurat: aktifkan Akurasi Lokasi Google dan WiFi/Bluetooth scanning, kalibrasi kompas (gerakan angka 8), keluar ruangan, lepas casing logam.
- Lama mendapat sinyal: buka aplikasi peta di area terbuka 1-2 menit, update Google Maps & Play Services.
- Aplikasi tidak bisa membaca lokasi: cek izin (Hanya saat digunakan / Selalu).

## Cek dengan ADB
```bash
bash skills/android-troubleshooter/scripts/diagnose.sh network
```
Menampilkan status WiFi (SSID, RSSI, link speed), IP, DNS, status mobile data, ping ke 8.8.8.8 dan DNS lookup, mode pesawat, status VPN.
Panduan RSSI WiFi: > -60 dBm bagus, -60 s/d -70 cukup, < -75 lemah.

## Eskalasi
Tidak ada sinyal di semua SIM/lokasi, WiFi tidak bisa menyala sama sekali setelah reset, IMEI hilang, setelah terkena air.
