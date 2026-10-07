from __future__ import annotations

import asyncio
import pytest

from src.tools.base import ToolContext
from src.tools.python_repl import PythonReplTool


def _ctx(chat_id: int = 1) -> ToolContext:
    return ToolContext(chat_id=chat_id, user_id=1)


async def test_python_repl_basic_print():
    tool = PythonReplTool()
    res = await tool.execute(_ctx(), code="print('Halo dari Termux!')")
    assert res.success
    assert "Halo dari Termux!" in res.output


async def test_python_repl_auto_expression_eval():
    tool = PythonReplTool()
    res = await tool.execute(_ctx(), code="25 * 4 + 7")
    assert res.success
    assert "=> 107" in res.output


async def test_python_repl_stateful_session():
    tool = PythonReplTool()
    ctx = _ctx(chat_id=10)

    # Step 1: Definisikan variabel
    res1 = await tool.execute(ctx, code="angka_dasar = 50")
    assert res1.success

    # Step 2: Gunakan variabel di pemanggilan berikutnya
    res2 = await tool.execute(ctx, code="angka_dasar * 2")
    assert res2.success
    assert "=> 100" in res2.output

    # Step 3: Definisikan fungsi
    res3 = await tool.execute(
        ctx,
        code="""
def kalikan_tiga(val):
    return val * 3
""",
    )
    assert res3.success

    # Step 4: Panggil fungsi
    res4 = await tool.execute(ctx, code="kalikan_tiga(angka_dasar)")
    assert res4.success
    assert "=> 150" in res4.output


async def test_python_repl_session_isolation():
    tool = PythonReplTool()
    ctx1 = _ctx(chat_id=101)
    ctx2 = _ctx(chat_id=102)

    # Set di chat 101
    await tool.execute(ctx1, code="rahasia = 'kunci_101'")

    # Cek di chat 102 (harus NameError)
    res = await tool.execute(ctx2, code="print(rahasia)")
    assert not res.success
    assert "NameError" in res.error


async def test_python_repl_inspect_and_reset():
    tool = PythonReplTool()
    ctx = _ctx(chat_id=20)

    # Awal: kosong
    res_empty = await tool.execute(ctx, action="inspect")
    assert res_empty.success
    assert "kosong" in res_empty.output

    # Isi variabel
    await tool.execute(ctx, code="skor = 99\nnama = 'faf'")
    res_inspect = await tool.execute(ctx, action="inspect")
    assert res_inspect.success
    assert "skor (int): 99" in res_inspect.output
    assert "nama (str): 'faf'" in res_inspect.output

    # Reset
    res_reset = await tool.execute(ctx, action="reset")
    assert res_reset.success
    assert "berhasil di-reset" in res_reset.output

    # Cek kembali (harus kosong)
    res_after = await tool.execute(ctx, action="inspect")
    assert res_after.success
    assert "kosong" in res_after.output


async def test_python_repl_runtime_error_handling():
    tool = PythonReplTool()
    res = await tool.execute(_ctx(), code="10 / 0")
    assert not res.success
    assert "ZeroDivisionError" in res.error


async def test_python_repl_syntax_error_handling():
    tool = PythonReplTool()
    res = await tool.execute(_ctx(), code="def salah_sintaks(:")
    assert not res.success
    assert "SyntaxError" in res.error


async def test_python_repl_credential_leak_guard():
    tool = PythonReplTool()
    res = await tool.execute(_ctx(), code="with open('.env') as f: print(f.read())")
    assert not res.success
    assert "Keamanan Terpicu" in res.error
    assert "kredensial" in res.error


async def test_python_repl_destructive_command_guard():
    tool = PythonReplTool()
    res = await tool.execute(_ctx(), code="import os; os.system('rm -rf /sdcard')")
    assert not res.success
    assert "Keamanan Terpicu" in res.error
    assert "destruktif" in res.error


async def test_python_repl_anti_self_termination():
    tool = PythonReplTool()
    # exit() atau sys.exit() tidak boleh mematikan proses utama pytest/bot
    res = await tool.execute(_ctx(), code="exit()")
    assert not res.success
    assert "SystemExit" in res.error or "dicegah" in res.error


async def test_python_repl_timeout_handling():
    tool = PythonReplTool()
    # Timeout 1 detik dengan sleep synchronous
    res = await tool.execute(
        _ctx(),
        code="import time; time.sleep(2)",
        timeout_seconds=1,
    )
    assert not res.success
    assert "melebihi batas waktu" in res.error


async def test_python_repl_registered_in_default_registry():
    from src.tools import create_default_registry

    reg = create_default_registry()
    assert reg.get("python_repl") is not None
