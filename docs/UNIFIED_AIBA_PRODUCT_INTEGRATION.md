# Unified AIBA product integration

AIBA Agent is the **execution layer** for the customer-facing AIBA product. It
must not replace the system prompt, life-coach behavior, voice personality, or
conversation orchestration already used by AskAIBA.com and the AIBA mobile app.

## Supported architecture

```text
Web / mobile
     |
Authenticated AIBA product backend
     |                 \
     |                  -> existing STT / TTS / voice session service
     |
     -> AIBA personality + conversation + product memory
              |
              -> AIBA Agent product bridge (when tools/work are needed)
```

The browser and iOS app must never call the Agent management API or product
bridge directly and must never receive `AIBA_API_TOKEN` or
`AIBA_PRODUCT_BRIDGE_TOKEN`.

## Why the bridge exists

`api.product_bridge` provides a narrow server-to-server contract that lets the
existing AIBA runtime use Agent capabilities without turning AIBA Agent into a
second user-facing chatbot. The product backend remains responsible for the
existing text/voice prompts and final user-facing response style.

Start it with:

```bash
pip install -e '.[api]'
export AIBA_PRODUCT_BRIDGE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
aiba-product
```

It binds to `127.0.0.1:8770` by default. Production deployments should keep it
on loopback or private service networking behind TLS.

## Execute endpoint

`POST /v1/product/execute`

Required headers:

```text
Authorization: Bearer <AIBA_PRODUCT_BRIDGE_TOKEN>
X-AIBA-User-ID: <canonical product user id>
```

Example body:

```json
{
  "instruction": "Research the three strongest competitors and summarize them",
  "input_mode": "text"
}
```

For a voice request, the product voice layer transcribes speech first and sends
the exact same execution request with `"input_mode": "voice"`. Text and voice
therefore have the same Agent tools and user-scoped memory path. Agent itself
does not replace the product's current STT/TTS or voice prompt.

The bridge namespaces the product identity as `product:<id>` before passing it
to `AgentLoop.handle`. This prevents collisions with local operator,
Telegram, and WhatsApp identities and keeps Agent memory/session tools scoped to
the authenticated product user.

## Approvals

Mutation-capable tools retain the existing `ToolRegistry` permission policy.
On a first server-side attempt, non-interactive Agent execution records the
requested tool and denies it. The bridge returns:

```json
{
  "status": "approval_required",
  "approval_required": [
    {"tool": "browser_click", "reason": "...redacted arguments..."}
  ]
}
```

The AIBA product backend should show a human-readable approval UI. Only after
that user approves should the trusted backend retry the instruction with the
exact approved tool names in `approved_tools`.

`approved_tools` is a **server-to-server trust field**. Never accept it directly
from an untrusted browser/mobile request, and never expose the bridge token to a
client. The grant is request-scoped with `ContextVar` state and is reset after
the request so it cannot leak into another user or later action.

## Voice

The Agent repository does not currently implement production STT/TTS. This is
intentional in the unified product architecture: existing AIBA mobile/web voice
services remain the voice layer so their current voice prompt, speaking style,
and behavior are preserved.

The required path is:

```text
microphone -> existing AIBA STT -> existing AIBA conversation runtime
                                      |
                                      -> Agent bridge when tools are needed
                                      |
                                  existing AIBA final response
                                      |
                                  existing AIBA TTS
```

Do not build a separate "voice agent" endpoint with reduced tools. A spoken and
typed request must reach the same product orchestration and the same Agent
execution bridge.

## Capability truthfulness

Use `GET /v1/product/capabilities` to inspect the runtime capability report.
Feature flags, permissions, optional dependencies, and release blockers remain
authoritative. A capability that is present in source but gated/off/unverified
must not be marketed as ready.

In particular, keep the browser, desktop, MCP, subagent, and mutation approval
security gates intact. The unified product integration is not permission to
turn those controls off.
