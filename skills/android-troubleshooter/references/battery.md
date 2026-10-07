# Troubleshooting: Baterai Boros & Charging

## Diagnosis awal: boros karena software atau baterai aus?

| Gejala | Kemungkinan |
|---|---|
| Turun cepat saat idle (> 2-3%/jam layar mati) | Wakelock / aplikasi latar belakang / sinyal buruk / sync berlebihan |
| Turun cepat hanya saat dipakai | Layar terang + refresh rate tinggi, game, GPS, 5G |
| Persentase lompat (mis. 30% langsung mati) | Baterai aus / sel rusak. Kalibrasi tidak akan menyembuhkan |
| Health baterai < 80% atau kapasitas turun jauh | Baterai menua, solusi ganti baterai |
| Baterai menggembung, casing renggang, layar terangkat | Berbahaya. Berhenti pakai, ke service center |
| Boros setelah update | Proses optimasi 1-3 hari, atau bug. Tunggu, lalu cek aplikasi boros |
| Boros + panas saat idle | Lihat [overheating.md](overheating.md) |

## Data yang dicek (ADB)

```bash
bash skills/android-troubleshooter/scripts/diagnose.sh battery
```
Perhatikan: level, status (charging/discharging), health (`GOOD`, `OVERHEAT`, `DEAD`, `OVER_VOLTAGE`), suhu, voltase, cycle count (jika tersedia), kapasitas desain vs saat ini (jika tersedia), aplikasi dengan estimasi daya tertinggi, wakelock terbanyak.

Tanpa ADB: Setting → Baterai → penggunaan per aplikasi; Samsung Members/Device Care → Diagnostik → Baterai; Pixel: Setting → Baterai → Kesehatan baterai; Xiaomi/Oppo/Vivo punya info kesehatan di menu baterai atau kode servis.

## Penanganan bertingkat

**Boros karena software**
1. Setting → Baterai → identifikasi aplikasi teratas. Force stop dan batasi latar belakang (opsi "Dibatasi").
2. Matikan fitur yang jarang dipakai: lokasi "selalu", Bluetooth/WiFi scanning, NFC, always-on display, hotspot, sinkronisasi akun berlebihan.
3. Turunkan kecerahan, aktifkan adaptive brightness dan dark mode (efektif di layar OLED), refresh rate adaptif/60Hz.
4. Pakai 4G alih-alih 5G bila sinyal 5G lemah. Aktifkan mode pesawat di area tanpa sinyal.
5. Update aplikasi dan OS. Uninstall aplikasi yang tidak dipakai (terutama media sosial dengan bug boros).
6. Aktifkan Battery Saver / Adaptive Battery.
7. Safe mode untuk memastikan penyebab aplikasi pihak ketiga.
8. Backup, lalu factory reset bila semua gagal dan baterai masih sehat.

**Masalah charging**
- Lambat/tidak mengisi: ganti kabel dan adaptor dulu (penyebab paling umum), colok ke port lain, bersihkan port USB dari debu/serabut dengan tusuk gigi kayu/sikat halus (HP mati).
- Charging putus-nyambung: kabel rusak atau port longgar.
- Pesan "Kelembapan terdeteksi": keringkan HP, jangan charging, tunggu beberapa jam.
- Charging berhenti di 80-85%: bisa fitur proteksi baterai (Adaptive/Optimized Charging). Cek setting baterai.
- Tidak mau charge sama sekali setelah kabel diganti: port rusak atau baterai mati, ke service center.

## Kebiasaan sehat baterai
- Jaga level 20-80% bila memungkinkan, hindari sering 0%.
- Hindari panas saat charging. Pakai charger sesuai spesifikasi.
- Gunakan fitur "Batasi pengisian 80%" jika ada.
- Kalibrasi baterai (kuras habis lalu isi penuh) tidak diperlukan dan tidak memperbaiki baterai aus.

## Eskalasi
Baterai menggembung, bau/cairan, panas ekstrem saat idle, mati mendadak di level tinggi, kesehatan < 70-80% dan mengganggu pemakaian.
