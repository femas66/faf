# Troubleshooting: Device Panas (Overheating)

## Ambang suhu (suhu baterai, dari `dumpsys battery`)

| Suhu | Arti |
|---|---|
| < 35°C | Normal |
| 35-40°C | Hangat, wajar saat dipakai berat/charging |
| 40-45°C | Panas, cari penyebab bila terjadi saat ringan |
| 45-50°C | Terlalu panas, thermal throttling aktif, kurangi beban |
| > 50°C | Berbahaya. Hentikan pemakaian, cabut charger, matikan perangkat |

Catatan: suhu CPU/skin bisa lebih tinggi daripada baterai. `dumpsys thermalservice` memberi status: NONE, LIGHT, MODERATE, SEVERE, CRITICAL, EMERGENCY, SHUTDOWN. MODERATE ke atas berarti sistem sudah menurunkan performa.

## Pertanyaan pembeda

Kapan panasnya? Itu menentukan arah diagnosis.

| Kondisi saat panas | Penyebab paling mungkin |
|---|---|
| Idle / layar mati | Aplikasi rakus di latar belakang (wakelock, sync loop), malware/adware, bug sistem setelah update, baterai rusak |
| Saat charging | Charger/kabel tidak orisinil, wireless charging, fast charging + dipakai main, casing tebal, ambient panas |
| Saat main game / video call / kamera | Beban wajar. Masalah bila cepat sekali panas: kurangi grafis/FPS, lepas casing, jangan charging sambil main |
| Setelah update OS/aplikasi | Proses indexing/optimasi (wajar 24-48 jam), atau bug versi baru |
| Saat sinyal lemah | Modem bekerja keras mencari sinyal. Pindah lokasi, nonaktifkan data/pakai WiFi |
| Dijemur / di dalam mobil | Faktor lingkungan, bukan kerusakan |
| Panas disertai baterai menggembung / bau | Kerusakan baterai. Berhenti pakai, ke service center segera |

## Cara cek dengan ADB

```bash
bash skills/android-troubleshooter/scripts/diagnose.sh thermal
bash skills/android-troubleshooter/scripts/diagnose.sh cpu
```

Cari: suhu baterai, thermal status, proses CPU tertinggi, aplikasi dengan wakelock lama, sedang charging atau tidak.

## Penanganan bertingkat

1. **Segera:** cabut charger, lepas casing, keluar dari game/kamera, pindah ke tempat teduh. Jangan dinginkan dengan kulkas/freezer/es.
2. **Tutup penyebab:** Setting → Baterai → lihat aplikasi dengan pemakaian tertinggi → Force stop. Matikan sementara: hotspot, Bluetooth, GPS, 5G (pakai 4G), kecerahan maksimal, mode refresh rate 120Hz.
3. **Restart** perangkat untuk membersihkan proses yang macet.
4. **Batasi aplikasi bermasalah:** Setting → Aplikasi → [app] → Baterai → Dibatasi. Cabut izin lokasi "selalu" dan auto-start yang tidak perlu.
5. **Update** aplikasi bermasalah dan OS (bug panas sering diperbaiki di patch).
6. **Cek aplikasi mencurigakan:** matikan iklan pop-up, uninstall aplikasi tak dikenal/APK dari sumber tidak resmi. Jalankan Google Play Protect.
7. **Safe mode:** boot ke safe mode (tahan tombol power → tahan "Matikan" → OK). Jika panas hilang, pelakunya aplikasi pihak ketiga: uninstall satu per satu yang baru dipasang.
8. **Charger:** pakai charger dan kabel orisinil/bersertifikat, hindari charging sambil main game.
9. **Reset pengaturan jaringan / factory reset** (backup dulu) bila setelah semua langkah di atas tetap panas saat idle.
10. **Service center:** panas > 45°C saat idle tanpa aplikasi berat, baterai menggembung, baterai sangat boros, bau terbakar.

## Pencegahan
- Jangan charging sambil game berat atau video call.
- Hindari casing tebal saat gaming/charging.
- Jangan tinggalkan HP di dashboard mobil atau di bawah sinar matahari.
- Jaga storage tidak penuh (< 85%) dan batasi aplikasi latar belakang.
- Ganti baterai jika kesehatan baterai sudah rendah (< 80%).
