from __future__ import annotations

import logging
import pathlib
from typing import Any

from src.custom_skills.manifest import SkillManifest
from src.custom_skills.runner import SkillRunner
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.custom_skill_adapter")


class CustomSkillToolAdapter(BaseTool):
    """Adapter wrapping an active custom skill into a native BaseTool."""

    def __init__(self, manifest: SkillManifest, skill_dir: pathlib.Path) -> None:
        self.manifest = manifest
        self.skill_dir = skill_dir
        self.name = manifest.name
        self.description = f"[Custom Skill] {manifest.description}"
        self.parameters = manifest.parameters
        self.runner = SkillRunner(manifest=manifest, skill_dir=skill_dir)

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute custom skill script via SkillRunner with AST security and resource isolation."""
        res = await self.runner.execute(arguments=kwargs, user_id=context.user_id)
        return ToolResult(
            success=res.success,
            output=res.output or (res.error if not res.success else ""),
            error=res.error,
        )
