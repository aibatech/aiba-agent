"""Scoped empirical skill outcomes; no prompts, arguments, or tool output retained."""
from __future__ import annotations
import hashlib
import json
import time
from sqlite_utils import connect


class SkillOutcomes:
    def __init__(self, path):
        self.path=path
        path.parent.mkdir(parents=True,exist_ok=True)
        with connect(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS skill_runs(
                id INTEGER PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                version TEXT NOT NULL, digest TEXT NOT NULL, success INTEGER NOT NULL,
                tool_calls INTEGER NOT NULL, verified_steps INTEGER NOT NULL,
                elapsed_ms REAL NOT NULL, created_at REAL NOT NULL)''')

    def record(self, owner, skill, outputs, elapsed_ms):
        digest=hashlib.sha256(json.dumps(skill.steps,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        success=bool(outputs) and len(outputs)==len(skill.steps) and all(row['ok'] for row in outputs)
        with connect(self.path) as db:
            db.execute('INSERT INTO skill_runs(owner,name,version,digest,success,tool_calls,verified_steps,elapsed_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (owner,skill.name,skill.version,digest,int(success),len(outputs),sum(row.get('verified') is True for row in outputs),elapsed_ms,time.time()))

    def summary(self, owner, name):
        with connect(self.path) as db:
            rows=db.execute('''SELECT version,digest,COUNT(*),SUM(success),AVG(tool_calls),AVG(elapsed_ms),SUM(verified_steps)
                FROM skill_runs WHERE owner=? AND name=? GROUP BY version,digest ORDER BY MIN(id)''',(owner,name)).fetchall()
        return [{'version':r[0],'digest':r[1],'runs':r[2],'successes':r[3],'success_rate':r[3]/r[2],
                 'mean_tool_calls':r[4],'mean_elapsed_ms':r[5],'verified_steps':r[6]} for r in rows]

    def compare(self, owner, name, baseline_digest, candidate_digest):
        summaries={row['digest']:row for row in self.summary(owner,name)}
        if baseline_digest==candidate_digest:raise ValueError('Distinct baseline and candidate required')
        if baseline_digest not in summaries or candidate_digest not in summaries:
            raise ValueError('Both workflows must have observed runs for this owner')
        baseline=summaries[baseline_digest];candidate=summaries[candidate_digest]
        return {'baseline':baseline,'candidate':candidate,
            'success_rate_delta':candidate['success_rate']-baseline['success_rate'],
            'mean_tool_calls_delta':candidate['mean_tool_calls']-baseline['mean_tool_calls'],
            'mean_elapsed_ms_delta':candidate['mean_elapsed_ms']-baseline['mean_elapsed_ms'],
            'certified_improvement':False,
            'limitation':'Observed runs may differ in task difficulty. Use a matched acceptance corpus before promotion; no automatic installation or privilege change.'}
