from __future__ import annotations

import logging
import mimetypes
import os
import re
import shlex
import shutil
import time
import urllib.parse
from typing import Any

import httpx

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.ocr")

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_INLINE_CHARS = 6000  # text longer than this is also saved to a .txt document
DEFAULT_LANG = "ind+eng"

TESSERACT_INSTALL_HINT = (
    "Tesseract OCR belum terpasang di perangkat. Pasang di Termux dengan perintah:\n"
    "pkg install tesseract\n\n"
    "Untuk akurasi teks bahasa Indonesia, pasang file traineddata bahasa Indonesia:\n"
    "curl -L -o $PREFIX/share/tessdata/ind.traineddata "
    "https://github.com/tesseract-ocr/tessdata_fast/raw/main/ind.traineddata"
)


def _find_tesseract() -> str | None:
    p = shutil.which("tesseract")
    if p:
        return p
    termux_bin = "/data/data/com.termux/files/usr/bin/tesseract"
    if os.path.exists(termux_bin) and os.access(termux_bin, os.X_OK):
        return termux_bin
    return None


async def _tesseract_langs(tess_bin: str) -> list[str]:
    res = await bridge.execute_shell(f"{shlex.quote(tess_bin)} --list-langs", timeout=10)
    out = f"{res.stdout}\n{res.stderr}"
    return [
        ln.strip()
        for ln in out.splitlines()
        if ln.strip() and not ln.lower().startswith("list of") and " " not in ln.strip()
    ]


def _resolve_lang(requested: str, installed: list[str]) -> str:
    """Keep only installed languages; fall back to eng (or first installed)."""
    wanted = [l for l in re.split(r"[+,\s]+", requested or DEFAULT_LANG) if l]
    usable = [l for l in wanted if l in installed] if installed else wanted
    if usable:
        return "+".join(usable)
    if "eng" in installed:
        return "eng"
    return installed[0] if installed else "eng"


def _clean_text(text: str) -> str:
    text = text.replace("\x0c", "").replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _validate_image(path: str) -> str | None:
    if not os.path.isfile(path):
        return f"Berkas tidak ditemukan: {path}"
    ext = os.path.splitext(path)[1].lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        return f"Format '{ext}' tidak didukung. Format yang didukung: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    size = os.path.getsize(path)
    if size == 0:
        return "Berkas gambar kosong (0 byte)."
    if size > MAX_IMAGE_BYTES:
        return f"Ukuran gambar {size / 1024 / 1024:.1f} MB melebihi batas 20 MB."
    return None


class OcrTool(BaseTool):
    """100% pure local OCR tool using offline Tesseract on Android Termux (zero LLM / zero cloud)."""

    name = "ocr_extract"
    description = (
        "Tool OCR murni lokal (100% offline lokal perangkat tanpa LLM/Cloud) untuk membaca teks "
        "dari gambar menggunakan mesin Tesseract OCR di Termux. "
        "Sumber gambar bisa berupa berkas lokal di HP (mis. /sdcard/DCIM/..., screenshot), "
        "URL gambar dari internet, atau tangkapan layar langsung (layar saat ini via root screencap). "
        "Gunakan saat pengguna meminta membaca teks dari foto, dokumen, struk belanja, screenshot, KTP, dll."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["extract", "check_engine"],
                "description": "'extract' (ambil teks dari gambar) atau 'check_engine' (cek kesiapan Tesseract lokal).",
                "default": "extract",
            },
            "source": {
                "type": "string",
                "enum": ["file", "url", "screen"],
                "description": "Sumber gambar: 'file' (path lokal), 'url' (unduh lokal lalu OCR), 'screen' (screenshot layar saat ini).",
                "default": "file",
            },
            "path": {
                "type": "string",
                "description": "Path absolut berkas gambar di perangkat (wajib jika source='file').",
            },
            "url": {
                "type": "string",
                "description": "URL gambar http/https untuk diunduh lokal lalu di-OCR (wajib jika source='url').",
            },
            "lang": {
                "type": "string",
                "description": "Kode bahasa Tesseract, gabungkan dengan '+' (default 'ind+eng'). Contoh: 'eng', 'ind', 'jpn'.",
                "default": DEFAULT_LANG,
            },
            "psm": {
                "type": "integer",
                "description": "Page Segmentation Mode Tesseract (default: 3 untuk deteksi otomatis; 6 untuk blok teks tunggal).",
                "default": 3,
            },
            "save_to": {
                "type": "string",
                "description": "Opsional: path file .txt untuk menyimpan hasil OCR. Teks panjang otomatis disimpan dan dikirim sebagai dokumen.",
            },
        },
        "required": [],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "extract").lower().strip()
        if action == "check_engine":
            return await self._check_engine()
        if action != "extract":
            return ToolResult(success=False, output="", error=f"Aksi '{action}' tidak dikenal.")

        settings = get_settings()
        source = str(kwargs.get("source") or "file").lower().strip()
        lang = str(kwargs.get("lang") or DEFAULT_LANG).strip()
        psm = int(kwargs.get("psm") or 3)

        if context.on_status_update:
            await context.on_status_update("● Menyiapkan gambar untuk OCR lokal...")

        image_path, temp_file, err = await self._prepare_image(source, kwargs, settings.temp_media_dir)
        if err:
            return ToolResult(success=False, output="", error=err)
        assert image_path is not None

        try:
            err = _validate_image(image_path)
            if err:
                return ToolResult(success=False, output="", error=err)

            # Cek ketersediaan Tesseract lokal
            tess_bin = _find_tesseract()
            if not tess_bin:
                return ToolResult(success=False, output="", error=TESSERACT_INSTALL_HINT)

            if context.cancel_event.is_set():
                return ToolResult(success=False, output="", error="Dibatalkan oleh pengguna.")

            if context.on_status_update:
                await context.on_status_update("● Memproses OCR secara lokal dengan Tesseract...")

            text, used_engine, err = await self._ocr_tesseract(tess_bin, image_path, lang, psm)
            if err:
                return ToolResult(success=False, output="", error=err)

            return self._build_result(text, used_engine, image_path, source, kwargs, settings.temp_media_dir)
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Image acquisition (Local)
    # ------------------------------------------------------------------
    async def _prepare_image(
        self, source: str, kwargs: dict[str, Any], temp_dir: str
    ) -> tuple[str | None, str | None, str | None]:
        """Return (image_path, temp_file_to_cleanup, error)."""
        if source == "file":
            path = str(kwargs.get("path") or "").strip()
            if not path:
                return None, None, "Parameter 'path' wajib diisi untuk source='file'."
            return os.path.expanduser(path), None, None

        if source not in ("url", "screen"):
            return None, None, f"Source '{source}' tidak dikenal. Gunakan file, url, atau screen."

        url = str(kwargs.get("url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        if source == "url" and (parsed.scheme not in ("http", "https") or not parsed.netloc):
            return None, None, f"URL tidak valid: '{url}'. Gunakan http:// atau https://."

        try:
            os.makedirs(temp_dir, exist_ok=True)
        except OSError as e:
            return None, None, f"Gagal membuat folder sementara '{temp_dir}': {e}"
        stamp = int(time.time() * 1000)

        if source == "url":
            ext = os.path.splitext(parsed.path)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                ext = ".img"
            dest = os.path.join(temp_dir, f"ocr_{stamp}{ext}")
            try:
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    async with client.stream("GET", url) as res:
                        if res.status_code != 200:
                            return None, None, f"Gagal mengunduh gambar (HTTP {res.status_code})."
                        ctype = res.headers.get("content-type", "")
                        if ctype and not ctype.startswith("image/"):
                            return None, None, f"URL bukan gambar (content-type: {ctype})."
                        total = 0
                        with open(dest, "wb") as f:
                            async for chunk in res.aiter_bytes():
                                total += len(chunk)
                                if total > MAX_IMAGE_BYTES:
                                    raise ValueError("Gambar melebihi batas 20 MB.")
                                f.write(chunk)
                if ext == ".img":
                    guessed = mimetypes.guess_extension(ctype.split(";")[0].strip()) if ctype else None
                    if guessed:
                        new_dest = dest[:-4] + guessed
                        os.replace(dest, new_dest)
                        dest = new_dest
            except Exception as e:
                if os.path.exists(dest):
                    os.remove(dest)
                return None, None, f"Gagal mengunduh gambar: {e}"
            return dest, dest, None

        # source == "screen"
        dest = os.path.join(temp_dir, f"ocr_screen_{stamp}.png")
        res = await bridge.execute_shell(f"screencap -p {shlex.quote(dest)}", as_root=True, timeout=15)
        if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
            return None, None, (
                "Gagal mengambil tangkapan layar (butuh akses root). "
                f"Detail: {(res.stderr or res.stdout)[:200]}"
            )
        return dest, dest, None

    # ------------------------------------------------------------------
    # 100% Local Tesseract Engine
    # ------------------------------------------------------------------
    async def _ocr_tesseract(
        self, tess_bin: str, image_path: str, lang: str, psm: int = 3
    ) -> tuple[str, str, str | None]:
        installed = await _tesseract_langs(tess_bin)
        use_lang = _resolve_lang(lang, installed)
        cmd = (
            f"{shlex.quote(tess_bin)} {shlex.quote(image_path)} stdout "
            f"-l {shlex.quote(use_lang)} --psm {psm}"
        )
        res = await bridge.execute_shell(cmd, timeout=120)
        if res.returncode != 0:
            return "", f"Tesseract ({use_lang})", f"Tesseract gagal: {(res.stderr or res.stdout)[:300]}"
        return _clean_text(res.stdout), f"Tesseract ({use_lang})", None

    # ------------------------------------------------------------------
    # Output formatting
    # ------------------------------------------------------------------
    def _build_result(
        self,
        text: str,
        used_engine: str,
        image_path: str,
        source: str,
        kwargs: dict[str, Any],
        temp_dir: str,
    ) -> ToolResult:
        if not text:
            return ToolResult(
                success=True,
                output=(
                    f"OCR selesai secara lokal dengan {used_engine}, tetapi tidak ada teks yang terdeteksi.\n"
                    "Saran: pastikan gambar cukup terang dan tajam, atau coba sesuaikan mode psm (misal psm=6 untuk satu blok teks)."
                ),
            )

        save_to = str(kwargs.get("save_to") or "").strip()
        if not save_to and len(text) > MAX_INLINE_CHARS:
            save_to = os.path.join(temp_dir, f"ocr_result_{int(time.time())}.txt")

        saved_path: str | None = None
        if save_to:
            try:
                save_to = os.path.expanduser(save_to)
                os.makedirs(os.path.dirname(save_to) or ".", exist_ok=True)
                with open(save_to, "w", encoding="utf-8") as f:
                    f.write(text)
                saved_path = save_to
            except OSError as e:
                logger.warning("Failed to save OCR result: %s", e)

        src_label = {"file": image_path, "url": kwargs.get("url", ""), "screen": "layar perangkat"}.get(source, source)
        shown = text if len(text) <= MAX_INLINE_CHARS else text[:MAX_INLINE_CHARS] + "\n...(dipotong, teks lengkap ada di berkas)"
        header = (
            f"Hasil OCR (100% Lokal)\n"
            f"• Sumber: {src_label}\n"
            f"• Mesin: {used_engine}\n"
            f"• Jumlah karakter: {len(text)}\n"
        )
        if saved_path:
            header += f"• Disimpan ke: {saved_path}\n"

        return ToolResult(
            success=True,
            output=f"{header}\n--- TEKS ---\n{shown}",
            media_path=saved_path,
            media_type="document" if saved_path else None,
        )

    async def _check_engine(self) -> ToolResult:
        lines = ["Status Engine OCR (100% Lokal):"]
        tess_bin = _find_tesseract()
        if tess_bin:
            ver = await bridge.execute_shell(f"{shlex.quote(tess_bin)} --version", timeout=10)
            ver_line = (ver.stdout or ver.stderr).splitlines()[0] if (ver.stdout or ver.stderr) else "?"
            langs = await _tesseract_langs(tess_bin)
            lines.append(f"• Tesseract: TERPASANG ({ver_line})")
            lines.append(f"• Lokasi binary: {tess_bin}")
            lines.append(f"• Model bahasa terpasang: {', '.join(langs) or 'Belum ada model bahasa terdeteksi'}")
            if "ind" not in langs:
                lines.append(
                    "• Perhatian: Model bahasa Indonesia ('ind') belum terpasang. Disarankan mengunduh ind.traineddata."
                )
            return ToolResult(success=True, output="\n".join(lines))
        else:
            lines.append("• Tesseract: BELUM TERPASANG")
            lines.append(f"\n{TESSERACT_INSTALL_HINT}")
            return ToolResult(success=False, output="\n".join(lines), error=TESSERACT_INSTALL_HINT)
