from __future__ import annotations

import logging
from typing import Any

from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.clarification")


class ClarificationTool(BaseTool):
    """Tool khusus untuk meminta klarifikasi kepada pengguna jika instruksi ambigu atau kurang lengkap."""

    name = "ask_clarification"
    description = (
        "WAJIB digunakan jika instruksi atau permintaan pengguna memiliki ambiguitas, "
        "kekurangan parameter esensial (seperti lokasi/folder berkas yang belum ditentukan, "
        "target entitas tidak spesifik, atau waktu/jadwal yang belum pasti), atau "
        "memiliki beberapa kemungkinan interpretasi yang berbeda. "
        "Tool ini akan mengajukan pertanyaan yang jelas, lugas, to the point, dan tidak bertele-tele."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "Pertanyaan klarifikasi yang singkat, jelas, langsung ke inti pokok permasalahan, "
                    "dan tidak bertele-tele."
                ),
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Daftar pilihan opsi jawaban singkat untuk memudahkan pengguna memilih di layar ponsel (opsional)."
                ),
            },
        },
        "required": ["question"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        question = kwargs.get("question", "").strip()
        options = kwargs.get("options") or []

        if not question:
            return ToolResult(
                success=False,
                output="",
                error="Parameter 'question' tidak boleh kosong untuk ask_clarification.",
            )

        output_lines = [question]
        if options:
            output_lines.append("")
            output_lines.append("Pilihan:")
            for opt in options:
                opt_str = str(opt).strip()
                if opt_str:
                    output_lines.append(f"• {opt_str}")

        formatted_output = "\n".join(output_lines)
        logger.info(f"Clarification question generated: {question}")

        return ToolResult(
            success=True,
            output=formatted_output,
        )
