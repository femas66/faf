"""CLI startup banner for faf-agent (Pure Python Unicode Block Art)."""
from __future__ import annotations

import os
import shutil
import sys
from typing import TextIO

from src.config import Settings, get_settings
from src.tools import default_registry

APP_VERSION = "0.1.0"

BANNER_WIDE: tuple[str, ...] = (
    "███████╗ █████╗ ███████╗     █████╗  ██████╗ ███████╗███╗   ██╗████████╗",
    "██╔════╝██╔══██╗██╔════╝    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝",
    "█████╗  ███████║█████╗      ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ",
    "██╔══╝  ██╔══██║██╔══╝      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ",
    "██║     ██║  ██║██║         ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ",
    "╚═╝     ╚═╝  ╚═╝╚═╝         ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ",
)

BANNER_COMPACT: tuple[str, ...] = (
    "█▀▀ ▄▀█ █▀▀   ▄▀█ █▀▀ █▀▀ █▄░█ ▀█▀",
    "█▀░ █▀█ █▀░   █▀█ █▄█ ██▄ █░▀█ ░█░",
)

_GRADIENT_WIDE: tuple[str, ...] = (
    "\033[38;5;51m",  # bright cyan
    "\033[38;5;45m",  # cyan-blue
    "\033[38;5;39m",  # sky blue
    "\033[38;5;33m",  # dodger blue
    "\033[38;5;27m",  # royal blue
    "\033[38;5;63m",  # indigo-blue
)

_GRADIENT_COMPACT: tuple[str, ...] = (
    "\033[38;5;51m",
    "\033[38;5;39m",
)


def _supports_color(stream: TextIO | None = None) -> bool:
    """Return True if ANSI colors should be emitted."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    target = stream or sys.stdout
    return bool(getattr(target, "isatty", lambda: False)())


def render_startup_banner(
    settings: Settings | None = None,
    *,
    width: int | None = None,
    color: bool | None = None,
    mode_label: str = "Online (Polling Telegram updates... Ctrl+C to stop)",
) -> str:
    """Render the FAF Agent CLI banner as a string."""
    cfg = settings or get_settings()
    term_width = width if width is not None else shutil.get_terminal_size((80, 24)).columns
    use_color = _supports_color() if color is None else color

    reset = "\033[0m" if use_color else ""
    bold = "\033[1m" if use_color else ""
    dim = "\033[2m" if use_color else ""
    cyan = "\033[38;5;45m" if use_color else ""
    green = "\033[38;5;48m" if use_color else ""
    gray = "\033[38;5;245m" if use_color else ""

    pid = os.getpid()
    model = cfg.openai_model or "gpt-4o"
    tools_count = len(default_registry.get_all())
    users_count = len(cfg.allowed_telegram_user_ids)
    users_str = f"{users_count} whitelisted" if users_count else "none (locked)"

    lines: list[str] = [""]

    if term_width >= 76:
        for grad, row in zip(_GRADIENT_WIDE, BANNER_WIDE):
            c = f"{bold}{grad}" if use_color else ""
            lines.append(f"  {c}{row}{reset}")
        divider = f"  {gray}{'─' * 72}{reset}"
        lines.append(
            f"  {dim}Autonomous Android AI Agent via Telegram • Pure Python • Zero Maturin{reset}"
        )
        lines.append(divider)
        col1_v = f"v{APP_VERSION}".ljust(20)
        col1_m = model[:20].ljust(20)
        lines.append(
            f"  {cyan}▸ Version :{reset} {col1_v} {cyan}▸ PID    :{reset} {pid}"
        )
        lines.append(
            f"  {cyan}▸ Model   :{reset} {col1_m} {cyan}▸ Tools  :{reset} {tools_count} active ({users_str})"
        )
        lines.append(
            f"  {cyan}▸ Status  :{reset} {green}●{reset} {mode_label}"
        )
        lines.append(divider)
    else:
        for grad, row in zip(_GRADIENT_COMPACT, BANNER_COMPACT):
            c = f"{bold}{grad}" if use_color else ""
            lines.append(f"  {c}{row}{reset}")
        rule_len = max(34, min(term_width - 4, 44))
        divider = f"  {gray}{'─' * rule_len}{reset}"
        lines.append(f"  {dim}Autonomous Android AI Agent • Pure Python{reset}")
        lines.append(divider)
        lines.append(f"  {cyan}▸ Version :{reset} v{APP_VERSION} (PID: {pid})")
        lines.append(f"  {cyan}▸ Model   :{reset} {model} ({tools_count} tools)")
        lines.append(f"  {cyan}▸ Status  :{reset} {green}●{reset} {mode_label}")
        lines.append(divider)

    lines.append("")
    return "\n".join(lines)


def print_startup_banner(
    settings: Settings | None = None,
    *,
    stream: TextIO | None = None,
    mode_label: str = "Online (Polling Telegram updates... Ctrl+C to stop)",
) -> None:
    """Print the FAF Agent startup banner to stdout (or given stream)."""
    target = stream or sys.stdout
    banner = render_startup_banner(
        settings=settings,
        color=_supports_color(target),
        mode_label=mode_label,
    )
    print(banner, file=target, flush=True)
