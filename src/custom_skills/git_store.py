from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import shutil
from typing import Any

from src.config import get_settings

logger = logging.getLogger("faf_agent.custom_skills.git_store")


class SkillGitStore:
    """Manages local git version control for custom_skills/ directory."""

    def __init__(self, skills_dir: str | pathlib.Path | None = None) -> None:
        self.settings = get_settings()
        self.skills_dir = pathlib.Path(skills_dir or self.settings.custom_skills_dir).resolve()
        self.git_bin = shutil.which("git") or "git"

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        """Execute git command within skills_dir."""
        proc = await asyncio.create_subprocess_exec(
            self.git_bin,
            *args,
            cwd=str(self.skills_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )

    async def ensure_git_repo(self) -> bool:
        """Initialize git repository in skills_dir if not already present."""
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        git_folder = self.skills_dir / ".git"
        if git_folder.exists() and git_folder.is_dir():
            return True

        logger.info(f"Inisialisasi git repository lokal di {self.skills_dir}")
        code, out, err = await self._run_git("init")
        if code != 0:
            logger.error(f"git init failed: {err}")
            return False

        await self._run_git("config", "user.name", "faf-agent")
        await self._run_git("config", "user.email", "faf-agent@local")
        await self._run_git(
            "commit", "--allow-empty", "-m", "chore: initialize custom skills repository"
        )
        return True

    async def commit_skill(self, skill_name: str, message: str) -> str:
        """Stage and commit changes for a specific skill. Returns commit hash or empty string on failure."""
        await self.ensure_git_repo()

        skill_path = self.skills_dir / skill_name
        if not skill_path.exists():
            logger.warning(f"Skill directory {skill_path} does not exist to commit.")
            return ""

        # git add <skill_name>
        code, out, err = await self._run_git("add", skill_name)
        if code != 0:
            logger.error(f"git add failed for {skill_name}: {err}")
            return ""

        # git commit -m <message>
        code, out, err = await self._run_git("commit", "-m", message)
        if code != 0:
            if "nothing to commit" in out or "nothing to commit" in err:
                logger.debug(f"Nothing to commit for {skill_name}")
                code_rev, out_rev, _ = await self._run_git("rev-parse", "HEAD")
                return out_rev if code_rev == 0 else ""
            logger.error(f"git commit failed for {skill_name}: {err}")
            return ""

        # Get latest commit hash
        code_rev, out_rev, _ = await self._run_git("rev-parse", "HEAD")
        return out_rev if code_rev == 0 else ""

    async def rollback_skill(self, skill_name: str, commit_ref: str = "HEAD~1") -> bool:
        """Rollback skill files to a previous commit reference."""
        await self.ensure_git_repo()

        code, out, err = await self._run_git("checkout", commit_ref, "--", skill_name)
        if code != 0:
            logger.error(f"git checkout {commit_ref} failed for {skill_name}: {err}")
            return False

        # Commit the reverted state
        await self._run_git("add", skill_name)
        await self._run_git(
            "commit",
            "-m",
            f"revert(skill): rollback {skill_name} to {commit_ref}",
        )
        logger.info(f"Skill '{skill_name}' berhasil di-rollback ke {commit_ref}")
        return True

    async def get_history(self, skill_name: str, limit: int = 5) -> list[dict[str, str]]:
        """Retrieve commit log history for a specific skill."""
        await self.ensure_git_repo()

        code, out, err = await self._run_git(
            "log",
            f"-n{limit}",
            "--pretty=format:%H|%an|%ad|%s",
            "--date=short",
            "--",
            skill_name,
        )
        if code != 0 or not out:
            return []

        entries: list[dict[str, str]] = []
        for line in out.splitlines():
            parts = line.strip().split("|", 3)
            if len(parts) == 4:
                entries.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "subject": parts[3],
                })
        return entries


# Default singleton instance
skill_git_store = SkillGitStore()
