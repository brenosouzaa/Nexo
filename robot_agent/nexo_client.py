from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests


class NexoClient:
    def __init__(self, base_url: str, token: str, agent_id: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.secret = token.encode("utf-8")
        self.agent_id = agent_id
        if len(self.secret) < 32:
            raise ValueError("NEXO_ROBOT_TOKEN precisa ter pelo menos 32 caracteres.")
        self.session = requests.Session()
        self.session.headers.update({
            "X-NEXO-Agent-ID": agent_id,
            "User-Agent": "NEXO-Robot-Agent/0.2",
        })

    @staticmethod
    def _canonical_json(payload: dict) -> bytes:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def _signed_headers(self, method: str, url: str, content_sha256: str) -> dict[str, str]:
        path = urlsplit(url).path
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        nonce = secrets.token_urlsafe(24)
        message = "\n".join([method.upper(), path, timestamp, nonce, content_sha256]).encode("utf-8")
        signature = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        return {
            "X-NEXO-Timestamp": timestamp,
            "X-NEXO-Nonce": nonce,
            "X-NEXO-Content-SHA256": content_sha256,
            "X-NEXO-Signature": signature,
        }

    def _post_json(self, path: str, payload: dict) -> requests.Response:
        url = f"{self.base_url}{path}"
        body = self._canonical_json(payload)
        digest = hashlib.sha256(body).hexdigest()
        headers = {
            "Content-Type": "application/json",
            **self._signed_headers("POST", url, digest),
        }
        return self.session.post(url, data=body, headers=headers, timeout=self.timeout)

    def _ok(self, response: requests.Response) -> dict:
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError(data.get("message") or "NEXO recusou a operação")
        return data

    def heartbeat(self, *, visible_orders: int, last_error: str = "") -> None:
        self._ok(self._post_json(
            "/api/robot/v1/heartbeat",
            {"visible_orders": visible_orders, "last_error": last_error},
        ))

    def missing_orders(self, order_numbers: list[str]) -> list[str]:
        data = self._ok(self._post_json(
            "/api/robot/v1/orders/check",
            {"order_numbers": order_numbers},
        ))
        return [str(x) for x in data.get("missing", [])]

    def upload_pdf(self, order_number: str, pdf_path: Path, sha256: str) -> dict:
        path = f"/api/robot/v1/orders/{order_number}/pdf"
        url = f"{self.base_url}{path}"
        headers = self._signed_headers("POST", url, sha256)
        with Path(pdf_path).open("rb") as handle:
            response = self.session.post(
                url,
                headers=headers,
                data={"sha256": sha256},
                files={"arquivo": (Path(pdf_path).name, handle, "application/pdf")},
                timeout=max(self.timeout, 90),
            )
        return self._ok(response)
