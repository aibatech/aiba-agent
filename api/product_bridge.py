from __future__ import annotations

import hmac
import os
import re
from typing import Literal


_USER_RE = re.compile(r"^[A-Za-z0-9._:@+-]{1,200}$")


def _principal(raw: str | None) -> str:
    """Return a stable product-scoped Agent identity.

    The trusted AIBA product backend supplies its canonical user id. Prefixing
    prevents accidental collision with Telegram/WhatsApp/local operator keys.
    """
    value = (raw or "").strip()
    if not value or not _USER_RE.fullmatch(value):
        raise ValueError("A valid X-AIBA-User-ID is required")
    return f"product:{value}"


def create_product_app(agent, bridge_token: str | None = None):
    """Create the internal execution API used by the unified AIBA product.

    This is deliberately *not* a public chat API. AskAIBA web/mobile should talk
    to the normal AIBA product backend, which keeps the existing AIBA system and
    voice prompts. That backend may call this bridge when AIBA needs tools,
    research, memory, browser work, or another Agent capability.

    Voice and text therefore share one execution path: speech is transcribed by
    the product voice service, then the resulting text can be sent here exactly
    like typed text. Agent does not replace the product STT/TTS or personality.
    """
    try:
        from fastapi import FastAPI, Header, HTTPException
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Install API dependencies: pip install -e '.[api]'") from exc

    token = bridge_token or os.getenv("AIBA_PRODUCT_BRIDGE_TOKEN", "")
    if not token:
        raise RuntimeError("AIBA_PRODUCT_BRIDGE_TOKEN is required for the product bridge")

    app = FastAPI(
        title="AIBA Product Execution Bridge",
        version="1.6.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    class ExecuteIn(BaseModel):
        instruction: str = Field(min_length=1, max_length=100_000)
        input_mode: Literal["text", "voice"] = "text"
        task_type: str | None = None
        model_id: str | None = None
        approved_tools: list[str] = Field(default_factory=list, max_length=50)

    def authorize(value: str | None) -> None:
        if not value or not value.startswith("Bearer ") or not hmac.compare_digest(value[7:], token):
            raise HTTPException(401, "Valid product bridge token required")

    def user_from_header(value: str | None) -> str:
        try:
            return _principal(value)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/health")
    def health():
        return {"ok": True, "version": "1.6.0", "role": "internal_product_execution_bridge"}

    @app.get("/v1/product/capabilities")
    def capabilities(
        authorization: str | None = Header(default=None),
        x_aiba_user_id: str | None = Header(default=None, alias="X-AIBA-User-ID"),
    ):
        authorize(authorization)
        user_from_header(x_aiba_user_id)
        return {"capabilities": agent.capability_report()}

    @app.post("/v1/product/execute")
    def execute(
        body: ExecuteIn,
        authorization: str | None = Header(default=None),
        x_aiba_user_id: str | None = Header(default=None, alias="X-AIBA-User-ID"),
    ):
        authorize(authorization)
        principal = user_from_header(x_aiba_user_id)

        # approved_tools must only be populated by the trusted server after a
        # real user approval. Browser/mobile clients must never receive the
        # bridge token or call this service directly.
        with agent.approvals.request_scope(body.approved_tools):
            result = agent.handle(
                body.instruction,
                propose_skill=False,
                task_type=body.task_type,
                manual_model_id=body.model_id,
                user_id=principal,
                onboard=False,
            )
            pending = agent.approvals.pending_requests()

        return {
            "status": "approval_required" if pending else "complete",
            "result": result,
            "approval_required": pending,
            "input_mode": body.input_mode,
            "user_scope": principal,
        }

    return app
