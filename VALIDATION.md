# AIBA v1.4 local validation record

## Messaging connector validation

- 35 automated tests passed, including Telegram owner authorization, WhatsApp owner authorization, webhook signature verification, duplicate-delivery suppression, outbound replies, and existing runtime regression coverage.
- Connector API route creation passed with the API dependencies installed.
- Python compilation passed.
- Dependency audit reported no known vulnerabilities.
- Static security and secret scans passed.

Live Telegram delivery and live Meta WhatsApp Cloud API delivery remain credential-gated external certification steps. No owner token, Meta app secret, business phone credential, or provider API key is included in this release.

Validated on Python 3.12:

- all modules compile;
- 30 unit tests pass;
- authenticated API smoke tests pass for liveness, readiness, authentication enforcement, operations, metrics, backup creation, and backup verification;
- a 1,000-request local Linux load smoke test passed with 25 concurrent clients, zero errors, and p95 below 35 ms in the development environment;
- the dependency audit reports no known vulnerabilities and the high-severity static and secret gates pass;
- clean-profile Linux x86-64 certification passes on Python 3.12;
- Windows PowerShell/batch and macOS/Linux/Docker launcher paths are present; POSIX installers pass shell syntax validation;
- secure token generation is idempotent and the generated `.env` is owner-only on POSIX;
- staged update checks cover SHA-256 verification, backup creation, secret preservation, HTTPS enforcement, and traversal rejection;
- authenticated provider/model/routing API CRUD passed through a real ASGI test client in the v1.1 baseline;
- provider presets cover OpenAI, Anthropic, Gemini, xAI, OpenRouter, Groq, Mistral, DeepSeek, Together, Perplexity, Azure OpenAI, AWS Bedrock, Ollama, LM Studio, and custom endpoints;
- stored API keys are encrypted and absent as plaintext from database bytes and API responses;
- missing master-key protection rejects credential storage;
- task classification, capability constraints, lowest-cost ordering, passive provider health, automatic failover, and usage accounting pass;
- local provider file listing, memory write, and memory retrieval pass;
- workspace traversal is rejected;
- blocked commands are rejected and local shell/Python execution is refused;
- private and loopback browser destinations are rejected;
- native provider tool schemas and tool-call parsing are tested;
- durable queue recovery, scheduling, task persistence, token hashing, and skill execution pass;
- package installation/import and release ZIP integrity pass;
- the release archive contains no caches, databases, logs, secrets, or generated runtime state.

This record does not certify Windows, macOS, live providers, signed installers, Docker/VPS, or the one-hour soak gate. See `PRODUCTION_GATE.md` for the external evidence still required.
