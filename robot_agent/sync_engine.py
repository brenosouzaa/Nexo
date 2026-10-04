from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .state import RobotState

log = logging.getLogger("nexo.robot")


def normalize_order_number(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip() if ch.isdigit())


def pdf_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(path: Path) -> None:
    path = Path(path)
    if not path.exists() or path.stat().st_size < 100:
        raise ValueError("PDF não foi gerado ou está vazio")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError("Arquivo gerado não é um PDF válido")


class SyncEngine:
    def __init__(self, rm, nexo, state: RobotState, pdf_dir: Path):
        self.rm = rm
        self.nexo = nexo
        self.state = state
        self.pdf_dir = Path(pdf_dir)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> dict:
        visible = sorted({
            normalize_order_number(x)
            for x in self.rm.refresh_and_list_order_numbers()
            if normalize_order_number(x)
        })
        missing = self.nexo.missing_orders(visible)
        result = {"visible": len(visible), "missing": len(missing), "sent": [], "failed": []}

        for order_number in missing:
            try:
                self.state.mark(order_number, "EXPORTANDO")
                pdf = self.rm.export_order_pdf(order_number, self.pdf_dir)
                validate_pdf(pdf)
                digest = pdf_sha256(pdf)
                self.state.mark(order_number, "ENVIANDO", pdf_path=str(pdf), sha256=digest)
                response = self.nexo.upload_pdf(order_number, pdf, digest)
                self.state.mark(order_number, "CONFIRMADO", pdf_path=str(pdf), sha256=digest)
                result["sent"].append({"order_number": order_number, "response": response})
            except Exception as exc:
                self.state.mark(order_number, "ERRO", error=str(exc))
                result["failed"].append({"order_number": order_number, "error": str(exc)})
                log.exception("Falha no pedido %s", order_number)

        error_text = "; ".join(f"{x['order_number']}: {x['error']}" for x in result["failed"][:3])
        self.nexo.heartbeat(visible_orders=len(visible), last_error=error_text)
        return result
