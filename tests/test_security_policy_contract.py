from pathlib import Path

def test_security_policy_declares_formal_trust_model():
    text=(Path(__file__).resolve().parents[1]/"SECURITY.md").read_text(encoding="utf-8")
    required=[
      "The only real containment boundary",
      "Agent process", "Input surface", "Trust envelope", "Stance",
      "defense-in-depth **heuristics and policy checks,\nnot isolation boundaries**",
      "## 4. Vulnerability disclosure scope",
      "### In scope", "### Normally out of scope by itself",
      "### 3.6 Plugins and skills",
      "fail closed", "Session IDs are routing handles, not authentication credentials",
      "do not certify a deployment",
    ]
    for phrase in required:
        assert phrase in text, f"SECURITY.md missing required trust-model language: {phrase}"
