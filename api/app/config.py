"""Validated runtime configuration for browser-facing security boundaries."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class AppSettings:
    public_origin: str
    rate_limit_key: bytes
    chat_enabled: bool = False
    pdf_enabled: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.public_origin)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("IMPOSTR_PUBLIC_ORIGIN must be a valid origin") from exc

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or self.public_origin != f"{parsed.scheme}://{parsed.netloc}"
        ):
            raise ValueError("IMPOSTR_PUBLIC_ORIGIN must be a canonical HTTP origin")

        if port is not None and not 1 <= port <= 65535:
            raise ValueError("IMPOSTR_PUBLIC_ORIGIN port is outside the valid range")

        if parsed.scheme == "http":
            host = parsed.hostname.lower()
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = host == "localhost"
            if not is_loopback:
                raise ValueError("Plain HTTP is supported only for loopback development")

        if len(self.rate_limit_key) < 32:
            raise ValueError("The rate-limit key must contain at least 32 bytes")
        if type(self.pdf_enabled) is not bool:
            raise ValueError("PDF processing must be explicitly enabled or disabled")

    @property
    def secure_cookies(self) -> bool:
        return self.public_origin.startswith("https://")

    @classmethod
    def from_environment(cls) -> AppSettings:
        public_origin = os.environ.get("IMPOSTR_PUBLIC_ORIGIN")
        if not public_origin:
            app_port = os.environ.get("APP_PORT") or "8080"
            public_origin = f"http://127.0.0.1:{app_port}"

        rate_limit_key = os.environ.get("IMPOSTR_RATE_LIMIT_KEY") or os.environ.get("DB_PASSWORD")
        if not rate_limit_key:
            raise RuntimeError("IMPOSTR_RATE_LIMIT_KEY must be configured")

        pdf_flag = os.environ.get("IMPOSTR_PDF_ENABLED", "0")
        if pdf_flag not in {"0", "1"}:
            raise ValueError("IMPOSTR_PDF_ENABLED must be 0 or 1")
        return cls(
            public_origin=public_origin,
            rate_limit_key=rate_limit_key.encode("utf-8"),
            chat_enabled=os.environ.get("IMPOSTR_CHAT_ENABLED") == "1",
            pdf_enabled=pdf_flag == "1",
        )
