import json,os,tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from agent.loop import AgentLoop
from api.server import create_app

def main():
    root=Path(__file__).resolve().parents[1];token='t'*48
    with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'AIBA_ROOT':str(root),'AIBA_DATA_DIR':tmp,'AIBA_API_TOKEN':token,'AIBA_MASTER_KEY':'m'*48,'AIBA_WORKER_ENABLED':'false'},clear=False):
        agent=AgentLoop(start_worker=False);client=TestClient(create_app(agent));headers={'Authorization':'Bearer '+token}
        checks=[]
        def check(name,response,status=200):checks.append({'name':name,'passed':response.status_code==status,'status':response.status_code,'body':response.text[:300]})
        check('health',client.get('/health'));check('ready',client.get('/ready'));check('auth-required',client.get('/v1/operations'),401);check('operations',client.get('/v1/operations',headers=headers));check('metrics',client.get('/metrics',headers=headers));backup=client.post('/v1/backups',headers=headers);check('backup-create',backup,201)
        if backup.status_code==201:check('backup-verify',client.post(f"/v1/backups/{backup.json()['backup_id']}/verify",headers=headers))
        agent.close();report={'checks':checks,'passed':all(x['passed'] for x in checks)};rendered=json.dumps(report,indent=2);out=root/'certification';out.mkdir(exist_ok=True);(out/'api-smoke.json').write_text(rendered+'\n');print(rendered);raise SystemExit(0 if report['passed'] else 1)
if __name__=='__main__':main()
