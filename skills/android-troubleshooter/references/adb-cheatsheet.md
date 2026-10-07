# Cheatsheet ADB untuk Diagnosis

## Perintah read-only (aman dijalankan tanpa izin khusus)

| Tujuan | Perintah |
|---|---|
| Daftar device | `adb devices -l` |
| Model, versi Android | `adb shell getprop ro.product.model`, `ro.build.version.release`, `ro.build.version.sdk`, `ro.product.manufacturer` |
| Baterai | `adb shell dumpsys battery` |
| Statistik baterai & wakelock | `adb shell dumpsys batterystats --charged` (besar, filter dengan grep) |
| Suhu / thermal | `adb shell dumpsys thermalservice`, `dumpsys hardware_properties` |
| CPU per proses | `adb shell top -b -n 1 -o %CPU` (atau `top -n 1`) |
| Memori sistem | `adb shell cat /proc/meminfo`, `adb shell dumpsys meminfo` |
| Memori per aplikasi | `adb shell dumpsys meminfo <package>` |
| Storage | `adb shell df -h /data`, `adb shell dumpsys diskstats` |
| Daftar aplikasi pihak ketiga | `adb shell pm list packages -3` |
| Ukuran aplikasi | `adb shell dumpsys diskstats` (bagian App Sizes) |
| Aplikasi aktif/proses | `adb shell dumpsys activity processes`, `ps -A` |
| Crash/ANR | `adb shell dumpsys dropbox --print data_app_crash`, `adb logcat -b crash -d` |
| Log umum | `adb logcat -d -t 500` |
| WiFi | `adb shell dumpsys wifi`, `dumpsys connectivity` |
| Radio/seluler | `adb shell dumpsys telephony.registry` |
| Pengaturan | `adb shell settings get global airplane_mode_on` |
| Uptime | `adb shell uptime` |
| Laporan lengkap | `adb bugreport file.zip` (besar, untuk kasus kompleks) |

## Perintah yang mengubah perangkat (BUTUH IZIN EKSPLISIT pengguna)

| Perintah | Dampak |
|---|---|
| `adb shell am force-stop <pkg>` | Menutup aplikasi (aman, tidak menghapus data) |
| `adb shell pm clear <pkg>` | **Menghapus semua data aplikasi** |
| `adb uninstall <pkg>` | Menghapus aplikasi |
| `adb shell pm uninstall -k --user 0 <pkg>` | Menonaktifkan bloatware (dapat dikembalikan) |
| `adb shell cmd package compile -m speed-profile -a` | Optimasi ulang aplikasi (memakan waktu dan baterai sementara) |
| `adb shell settings put ...` | Mengubah setelan |
| `adb reboot [recovery\|bootloader]` | Restart |

## Peta gejala → data → kemungkinan penyebab

| Gejala | Data kunci | Penyebab khas |
|---|---|---|
| Panas saat idle | thermal + top + batterystats wakelock | Aplikasi/wakelock, malware, baterai rusak |
| Boros baterai | batterystats, dumpsys battery | Aplikasi rakus, sinyal lemah, baterai aus |
| Lemot | meminfo, df, top | Storage penuh, RAM tertekan, thermal throttle |
| Aplikasi menutup sendiri | dropbox crash, logcat | OOM, bug aplikasi, izin, WebView lama |
| Internet lambat | dumpsys wifi (RSSI), ping | Sinyal lemah, DNS, VPN |
| Reboot sendiri | `dumpsys dropbox` (SYSTEM_RESTART, kernel panic), uptime pendek | Panas, baterai, hardware, driver |

## Cara baca tampilan penting

- `dumpsys battery`: `temperature` dalam persepuluh °C (`455` = 45.5°C). `voltage` dalam mV. `health: 2` = GOOD, `3` = OVERHEAT, `4` = DEAD, `5` = OVER_VOLTAGE, `6` = UNSPECIFIED_FAILURE, `7` = COLD.
- `/proc/meminfo`: pakai `MemAvailable` (bukan `MemFree`). Jika MemAvailable < 10% MemTotal, perangkat tertekan memori. `SwapTotal - SwapFree` besar → zRAM padat.
- `top`: kolom `%CPU` bisa melebihi 100% pada multi-core. Proses sistem (`system_server`, `surfaceflinger`, `kswapd`) tinggi terus-menerus mengindikasikan tekanan memori/UI.
- `thermalservice` Current temperatures: `mType=` 0 CPU, 1 GPU, 2 BATTERY, 3 SKIN.

## Catatan kompatibilitas
- Output berbeda antar versi Android dan merek. Bila satu perintah gagal, lanjutkan dengan yang lain, jangan berhenti.
- Android 11+ membatasi akses sebagian dumpsys tanpa shell. Beberapa merek (Xiaomi/Oppo) memblokir data tertentu.
- Tidak ada root yang diperlukan. Jangan meminta pengguna melakukan root.
