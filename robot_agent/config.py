from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    nexo_base_url: str
    nexo_robot_token: str
    agent_id: str
    poll_seconds: int
    pdf_dir: Path
    rm_window_title_regex: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            nexo_base_url=os.getenv("NEXO_BASE_URL", "http://127.0.0.1:8785").rstrip("/"),
            nexo_robot_token=os.getenv("NEXO_ROBOT_TOKEN", ""),
            agent_id=os.getenv("NEXO_ROBOT_AGENT_ID", "rm-principal-01"),
            poll_seconds=max(10, int(os.getenv("NEXO_POLL_SECONDS", "120"))),
            pdf_dir=Path(os.getenv("NEXO_PDF_DIR", r"C:\NEXO-Robot\pdfs")),
            rm_window_title_regex=os.getenv("RM_WINDOW_TITLE_REGEX", r".*TOTVS.*RM.*"),
        )
