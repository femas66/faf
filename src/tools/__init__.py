from __future__ import annotations

from src.tools.base import BaseTool, ToolContext, ToolResult, ToolRegistry
from src.tools.root_exec import RootShellExecTool
from src.tools.system import SystemSettingsTool
from src.tools.productivity import ProductivityControlTool
from src.tools.media import MediaControlTool
from src.tools.package_mgr import PackageManagerTool
from src.tools.process_mgr import ProcessManagerTool
from src.tools.time_mgr import TimeManagerTool
from src.tools.file_mgr import FileManagerTool


def create_default_registry() -> ToolRegistry:
    """Create and populate the default tool registry with all Android tools."""
    registry = ToolRegistry()
    registry.register(RootShellExecTool())
    registry.register(SystemSettingsTool())
    registry.register(ProductivityControlTool())
    registry.register(MediaControlTool())
    registry.register(PackageManagerTool())
    registry.register(ProcessManagerTool())
    registry.register(TimeManagerTool())
    registry.register(FileManagerTool())
    return registry


# Global default registry
default_registry = create_default_registry()

__all__ = [
    "BaseTool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "RootShellExecTool",
    "SystemSettingsTool",
    "ProductivityControlTool",
    "MediaControlTool",
    "PackageManagerTool",
    "ProcessManagerTool",
    "TimeManagerTool",
    "FileManagerTool",
    "create_default_registry",
    "default_registry",
]
