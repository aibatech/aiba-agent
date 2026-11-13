"""Advisory outcome learning with an explicit, content-bound owner review."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from skills.manager import SkillManager
from tools.registry import _valid

FORBIDDEN_SKILL_TOOLS = {'run_skill', 'create_skill', 'approve_skill', 'install_skill', 'update_security_policy', 'approve_operation'}


class SkillImprover:
    def __init__(self, manager: SkillManager, proposals_dir: Path, tasks=None):
        self.manager = manager
        self.proposals_dir = proposals_dir
        proposals_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = tasks

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
    def _digest(data: object) -> str:
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
        self._validate_evidence(data)
        if not steps:
            raise ValueError('Review requires executable steps with explicit arguments')
        for step in steps:
            if not isinstance(step, dict) or set(step) != {'tool', 'arguments'}:
                raise ValueError('Each reviewed step requires only tool and arguments')
            name = step['tool']
            if name in FORBIDDEN_SKILL_TOOLS:
                raise ValueError('Skills cannot install, approve, change policy, or recursively execute skills')
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
        self._validate_evidence(data)
        if (data.get('status') != 'reviewed' or not data.get('executable') or not data.get('steps')
                or reviewed_digest != self._digest(data)):
            raise ValueError('Explicit approval of the exact reviewed proposal is required')
        skill = self.manager.create(data['name'], data['description'], data['steps'], data['version'])
        data['status'] = 'installed'
        proposal_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return skill

    def _evidence(self, task_id, tasks, owner):
        task=tasks.get(task_id)
        if not task or task.get('owner') != owner or task['status'] != 'complete':
            raise ValueError('A completed task belonging to this owner is required')
        def signature(row):
            events=json.loads(row['events'])
            results=[e['tool_result'] for e in events if 'tool_result' in e]
            if not results or any(not r.get('ok') or r.get('verified') is not True for r in results):return None
            return [r['tool'] for r in results]
        observed=signature(task)
        if not observed:raise ValueError('Verified action outcomes are required')
        from sqlite_utils import connect
        import sqlite3
        with connect(tasks.path) as db:
            db.row_factory=sqlite3.Row
            feedback=db.execute('SELECT * FROM task_feedback WHERE task_id=? AND owner=?',(task_id,owner)).fetchone()
            if not feedback or not feedback['accepted']:raise ValueError('Explicit accepted workflow feedback required')
            rows=db.execute('''SELECT t.*,f.workflow_id,f.accepted,f.note,f.updated_at AS feedback_at
                FROM tasks t JOIN task_feedback f ON f.task_id=t.id AND f.owner=t.owner
                WHERE t.owner=? AND f.workflow_id=? ORDER BY t.created_at DESC,t.id LIMIT 100''',
                (owner,feedback['workflow_id'])).fetchall()
        if any(not r['accepted'] or r['status']!='complete' or signature(r)!=observed for r in rows):
            raise ValueError('Workflow has rejected, unverified or divergent outcomes; resolve feedback before proposing')
        matches=[r['id'] for r in rows if signature(r)==observed]
        if len(matches)<3:raise ValueError('At least three matched verified task outcomes are required')
        return task,observed,matches,feedback['workflow_id'],self._digest([dict(r) for r in rows])

    def _validate_evidence(self,data):
        if 'evidence_digest' not in data:return
        if self.tasks is None:raise ValueError('Outcome store required to revalidate learned evidence')
        *_,digest=self._evidence(data['task_id'],self.tasks,data['owner'])
        if digest!=data['evidence_digest']:raise ValueError('Workflow evidence changed; repeat proposal and review')

    def propose_from_outcomes(self, task_id, tasks, owner, feedback=''):
        """Require explicit matching intent, accepted feedback and verified outcomes.

        No arguments are inferred. All proposals remain advisory until reviewed.
        """
        if self.tasks is not None and self.tasks.path.resolve()!=tasks.path.resolve():raise ValueError('Unexpected task outcome store')
        self.tasks=tasks
        task,observed,matches,workflow,digest=self._evidence(task_id,tasks,owner)
        path=self._path(task_id)
        if path.exists():
            data=self._load(path)
            if data.get('status')!='requires_review' or data.get('executable') or data.get('steps'):
                raise ValueError('Evidence enrichment cannot overwrite an owner-reviewed proposal')
        else:
            path=self.propose(task_id,task['input'],observed,'Repeated verified workflow; owner review required')
            data=self._load(path)
        data.update(owner=owner,evidence_task_ids=matches,feedback=feedback,workflow_id=workflow,evidence_digest=digest,
                    evidence_limit='Owner-labeled intent and accepted outcomes do not infer safe arguments or certify general improvement')
        path.write_text(json.dumps(data,indent=2),encoding='utf-8')
        return path
