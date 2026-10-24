#!/usr/bin/env python3
"""Script pemeriksa kelengkapan instalasi tools dan dependensi faf-agent di Termux / Android."""

import sys
from src.bot.ui.banner import print_startup_banner
from src.core.diagnostics import check_all_dependencies, format_dependency_report


def main() -> None:
    print_startup_banner(mode_label="Dependency & System Diagnostics")
    print("🔍 Memeriksa dependensi dan tools faf-agent...\n")
    results = check_all_dependencies()
    report = format_dependency_report(results)
    print(report)
    print("\n" + "=" * 60 + "\n")

    missing = [r for r in results if not r.installed]
    critical_missing = [r for r in missing if r.is_critical]

    if critical_missing:
        print(f"⚠️  Peringatan: Terdapat {len(critical_missing)} dependensi kritis yang belum terpasang.")
        sys.exit(1)
    elif missing:
        print(f"ℹ️  Info: Terdapat {len(missing)} fitur opsional/tool tambahan yang belum terpasang.")
        sys.exit(0)
    else:
        print("✅ Seluruh tools dan dependensi faf-agent siap digunakan!")
        sys.exit(0)


if __name__ == "__main__":
    main()
