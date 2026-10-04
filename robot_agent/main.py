from __future__ import annotations

import logging
import time
from pathlib import Path

from .config import Settings
from .nexo_client import NexoClient
from .rm.windows_uia import WindowsRMAdapter
from .state import RobotState
from .sync_engine import SyncEngine


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = Settings.from_env()
    if not cfg.nexo_robot_token:
        raise SystemExit("Defina NEXO_ROBOT_TOKEN antes de iniciar o robô.")

    rm = WindowsRMAdapter(cfg.rm_window_title_regex)
    nexo = NexoClient(cfg.nexo_base_url, cfg.nexo_robot_token, cfg.agent_id)
    state = RobotState(Path("data") / "robot_state.db")
    engine = SyncEngine(rm, nexo, state, cfg.pdf_dir)

    while True:
        started = time.monotonic()
        try:
            engine.run_once()
        except Exception:
            logging.getLogger("nexo.robot").exception("Falha no ciclo principal")
        elapsed = time.monotonic() - started
        time.sleep(max(1, cfg.poll_seconds - elapsed))


if __name__ == "__main__":
    main()
