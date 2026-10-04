from __future__ import annotations

from pathlib import Path
import requests


class NexoClient:
    def __init__(self, base_url: str, token: str, agent_id: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "X-NEXO-Agent-ID": agent_id,
            "User-Agent": "NEXO-Robot-Agent/0.1",
        })

    def _ok(self, response: requests.Response) -> dict:
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError(data.get("message") or "NEXO recusou a operação")
        return data

    def heartbeat(self, *, visible_orders: int, last_error: str = "") -> None:
        self._ok(self.session.post(
            f"{self.base_url}/api/robot/v1/heartbeat",
            json={"visible_orders": visible_orders, "last_error": last_error},
            timeout=self.timeout,
        ))

    def missing_orders(self, order_numbers: list[str]) -> list[str]:
        data = self._ok(self.session.post(
            f"{self.base_url}/api/robot/v1/orders/check",
            json={"order_numbers": order_numbers},
            timeout=self.timeout,
        ))
        return [str(x) for x in data.get("missing", [])]

    def upload_pdf(self, order_number: str, pdf_path: Path, sha256: str) -> dict:
        with Path(pdf_path).open("rb") as handle:
            response = self.session.post(
                f"{self.base_url}/api/robot/v1/orders/{order_number}/pdf",
                data={"sha256": sha256},
                files={"arquivo": (Path(pdf_path).name, handle, "application/pdf")},
                timeout=max(self.timeout, 90),
            )
        return self._ok(response)
