"""Subprocess worker untuk isolasi eksekusi kode faf-agent Python REPL.

Worker ini berjalan dalam proses terpisah dengan environment tersanitasi (tanpa kredensial)
dan direktori kerja aman, sehingga eksekusi kode pengguna tidak dapat mengganggu
proses utama bot atau membocorkan data sensitif.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import struct
import sys
import traceback
from typing import Any

# Simpan descriptor asli stdin & stdout sebelum dialihkan agar komunikasi IPC tidak bocor
_ipc_read_fd = os.dup(0)
_ipc_write_fd = os.dup(1)

# Alihkan fd 0 & 1 bawaan proses ke devnull untuk mencegah output native/C mengotori kanal IPC
try:
    _devnull_in = os.open(os.devnull, os.O_RDONLY)
    _devnull_out = os.open(os.devnull, os.O_WRONLY)
    os.dup2(_devnull_in, 0)
    os.dup2(_devnull_out, 1)
    os.close(_devnull_in)
    os.close(_devnull_out)
except OSError:
    pass

_ipc_in = io.open(_ipc_read_fd, "rb", buffering=0)
_ipc_out = io.open(_ipc_write_fd, "wb", buffering=0)

# Bersihkan sys.path dari root faf-agent agar kode REPL tidak dapat meng-import internal modul bot
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, "..", ".."))
sys.path = [
    p
    for p in sys.path
    if not (p == _current_dir or p == _project_root or p.startswith(_project_root + os.sep))
]


def _safe_exit(*args: Any, **kwargs: Any) -> None:
    raise SystemExit("Pemanggilan sys.exit() dicegah dalam sesi REPL.")


def _init_scope() -> dict[str, Any]:
    scope: dict[str, Any] = {
        "__name__": "__main__",
        "__doc__": "faf-agent in-memory Python REPL",
        "exit": _safe_exit,
        "quit": _safe_exit,
    }
    return scope


def _send_response(resp: dict[str, Any]) -> None:
    payload = json.dumps(resp).encode("utf-8")
    _ipc_out.write(struct.pack(">I", len(payload)) + payload)
    _ipc_out.flush()


def main() -> None:
    scope = _init_scope()
    sys.exit = _safe_exit

    while True:
        try:
            header = _ipc_in.read(4)
        except Exception:
            break
        if not header or len(header) < 4:
            break

        length = struct.unpack(">I", header)[0]
        payload = b""
        while len(payload) < length:
            chunk = _ipc_in.read(length - len(payload))
            if not chunk:
                break
            payload += chunk

        if len(payload) < length:
            break

        try:
            req = json.loads(payload.decode("utf-8"))
        except Exception as e:
            _send_response({"status": "error", "error": f"Payload tidak valid: {e}"})
            continue

        action = req.get("action", "execute")

        if action == "reset":
            scope.clear()
            scope.update(_init_scope())
            _send_response({"status": "ok"})

        elif action == "inspect":
            user_vars = {}
            for k, v in scope.items():
                if k.startswith("__") or k in ("exit", "quit"):
                    continue
                tname = type(v).__name__
                val_repr = repr(v)
                if len(val_repr) > 100:
                    val_repr = val_repr[:100] + "..."
                user_vars[k] = {"type": tname, "repr": val_repr}
            _send_response({"status": "ok", "user_vars": user_vars})

        elif action == "execute":
            code = req.get("code", "")
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            eval_result: str | None = None
            exec_err: str | None = None

            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                try:
                    tree = ast.parse(code)
                    if tree.body:
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

            _send_response(
                {
                    "status": "ok",
                    "stdout": stdout_buf.getvalue(),
                    "stderr": stderr_buf.getvalue(),
                    "eval_result": eval_result,
                    "error": exec_err,
                }
            )
        else:
            _send_response({"status": "error", "error": f"Aksi '{action}' tidak dikenal."})


if __name__ == "__main__":
    main()
