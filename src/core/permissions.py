from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Awaitable

import psutil

from src.config import get_settings

logger = logging.getLogger("faf_agent.permissions")


@dataclass
class PendingConfirmation:
    request_id: str
    chat_id: int
    title: str
    details: str
    future: asyncio.Future[bool]
    created_at: float = field(default_factory=time.time)
    timeout: int = 60


class PermissionManager:
    """Manages security validation, destructive command interception,

    process immunity, and approval sessions.
    """

    # Destructive keywords and regex patterns
    DESTRUCTIVE_PATTERNS = [
        r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f?|-f\s+-[a-zA-Z]*r)\b",  # rm -rf, rm -fr, etc.
        r"\brm\s+-[a-zA-Z]*r\b",                               # rm -r
        r"\bdd\s+if=",                                          # dd raw write
        r"\bmkfs\b",                                            # format filesystem
        r"\bformat\b",                                          # format command
        r"\breboot\b",                                          # system reboot
        r"\bshutdown\b",                                        # system shutdown
        r"\bpoweroff\b",                                        # system poweroff
        r"\bpm\s+uninstall\b",                                  # package uninstall
        r"\bpm\s+clear\b",                                      # clear app data
        r"\bwipe\b",                                            # wipe partition
        r"\bfdisk\b",                                           # partition edit
    ]

    # Protected processes for anti self-termination
    PROTECTED_PROCESS_NAMES = {
        "faf-agent",
        "python",
        "python3",
        "sshd",
        "tmux",
        "termux",
        "com.termux",
        "zygote",
        "zygote64",
        "init",
    }

    # Sensitive credential files patterns
    CREDENTIAL_PATTERNS = [
        r"\.env\b",
        r"id_rsa",
        r"id_ecdsa",
        r"id_ed25519",
        r"\.ssh/",
        r"\.gnupg/",
        r"keystore\b",
        r"telegram_bot_token",
        r"openai_api_key",
    ]

    def __init__(self) -> None:
        self.settings = get_settings()
        self._pending_requests: dict[str, PendingConfirmation] = {}
        self._lock = asyncio.Lock()

    def get_own_pids(self) -> set[int]:
        """Return set of current process PID and immediate parent PID."""
        pids = {os.getpid(), os.getppid()}
        try:
            current_proc = psutil.Process(os.getpid())
            for child in current_proc.children(recursive=True):
                pids.add(child.pid)
            parent = current_proc.parent()
            if parent:
                pids.add(parent.pid)
        except Exception:
            pass
        return pids

    def check_destructive(self, command: str) -> tuple[bool, str]:
        """Check if command matches any destructive pattern."""
        cmd_clean = command.strip()
        for pattern in self.DESTRUCTIVE_PATTERNS:
            match = re.search(pattern, cmd_clean, re.IGNORECASE)
            if match:
                matched_token = match.group(0)
                return True, f"Terdeteksi perintah destruktif berisiko tinggi: `{matched_token}`"
        return False, ""

    def check_self_termination(
        self, command: str, target_pid: int | None = None
    ) -> tuple[bool, str]:
        """Check if command or target PID attempts to terminate protected processes."""
        own_pids = self.get_own_pids()

        # Direct target PID check
        if target_pid is not None and target_pid in own_pids:
            return (
                True,
                f"IMMUNITY VIOLATION: Tidak dapat mematikan PID {target_pid} (milik proses faf-agent/parent).",
            )

        tokens = command.strip().split()
        if not tokens:
            return False, ""

        kill_cmds = {"kill", "pkill", "killall"}
        targets: list[str] = []

        i = 0
        while i < len(tokens):
            t = tokens[i]
            base = t.split("/")[-1].lower()
            if base in kill_cmds:
                i += 1
                while i < len(tokens) and tokens[i] not in (";", "&&", "||", "|"):
                    arg = tokens[i]
                    if arg.startswith("-"):
                        # Skip signal options like -9, -SIGKILL, -s KILL
                        if arg in ("-s", "--signal") and i + 1 < len(tokens):
                            i += 2
                            continue
                        i += 1
                        continue
                    targets.append(arg)
                    i += 1
            i += 1

        for target in targets:
            # Check if target is a PID
            if target.isdigit():
                pid_num = int(target)
                if pid_num in own_pids:
                    return (
                        True,
                        f"IMMUNITY VIOLATION: Perintah menargetkan PID {pid_num} (proses faf-agent sendiri).",
                    )
                # Check process name of target PID
                try:
                    proc = psutil.Process(pid_num)
                    if proc.name().lower() in self.PROTECTED_PROCESS_NAMES:
                        return (
                            True,
                            f"IMMUNITY VIOLATION: Perintah menargetkan proses esensial sistem/Termux (`{proc.name()}`).",
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            else:
                # Target is process name
                target_lower = target.lower()
                for prot in self.PROTECTED_PROCESS_NAMES:
                    if prot in target_lower or target_lower == prot:
                        return (
                            True,
                            f"IMMUNITY VIOLATION: Dilarang mematikan proses esensial/Termux (`{target}`).",
                        )

        return False, ""

    def check_credential_exfiltration(self, text: str) -> tuple[bool, str]:
        """Check for attempts to read or exfiltrate secret/credential files."""
        for pattern in self.CREDENTIAL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return (
                    True,
                    "SECURITY GUARD: Akses ke berkas kredensial, token, atau kunci privat dilarang keras.",
                )
        return False, ""

    async def create_confirmation_request(
        self,
        chat_id: int,
        title: str,
        details: str,
        timeout: int | None = None,
    ) -> tuple[str, asyncio.Future[bool]]:
        """Create a pending confirmation request and return its ID and Future."""
        timeout = timeout or self.settings.security_confirmation_timeout
        request_id = uuid.uuid4().hex[:8]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        pending = PendingConfirmation(
            request_id=request_id,
            chat_id=chat_id,
            title=title,
            details=details,
            future=future,
            timeout=timeout,
        )

        async with self._lock:
            self._pending_requests[request_id] = pending

        # Schedule automatic timeout task
        asyncio.create_task(self._handle_timeout(request_id, timeout))

        return request_id, future

    async def _handle_timeout(self, request_id: str, timeout: int) -> None:
        """Expire confirmation if not resolved within timeout duration."""
        await asyncio.sleep(timeout)
        async with self._lock:
            pending = self._pending_requests.pop(request_id, None)
            if pending and not pending.future.done():
                logger.info(f"Confirmation request {request_id} timed out.")
                pending.future.set_result(False)

    async def resolve_confirmation(self, request_id: str, approved: bool) -> bool:
        """Resolve a pending confirmation by user interaction (button click)."""
        async with self._lock:
            pending = self._pending_requests.pop(request_id, None)

        if pending and not pending.future.done():
            pending.future.set_result(approved)
            logger.info(f"Confirmation {request_id} resolved: approved={approved}")
            return True
        return False

    def get_pending(self, request_id: str) -> PendingConfirmation | None:
        return self._pending_requests.get(request_id)


# Global singleton permission manager
permission_manager = PermissionManager()
