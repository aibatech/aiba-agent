"""Advisory outcome learning with an explicit, content-bound owner review."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from skills.manager import SkillManager
from tools.registry import _valid


class SkillImprover:
    def __init__(self, manager: SkillManager, proposals_dir: Path):
        self.manager = manager
        self.proposals_dir = proposals_dir
        proposals_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task_id):
            raise ValueError('Invalid proposal identifier')
        path = self.proposals_dir / f'{task_id}.json'
        if path.is_symlink():
            raise ValueError('Proposal symlinks are forbidden')
        return path

    def _load(self, path: Path) -> dict:
        if path.parent.resolve() != self.proposals_dir.resolve() or self._path(path.stem) != path:
            raise ValueError('Proposal must belong to the proposal directory')
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def _digest(data: dict) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def propose(self, task_id: str, task: str, tools: list[str], result: str) -> Path:
        proposal = {'task_id': task_id, 'name': f'learned-{task_id[:8]}',
                    'description': f'Draft learned from: {task[:160]}',
                    'status': 'requires_review', 'executable': False,
                    'observed_tools': list(tools), 'steps': [], 'result_excerpt': result[:500]}
        path = self._path(task_id)
        # Do not overwrite an existing owner-reviewed proposal.
        with path.open('x', encoding='utf-8') as stream:
            json.dump(proposal, stream, indent=2)
        return path

    def review(self, task_id: str, steps: list[dict], registry, feedback: str = '', version: str = '0.1.0') -> dict:
        path = self._path(task_id)
        data = self._load(path)
        if not steps:
            raise ValueError('Review requires executable steps with explicit arguments')
        for step in steps:
            if not isinstance(step, dict) or set(step) != {'tool', 'arguments'}:
                raise ValueError('Each reviewed step requires only tool and arguments')
            name = step['tool']
            if not isinstance(name, str) or registry._availability(name):
                raise ValueError(f'Unavailable tool: {name}')
            if not isinstance(step['arguments'], dict) or not _valid(step['arguments'], registry._tools[name].parameters):
                raise ValueError(f'Invalid arguments for {name}')
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', version):
            raise ValueError('Invalid skill version')
        data.update(steps=steps, feedback=feedback, version=version, status='reviewed', executable=True)
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return {'proposal': data, 'review_digest': self._digest(data)}

    def approve(self, proposal_path: Path, reviewed_digest: str | None = None):
        data = self._load(proposal_path)
        if (data.get('status') != 'reviewed' or not data.get('executable') or not data.get('steps')
                or reviewed_digest != self._digest(data)):
            raise ValueError('Explicit approval of the exact reviewed proposal is required')
        skill = self.manager.create(data['name'], data['description'], data['steps'], data['version'])
        data['status'] = 'installed'
        proposal_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return skill
