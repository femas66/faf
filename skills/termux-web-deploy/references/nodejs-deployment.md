# Playbook Deploy Website Node.js di Termux Android

Node.js di Termux sangat fleksibel untuk REST API, microservices, maupun fullstack framework (Express, Fastify, Next.js). Karena Node.js menjalankan V8 engine yang membutuhkan memori dinamis, pengelolaan proses dan limit memori adalah kunci utama.

---

## 1. Persiapan & Instalasi

### Selalu Gunakan Node.js LTS
Versi LTS (`nodejs-lts`) jauh lebih stabil di kernel Android dibanding versi *current*:
```bash
pkg update
pkg install nodejs-lts git build-essential python
node -v
npm -v
```

Pasang PM2 secara global untuk process manager:
```bash
npm install -g pm2
```

---

## 2. Implementasi Web Server

### A. Fastify (Rekomendasi Utama: Sangat Cepat & Hemat RAM)
Fastify memiliki overhead jauh lebih kecil dibanding Express, sangat cocok untuk arsitektur mobile:
```bash
mkdir -p ~/projects/my-node-web && cd ~/projects/my-node-web
npm init -y
npm install fastify
```

Buat file `server.js`:
```javascript
const fastify = require('fastify')({ logger: false });

fastify.get('/', async (request, reply) => {
  return {
    status: 'online',
    runtime: `Node.js ${process.version}`,
    platform: 'Android Termux',
    memory_usage: process.memoryUsage(),
    timestamp: new Date().toISOString()
  };
});

const start = async () => {
  try {
    // Wajib listen ke '0.0.0.0' agar bisa diakses lewat Wi-Fi LAN
    await fastify.listen({ port: 3000, host: '0.0.0.0' });
    console.log('Fastify server online di port 3000');
  } catch (err) {
    console.error(err);
    process.exit(1);
  }
};
start();
```

### B. Express.js
```bash
npm install express
```
File `app.js`:
```javascript
const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

app.get('/', (req, res) => {
  res.json({ message: 'Hello dari Express di Android Termux!' });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Express berjalan di http://0.0.0.0:${PORT}`);
});
```

---

## 3. Deploy Next.js di Termux (Mode Standalone)

Next.js bisa dijalankan di Termux dengan teknik **Standalone Build** agar runtime produksi sangat ringan tanpa seluruh folder `node_modules` pengembangan:

1. Di file `next.config.js`:
```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone', // Penting untuk deploy efisien di Termux
};
module.exports = nextConfig;
```

2. Build di project:
```bash
npm run build
```

3. Jalankan server standalone:
```bash
PORT=3000 HOSTNAME=0.0.0.0 node .next/standalone/server.js
```

---

## 4. Konfigurasi PM2 Ecosystem & Memory Limits

Buat file `ecosystem.config.js` di direktori proyek:
```javascript
module.exports = {
  apps: [{
    name: 'node-web-app',
    script: 'server.js',
    instances: 1, // Hindari cluster mode berat di ponsel
    autorestart: true,
    watch: false,
    max_memory_restart: '400M', // Cegah OOM kill oleh Android
    node_args: '--max-old-space-size=384',
    env: {
      NODE_ENV: 'production',
      PORT: 3000
    }
  }]
};
```

Jalankan dengan PM2:
```bash
pm2 start ecosystem.config.js
pm2 save
```
