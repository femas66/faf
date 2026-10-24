"""Helper HTTP aman (anti-SSRF, batas ukuran, validasi tiap redirect) untuk tool riset & digest."""
from __future__ import annotations

import asyncio
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from src.tools.web_search import _check_url_safety

_REDIRECT_CODES = (301, 302, 303, 307, 308)
DEFAULT_USER_AGENT = "faf-agent/1.0 (+personal research assistant)"


class UnsafeURLError(ValueError):
    """URL ditolak oleh pemeriksaan keamanan SSRF."""


class ResponseTooLargeError(ValueError):
    """Respons melebihi batas ukuran yang diizinkan."""


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    max_redirects: int = 3,
    cancel_event: asyncio.Event | None = None,
) -> tuple[bytes, httpx.Headers, str]:
    """GET dengan validasi SSRF pada setiap hop redirect dan batas ukuran streaming.

    Mengembalikan (body, response_headers, final_url).
    Melempar UnsafeURLError, ResponseTooLargeError, atau httpx.HTTPError.
    """
    merged_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        merged_headers.update(headers)

    current = url
    current_params = params
    for _ in range(max_redirects + 1):
        ok, msg, _ = _check_url_safety(current)
        if not ok:
            raise UnsafeURLError(msg)

        async with client.stream(
            "GET",
            current,
            params=current_params,
            headers=merged_headers,
            follow_redirects=False,
        ) as resp:
            if resp.status_code in _REDIRECT_CODES:
                location = resp.headers.get("location")
                if not location:
                    raise ValueError("Redirect tanpa header Location.")
                current = urllib.parse.urljoin(current, location)
                current_params = None
                continue

            resp.raise_for_status()

            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise ResponseTooLargeError(
                    f"Ukuran respons {int(declared)} byte melebihi batas {max_bytes} byte."
                )

            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError()
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise ResponseTooLargeError(
                        f"Ukuran respons melebihi batas {max_bytes} byte."
                    )
            return bytes(buf), resp.headers, current

    raise ValueError("Terlalu banyak redirect.")


def parse_xml_safely(data: bytes) -> ET.Element:
    """Parse XML dengan menolak deklarasi ENTITY (mencegah entity-expansion attack)."""
    if b"<!entity" in data.lower():
        raise ValueError("XML ditolak: memuat deklarasi ENTITY.")
    return ET.fromstring(data)
