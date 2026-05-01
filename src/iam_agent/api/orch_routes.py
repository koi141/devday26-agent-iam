from __future__ import annotations

from pathlib import Path

from chainlit.utils import mount_chainlit
from fastapi import Body
from fastapi import FastAPI, HTTPException
from fastapi import Header
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from iam_agent.app.chainlit_entry import get_orchestrator, get_snapshot, process_message


app = FastAPI(
    title="iam-agent",
    version="0.1.0",
    description="OCI IAM / Identity Domains 運用支援エージェント",
)


class _SocketPathCompatMiddleware:
    """旧UIキャッシュ向けに socket.io パスを /ui 配下へ互換変換する。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") in {"http", "websocket"}:
            path = str(scope.get("path") or "")
            if path.startswith("/ws/socket.io") or path.startswith("/socket.io"):
                patched = dict(scope)
                patched["path"] = f"/ui{path}"
                raw_path = scope.get("raw_path")
                if isinstance(raw_path, (bytes, bytearray)):
                    patched["raw_path"] = b"/ui" + bytes(raw_path)
                scope = patched
        await self.app(scope, receive, send)


app.add_middleware(_SocketPathCompatMiddleware)


@app.on_event("startup")
def startup_preflight() -> None:
    # 起動時にOrchestratorを構築し、設定不足があれば起動を失敗させる。
    get_orchestrator()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="ユーザー入力")


def _bearer_token(authorization: str) -> str:
    raw = authorization.strip()
    if not raw:
        return ""
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def _error_status_for_code(*, code: str, token: str = "") -> int:
    if code in {"missing_input", "invalid_argument"}:
        return 400
    if code in {"peer_untrusted"}:
        return 401 if not token else 403
    if code in {"loop_detected", "idempotency_conflict"}:
        return 409
    if code in {"delegation_timeout"}:
        return 504
    return 403 if code in {"a2a_disabled"} else 500


def infer_route_mode(message: str) -> str:
    text = message.strip().lower()
    if not text:
        return "single_tool_passthrough"
    if any(key in text for key in ("アクセス拒否", "アクセスできない", "権限不足", "denied", "not authorized")):
        return "access_denial_troubleshooting"
    if ("操作" in text or "権限" in text) and ("許可" in text):
        return "permission_investigation"
    if any(
        key in text
        for key in (
            "何ができます",
            "何ができる",
            "権限を教えて",
            "できること",
            "許可されている操作",
            "何の操作が許可",
            "どのような操作を許可",
            "どのような操作が許可",
            "許可されていますか",
            "許可されているか",
            "許可されている",
        )
    ):
        return "permission_investigation"
    return "single_tool_passthrough"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "iam-agent", "status": "running", "chainlit_ui": "/ui"}


@app.get("/chat")
def chat_ui_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui", status_code=307)


@app.post("/chat")
def chat_api(request: ChatRequest) -> dict:
    try:
        payload = process_message(request.message)
        route_mode = infer_route_mode(request.message)
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(meta, dict):
            meta = {}
        meta.update(
            {
                "route_mode": route_mode,
                "compatibility": {
                    "single_tool_contract_preserved": route_mode == "single_tool_passthrough",
                    "additive_layer_active": route_mode != "single_tool_passthrough",
                },
            }
        )
        payload["meta"] = meta
        return payload
    except Exception as exc:  # pragma: no cover - runtime path
        raise HTTPException(status_code=500, detail=f"処理中に内部エラーが発生しました: {type(exc).__name__}") from exc


def _build_a2a_capabilities_response(
    *,
    source_agent_id: str,
    authorization: str,
    x_source_agent_id: str,
):
    orchestrator = get_orchestrator()
    token = _bearer_token(authorization)
    resolved_source = source_agent_id or x_source_agent_id
    payload = orchestrator.get_a2a_capabilities(source_agent_id=resolved_source, auth_token=token)
    error_code = str(payload.get("error_code") or "")
    if error_code:
        return JSONResponse(payload, status_code=_error_status_for_code(code=error_code, token=token))
    return payload


@app.get("/.well-known/agent.json")
def agent_card(
    source_agent_id: str = "",
    authorization: str = Header(default="", alias="Authorization"),
    x_source_agent_id: str = Header(default="", alias="X-Source-Agent-ID"),
):
    return _build_a2a_capabilities_response(
        source_agent_id=source_agent_id,
        authorization=authorization,
        x_source_agent_id=x_source_agent_id,
    )


@app.get("/a2a/capabilities")
def a2a_capabilities(
    source_agent_id: str = "",
    authorization: str = Header(default="", alias="Authorization"),
    x_source_agent_id: str = Header(default="", alias="X-Source-Agent-ID"),
):
    # Backward compatibility endpoint. Canonical card path is /.well-known/agent.json.
    return _build_a2a_capabilities_response(
        source_agent_id=source_agent_id,
        authorization=authorization,
        x_source_agent_id=x_source_agent_id,
    )


@app.post("/a2a/execute")
def a2a_execute(
    request_body: dict = Body(...),
    authorization: str = Header(default="", alias="Authorization"),
    x_source_agent_id: str = Header(default="", alias="X-Source-Agent-ID"),
):
    orchestrator = get_orchestrator()
    payload = dict(request_body or {})
    if x_source_agent_id and not str(payload.get("source_agent_id") or "").strip():
        payload["source_agent_id"] = x_source_agent_id
    token = _bearer_token(authorization)
    response = orchestrator.handle_a2a_request(payload=payload, auth_token=token)
    body = response.to_dict()

    request_id = str((body.get("data") or {}).get("request_id") or payload.get("request_id") or "")
    correlation_id = str((body.get("data") or {}).get("correlation_id") or payload.get("correlation_id") or "")

    if response.status == "error":
        error_code = ""
        missing_inputs: list[str] = []
        if response.errors:
            error_code = response.errors[0].code
        if isinstance(body.get("meta"), dict):
            raw_missing = body["meta"].get("missing_inputs")
            if isinstance(raw_missing, list):
                missing_inputs = [str(item) for item in raw_missing]
        error_payload = {
            "error_code": error_code or "execution_error",
            "missing_inputs": missing_inputs,
            "facts": body.get("facts") or [],
            "interpretation": body.get("interpretation") or [],
            "proposal": body.get("proposal") or [],
            "meta": body.get("meta") or {},
        }
        return JSONResponse(error_payload, status_code=_error_status_for_code(code=error_payload["error_code"], token=token))

    execute_payload = {
        "request_id": request_id,
        "correlation_id": correlation_id,
        "status": response.status,
        "facts": body.get("facts") or [],
        "interpretation": body.get("interpretation") or [],
        "proposal": body.get("proposal") or [],
        "data": body.get("data") or {},
        "meta": body.get("meta") or {},
        "audit": body.get("audit") or {},
    }
    return JSONResponse(execute_payload, status_code=200)


@app.get("/telemetry/comparison")
def telemetry_comparison(scope: str = "single_tool_passthrough", window_start: str = "", window_end: str = "") -> dict:
    snapshot = get_snapshot(scope=scope, window_start=window_start, window_end=window_end)
    return {
        "facts": [
            f"対象スコープ: {snapshot.get('scope')}",
            f"成功率: {float(snapshot.get('success_rate') or 0.0):.2%}",
            f"p95処理時間: {int(snapshot.get('p95_latency_ms') or 0)} ms",
            f"再試行率: {float(snapshot.get('retry_rate') or 0.0):.2%}",
        ],
        "interpretation": ["改善前後の差分確認に利用できます。"],
        "proposal": ["必要に応じて scope と期間パラメータを指定してください。"],
        "data": snapshot,
        "meta": {
            "route_mode": "telemetry_comparison",
            "compatibility": {
                "single_tool_contract_preserved": True,
                "additive_layer_active": True,
            },
        },
    }


CHAINLIT_ENTRY = Path(__file__).resolve().parents[1] / "app" / "chainlit_entry.py"
mount_chainlit(app=app, target=str(CHAINLIT_ENTRY), path="/ui")
