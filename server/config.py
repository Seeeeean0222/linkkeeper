"""Application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8792
    workers: int = 10
    timeout_seconds: float = 7.0
    max_bookmarks: int = 300

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("LINK_KEEPER_HOST", "127.0.0.1"),
            port=int(os.getenv("LINK_KEEPER_PORT", "8792")),
            workers=max(1, min(24, int(os.getenv("LINK_KEEPER_WORKERS", "10")))),
            timeout_seconds=max(
                1.0, min(20.0, float(os.getenv("LINK_KEEPER_TIMEOUT", "7")))
            ),
            max_bookmarks=max(
                1, min(1000, int(os.getenv("LINK_KEEPER_MAX_BOOKMARKS", "300")))
            ),
        )
