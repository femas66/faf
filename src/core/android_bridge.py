from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import signal
from dataclasses import dataclass
from typing import Any

from src.config import get_settings

logger = logging.getLogger("faf_agent.bridge")


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int
    command: str
    executed_as_root: bool

    @property
    def success(self) -> bool:
        return self.returncode == 0


class AndroidBridge:
    """Bridge for interacting with Android via Termux, Termux:API, and Root shell (Pure Python)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._active_processes: set[asyncio.subprocess.Process] = set()
        self._lock = asyncio.Lock()

    @property
    def is_android_termux(self) -> bool:
        """Check whether current runtime is within an Android Termux environment."""
        return (
            "com.termux" in os.environ.get("PREFIX", "")
            or os.path.exists("/data/data/com.termux")
            or os.path.exists("/data/data/com.termux/files/usr/bin/termux-info")
        )

    def is_root_available(self) -> bool:
        """Check if `su` binary exists on PATH or standard Android root locations."""
        if not self.settings.enable_root_commands:
            return False

        su_paths = [
            "/system/bin/su",
            "/system/xbin/su",
            "/sbin/su",
            "/su/bin/su",
            "/data/local/xbin/su",
            "/data/local/bin/su",
        ]
        if shutil.which("su") is not None:
            return True
        return any(os.path.exists(p) for p in su_paths)

    def has_command(self, cmd: str) -> bool:
        """Check if command binary exists in system PATH."""
        return shutil.which(cmd) is not None

    async def get_prop(self, prop_name: str, default: str = "") -> str:
        """Fetch Android system property using getprop."""
        if self.has_command("getprop"):
            res = await self.execute_shell(f"getprop {prop_name}", timeout=3)
            if res.success and res.stdout.strip():
                return res.stdout.strip()
        return default

    def _build_root_command(self, raw_cmd: str) -> str:
        """Wrap command with root privileges and Termux environment persistence."""
        termux_prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        termux_bin = f"{termux_prefix}/bin"
        termux_lib = f"{termux_prefix}/lib"

        env_setup = (
            f"export PREFIX={termux_prefix}; "
            f"export PATH={termux_bin}:/system/bin:/system/xbin:$PATH; "
            f"export LD_LIBRARY_PATH={termux_lib}:$LD_LIBRARY_PATH; "
        )
        safe_payload = raw_cmd.replace('"', '\\"')
        return f'su -c "{env_setup} {safe_payload}"'

    async def execute_shell(
        self,
        command: str,
        as_root: bool = False,
        timeout: int | None = None,
    ) -> CommandResult:
        """Execute a shell command asynchronously with timeout and tracking."""
        timeout = timeout or self.settings.command_timeout
        actual_cmd = command
        executed_as_root = False

        if as_root:
            if not self.settings.enable_root_commands:
                return CommandResult(
                    stdout="",
                    stderr="Root execution is disabled in faf-agent settings.",
                    returncode=126,
                    command=command,
                    executed_as_root=False,
                )
            actual_cmd = self._build_root_command(command)
            executed_as_root = True

        logger.debug(f"Executing [root={executed_as_root}]: {actual_cmd}")

        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                actual_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async with self._lock:
                self._active_processes.add(proc)

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(timeout),
            )

            stdout_str = stdout_bytes.decode(errors="replace").strip()
            stderr_str = stderr_bytes.decode(errors="replace").strip()
            rc = proc.returncode if proc.returncode is not None else 0

            return CommandResult(
                stdout=stdout_str,
                stderr=stderr_str,
                returncode=rc,
                command=command,
                executed_as_root=executed_as_root,
            )

        except asyncio.TimeoutError:
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception as e:
                    logger.warning(f"Error killing timed-out process: {e}")
            return CommandResult(
                stdout="",
                stderr=f"Command timed out after {timeout} seconds.",
                returncode=124,
                command=command,
                executed_as_root=executed_as_root,
            )
        except asyncio.CancelledError:
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            raise
        except Exception as e:
            return CommandResult(
                stdout="",
                stderr=f"Execution error: {str(e)}",
                returncode=1,
                command=command,
                executed_as_root=executed_as_root,
            )
        finally:
            if proc:
                async with self._lock:
                    self._active_processes.discard(proc)

    async def cancel_all_subprocesses(self) -> int:
        """Cancel and terminate all currently active subprocesses."""
        async with self._lock:
            processes = list(self._active_processes)

        count = len(processes)
        if count == 0:
            return 0

        logger.info(f"Terminating {count} active subprocess(es)...")
        for proc in processes:
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        # Give processes a short grace period to terminate
        await asyncio.sleep(0.2)
        for proc in processes:
            try:
                if proc.returncode is None:
                    proc.kill()
            except Exception:
                pass

        async with self._lock:
            self._active_processes.clear()

        return count

    def get_ram_info(self) -> dict[str, Any]:
        """Fetch RAM memory info from /proc/meminfo or fallback."""
        total_mb = 0.0
        avail_mb = 0.0
        used_pct = 0.0
        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r") as f:
                    mem_data: dict[str, int] = {}
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            k = parts[0].strip()
                            v = parts[1].strip().split()[0]
                            if v.isdigit():
                                mem_data[k] = int(v)
                    total_kb = mem_data.get("MemTotal", 0)
                    avail_kb = mem_data.get("MemAvailable", mem_data.get("MemFree", 0))
                    total_mb = round(total_kb / 1024.0, 1)
                    avail_mb = round(avail_kb / 1024.0, 1)
                    if total_kb > 0:
                        used_pct = round(((total_kb - avail_kb) / total_kb) * 100.0, 1)
            except Exception:
                pass
        return {
            "total_mb": total_mb,
            "available_mb": avail_mb,
            "used_percent": used_pct,
        }

    async def get_device_info(self) -> dict[str, Any]:
        """Fetch device information (Manufacturer, Model, Android version, Root, RAM)."""
        info: dict[str, Any] = {
            "platform": platform.platform(),
            "is_termux": self.is_android_termux,
            "root_available": self.is_root_available(),
        }

        # Query Android properties via getprop
        if self.has_command("getprop"):
            res_mfg = await self.execute_shell("getprop ro.product.manufacturer", timeout=5)
            res_model = await self.execute_shell("getprop ro.product.model", timeout=5)
            res_rel = await self.execute_shell("getprop ro.build.version.release", timeout=5)
            res_sdk = await self.execute_shell("getprop ro.build.version.sdk", timeout=5)

            info["manufacturer"] = res_mfg.stdout or "Unknown"
            info["model"] = res_model.stdout or "Unknown"
            info["android_version"] = res_rel.stdout or "Unknown"
            info["sdk_version"] = res_sdk.stdout or "Unknown"
        else:
            info["manufacturer"] = platform.system()
            info["model"] = platform.machine()
            info["android_version"] = platform.release()
            info["sdk_version"] = "N/A"

        ram = self.get_ram_info()
        info["total_ram_mb"] = ram["total_mb"]
        info["available_ram_mb"] = ram["available_mb"]
        info["used_ram_percent"] = ram["used_percent"]

        return info

    async def get_battery_info(self) -> dict[str, Any]:
        """Fetch battery details via termux-battery-status, dumpsys battery, or sysfs."""
        # 1. Try termux-battery-status
        if self.has_command("termux-battery-status"):
            res = await self.execute_shell("termux-battery-status", timeout=6)
            if res.success and res.stdout:
                try:
                    return json.loads(res.stdout)
                except json.JSONDecodeError:
                    pass

        # 2. Try dumpsys battery (root or adb shell)
        res_dump = await self.execute_shell("dumpsys battery", as_root=self.is_root_available(), timeout=6)
        if res_dump.success and res_dump.stdout:
            data: dict[str, Any] = {}
            for line in res_dump.stdout.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if key == "level":
                        data["percentage"] = int(val)
                    elif key == "temperature":
                        data["temperature"] = float(val) / 10.0
                    elif key == "status":
                        data["status"] = "Charging" if val == "2" else "Discharging"
                    elif key == "plugged":
                        data["plugged"] = val
            if data:
                return data

        # 3. Android sysfs battery fallback
        cap_file = "/sys/class/power_supply/battery/capacity"
        status_file = "/sys/class/power_supply/battery/status"
        temp_file = "/sys/class/power_supply/battery/temp"
        if os.path.exists(cap_file):
            try:
                pct = open(cap_file).read().strip()
                status = open(status_file).read().strip() if os.path.exists(status_file) else "Unknown"
                temp_raw = open(temp_file).read().strip() if os.path.exists(temp_file) else "0"
                temp_c = round(float(temp_raw) / 10.0, 1) if temp_raw.isdigit() else "N/A"
                return {
                    "percentage": int(pct) if pct.isdigit() else "N/A",
                    "status": status,
                    "temperature": temp_c,
                    "plugged": "Unknown",
                }
            except Exception:
                pass

        return {
            "percentage": "N/A",
            "status": "Unknown",
            "temperature": "N/A",
            "plugged": "Unknown",
        }


# Singleton bridge instance
bridge = AndroidBridge()
