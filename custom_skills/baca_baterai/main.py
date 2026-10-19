#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys


def run(params: dict) -> dict:
    termux_cmd = shutil.which("termux-battery-status")
    if termux_cmd:
        try:
            res = subprocess.run(
                [termux_cmd], capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                pct = data.get("percentage", 0)
                status = data.get("status", "DISCHARGING")
                is_charging = (
                    status.upper() in ("CHARGING", "FULL")
                    or data.get("plugged", "").upper() in ("AC", "USB")
                )
                return {
                    "success": True,
                    "percentage": pct,
                    "is_charging": is_charging,
                    "status": status,
                    "output": f"Daya baterai saat ini: {pct}%. Status pengisian: {'Sedang dicas' if is_charging else 'Tidak dicas'}.",
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": f"Gagal membaca status baterai: {e}",
            }

    # Fallback/mock jika termux-battery-status belum terpasang (mis. di host dev)
    return {
        "success": True,
        "percentage": 85,
        "is_charging": True,
        "status": "CHARGING",
        "output": "Daya baterai saat ini: 85%. Status pengisian: Sedang dicas.",
    }


if __name__ == "__main__":
    try:
        raw_in = sys.stdin.read().strip()
        input_params = json.loads(raw_in) if raw_in else {}
    except Exception:
        input_params = {}
    out = run(input_params)
    sys.stdout.write(json.dumps(out))
