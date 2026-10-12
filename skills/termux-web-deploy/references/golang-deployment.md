# Playbook Deploy Website Golang di Termux Android

Golang adalah pilihan terbaik untuk hosting di Android/Termux karena menghasilkan **single static binary**, konsumsi RAM sangat rendah (< 30 MB), dan performa konkurensi goroutine yang luar biasa pada CPU ARM64.

---

## 1. Persiapan Lingkungan

### A. Instalasi Kompiler Go di Termux
```bash
pkg update && pkg install golang git
go version
```

### B. Konfigurasi `GOPATH` & Environment
Pastikan direktori project berada di `$HOME` (bukan `/sdcard`):
```bash
mkdir -p ~/projects/my-go-web
cd ~/projects/my-go-web
go mod init my-go-web
```

---

## 2. Struktur Kode Web Server Production-Ready

Contoh web server berkinerja tinggi menggunakan framework standar `net/http` dengan dukungan graceful shutdown dan logging:

```go
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"status":"ok","message":"Halo dari Golang di Android Termux!","time":"%s"}`, time.Now().Format(time.RFC3339))
	})

	server := &http.Server{
		Addr:         "0.0.0.0:" + port, // Bind ke seluruh interface untuk akses LAN
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Goroutine untuk menjalankan server
	go func() {
		log.Printf("Server Golang berjalan di http://0.0.0.0:%s", port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Error listen: %v", err)
		}
	}()

	// Menunggu sinyal shutdown (SIGINT / SIGTERM)
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("Mematikan server Golang dengan anggun...")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := server.Shutdown(ctx); err != nil {
		log.Fatalf("Server dipaksa berhenti: %v", err)
	}
	log.Println("Server Golang telah berhenti dengan aman.")
}
```

---

## 3. Kompilasi & Optimasi Binary

### A. Kompilasi Langsung di Termux
Gunakan flag linker `-ldflags="-s -w"` untuk membuang simbol debug dan DWARF table sehingga ukuran file berkurang drastis:
```bash
# Nonaktifkan CGO agar binary murni static tanpa ketergantungan Bionic libc
CGO_ENABLED=0 go build -ldflags="-s -w" -o app-server main.go
```

### B. Cross-Compile dari PC / Laptop ke Android Termux
Jika Anda coding di PC (Linux, macOS, atau Windows), Anda bisa langsung mengompilasi binary ARM64 dan mengirimkannya ke Termux via `scp` atau `curl`:
```bash
# Di terminal laptop:
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -ldflags="-s -w" -o app-server-arm64 main.go
# Kirim ke Termux:
scp -P 8022 app-server-arm64 termux_user@192.168.1.50:~/projects/my-go-web/
```

---

## 4. Menjalankan di Background

### Opsi A: Dengan PM2 (Direkomendasikan)
```bash
pm2 start ./app-server --name "go-web"
pm2 save
```

### Opsi B: Dengan Nohup
```bash
nohup ./app-server > server.log 2>&1 & echo $! > server.pid
```

---

## 5. Tips & Rekomendasi Framework Populer
* **Fiber (Express-like, ultra-fast)**: Menggunakan Fasthttp. Sangat hemat alokasi memori di Termux.
* **Gin**: Sangat stabil dan dokumentasi lengkap.
* **Chi**: Router ringan yang 100% kompatibel dengan interface standar `net/http`.
* **Database**: Gunakan `modernc.org/sqlite` (pure Go SQLite tanpa CGO) jika membutuhkan database lokal di Termux agar tidak perlu memasang compiler C/Clang.
