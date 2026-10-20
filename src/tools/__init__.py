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
from src.tools.device_interaction import DeviceInteractionTool
from src.tools.reminder_mgr import ReminderManagerTool
from src.tools.web_screenshot import WebScreenshotTool
from src.tools.media_downloader import MediaDownloaderTool
from src.tools.ocr import OcrTool
from src.tools.web_search import WebSearchTool
from src.tools.memory_mgr import MemoryManagerTool
from src.tools.python_repl import PythonReplTool
from src.tools.clarification import ClarificationTool
from src.tools.cronjob_mgr import CronJobTool
from src.tools.weather_mgr import WeatherForecastTool
from src.tools.pdf_mgr import PDFManagerTool
from src.tools.skill_maker import CreateCustomSkillTool
from src.tools.code_to_image import CodeToImageTool


def create_default_registry() -> ToolRegistry:
    """Create and populate the default tool registry with all Android tools."""
    registry = ToolRegistry()
    registry.register(ClarificationTool())
    registry.register(CreateCustomSkillTool())
    registry.register(RootShellExecTool())
    registry.register(SystemSettingsTool())
    registry.register(ProductivityControlTool())
    registry.register(MediaControlTool())
    registry.register(PackageManagerTool())
    registry.register(ProcessManagerTool())
    registry.register(TimeManagerTool())
    registry.register(FileManagerTool())
    registry.register(PDFManagerTool())
    registry.register(DeviceInteractionTool())
    registry.register(ReminderManagerTool())
    registry.register(CronJobTool())
    registry.register(WeatherForecastTool())
    registry.register(WebScreenshotTool())
    registry.register(MediaDownloaderTool())
    registry.register(OcrTool())
    registry.register(WebSearchTool())
    registry.register(MemoryManagerTool())
    registry.register(PythonReplTool())
    registry.register(CodeToImageTool())
    return registry


# Global default registry
default_registry = create_default_registry()

__all__ = [
    "BaseTool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "ClarificationTool",
    "CreateCustomSkillTool",
    "RootShellExecTool",
    "SystemSettingsTool",
    "ProductivityControlTool",
    "MediaControlTool",
    "PackageManagerTool",
    "ProcessManagerTool",
    "TimeManagerTool",
    "FileManagerTool",
    "PDFManagerTool",
    "DeviceInteractionTool",
    "ReminderManagerTool",
    "CronJobTool",
    "WeatherForecastTool",
    "WebScreenshotTool",
    "MediaDownloaderTool",
    "OcrTool",
    "WebSearchTool",
    "MemoryManagerTool",
    "PythonReplTool",
    "CodeToImageTool",
    "create_default_registry",
    "default_registry",
]


