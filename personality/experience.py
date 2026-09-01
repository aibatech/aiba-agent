"""Per-user personality and resumable onboarding.

Gives AIBA a stable shared soul plus a separate, private profile for each
Telegram / WhatsApp user. Profiles live under ``<data_dir>/profiles/`` (the
``agent_system/profiles`` directory), are gitignored, and carry 0600
permissions. No private chain-of-thought, hidden prompts, or credentials are
ever exposed to the model conversation -- only plain, consented preference
facts the user shared during onboarding.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# One focused question per step, in order. Each entry is (question, profile key).
ONBOARDING_QUESTIONS: list[tuple[str, str]] = [
    ("What should I call you?", "name"),
    ("What kind of work do you do?", "work"),
    ("What's the main thing you'd like my help with?", "goal"),
    ("How do you like to communicate?", "style"),
]

MAIN_QUESTION = "What should we tackle first?"
WRAPUP = "Got it. I'll keep things clear and check in as we go — what should we tackle first?"


class PersonalExperience:
    """Resumable, per-user personality: SOUL + private profile + onboarding."""

    def __init__(self, root_dir, data_dir):
        self.root_dir = Path(root_dir)
        self.profiles_dir = Path(data_dir) / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.soul = self._load_soul()
        self._cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ files
    def _load_soul(self) -> str:
        soul_path = self.root_dir / "SOUL.md"
        if soul_path.exists():
            return soul_path.read_text(encoding="utf-8").strip()
        return ""

    def _profile_path(self, user_id: str) -> Path:
        # "telegram:12345" -> "telegram_12345.json" (filesystem-safe, opaque)
        safe = user_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        return self.profiles_dir / f"{safe}.json"

    def _user_md_path(self, user_id: str) -> Path:
        base = self._profile_path(user_id).stem.replace("_", "-")
        return self.profiles_dir / f"{base}-USER.md"

    # ------------------------------------------------------------ load/save
    def _profile(self, user_id: str) -> dict:
        if user_id in self._cache:
            return self._cache[user_id]
        path = self._profile_path(user_id)
        if path.exists():
            profile = json.loads(path.read_text(encoding="utf-8"))
        else:
            profile = {"user_id": user_id, "step": 0, "done": False, "memory_active": True}
        self._cache[user_id] = profile
        return profile

    def _save(self, user_id: str, profile: dict) -> None:
        path = self._profile_path(user_id)
        path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
        self._write_user_md(user_id, profile)
        self._cache[user_id] = profile

    def _write_user_md(self, user_id: str, profile: dict) -> None:
        """Human-readable mirror of the remembered preferences (no secrets)."""
        lines = ["# User Profile", "", f"- User: {user_id}"]
        labels = [("name", "Preferred name"), ("work", "Work"), ("goal", "Main goal"), ("style", "Style")]
        for key, label in labels:
            value = profile.get(key)
            if value:
                lines.append(f"- {label}: {value}")
        memory = "active" if profile.get("memory_active", True) else "paused"
        lines.append(f"- Memory: {memory}")
        path = self._user_md_path(user_id)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    # -------------------------------------------------------------- workflow
    def begin(self, user_id: str) -> str:
        """Return the next onboarding prompt for a user ("" if already done)."""
        profile = self._profile(user_id)
        if profile.get("done"):
            return ""
        step = profile.get("step", 0)
        if step < len(ONBOARDING_QUESTIONS):
            return ONBOARDING_QUESTIONS[step][0]
        return MAIN_QUESTION

    def intercept(self, user_id: str, text: str):
        """Handle onboarding/memory commands. Returns prompt text, or None if
        the message should flow to the agent as a normal task."""
        profile = self._profile(user_id)
        text = text.strip()
        if text.startswith("/"):
            return self._command(user_id, text, profile)
        if profile.get("done"):
            return None
        step = profile.get("step", 0)
        if step < len(ONBOARDING_QUESTIONS):
            key = ONBOARDING_QUESTIONS[step][1]
            profile[key] = text
            profile["step"] = step + 1
            self._save(user_id, profile)
            # If this was the final personal question, onboarding is complete:
            # the next normal message flows straight to the agent.
            if profile["step"] >= len(ONBOARDING_QUESTIONS):
                profile["done"] = True
                self._save(user_id, profile)
                return WRAPUP
            return self.begin(user_id)
        # past all the personal questions: wrap up onboarding
        profile["done"] = True
        profile["step"] = step + 1
        self._save(user_id, profile)
        return WRAPUP

    def start_conversation(self, user_id: str) -> str:
        """Entry point used by connectors on first contact."""
        prompt = self.begin(user_id)
        if prompt:
            return prompt
        return "Hey, I'm AIBA. What would you like to work on?"

    # -------------------------------------------------------------- commands
    def _command(self, user_id: str, text: str, profile: dict):
        lower = text.lower()
        if lower == "/profile":
            return self._format_profile(profile)
        if lower == "/memory pause":
            if profile.get("memory_active") is not False:
                profile["memory_active"] = False
                self._save(user_id, profile)
            return "Memory paused. I'll stop keeping new notes about your preferences."
        if lower == "/memory resume":
            if profile.get("memory_active") is not True:
                profile["memory_active"] = True
                self._save(user_id, profile)
            return "Memory resumed. I'll start keeping notes again."
        if lower == "/skip":
            profile["step"] = len(ONBOARDING_QUESTIONS)
            profile["done"] = True
            profile["complete_via"] = "skip"
            self._save(user_id, profile)
            return ("No problem — we can skip the setup for now. "
                    "You can use /profile anytime to review or add your preferences.")
        return None

    def _format_profile(self, profile: dict) -> str:
        lines = ["Here's what I know about you:"]
        labels = [("name", "Name"), ("work", "Work"), ("goal", "Main goal"), ("style", "Style")]
        for key, label in labels:
            value = profile.get(key)
            if value:
                lines.append(f"- {label}: {value}")
        memory = "active" if profile.get("memory_active", True) else "paused"
        lines.append(f"- Memory: {memory}")
        return "\n".join(lines)

    # ------------------------------------------------------ model assistance
    def prompt_context(self, user_id: str | None) -> str:
        """Plain, consented context injected into the conversation. Never
        includes chain-of-thought, hidden prompts, credentials, or internal
        deliberation. Returns "" for anonymous (no-user) calls."""
        if not user_id:
            return ""
        profile = self._profile(user_id)
        parts: list[str] = []
        if self.soul:
            parts.append(self.soul)
        if profile.get("name"):
            parts.append(f"User's preferred name: {profile['name']}")
        if profile.get("work"):
            parts.append(f"User's work: {profile['work']}")
        if profile.get("goal"):
            parts.append(f"User's main goal: {profile['goal']}")
        if profile.get("style"):
            parts.append(f"User's communication style: {profile['style']}")
        if profile.get("memory_active") is False:
            parts.append("Note: this user has paused memory; do not store new preferences this session.")
        return "\n".join(parts)

    def load(self, user_id: str) -> dict:
        """Return a shallow copy of a user's profile (for tests / inspection)."""
        return dict(self._profile(user_id))
