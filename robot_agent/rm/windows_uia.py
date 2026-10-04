from __future__ import annotations

import time
from pathlib import Path
from pywinauto import Desktop


class WindowsRMAdapter:
    """Adaptador real do TOTVS RM via Windows UI Automation.

    Os seletores exatos serão mapeados na VM real. A arquitetura evita
    coordenadas fixas de mouse sempre que o RM expuser controles acessíveis.
    """

    def __init__(self, window_title_regex: str):
        self.window_title_regex = window_title_regex

    def _window(self):
        window = Desktop(backend="uia").window(title_re=self.window_title_regex)
        window.wait("visible enabled ready", timeout=20)
        return window

    def refresh_and_list_order_numbers(self) -> list[str]:
        window = self._window()
        try:
            window.type_keys("{F5}")
            time.sleep(2)
        except Exception:
            pass
        raise NotImplementedError("Mapear o grid real de pedidos do TOTVS RM na VM")

    def export_order_pdf(self, order_number: str, destination_dir: Path) -> Path:
        raise NotImplementedError("Mapear a geração do PDF original no TOTVS RM")
