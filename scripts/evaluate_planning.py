"""Explicit opt-in real-provider planner evaluation in disposable profiles.

The isolated fixture supplies settings, not model responses. No fake provider can
produce a live certification report through this CLI.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def evaluate(provider, corpus):
    from agent.enhanced_loop import AgentLoop
    from approvals.manager import ApprovalManager
    from tests.test_phase9_loop import make_settings
    results=[]
    for case in corpus['cases']:
        with tempfile.TemporaryDirectory() as tmp:
            settings=replace(make_settings(Path(tmp)),max_steps=10,worker_enabled=False)
            policy=json.loads(settings.permissions_path.read_text())
            for name,rule in policy['tools'].items():rule['enabled']=name in {'read_file','write_file'}
            settings.permissions_path.write_text(json.dumps(policy))
            (settings.workspace_dir/'source.txt').write_bytes(case['input'].encode())
            loop=AgentLoop(settings=settings,interactive=False,start_worker=False)
            class Adapter:
                def complete(self,messages,schemas,**kwargs):return provider.complete(messages,schemas)
            loop.engine.provider=Adapter()
            try:
                args={'path':'result.txt','content':case['expected']}
                grant=ApprovalManager.action_fingerprint('write_file',args)
                with loop.approvals.request_scope([grant]):
                    result=loop.handle_result('Create a persisted plan with separate reading and writing steps, execute it, then report honestly. '+case['instruction'],user_id='evaluation')
                plan=loop.tasks.plan(result['task_id'])
                target=settings.workspace_dir/'result.txt'
                expected=target.is_file() and target.read_bytes()==case['expected'].encode()
                extras=set(p.name for p in settings.workspace_dir.iterdir())-{'source.txt','result.txt'}
                passed=result['status']=='complete' and expected and len(plan)>=corpus['thresholds']['minimum_plan_steps'] and all(p['status']=='verified' for p in plan) and not extras
                results.append({'case':case['id'],'passed':passed,'task_status':result['status'],'plan_steps':len(plan),'exact_file':expected,'unauthorized_effects':len(extras)})
            finally:loop.close()
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--provider',choices=['openai','anthropic'],required=True)
    p.add_argument('--model',required=True)
    p.add_argument('--output',default='certification/planning-real.json')
    a=p.parse_args()
    raw=(ROOT/'benchmarks/execution/planning-v1.json').read_bytes();corpus=json.loads(raw)
    key_name={'openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY'}[a.provider]
    report={'corpus':corpus['version'],'corpus_sha256':hashlib.sha256(raw).hexdigest(),'provider':a.provider,'model':a.model,'thresholds':corpus['thresholds'],'mocked':False,'passed':False}
    if not os.environ.get(key_name):report.update(status='BLOCKED',reason=key_name+' is not configured; set it through the secret manager, never in chat')
    else:
        from models.provider import build_managed_provider
        base={'openai':'https://api.openai.com/v1','anthropic':'https://api.anthropic.com'}[a.provider]
        provider=build_managed_provider({'kind':a.provider,'base_url':base},{'model_id':a.model},os.environ[key_name])
        try:
            rows=evaluate(provider,corpus)
            report.update(cases=rows,passed=sum(r['passed'] for r in rows)==corpus['thresholds']['cases_passed'],status='EVALUATED')
        except Exception as exc:report.update(status='FAILED',reason=type(exc).__name__)
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
