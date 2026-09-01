"""Per-user personality and resumable onboarding.

Gives AIBA a stable shared soul plus a separate, private profile for each
Telegram / WhatsApp / API / CLI conversation. Profiles live under
``<data_dir>/profiles/`` (the ``agent_system/profiles`` directory), are
gitignored, use opaque SHA-256-derived filenames, and carry owner-only
permissions on POSIX (0700 directory / 0600 files). On Windows Unix modes are
not faked; a minimal directory/file ownership model is applied where the OS
supports it and behavior is documented honestly.

No raw connector identifiers (Telegram user IDs, WhatsApp phone numbers) ever
appear in provider filenames or in the human-readable USER.md mirror; they are
stored only inside the protected JSON when operationally necessary. No private
chain-of-thought, hidden prompts, or credentials are exposed to the model
conversation -- only plain, consented preference facts from onboarding.

Two hard privacy controls are enforced here:

* ``prompt_context(user_id=None)`` always returns the shared SOUL (so API, CLI,
  and scheduled/background conversations are in-character) and, *only* when a
  real ``user_id`` is supplied, appends that user's private profile facts.
* A paused user ("/memory pause") cannot write new durable memory: the
  ``remember`` tool is blocked for their conversation both at the schema level
  (removed from what the model may call) and at runtime (tool execution is
  rejected), and no new preference facts are persisted to their profile.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

_POSIX = sys.platform.startswith(("linux", "darwin", "freebsd", "openbsd"))


def _now_ts() -> str:
    return str(int(time.time()))


# One focused question per step, in order. Each entry is (question, profile key).
_ONBOARDING_QUESTIONS: list[tuple[str, str]] = [
    ("What should I call you?", "name"),
    ("What kind of work do you do?", "work"),
    ("What's the main thing you'd like my help with?", "goal"),
]

# Communication style is a selectable, numbered choice (asked after the three
# open questions). 1/2/3 are accepted and normalized; anything else is refused
# with a polite re-prompt so a stray task or typo is never stored as a style.
_STYLE_OPTIONS: dict[int, str] = {
    1: "Quick and direct - recommended for everyday work",
    2: "Friendly and conversational",
    3: "Detailed and strategic",
}
_STYLE_PROMPT = (
    "How do you like to communicate? Choose one:\n"
    "1. Quick and direct - recommended for everyday work\n"
    "2. Friendly and conversational\n"
    "3. Detailed and strategic\n"
    "Reply 1, 2, or 3."
)
_STYLE_INVALID = (
    "That doesn't look like a choice. Please reply 1, 2, or 3 "
    "(or, if you prefer, just describe how you like to communicate)."
)

MAIN_QUESTION = "What should we tackle first?"
WRAPUP = "Got it. I'll keep things clear and check in as we go - what should we tackle first?"
INTRO = "Hey, I'm AIBA. I'm here to learn how you work and help you get things done."

# A first-contact message that looks like a task (not a name) is never stored as
# the user's name; we re-prompt for a name instead.
_NAME_MAXLEN = 60
_FIRST_TASK_HINT_WORDS = (
    "build", "make", "help", "create", "need", "want", "please", "write",
    "set up", "design", "plan", "organize", "schedule", "remind", "search",
    "tell me", "can you", "i need", "i want", "let's", "lets", "like to",
)


def _protect_dir(path: Path) -> None:
    """Apply owner-only protection to a directory on POSIX; no-op elsewhere."""
    if _POSIX:
        try:
            path.chmod(0o700)
        except OSError:
            pass


def _protect_file(path: Path) -> None:
    """Apply owner-only protection to a file on POSIX; no-op elsewhere.

    On Windows, POSIX mode bits are not meaningful and are deliberately NOT
    faked. Files are created in the user-owned data directory, giving them the
    same default ACL as the rest of that user's private AIBA data.
    """
    if _POSIX:
        try:
            path.chmod(0o600)
        except OSError:
            pass


class PersonalExperience:
    """Resumable, per-user personality: SOUL + private profile + onboarding."""

    def __init__(self, root_dir, data_dir):
        self.root_dir = Path(root_dir)
        self.profiles_dir = Path(data_dir) / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        _protect_dir(self.profiles_dir)
        self.soul = self._load_soul()
        self._cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ files
    def _load_soul(self) -> str:
        soul_path = self.root_dir / "SOUL.md"
        if soul_path.exists():
            return soul_path.read_text(encoding="utf-8").strip()
        return _DEFAULT_SOUL

    @staticmethod
    def _opaque_id(user_id: str) -> str:
        """SHA-256 digest of the channel-qualified id -> opaque 32-char hex name.

        Never contains the raw connector identifier (Telegram id / WhatsApp
        number); a 24-32 char hash prefix is sufficient and stable for the same
        user across restarts.
        """
        digest = hashlib.sha256(("aiba-profile:" + user_id).encode("utf-8")).hexdigest()
        return digest[:32]

    def _profile_path(self, user_id: str) -> Path:
        return self.profiles_dir / f"{self._opaque_id(user_id)}.json"

    def _user_md_path(self, user_id: str) -> Path:
        return self.profiles_dir / f"{self._opaque_id(user_id)}-USER.md"

    # ------------------------------------------------------------ load/save
    def _load_profile_from_disk(self, path: Path, user_id: str) -> dict:
        """Read a profile, tolerating a malformed file without crashing.

        A corrupt JSON file is moved aside (recoverable backup), diagnosed, and
        a fresh profile is returned so the user is not locked out.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("profile is not a JSON object")
            return data
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            # Preserve the corrupt file for diagnosis/inspection, then start fresh.
            backup = path.with_suffix(".corrupt-" + _now_ts() + path.suffix)
            try:
                os.replace(path, backup)
            except OSError:
                pass
            self._cache.pop(user_id, None)
            return {"user_id": user_id, "step": 0, "done": False,
                    "memory_active": True, "_recovered": str(exc),
                    "_recovered_from": backup.name}

    def _profile(self, user_id: str) -> dict:
        if user_id in self._cache:
            return self._cache[user_id]
        path = self._profile_path(user_id)
        if path.exists():
            profile = self._load_profile_from_disk(path, user_id)
        else:
            profile = {"user_id": user_id, "step": 0, "done": False, "memory_active": True}
        self._cache[user_id] = profile
        return profile

    def _save(self, user_id: str, profile: dict) -> None:
        """Atomically persist a profile: temp file in the same dir, then replace."""
        path = self._profile_path(user_id)
        tmp = self.profiles_dir / f".{self._opaque_id(user_id)}.tmp"
        payload = json.dumps(profile, indent=2, ensure_ascii=False)
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        _protect_file(tmp)
        os.replace(tmp, path)
        _protect_file(path)
        self._write_user_md(user_id, profile)
        self._cache[user_id] = profile

    def _write_user_md(self, user_id: str, profile: dict) -> None:
        """Human-readable mirror of the endorsed preferences.

        Never contains the raw connector identifier or any secret -- only the
        (already consented) preference facts the user shared during onboarding.
        """
        labels = [("name", "Preferred name"), ("work", "Work"),
                  ("goal", "Main goal"), ("style", "Style")]
        lines = ["# User Profile", ""]
        for key, label in labels:
            value = profile.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"- {label}: {value.strip()}")
        memory = "active" if profile.get("memory_active", True) else "paused"
        lines.append(f"- Memory: {memory}")
        path = self._user_md_path(user_id)
        tmp = self.profiles_dir / f".{self._opaque_id(user_id)}-USER.md.tmp"
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            _protect_file(tmp)
            os.replace(tmp, path)
            _protect_file(path)
        except OSError:
            pass

    # -------------------------------------------------------------- workflow
    def begin(self, user_id: str) -> str:
        """Return the next onboarding prompt for a user ("" if already done)."""
        profile = self._profile(user_id)
        if profile.get("done"):
            return ""
        step = profile.get("step", 0)
        if step < len(_ONBOARDING_QUESTIONS):
            return _ONBOARDING_QUESTIONS[step][0]
        if step == len(_ONBOARDING_QUESTIONS):
            return _STYLE_PROMPT  # style selection is the final onboarding step
        return MAIN_QUESTION

    def start_conversation(self, user_id: str) -> str:
        """Entry point used by connectors on first contact. Sets the introduced
        state, shows the introduction once, and starts onboarding."""
        profile = self._profile(user_id)
        if not profile.get("introduced"):
            profile["introduced"] = True
            self._save(user_id, profile)
            return INTRO + " " + self.begin(user_id)
        prompt = self.begin(user_id)
        if prompt:
            return prompt
        return "Hey, I'm AIBA. What would you like to work on?"

    def intercept(self, user_id: str, text: str):
        """Handle onboarding/memory commands. Returns prompt text, or None if the
        message should flow to the agent as a normal task."""
        profile = self._profile(user_id)
        text = (text or "").strip()
        if text.startswith("/"):
            profile["introduced"] = True  # engaging with a command counts as contact
            self._save(user_id, profile)
            return self._command(user_id, text, profile)
        # First contact: introduce once, never consume the raw message as data.
        if not profile.get("introduced"):
            profile["introduced"] = True
            self._save(user_id, profile)
            return INTRO + " " + self.begin(user_id)
        if profile.get("done"):
            return None
        step = profile.get("step", 0)
        # Open questions (name, work, goal).
        if step < len(_ONBOARDING_QUESTIONS):
            key = _ONBOARDING_QUESTIONS[step][1]
            if key == "name" and self._looks_like_task(text):
                return ("That looks like a task - I'll save it for after intro. "
                        "For now, what should I call you? Just a name is fine.")
            if not self._memory_writes_allowed(user_id):
                # Paused memory: acknowledge but persist nothing, and advance so
                # onboarding finishes without storing new private data.
                profile["step"] = step + 1
                if profile["step"] >= len(_ONBOARDING_QUESTIONS) + 1:
                    profile["done"] = True
                self._save(user_id, profile)
                return WRAPUP
            profile[key] = text
            profile["step"] = step + 1
            self._save(user_id, profile)
            if profile["step"] >= len(_ONBOARDING_QUESTIONS) + 1:
                profile["done"] = True
                self._save(user_id, profile)
                return WRAPUP
            return self.begin(user_id)
        # Final onboarding step: the selectable communication-style choice.
        if step == len(_ONBOARDING_QUESTIONS):
            if not self._memory_writes_allowed(user_id):
                profile["step"] = step + 1
                profile["done"] = True
                self._save(user_id, profile)
                return WRAPUP
            normalized, ok = self._parse_style(text)
            if not ok:
                return _STYLE_INVALID
            profile["style"] = normalized
            profile["step"] = step + 1
            profile["done"] = True
            self._save(user_id, profile)
            return WRAPUP
        # Past all the personal questions: wrap up onboarding.
        profile["done"] = True
        self._save(user_id, profile)
        return WRAPUP

    # -------------------------------------------------------------- helpers
    def _looks_like_task(self, text: str) -> bool:
        if len(text) > _NAME_MAXLEN:
            return True
        low = text.lower()
        return any(h in low for h in _FIRST_TASK_HINT_WORDS)

    def _parse_style(self, text: str) -> tuple[str, bool]:
        """Accept 1/2/3 and return the normalized selected label; refuse anything
        else so a stray task, typo, or casual message is never stored as a style."""
        t = (text or "").strip().lower()
        if t == "1":
            return _STYLE_OPTIONS[1], True
        if t == "2":
            return _STYLE_OPTIONS[2], True
        if t == "3":
            return _STYLE_OPTIONS[3], True
        return "", False

    def _memory_writes_allowed(self, user_id: str) -> bool:
        return self._profile(user_id).get("memory_active", True) is not False

    # -------------------------------------------------------------- commands
    def _command(self, user_id: str, text: str, profile: dict):
        lower = text.lower()
        if lower == "/profile":
            return self._format_profile(profile)
        if lower == "/memory pause":
            if profile.get("memory_active") is not False:
                profile["memory_active"] = False
                self._save(user_id, profile)
            return ("Memory paused. I'll stop keeping new notes about you and I "
                    "won't store new preferences. I can still use what I already know.")
        if lower == "/memory resume":
            if profile.get("memory_active") is not True:
                profile["memory_active"] = True
                self._save(user_id, profile)
            return "Memory resumed. I'll start keeping notes again."
        if lower == "/skip":
            profile["step"] = len(_ONBOARDING_QUESTIONS) + 1
            profile["done"] = True
            profile["complete_via"] = "skip"
            self._save(user_id, profile)
            return ("No problem - we can skip the setup for now. "
                    "You can use /profile anytime to review or add your preferences.")
        return None

    def _format_profile(self, profile: dict) -> str:
        lines = ["Here's what I know about you:"]
        labels = [("name", "Name"), ("work", "Work"),
                  ("goal", "Main goal"), ("style", "Style")]
        for key, label in labels:
            value = profile.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"- {label}: {value.strip()}")
        memory = "active" if profile.get("memory_active", True) else "paused"
        lines.append(f"- Memory: {memory}")
        return "\n".join(lines)

    # ------------------------------------------------------ model assistance
    def prompt_context(self, user_id: str | None) -> str:
        """Shared SOUL always returned; private profile facts only for a real user.

        Returns the soul for anonymous (API/CLI/scheduled/background) calls so
        AIBA is in-character everywhere. Never includes chain-of-thought, hidden
        prompts, credentials, or internal deliberation.
        """
        parts: list[str] = []
        if self.soul:
            parts.append(self.soul)
        if not user_id:
            return "\n".join(parts)
        profile = self._profile(user_id)
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

    def blocked_tools(self, user_id: str | None) -> set[str]:
        """Tools that must be disabled for a user's conversation.

        When memory is paused, the durable ``remember`` tool is removed from the
        model's toolkit (schema) and rejected at runtime. Anonymous/scheduled
        calls (no user_id) have no per-user pause and are unaffected.
        """
        if not user_id:
            return set()
        if self._profile(user_id).get("memory_active") is False:
            return {"remember"}
        return set()

    def load(self, user_id: str) -> dict:
        """Return a shallow copy of a user's profile (for tests / inspection)."""
        return dict(self._profile(user_id))


_DEFAULT_SOUL = (
    "AIBA is a calm, capable, playful personal assistant that helps people turn "
    "ideas into action. Warm, curious, confident, and honest. Simple on the "
    "surface and powerful underneath."
)
