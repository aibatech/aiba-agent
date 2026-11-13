from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

class DreamEngine:
    def __init__(self, reflections_dir: Path, vault):
        self.dir = reflections_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.vault = vault

    def reflect(self, task_id: str, task: str, answer: str, tools_used: list[str], owner: str = "default", status: str = "complete"):
        now = datetime.now(timezone.utc)
        record = {
            "task_id": task_id,
            "created_at": now.isoformat(),
            "owner": owner,
            "status": status,
            "tools_used": tools_used,
        }
        stem = now.strftime("%Y%m%dT%H%M%S%f")
        json_path = self.dir / f"{stem}.json"
        # Reflection is operational metadata, not an indefinite copy of dialogue.
        # Durable facts are selected separately by the owner-scoped learner.
        json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        return json_path
