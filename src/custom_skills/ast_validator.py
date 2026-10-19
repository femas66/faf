from __future__ import annotations

import ast
import logging
from typing import Any

from src.custom_skills.manifest import SkillPermissions

logger = logging.getLogger("faf_agent.custom_skills.ast_validator")

# Default safe standard modules
DEFAULT_ALLOWED_MODULES = {
    "json",
    "math",
    "re",
    "datetime",
    "time",
    "urllib.parse",
    "dataclasses",
    "typing",
    "sys",
    "collections",
    "itertools",
    "functools",
    "string",
    "decimal",
    "fractions",
    "random",
}

# Dangerous functions and attributes forbidden under all circumstances
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
}

FORBIDDEN_ATTRIBUTES = {
    "__subclasses__",
    "__bases__",
    "__mro__",
    "__globals__",
    "__builtins__",
    "__code__",
}

FORBIDDEN_MODULES = {
    "ctypes",
    "cffi",
    "pickle",
    "shelve",
    "marshal",
    "importlib",
    "pty",
    "code",
    "codeop",
    "builtins",
    "multiprocessing",
    "posix",
    "resource",
    "gc",
}

SECRET_STRING_PATTERNS = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "faf_memory.db",
    "faf_agent.lock",
    "telegram_bot_token",
    "openai_api_key",
}


class ASTValidationError(ValueError):
    """Raised when source code fails static security analysis."""
    pass


class ASTSecurityVisitor(ast.NodeVisitor):
    """AST visitor traversing Python code to inspect imports, function calls, and syntax patterns."""

    def __init__(self, permissions: SkillPermissions | None = None) -> None:
        self.permissions = permissions or SkillPermissions()
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod_name = alias.name.split(".")[0]
            self._check_module(mod_name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod_name = node.module.split(".")[0]
            self._check_module(mod_name, node.lineno)
        self.generic_visit(node)

    def _check_module(self, mod_name: str, lineno: int) -> None:
        if mod_name in FORBIDDEN_MODULES:
            self.violations.append(
                f"[Baris {lineno}] Modul terlarang '{mod_name}' dilarang demi keamanan sistem."
            )
            return

        # Check network modules
        if mod_name in ("socket", "http", "urllib", "requests", "httpx", "aiohttp"):
            if not self.permissions.network:
                self.violations.append(
                    f"[Baris {lineno}] Modul jaringan '{mod_name}' dilarang karena manifest tidak memiliki izin network."
                )
            return

        # Check process / shell modules
        if mod_name in ("subprocess", "shutil"):
            if not self.permissions.termux_api and not self.permissions.shell:
                self.violations.append(
                    f"[Baris {lineno}] Modul eksekusi '{mod_name}' dilarang tanpa izin termux_api atau shell."
                )
            return

        if mod_name == "os":
            # Direct os module is restricted; os.system, os.popen, os.kill are strictly disallowed
            # If filesystem is permitted, os.path might be used, but we verify call nodes
            pass

        # Check against allowlist
        allowed = set(DEFAULT_ALLOWED_MODULES)
        if self.permissions.termux_api:
            allowed.update({"subprocess", "shutil"})
        if self.permissions.network:
            allowed.update({"urllib", "http"})
        if self.permissions.fs_read or self.permissions.fs_write:
            allowed.update({"pathlib", "os"})

        if mod_name not in allowed and mod_name != "os":
            self.violations.append(
                f"[Baris {lineno}] Modul '{mod_name}' tidak ada dalam allowlist modul yang diizinkan."
            )

    def visit_Call(self, node: ast.Call) -> None:
        # Check forbidden direct function calls
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in FORBIDDEN_CALLS:
                self.violations.append(
                    f"[Baris {node.lineno}] Pemanggilan fungsi berbahaya '{func_name}()' dilarang."
                )

            # Check open() if no fs permissions
            if func_name == "open" and not (self.permissions.fs_read or self.permissions.fs_write):
                self.violations.append(
                    f"[Baris {node.lineno}] Pemanggilan open() dilarang tanpa izin fs_read atau fs_write."
                )

        # Check attribute calls (e.g. os.system, os.popen, os.kill, subprocess.Popen)
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in FORBIDDEN_CALLS:
                self.violations.append(
                    f"[Baris {node.lineno}] Pemanggilan method berbahaya '{attr_name}()' dilarang."
                )

            # Check os execution calls
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                if attr_name in ("system", "popen", "spawn", "exec", "execl", "kill", "remove", "unlink"):
                    self.violations.append(
                        f"[Baris {node.lineno}] Pemanggilan 'os.{attr_name}()' dilarang. Gunakan izin termux_api resmi."
                    )

            # Check subprocess calls: verify it only calls allowed termux_api commands if present
            if isinstance(node.func.value, ast.Name) and node.func.value.id in ("subprocess", "shutil"):
                if node.func.value.id == "subprocess" and attr_name in ("Popen", "run", "call", "check_output"):
                    self._check_subprocess_args(node)

        self.generic_visit(node)

    def _check_subprocess_args(self, node: ast.Call) -> None:
        """Inspect arguments to subprocess.run/call to ensure only allowed termux commands are invoked."""
        if not self.permissions.termux_api:
            self.violations.append(
                f"[Baris {node.lineno}] Pemanggilan subprocess dilarang karena tidak memiliki izin termux_api."
            )
            return

        if not node.args:
            return

        first_arg = node.args[0]
        cmd_target: str | None = None

        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            cmd_target = first_arg.value.split()[0]
        elif isinstance(first_arg, (ast.List, ast.Tuple)) and first_arg.elts:
            elt0 = first_arg.elts[0]
            if isinstance(elt0, ast.Constant) and isinstance(elt0.value, str):
                cmd_target = elt0.value
            elif isinstance(elt0, ast.Name):
                # Variable argument, allow if termux_api is defined
                return

        if cmd_target:
            cmd_base = cmd_target.split("/")[-1]
            if cmd_base not in self.permissions.termux_api:
                self.violations.append(
                    f"[Baris {node.lineno}] Eksekusi command '{cmd_base}' di luar daftar izin termux_api: {self.permissions.termux_api}."
                )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Check introspection / dunder attribute access
        if node.attr in FORBIDDEN_ATTRIBUTES:
            self.violations.append(
                f"[Baris {node.lineno}] Akses atribut refleksi '{node.attr}' dilarang."
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        # Check for hardcoded secret file names in string constants
        if isinstance(node.value, str):
            val_lower = node.value.lower()
            for secret in SECRET_STRING_PATTERNS:
                if secret in val_lower:
                    self.violations.append(
                        f"[Baris {node.lineno}] String merujuk pada file/kredensial rahasia '{secret}'."
                    )
        self.generic_visit(node)


class ASTValidator:
    """Static security validator for skill source code."""

    @classmethod
    def validate_code(cls, source_code: str, permissions: SkillPermissions | None = None) -> list[str]:
        """Parse and statically validate Python code. Returns list of security violations (empty if safe)."""
        if not source_code or not source_code.strip():
            return ["Kode sumber skill kosong."]

        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            return [f"Kesalahan sintaks Python pada baris {e.lineno}: {e.msg}"]

        visitor = ASTSecurityVisitor(permissions=permissions)
        visitor.visit(tree)
        return visitor.violations
