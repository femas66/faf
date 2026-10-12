#!/usr/bin/env bash
# ==============================================================================
# Termux Web Control CLI (termux-web-ctl.sh)
# DevOps & Local Web Deployment Helper for Termux on Android
# ==============================================================================

set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }

# ------------------------------------------------------------------------------
# 1. Environment & Architecture Detection
# ------------------------------------------------------------------------------
cmd_status() {
    echo -e "${BLUE}======================================================${NC}"
    echo -e "${GREEN}      Termux Web Deployment Environment Status         ${NC}"
    echo -e "${BLUE}======================================================${NC}"

    echo -e "\n${YELLOW}--- Perangkat & Sistem ---${NC}"
    echo "OS: $(uname -s) $(uname -m)"
    echo "Shell: $SHELL"
    echo "Prefix: ${PREFIX:-/data/data/com.termux/files/usr}"
    echo "Home: ${HOME:-/data/data/com.termux/files/home}"

    # Cek lokasi direktori kerja (peringatan jika di /sdcard)
    CURRENT_DIR="$(pwd)"
    if [[ "$CURRENT_DIR" == *"/sdcard"* ]] || [[ "$CURRENT_DIR" == *"/storage/emulated"* ]]; then
        log_warn "Direktori saat ini berada di shared storage Android ($CURRENT_DIR)!"
        log_warn "PERINGATAN: Jangan run web server / node_modules di /sdcard karena pembatasan permission (noexec) & symlink!"
    else
        log_ok "Direktori kerja aman di penyimpanan internal Termux."
    fi

    echo -e "\n${YELLOW}--- Runtime & Tools Terpasang ---${NC}"
    check_tool() {
        local name="$1"
        local cmd="$2"
        local ver_arg="${3:---version}"
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" $ver_arg 2>&1 | head -n 1 || true)
            echo -e "  [${GREEN}✓${NC}] $name: $ver"
        else
            echo -e "  [${RED}✗${NC}] $name: Tidak terpasang"
        fi
    }

    check_tool "Golang" "go" "version"
    check_tool "Python" "python" "--version"
    check_tool "PHP" "php" "-v"
    check_tool "Node.js" "node" "-v"
    check_tool "PM2" "pm2" "-v"
    check_tool "Caddy" "caddy" "version"
    check_tool "Nginx" "nginx" "-v"
    check_tool "cURL" "curl" "--version"
    check_tool "Git" "git" "--version"

    echo -e "\n${YELLOW}--- Status Wake-Lock (Background Persistence) ---${NC}"
    if command -v termux-wake-lock &>/dev/null; then
        log_ok "termux-wake-lock tersedia."
    else
        log_warn "termux-wake-lock tidak ditemukan. Pasang termux-api bila perlu."
    fi

    echo -e "\n${YELLOW}--- Alamat IP Jaringan (LAN / Wi-Fi) ---${NC}"
    cmd_ip

    echo -e "\n${YELLOW}--- Port Aktif Mendengarkan (Listening Ports) ---${NC}"
    cmd_ports
}

# ------------------------------------------------------------------------------
# 2. IP Detection (Localhost & Wi-Fi LAN)
# ------------------------------------------------------------------------------
cmd_ip() {
    local wifi_ip
    wifi_ip=$(ip -4 addr show wlan0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || true)
    
    if [ -z "$wifi_ip" ]; then
        wifi_ip=$(ifconfig wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | sed 's/addr://' || true)
    fi

    if [ -n "$wifi_ip" ]; then
        echo -e "  Localhost : ${GREEN}http://127.0.0.1${NC} (Akses internal di HP ini)"
        echo -e "  Wi-Fi LAN : ${CYAN}http://${wifi_ip}${NC} (Akses dari laptop/HP lain satu Wi-Fi)"
    else
        echo -e "  Localhost : ${GREEN}http://127.0.0.1${NC} (Akses internal di HP ini)"
        echo -e "  Wi-Fi LAN : ${YELLOW}Tidak terhubung ke Wi-Fi (wlan0 offline)${NC}"
    fi
}

# ------------------------------------------------------------------------------
# 3. Port Management & Inspection
# ------------------------------------------------------------------------------
cmd_ports() {
    if command -v ss &>/dev/null; then
        ss -tulpn 2>/dev/null | grep -E 'LISTEN|State' || true
    elif command -v netstat &>/dev/null; then
        netstat -tlpn 2>/dev/null || true
    elif command -v lsof &>/dev/null; then
        lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null || true
    else
        log_warn "Tool inspeksi socket (ss/netstat/lsof) tidak tersedia. Pasang iproute2 / net-tools."
    fi
}

cmd_kill_port() {
    local port="$1"
    if [ -z "$port" ]; then
        log_err "Harap sertakan nomor port. Contoh: $0 kill-port 8080"
        exit 1
    fi

    log_info "Mencari proses pada port $port..."
    local pids=""

    if command -v lsof &>/dev/null; then
        pids=$(lsof -ti ":$port" 2>/dev/null || true)
    fi

    if [ -z "$pids" ] && command -v fuser &>/dev/null; then
        pids=$(fuser "$port/tcp" 2>/dev/null || true)
    fi

    if [ -n "$pids" ]; then
        for pid in $pids; do
            log_info "Mematikan PID $pid (Port $port)..."
            kill -15 "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
        done
        log_ok "Port $port berhasil dibebaskan."
    else
        log_warn "Tidak ditemukan proses aktif yang mendengarkan di port $port."
    fi
}

# ------------------------------------------------------------------------------
# 4. Wake-Lock Management
# ------------------------------------------------------------------------------
cmd_wake_lock() {
    if command -v termux-wake-lock &>/dev/null; then
        termux-wake-lock
        log_ok "Termux Wake-Lock diaktifkan (Mencegah Android mematikan proses saat layar mati)."
    else
        log_err "termux-wake-lock tidak ditemukan! Pasang paket 'termux-api'."
    fi
}

cmd_wake_unlock() {
    if command -v termux-wake-unlock &>/dev/null; then
        termux-wake-unlock
        log_ok "Termux Wake-Lock dinonaktifkan."
    else
        log_err "termux-wake-unlock tidak ditemukan!"
    fi
}

# ------------------------------------------------------------------------------
# 5. Quick Static Web Server
# ------------------------------------------------------------------------------
cmd_serve_static() {
    local dir="${1:-.}"
    local port="${2:-8080}"

    if [ ! -d "$dir" ]; then
        log_err "Direktori '$dir' tidak ditemukan!"
        exit 1
    fi

    log_info "Menjalankan static web server untuk '$dir' di port $port..."
    cmd_ip

    if command -v caddy &>/dev/null; then
        log_ok "Menggunakan Caddy File Server..."
        caddy file-server --root "$dir" --listen "0.0.0.0:$port"
    elif command -v python &>/dev/null; then
        log_ok "Menggunakan Python http.server..."
        python -m http.server "$port" --bind 0.0.0.0 --directory "$dir"
    elif command -v php &>/dev/null; then
        log_ok "Menggunakan PHP built-in server..."
        php -S "0.0.0.0:$port" -t "$dir"
    elif command -v npx &>/dev/null; then
        log_ok "Menggunakan Node.js serve..."
        npx serve -l "$port" "$dir"
    else
        log_err "Tidak ada runtime web server (Caddy / Python / PHP / Node) yang terpasang!"
        exit 1
    fi
}

# ------------------------------------------------------------------------------
# 6. Health Check / Ping
# ------------------------------------------------------------------------------
cmd_health() {
    local url="${1:-http://127.0.0.1:8080}"
    log_info "Menguji respons HTTP ke $url..."

    if command -v curl &>/dev/null; then
        local response
        response=$(curl -sI -m 5 "$url" | head -n 5 || true)
        if [ -n "$response" ]; then
            log_ok "Website online dan merespons!"
            echo -e "${CYAN}$response${NC}"
        else
            log_err "Gagal terhubung ke $url (Connection refused / Timeout)."
        fi
    else
        log_err "curl tidak terpasang."
    fi
}

# ------------------------------------------------------------------------------
# Help & Dispatcher
# ------------------------------------------------------------------------------
cmd_help() {
    echo -e "${GREEN}Termux Web Deployment Control CLI${NC}"
    echo "Penggunaan: $0 <perintah> [argumen]"
    echo ""
    echo "Perintah yang tersedia:"
    echo "  status                  Cek lingkungan Termux, runtime (Go, Py, PHP, Node), IP, dan port"
    echo "  ip                      Tampilkan IP localhost dan IP LAN Wi-Fi Android"
    echo "  ports                   Daftar port yang sedang mendengarkan (listening)"
    echo "  kill-port <PORT>        Hentikan proses yang memblokir port tertentu"
    echo "  wake-lock               Aktifkan CPU wake-lock agar server tidak mati saat layar mati"
    echo "  wake-unlock             Matikan CPU wake-lock"
    echo "  serve-static [DIR] [PORT] Jalankan web server static cepat (Caddy/Python/PHP)"
    echo "  health [URL]            Uji respon HTTP ke server lokal"
    echo "  help                    Tampilkan bantuan ini"
}

case "${1:-status}" in
    status)        cmd_status ;;
    ip)            cmd_ip ;;
    ports)         cmd_ports ;;
    kill-port)     cmd_kill_port "$2" ;;
    wake-lock)     cmd_wake_lock ;;
    wake-unlock)   cmd_wake_unlock ;;
    serve-static)  cmd_serve_static "$2" "$3" ;;
    health)        cmd_health "$2" ;;
    help|--help|-h) cmd_help ;;
    *)
        log_err "Perintah tidak dikenal: $1"
        cmd_help
        exit 1
        ;;
esac
