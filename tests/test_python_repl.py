from __future__ import annotations

import asyncio
import sys
import pytest

from src.tools.base import ToolContext
from src.tools.python_repl import PythonReplTool


@pytest.fixture(autouse=True)
async def cleanup_repl_subprocesses():
    yield
    for tool in list(PythonReplTool._active_tools):
        await tool.close()


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


async def test_python_repl_credential_env_isolation(monkeypatch):
    # Kredensial di proses utama tidak boleh tembus ke environment subprocess REPL
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:SECRET_TELEGRAM_TOKEN")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-SUPER_SECRET_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("CUSTOM_BOT_SECRET", "super_secret_val_xyz")

    tool = PythonReplTool()
    res = await tool.execute(
        _ctx(),
        code=(
            "import os\n"
            "env_keys = list(os.environ.keys())\n"
            "custom = os.environ.get('CUSTOM_BOT_SECRET')\n"
            "has_secrets = any('KEY' in k or 'TOKEN' in k or 'SECRET' in k for k in env_keys)\n"
            "print(f'has_secrets={has_secrets}, custom={custom}')"
        ),
    )
    assert res.success
    assert "has_secrets=False, custom=None" in res.output

    # Cek bahwa token telegram jika dicari secara dinamis mengembalikan None
    res2 = await tool.execute(
        _ctx(),
        code=(
            "import os\n"
            "k = 'TELEGRAM_' + 'BOT_' + 'TOKEN'\n"
            "print('val:', os.environ.get(k))"
        ),
    )
    assert res2.success
    assert "val: None" in res2.output


async def test_python_repl_memory_isolation_cannot_pollute_parent():
    # Modifikasi runtime/sys di REPL tidak boleh memengaruhi memori proses bot
    tool = PythonReplTool()
    flag_name = "_faf_test_pwn_flag"
    res = await tool.execute(_ctx(), code=f"import sys; sys.{flag_name} = True")
    assert res.success
    assert not hasattr(sys, flag_name)


async def test_python_repl_cannot_import_project_internals():
    # Subprocess REPL tidak boleh mengimpor modul internal bot
    tool = PythonReplTool()
    res = await tool.execute(_ctx(), code="import src.config")
    assert not res.success
    assert "ModuleNotFoundError" in res.error


async def test_python_repl_hard_exit_does_not_crash_bot():
    # Pemanggilan os._exit tidak boleh mematikan proses utama
    tool = PythonReplTool()
    res = await tool.execute(_ctx(), code="import os; os._exit(42)")
    assert not res.success
    assert "SystemExit" in res.error or "keluar" in res.error

