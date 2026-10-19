#!/usr/bin/env python3
import json
import sys


def run(params: dict) -> dict:
    try:
        harga = float(params.get("harga", 0))
        diskon = float(params.get("diskon_persen", 0))

        if harga < 0 or diskon < 0:
            return {
                "success": False,
                "error": "Harga atau diskon tidak boleh bernilai negatif.",
                "output": "Gagal: Nilai harga atau diskon tidak boleh negatif.",
            }

        if diskon > 100:
            return {
                "success": False,
                "error": "Diskon tidak boleh lebih dari 100%.",
                "output": "Gagal: Nilai diskon maksimal 100%.",
            }

        potongan = harga * (diskon / 100.0)
        harga_akhir = harga - potongan

        return {
            "success": True,
            "harga_awal": harga,
            "diskon_persen": diskon,
            "potongan": potongan,
            "harga_akhir": harga_akhir,
            "output": (
                f"Harga awal: Rp {harga:,.0f}\n"
                f"Diskon: {diskon}%\n"
                f"Potongan: Rp {potongan:,.0f}\n"
                f"Total bayar: Rp {harga_akhir:,.0f}"
            ),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "output": f"Terjadi kesalahan kalkulasi diskon: {e}",
        }


if __name__ == "__main__":
    try:
        raw_in = sys.stdin.read().strip()
        input_params = json.loads(raw_in) if raw_in else {}
    except Exception:
        input_params = {}
    out = run(input_params)
    sys.stdout.write(json.dumps(out))
