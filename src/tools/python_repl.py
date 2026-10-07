from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import sys
import tempfile
import time
from typing import Any

from src.config import get_settings
from src.core.permissions import permission_manager
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.python_repl")

MAX_OUTPUT_CHARS = 4500
DEFAULT_TIMEOUT_SEC = 15


def _clean_traceback(tb_str: str) -> str:
    """Bersihkan frame traceback internal dari faf-agent agar hanya menampilkan error kode pengguna."""
    lines = tb_str.splitlines()
    filtered: list[str] = []
    skip = False
    for line in lines:
        if "python_repl.py" in line or "repl_worker.py" in line:
            skip = True
            continue
        if skip and line.strip().startswith("exec("):
            skip = False
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def _get_clean_env() -> dict[str, str]:
    """Bangun environment variabel yang bersih tanpa token rahasia atau kredensial."""
    allowed_keys = {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONIOENCODING",
        "PYTHONUNBUFFERED",
        "TMPDIR",
        "TEMP",
        "TMP",
        "VIRTUAL_ENV",
        "TERM",
    }
    clean_env = {k: os.environ[k] for k in allowed_keys if k in os.environ}

    # Pastikan direktori binary python aktif masuk ke PATH
    py_bin_dir = os.path.dirname(sys.executable)
    existing_path = clean_env.get("PATH", "/usr/bin:/bin:/usr/local/bin")
    if py_bin_dir not in existing_path.split(os.pathsep):
        clean_env["PATH"] = f"{py_bin_dir}{os.pathsep}{existing_path}"
    else:
        clean_env["PATH"] = existing_path

    clean_env["PYTHONUNBUFFERED"] = "1"
    clean_env["PYTHONIOENCODING"] = "utf-8"
    clean_env["HOME"] = tempfile.gettempdir()
    return clean_env


class ReplSession:
    """Mengelola proses worker Python terisolasi untuk satu sesi chat."""

    def __init__(self, chat_id: int) -> None:
        self.chat_id = chat_id
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()

    async def ensure_started(self) -> asyncio.subprocess.Process:
        """Pastikan proses worker aktif dan siap menerima perintah."""
        if self.process is not None and self.process.returncode is None:
            return self.process

        worker_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "repl_worker.py"))
        clean_env = _get_clean_env()

        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            worker_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
            cwd=tempfile.gettempdir(),
        )
        return self.process

    async def send_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Kirim perintah JSON ke worker via length-prefixed framing."""
        proc = await self.ensure_started()
        if not proc.stdin or not proc.stdout:
            raise RuntimeError("Subproses REPL tidak memiliki stream stdin/stdout aktif.")

        data = json.dumps(payload).encode("utf-8")
        header = struct.pack(">I", len(data))
        proc.stdin.write(header + data)
        await proc.stdin.drain()

        try:
            resp_header = await proc.stdout.readexactly(4)
            resp_len = struct.unpack(">I", resp_header)[0]
            resp_bytes = await proc.stdout.readexactly(resp_len)
            return json.loads(resp_bytes.decode("utf-8"))
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            await self.kill()
            return {
                "status": "error",
                "stdout": "",
                "stderr": "",
                "eval_result": None,
                "error": "SystemExit: Program mencoba keluar atau proses REPL terhenti.",
            }

    async def kill(self) -> None:
        """Hentikan paksa proses worker dan tutup transport stream."""
        proc = self.process
        self.process = None
        if proc is not None:
            if proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            if proc.stdin and not proc.stdin.is_closing():
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            if hasattr(proc, "_transport") and proc._transport and not proc._transport.is_closing():
                try:
                    proc._transport.close()
                except Exception:
                    pass

    def terminate_sync(self) -> None:
        """Terminasi sinkron saat garbage collection atau shutdown."""
        proc = self.process
        self.process = None
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
            if hasattr(proc, "_transport") and proc._transport and not proc._transport.is_closing():
                try:
                    proc._transport.close()
                except Exception:
                    pass


class PythonReplTool(BaseTool):
    """Tool interpreter Python in-memory stateful terisolasi untuk kalkulasi, transformasi data, dan eksekusi algoritma."""

    name = "python_repl"
    description = (
        "Tool interpreter kode Python stateful terisolasi tingkat tinggi (Hermes-grade Stateful Python REPL). "
        "Mengeksekusi kode Python dalam subproses terisolasi dengan sanitasi kredensial secara aman. "
        "Fitur utama: "
        "1. Stateful/Persisten: Variabel, fungsi, class, dan modul yang di-import pada pemanggilan sebelumnya "
        "tetap tersimpan dalam memori untuk pemanggilan berikutnya dalam satu sesi chat. "
        "2. Auto Expression Evaluation: Ekspresi baris terakhir otomatis dihitung dan ditampilkan (misal: 12 * 8 langsung menghasilkan 96 tanpa perlu fungsi print). "
        "3. Tangkap Output Lengkap: Menangkap stdout (print), stderr, serta hasil kalkulasi secara simultan. "
        "4. Proteksi Keamanan: Terisolasi dalam subproses, proteksi kebocoran kredensial (os.environ bersih), anti-self termination, dan timeout aman. "
        "Gunakan saat membutuhkan perhitungan matematika rumit, manipulasi/parsing JSON, regex, pemrosesan teks besar, "
        "konversi unit/waktu, hashing/encoding, atau pengujian logika Python."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["execute", "inspect", "reset"],
                "description": (
                    "Aksi: 'execute' (jalankan kode Python), 'inspect' (lihat variabel yang tersimpan di memori saat ini), "
                    "'reset' (bersihkan memori sesi Python dan mulai ulang ruang lingkup kosong)."
                ),
                "default": "execute",
            },
            "code": {
                "type": "string",
                "description": "Kode Python yang akan dieksekusi (wajib jika action='execute').",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Batas waktu eksekusi dalam detik (default 15 detik, maksimal 60 detik).",
                "default": 15,
            },
        },
        "required": [],
    }

    _active_tools: set[PythonReplTool] = set()

    def __init__(self) -> None:
        super().__init__()
        # Simpan instance ReplSession per chat_id agar antar pengguna/sesi terisolasi
        self._sessions: dict[int, ReplSession] = {}
        self._lock = asyncio.Lock()
        self._active_tools.add(self)

    def _reset_session(self, chat_id: int) -> int:
        """Kosongkan dan hentikan subproses sesi."""
        session = self._sessions.pop(chat_id, None)
        if session:
            session.terminate_sync()
            return 1
        return 0

    async def close(self) -> None:
        """Bersihkan seluruh worker aktif."""
        async with self._lock:
            for session in list(self._sessions.values()):
                await session.kill()
            self._sessions.clear()
        self._active_tools.discard(self)

    def __del__(self) -> None:
        self._active_tools.discard(self)
        for session in list(self._sessions.values()):
            session.terminate_sync()
        self._sessions.clear()

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "execute").lower().strip()
        chat_id = context.chat_id
        settings = get_settings()

        # ------------------------------------------------------------------
        # 1. Action: RESET
        # ------------------------------------------------------------------
        if action == "reset":
            async with self._lock:
                session = self._sessions.pop(chat_id, None)
                if session:
                    await session.kill()
            return ToolResult(
                success=True,
                output="Ruang lingkup memori Python REPL berhasil di-reset ke kondisi awal yang bersih.",
            )

        # ------------------------------------------------------------------
        # 2. Action: INSPECT
        # ------------------------------------------------------------------
        elif action == "inspect":
            async with self._lock:
                session = self._sessions.get(chat_id)
                if session is None:
                    return ToolResult(
                        success=True,
                        output="Memori sesi Python saat ini kosong (belum ada variabel atau fungsi tersimpan).",
                    )
                resp = await session.send_command({"action": "inspect"})

            user_vars = resp.get("user_vars", {})
            if not user_vars:
                return ToolResult(
                    success=True,
                    output="Memori sesi Python saat ini kosong (belum ada variabel atau fungsi tersimpan).",
                )

            lines = [f"Variabel & Objek Tersimpan di Memori ({len(user_vars)} item):", ""]
            for k, info in sorted(user_vars.items()):
                lines.append(f"• {k} ({info['type']}): {info['repr']}")

            return ToolResult(success=True, output="\n".join(lines))

        # ------------------------------------------------------------------
        # 3. Action: EXECUTE
        # ------------------------------------------------------------------
        elif action == "execute":
            raw_code = str(kwargs.get("code") or "").strip()
            if not raw_code:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'code' wajib diisi untuk action='execute'.",
                )

            # Security Check: Cegah kebocoran kredensial sensitif via kode python
            is_leak, leak_item = permission_manager.check_credential_exfiltration(raw_code)
            if is_leak:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Keamanan Terpicu: Akses atau kebocoran berkas kredensial sensitif ('{leak_item}') diblokir.",
                )

            # Security Check: Cegah perintah destruktif fatal di dalam string kode
            is_destr, reason = permission_manager.check_destructive(raw_code)
            if is_destr:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Keamanan Terpicu: Kode mengandung instruksi destruktif ('{reason}'). Operasi dibatalkan.",
                )

            timeout_sec = min(max(int(kwargs.get("timeout_seconds") or DEFAULT_TIMEOUT_SEC), 1), 60)

            if context.on_status_update:
                await context.on_status_update("● Menjalankan kode Python di memori...")

            async with self._lock:
                if chat_id not in self._sessions:
                    self._sessions[chat_id] = ReplSession(chat_id)
                session = self._sessions[chat_id]

            try:
                async with session.lock:
                    resp = await asyncio.wait_for(
                        session.send_command({"action": "execute", "code": raw_code}),
                        timeout=float(timeout_sec),
                    )
            except asyncio.TimeoutError:
                await session.kill()
                async with self._lock:
                    self._sessions.pop(chat_id, None)
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Eksekusi kode Python melebihi batas waktu ({timeout_sec} detik). Mungkin terjadi loop tak terhingga.",
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Kesalahan internal saat menjalankan REPL: {e}",
                )

            if context.cancel_event.is_set():
                return ToolResult(success=False, output="", error="Dibatalkan oleh pengguna.")

            exec_err = resp.get("error")
            stdout_str = resp.get("stdout", "")
            stderr_str = resp.get("stderr", "")
            eval_result = resp.get("eval_result")

            if exec_err:
                clean_err = _clean_traceback(exec_err)
                return ToolResult(
                    success=False,
                    output=stdout_str if stdout_str else "",
                    error=f"Kesalahan Eksekusi Python:\n{clean_err}",
                )

            # Format output gabungan (stdout + eval_result)
            out_blocks: list[str] = []
            if stdout_str:
                out_blocks.append(stdout_str.rstrip())
            if eval_result is not None:
                out_blocks.append(f"=> {eval_result}")
            if stderr_str:
                out_blocks.append(f"[stderr]:\n{stderr_str.rstrip()}")

            final_output = "\n".join(out_blocks).strip()
            if not final_output:
                final_output = "(Kode berhasil dieksekusi tanpa keluaran output)"

            # Tangani jika output sangat panjang
            saved_doc: str | None = None
            if len(final_output) > MAX_OUTPUT_CHARS:
                temp_dir = settings.temp_media_dir
                try:
                    os.makedirs(temp_dir, exist_ok=True)
                    doc_path = os.path.join(temp_dir, f"repl_output_{int(time.time())}.txt")
                    with open(doc_path, "w", encoding="utf-8") as f:
                        f.write(f"# Output Python REPL:\n{final_output}")
                    saved_doc = doc_path
                except OSError:
                    pass

                final_output = (
                    final_output[:MAX_OUTPUT_CHARS]
                    + "\n\n...(keluaran terpotong karena batas panjang pesan, berkas lengkap tersimpan)"
                )

            return ToolResult(
                success=True,
                output=final_output,
                media_path=saved_doc,
                media_type="document" if saved_doc else None,
            )

        return ToolResult(
            success=False,
            output="",
            error=f"Aksi '{action}' tidak dikenal. Pilihan: execute, inspect, reset.",
        )
