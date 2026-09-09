from __future__ import annotations

import os

from agent.enhanced_loop import AgentLoop
from api.product_bridge import create_product_app


def build_app():
    agent = AgentLoop(interactive=False, auto_approve=False)
    return create_product_app(agent)


app = build_app()


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Install API dependencies: pip install -e '.[api]'") from exc
    host = os.getenv("AIBA_PRODUCT_BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("AIBA_PRODUCT_BRIDGE_PORT", "8770"))
    uvicorn.run(app, host=host, port=port)
