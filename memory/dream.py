from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

class DreamEngine:
    def __init__(self, reflections_dir: Path, vault):
        self.dir = reflections_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.vault = vault

    def reflect(self, task_id: str, task: str, answer: str, tools_used: list[str]):
        now = datetime.now(timezone.utc)
        record = {
            "task_id": task_id,
            "created_at": now.isoformat(),
            "task": task,
            "answer": answer,
            "tools_used": tools_used,
        }
        stem = now.strftime("%Y%m%dT%H%M%S%f")
        json_path = self.dir / f"{stem}.json"
        md_path = self.dir / f"{stem}.md"
        json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(
            f"# Task Reflection\n\n- Task ID: {task_id}\n- Created: {now.isoformat()}\n"
            f"- Tools: {', '.join(tools_used) or 'None'}\n\n## Task\n{task}\n\n## Result\n{answer}\n",
            encoding="utf-8",
        )
        self.vault.sync_markdown()
        return json_path
