from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from .storage import CsvStore

robot_api_bp = Blueprint("robot_api", __name__, url_prefix="/api/robot/v1")

MAX_CLOCK_SKEW_SECONDS = 120
NONCE_TTL_SECONDS = 300


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_order_number(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip() if ch.isdigit())


def main_store() -> CsvStore:
    return CsvStore(current_app.config["NEXO_DATA"])


class RobotGatewayStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "robot_gateway.db"
        self.inbox = self.data_dir / "robot_inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    last_seen TEXT NOT NULL,
                    visible_orders INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS imports (
                    order_number TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pdf_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS request_nonces (
                    nonce TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_request_nonces_expiry
                    ON request_nonces(expires_at);
            """)
            con.commit()

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def heartbeat(self, agent_id: str, visible_orders: int, last_error: str):
        with self._connect() as con:
            con.execute("""
                INSERT INTO agents(agent_id,last_seen,visible_orders,last_error)
                VALUES(?,?,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    visible_orders=excluded.visible_orders,
                    last_error=excluded.last_error
            """, (agent_id, now_utc(), visible_orders, last_error[:2000]))
            con.commit()

    def use_nonce(self, nonce: str, agent_id: str) -> bool:
        now = datetime.now(timezone.utc)
        expires = datetime.fromtimestamp(now.timestamp() + NONCE_TTL_SECONDS, timezone.utc).isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute("DELETE FROM request_nonces WHERE expires_at <= ?", (now.isoformat(timespec="seconds"),))
            try:
                con.execute(
                    "INSERT INTO request_nonces(nonce,agent_id,expires_at,created_at) VALUES(?,?,?,?)",
                    (nonce, agent_id, expires, now.isoformat(timespec="seconds")),
                )
                con.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def known_orders(self) -> set[str]:
        with self._connect() as con:
            rows = con.execute("SELECT order_number FROM imports WHERE status <> 'CANCELADO'").fetchall()
        return {str(row[0]) for row in rows}

    def get_import(self, order_number: str) -> dict | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM imports WHERE order_number = ?", (order_number,)).fetchone()
        return dict(row) if row else None

    def register_import(self, order_number: str, pdf_path: Path, sha256: str, agent_id: str):
        stamp = now_utc()
        import_id = uuid.uuid4().hex
        with self._connect() as con:
            con.execute("""
                INSERT INTO imports(order_number,import_id,status,pdf_path,sha256,agent_id,received_at,updated_at,error)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (order_number, import_id, "RECEBIDO", str(pdf_path), sha256, agent_id, stamp, stamp, ""))
            con.commit()
        return import_id


def gateway() -> RobotGatewayStore:
    return RobotGatewayStore(current_app.config["NEXO_DATA"])


def _configured_secret() -> bytes:
    token = os.environ.get("NEXO_ROBOT_TOKEN", "").strip()
    if not token:
        cfg = current_app.config.get("NEXO_CONFIG", {})
        token = str((cfg.get("robot_api") or {}).get("token") or "").strip()
    return token.encode("utf-8")


def _agent_id() -> str:
    return (request.headers.get("X-NEXO-Agent-ID") or "").strip()[:100]


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _require_robot():
    secret = _configured_secret()
    agent_id = _agent_id()
    timestamp = str(request.headers.get("X-NEXO-Timestamp") or "")
    nonce = str(request.headers.get("X-NEXO-Nonce") or "")
    declared_sha = str(request.headers.get("X-NEXO-Content-SHA256") or "").lower()
    supplied_signature = str(request.headers.get("X-NEXO-Signature") or "").lower()

    if len(secret) < 32 or not agent_id or not timestamp or not nonce or not declared_sha or not supplied_signature:
        return jsonify(ok=False, message="Robô não autorizado."), 401
    if len(nonce) < 16 or len(nonce) > 128:
        return jsonify(ok=False, message="Requisição do robô inválida."), 401

    parsed = _parse_timestamp(timestamp)
    if not parsed or abs((datetime.now(timezone.utc) - parsed).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
        return jsonify(ok=False, message="Requisição do robô expirada."), 401

    if request.mimetype != "multipart/form-data":
        actual_body_sha = hashlib.sha256(request.get_data(cache=True)).hexdigest()
        if not hmac.compare_digest(actual_body_sha, declared_sha):
            return jsonify(ok=False, message="Integridade da requisição inválida."), 401

    message = "\n".join([
        request.method.upper(),
        request.path,
        timestamp,
        nonce,
        declared_sha,
    ]).encode("utf-8")
    expected_signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, supplied_signature):
        return jsonify(ok=False, message="Robô não autorizado."), 401

    if not gateway().use_nonce(nonce, agent_id):
        return jsonify(ok=False, message="Requisição repetida bloqueada."), 409
    return None


@robot_api_bp.post("/heartbeat")
def heartbeat():
    guard = _require_robot()
    if guard:
        return guard
    payload = request.get_json(silent=True) or {}
    gateway().heartbeat(_agent_id(), int(payload.get("visible_orders") or 0), str(payload.get("last_error") or ""))
    return jsonify(ok=True, status="ONLINE", server_time=now_utc())


@robot_api_bp.post("/orders/check")
def check_orders():
    guard = _require_robot()
    if guard:
        return guard
    payload = request.get_json(silent=True) or {}
    raw = payload.get("order_numbers") or []
    if not isinstance(raw, list):
        return jsonify(ok=False, message="order_numbers deve ser uma lista."), 400

    requested = []
    seen = set()
    for value in raw[:5000]:
        number = normalize_order_number(value)
        if number and number not in seen:
            seen.add(number)
            requested.append(number)

    nexo_orders = {str(row.get("pedido", "")) for row in main_store().read("pedidos.csv") if row.get("pedido")}
    known = nexo_orders | gateway().known_orders()
    return jsonify(
        ok=True,
        existing=[n for n in requested if n in known],
        missing=[n for n in requested if n not in known],
    )


@robot_api_bp.post("/orders/<order_number>/pdf")
def upload_pdf(order_number: str):
    guard = _require_robot()
    if guard:
        return guard

    order_number = normalize_order_number(order_number)
    if not order_number:
        return jsonify(ok=False, message="Número do pedido inválido."), 400

    if any(row.get("pedido") == order_number for row in main_store().read("pedidos.csv")):
        return jsonify(ok=True, status="JA_EXISTE", order_number=order_number)

    uploaded = request.files.get("arquivo")
    if not uploaded or not uploaded.filename:
        return jsonify(ok=False, message="Envie o PDF no campo arquivo."), 400
    if Path(secure_filename(uploaded.filename)).suffix.lower() != ".pdf":
        return jsonify(ok=False, message="Somente PDF é aceito."), 400

    g = gateway()
    previous = g.get_import(order_number)
    fd, temp_name = tempfile.mkstemp(prefix=f"nexo_{order_number}_", suffix=".pdf", dir=g.inbox)
    os.close(fd)
    temp_path = Path(temp_name)

    try:
        digest = hashlib.sha256()
        total = 0
        with temp_path.open("wb") as out:
            while True:
                chunk = uploaded.stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 25 * 1024 * 1024:
                    return jsonify(ok=False, message="PDF excede 25 MB."), 413
                digest.update(chunk)
                out.write(chunk)

        with temp_path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return jsonify(ok=False, message="Arquivo recebido não é PDF válido."), 400

        actual_sha = digest.hexdigest()
        declared_form = str(request.form.get("sha256") or "").lower()
        declared_header = str(request.headers.get("X-NEXO-Content-SHA256") or "").lower()
        if not declared_form or not declared_header:
            return jsonify(ok=False, message="SHA-256 obrigatório."), 400
        if not hmac.compare_digest(declared_form, actual_sha) or not hmac.compare_digest(declared_header, actual_sha):
            return jsonify(ok=False, message="SHA-256 do PDF não confere."), 400

        if previous:
            if hmac.compare_digest(previous.get("sha256", ""), actual_sha):
                return jsonify(ok=True, status=previous.get("status", "RECEBIDO"), duplicate=True)
            return jsonify(ok=False, status="CONFLITO_PDF", message="Já existe outro PDF para este pedido."), 409

        final_path = g.inbox / f"Pedido_{order_number}_RM.pdf"
        temp_path.replace(final_path)
        import_id = g.register_import(order_number, final_path, actual_sha, _agent_id())
        main_store().event(
            "ROBOT_PDF_RECEBIDO",
            pedido=order_number,
            usuario=f"robot:{_agent_id()}",
            detalhe=f"PDF original do RM recebido; sha256={actual_sha}",
        )
        return jsonify(ok=True, status="RECEBIDO", order_number=order_number, import_id=import_id, sha256=actual_sha), 201
    finally:
        temp_path.unlink(missing_ok=True)
