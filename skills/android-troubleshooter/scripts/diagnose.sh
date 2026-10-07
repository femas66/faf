#!/usr/bin/env bash
# Android diagnostic collector (READ-ONLY). Tidak mengubah apa pun di device.
# Pakai: diagnose.sh [-s SERIAL] [overview|thermal|battery|memory|storage|cpu|network|crash|all]

set -u
SERIAL=""
if [ "${1:-}" = "-s" ]; then SERIAL="${2:-}"; shift 2; fi
TOPIC="${1:-all}"

command -v adb >/dev/null 2>&1 || { echo "ERROR: adb tidak ditemukan. Pasang Android platform-tools."; exit 2; }

ADB=(adb)
[ -n "$SERIAL" ] && ADB=(adb -s "$SERIAL")

DEVS=$(adb devices | awk 'NR>1 && $2=="device"{print $1}')
if [ -z "$DEVS" ]; then
  echo "ERROR: tidak ada device terhubung/terotorisasi."
  echo "Aktifkan USB debugging, colok kabel, lalu setujui prompt 'Allow USB debugging' di HP."
  adb devices -l
  exit 3
fi
if [ -z "$SERIAL" ] && [ "$(echo "$DEVS" | wc -l | tr -d ' ')" -gt 1 ]; then
  echo "ERROR: lebih dari satu device. Gunakan -s SERIAL. Daftar:"; echo "$DEVS"; exit 4
fi

sh() { "${ADB[@]}" shell "$@" 2>/dev/null | tr -d '\r'; }
hdr() { echo; echo "=== $* ==="; }
FINDINGS=()
warn() { FINDINGS+=("$*"); }

num() { echo "${1:-}" | grep -Eo '^-?[0-9]+' | head -1; }

do_overview() {
  hdr "OVERVIEW"
  echo "Merek/Model : $(sh getprop ro.product.manufacturer) $(sh getprop ro.product.model)"
  echo "Android     : $(sh getprop ro.build.version.release) (SDK $(sh getprop ro.build.version.sdk))"
  echo "Patch       : $(sh getprop ro.build.version.security_patch)"
  echo "Build       : $(sh getprop ro.build.display.id)"
  echo "Uptime      : $(sh uptime)"
  local sdk; sdk=$(num "$(sh getprop ro.build.version.sdk)")
  if [ -n "$sdk" ] && [ "$sdk" -lt 29 ]; then warn "Android sangat lama (SDK $sdk): tidak mendapat patch keamanan/performa; wajar lemot/rentan."; fi
}

do_thermal() {
  hdr "THERMAL"
  local bat temp
  bat=$(sh dumpsys battery)
  temp=$(echo "$bat" | awk -F': ' '/temperature/{print $2}' | head -1)
  if [ -n "$temp" ]; then
    local c=$((temp/10))
    echo "Suhu baterai: $((temp/10)).$((temp%10)) C"
    if [ "$c" -ge 50 ]; then warn "KRITIS: suhu baterai >= 50C. Hentikan pemakaian, cabut charger."
    elif [ "$c" -ge 45 ]; then warn "Suhu baterai tinggi (>=45C): thermal throttling kemungkinan aktif."
    elif [ "$c" -ge 40 ]; then warn "Suhu baterai hangat (40-45C): cek apakah sedang charging/beban berat."; fi
  fi
  echo "-- thermalservice (status & suhu)"
  sh dumpsys thermalservice | grep -Ei "Thermal Status|mStatus|mValue|mName|mType|Temperature" | head -25
  local st; st=$(sh dumpsys thermalservice | grep -Eo "Thermal Status: [0-9]+" | head -1 | grep -Eo '[0-9]+$')
  if [ -n "$st" ] && [ "$st" -ge 2 ]; then warn "Thermal status $st (>=2 MODERATE): sistem menurunkan performa karena panas."; fi
  echo "-- charging: $(echo "$bat" | grep -Ei 'AC powered|USB powered|Wireless powered' | tr '\n' ' ')"
}

do_battery() {
  hdr "BATTERY"
  local bat; bat=$(sh dumpsys battery)
  echo "$bat" | grep -Ei "level|status|health|present|voltage|temperature|technology|Charge counter|Max charging|powered"
  local health; health=$(echo "$bat" | awk -F': ' '/health/{print $2}' | head -1)
  case "$health" in
    3) warn "Health baterai: OVERHEAT.";;
    4) warn "Health baterai: DEAD (baterai rusak, ganti).";;
    5) warn "Health baterai: OVER_VOLTAGE (charger tidak cocok/rusak).";;
    6) warn "Health baterai: UNSPECIFIED_FAILURE.";;
  esac
  echo "-- cycle count / kapasitas (jika tersedia)"
  sh cat /sys/class/power_supply/battery/cycle_count | sed 's/^/cycle_count: /'
  sh dumpsys batterystats | grep -Ei "Capacity:|Computed drain|Estimated power use" | head -5
  echo "-- Estimasi pemakaian daya per UID (teratas)"
  sh dumpsys batterystats | sed -n '/Estimated power use/,/^$/p' | head -20
  echo "-- Wakelock aktif"
  sh dumpsys power | grep -Ei "Wake Locks|PARTIAL_WAKE_LOCK" | head -10
}

do_memory() {
  hdr "MEMORY"
  local total avail swt swf
  total=$(sh cat /proc/meminfo | awk '/MemTotal/{print $2}')
  avail=$(sh cat /proc/meminfo | awk '/MemAvailable/{print $2}')
  swt=$(sh cat /proc/meminfo | awk '/SwapTotal/{print $2}')
  swf=$(sh cat /proc/meminfo | awk '/SwapFree/{print $2}')
  if [ -n "$total" ] && [ -n "$avail" ]; then
    local pct=$((avail*100/total))
    echo "RAM total: $((total/1024)) MB, tersedia: $((avail/1024)) MB ($pct%)"
    [ -n "$swt" ] && echo "Swap terpakai: $(((swt-swf)/1024)) / $((swt/1024)) MB"
    if [ "$pct" -lt 10 ]; then warn "RAM tersedia < 10% ($pct%): tekanan memori tinggi."; fi
    if [ "$total" -lt 3500000 ]; then warn "RAM kecil (~$((total/1024)) MB): rentan lag di Android modern."; fi
  fi
  echo "-- Pemakaian RAM per proses (teratas, PSS)"
  sh dumpsys meminfo | sed -n '/Total PSS by process/,/^$/p' | head -15
}

do_storage() {
  hdr "STORAGE"
  sh df -h /data
  local use; use=$(sh df /data | awk 'NR==2{gsub("%","",$5); print $5}')
  if [ -n "$use" ]; then
    if [ "$use" -ge 95 ]; then warn "Storage /data $use% penuh: KRITIS, sebab umum lag/crash/update gagal."
    elif [ "$use" -ge 90 ]; then warn "Storage /data $use% penuh: sangat berpengaruh ke performa."
    elif [ "$use" -ge 85 ]; then warn "Storage /data $use%: mendekati penuh."; fi
  fi
  echo "-- diskstats"
  sh dumpsys diskstats | grep -Ei "Data-Free|App Size|App Data Size|Cache Size|Photos|Videos|Audio|Downloads|System Size" | head -12
  echo "-- Jumlah aplikasi pihak ketiga: $(sh pm list packages -3 | wc -l | tr -d ' ')"
}

do_cpu() {
  hdr "CPU / PROSES"
  sh top -b -n 1 -o %CPU 2>/dev/null | head -20 || true
  if [ -z "$(sh top -b -n 1 -o %CPU 2>/dev/null | head -1)" ]; then sh top -n 1 | head -20; fi
  echo "-- Proses dengan CPU tertinggi"
  local out; out=$(sh top -b -n 1 2>/dev/null | awk 'NR>7 && $9+0>=25 {print "CPU "$9"%  "$NF}' | head -5)
  [ -n "$out" ] && { echo "$out"; warn "Ada proses dengan CPU >= 25% saat diambil sampel: $(echo "$out" | head -1)"; }
}

do_network() {
  hdr "NETWORK"
  echo "Mode pesawat: $(sh settings get global airplane_mode_on)"
  echo "-- WiFi"
  sh dumpsys wifi | grep -Ei "Wi-Fi is|mWifiInfo|SSID:|RSSI|Link speed|Frequency" | head -6
  local rssi; rssi=$(sh dumpsys wifi | grep -Eo "RSSI: -?[0-9]+" | head -1 | grep -Eo -- '-?[0-9]+$')
  if [ -n "$rssi" ] && [ "$rssi" -lt -75 ]; then warn "Sinyal WiFi lemah (RSSI $rssi dBm)."; fi
  echo "-- IP & DNS"
  sh ip -4 addr show 2>/dev/null | grep -E "inet " | head -4
  sh getprop net.dns1
  echo "-- Ping 8.8.8.8"
  local p; p=$(sh ping -c 3 -W 2 8.8.8.8 | tail -3); echo "$p"
  echo "$p" | grep -q " 0 received\|100% packet loss" && warn "Ping 8.8.8.8 gagal: tidak ada internet (periksa WiFi/data/VPN)."
  echo "-- Resolusi DNS"
  sh ping -c 1 -W 2 google.com | head -2
  echo "-- Seluler"
  sh dumpsys telephony.registry | grep -Ei "mServiceState|mDataConnectionState|mSignalStrength" | head -4
}

do_crash() {
  hdr "CRASH / ANR"
  echo "-- Crash terakhir (dropbox)"
  sh dumpsys dropbox --print data_app_crash | grep -E "^Process:|^Package:|Exception|Error" | head -12
  echo "-- ANR terakhir"
  sh dumpsys dropbox --print data_app_anr | grep -E "^Process:|^Subject:|ANR in" | head -8
  echo "-- Restart sistem / kernel (jika ada)"
  sh dumpsys dropbox | grep -Ei "SYSTEM_RESTART|SYSTEM_BOOT|kernel_panic|system_server_crash" | tail -5
  if sh dumpsys dropbox --print data_app_crash | grep -q "OutOfMemoryError"; then warn "Ada OutOfMemoryError di crash aplikasi: RAM/storage tertekan."; fi
}

case "$TOPIC" in
  overview) do_overview;;
  thermal)  do_overview; do_thermal;;
  battery)  do_overview; do_battery;;
  memory)   do_memory;;
  storage)  do_storage;;
  cpu)      do_cpu;;
  network)  do_network;;
  crash)    do_crash;;
  all)      do_overview; do_thermal; do_battery; do_memory; do_storage; do_cpu; do_network; do_crash;;
  *) echo "Topik tidak dikenal: $TOPIC"; echo "Pilihan: overview thermal battery memory storage cpu network crash all"; exit 1;;
esac

hdr "TEMUAN"
if [ ${#FINDINGS[@]} -eq 0 ]; then
  echo "Tidak ada anomali otomatis terdeteksi. Analisis manual dari data di atas."
else
  for f in "${FINDINGS[@]}"; do echo "- $f"; done
fi
