from __future__ import annotations

import logging
from typing import Any

from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.skill_maker")


class CreateCustomSkillTool(BaseTool):
    """Tool enabling the agent to iteratively create, validate, and propose new custom skills."""

    name = "create_custom_skill"
    description = (
        "Menghasilkan dan menguji modul skill Python baru di lingkungan terisolasi "
        "saat pengguna meminta kemampuan baru atau belum ada tool yang sesuai. "
        "Skill yang berhasil lolos analisis statis AST dan pengujian otomatis "
        "akan diajukan ke pengguna untuk mendapatkan persetujuan eksplisit sebelum aktif."
    )
    parameters = {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "Deskripsi spesifik fungsi, input, dan tujuan skill yang ingin dibuat",
            }
        },
        "required": ["request"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        from src.custom_skills.pipeline import skill_pipeline
        req = str(kwargs.get("request", "")).strip()
        if not req:
            return ToolResult(
                success=False,
                output="",
                error="Parameter 'request' wajib diisi untuk membuat skill baru.",
            )

        if context.on_status_update:
            await context.on_status_update("🛠️ Merancang kode skill dan menjalankan pengujian terisolasi...")

        success, summary_or_err, proposal = await skill_pipeline.create_skill(
            prompt_request=req,
            chat_id=context.chat_id,
            user_id=context.user_id,
            max_iterations=3,
        )

        if not success:
            return ToolResult(
                success=False,
                output=summary_or_err,
                error=summary_or_err,
            )

        return ToolResult(
            success=True,
            output=summary_or_err,
        )
