from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import logging
import os
import re
import sys
import time
import traceback
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
        if "python_repl.py" in line:
            skip = True
            continue
        if skip and line.strip().startswith("exec("):
            skip = False
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


class PythonReplTool(BaseTool):
    """Tool interpreter Python in-memory stateful untuk kalkulasi, transformasi data, dan eksekusi algoritma."""

    name = "python_repl"
    description = (
        "Tool interpreter kode Python in-memory tingkat tinggi (Hermes-grade Stateful Python REPL). "
        "Mengeksekusi kode Python langsung di dalam memori proses Termux secara instan dan aman. "
        "Fitur utama: "
        "1. Stateful/Persisten: Variabel, fungsi, class, dan modul yang di-import pada pemanggilan sebelumnya "
        "tetap tersimpan dalam memori untuk pemanggilan berikutnya dalam satu sesi chat. "
        "2. Auto Expression Evaluation: Ekspresi baris terakhir otomatis dihitung dan ditampilkan (misal: 12 * 8 langsung menghasilkan 96 tanpa perlu fungsi print). "
        "3. Tangkap Output Lengkap: Menangkap stdout (print), stderr, serta hasil kalkulasi secara simultan. "
        "4. Proteksi Keamanan: Kebal terminasi diri (anti-self termination), timeout aman, dan proteksi kredensial. "
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

    def __init__(self) -> None:
        super().__init__()
        # Simpan namespace memori per chat_id agar antar pengguna/sesi terisolasi
        self._sessions: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def _get_session_scope(self, chat_id: int) -> dict[str, Any]:
        """Ambil atau inisialisasi namespace variabel Python untuk chat tertentu."""
        if chat_id not in self._sessions:
            scope: dict[str, Any] = {
                "__name__": "__main__",
                "__doc__": "faf-agent in-memory Python REPL",
            }
            # Pasang proteksi anti-exit di dalam namespace
            def _safe_exit(*args: Any, **kwargs: Any) -> None:
                raise SystemExit("Pemanggilan sys.exit() dicegah dalam sesi REPL.")

            def _safe_os_exit(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("Pemanggilan os._exit() diblokir oleh sistem proteksi.")

            scope["exit"] = _safe_exit
            scope["quit"] = _safe_exit
            self._sessions[chat_id] = scope

        return self._sessions[chat_id]

    def _reset_session(self, chat_id: int) -> int:
        """Kosongkan namespace memori sesi."""
        old_count = len(self._sessions.get(chat_id, {}))
        self._sessions.pop(chat_id, None)
        return old_count

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "execute").lower().strip()
        chat_id = context.chat_id
        settings = get_settings()

        # ------------------------------------------------------------------
        # 1. Action: RESET
        # ------------------------------------------------------------------
        if action == "reset":
            async with self._lock:
                self._reset_session(chat_id)
            return ToolResult(
                success=True,
                output="Ruang lingkup memori Python REPL berhasil di-reset ke kondisi awal yang bersih.",
            )

        # ------------------------------------------------------------------
        # 2. Action: INSPECT
        # ------------------------------------------------------------------
        elif action == "inspect":
            async with self._lock:
                scope = self._get_session_scope(chat_id)
                # Filter builtins dan internal keys
                user_vars = {
                    k: v
                    for k, v in scope.items()
                    if not k.startswith("__") and k not in ("exit", "quit")
                }

            if not user_vars:
                return ToolResult(
                    success=True,
                    output="Memori sesi Python saat ini kosong (belum ada variabel atau fungsi tersimpan).",
                )

            lines = [f"Variabel & Objek Tersimpan di Memori ({len(user_vars)} item):", ""]
            for k, v in sorted(user_vars.items()):
                tname = type(v).__name__
                val_repr = repr(v)
                if len(val_repr) > 100:
                    val_repr = val_repr[:100] + "..."
                lines.append(f"• {k} ({tname}): {val_repr}")

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
                scope = self._get_session_scope(chat_id)

            try:
                # Eksekusi sinkron di thread terpisah dengan timeout asyncio
                stdout_str, stderr_str, eval_result, exec_err = await asyncio.wait_for(
                    asyncio.to_thread(self._run_code_sync, raw_code, scope),
                    timeout=float(timeout_sec),
                )
            except asyncio.TimeoutError:
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

    def _run_code_sync(
        self, code: str, scope: dict[str, Any]
    ) -> tuple[str, str, str | None, str | None]:
        """Eksekusi kode Python secara sinkron dengan isolasi stdout/stderr dan auto-expression eval."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        eval_result: str | None = None
        exec_err: str | None = None

        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            try:
                tree = ast.parse(code)
                if not tree.body:
                    return "", "", None, None

                # Jika baris terakhir adalah sebuah ekspresi (misal kalkulasi tanpa print),
                # pisahkan agar di-eval dan ditampilkan nilainya (seperti REPL interaktif).
                if isinstance(tree.body[-1], ast.Expr):
                    last_expr = tree.body.pop()
                    if tree.body:
                        code_obj = compile(tree, filename="<repl>", mode="exec")
                        exec(code_obj, scope)

                    eval_code_obj = compile(
                        ast.Expression(last_expr.value), filename="<repl>", mode="eval"
                    )
                    raw_val = eval(eval_code_obj, scope)
                    if raw_val is not None:
                        eval_result = repr(raw_val)
                else:
                    code_obj = compile(tree, filename="<repl>", mode="exec")
                    exec(code_obj, scope)

            except SystemExit as se:
                exec_err = f"SystemExit: Program mencoba keluar ({se})."
            except Exception:
                exec_err = traceback.format_exc()

        return (
            stdout_buf.getvalue(),
            stderr_buf.getvalue(),
            eval_result,
            exec_err,
        )
