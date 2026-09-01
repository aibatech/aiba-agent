import json,os,platform,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
checks=[]
def run(name,command):
    result=subprocess.run(command,cwd=root,text=True,capture_output=True);checks.append({'name':name,'passed':result.returncode==0,'output':(result.stdout+result.stderr)[-2000:]})
run('compile',[sys.executable,'-m','compileall','-q','.']);run('unit-tests',[sys.executable,'-m','unittest','discover','-s','tests'])
with tempfile.TemporaryDirectory() as tmp:
    env={**os.environ,'AIBA_ROOT':str(root),'AIBA_DATA_DIR':str(Path(tmp)/'data'),'AIBA_API_TOKEN':'x'*48,'AIBA_MASTER_KEY':'y'*48,'AIBA_WORKER_ENABLED':'false'}
    result=subprocess.run([sys.executable,str(root/'main.py'),'--doctor'],cwd=root,env=env,text=True,capture_output=True);checks.append({'name':'clean-profile-startup','passed':result.returncode==0,'output':(result.stdout+result.stderr)[-2000:]})
report={'platform':platform.platform(),'python':platform.python_version(),'checks':checks,'certified':all(x['passed'] for x in checks)};out=root/'certification';out.mkdir(exist_ok=True);(out/f'{platform.system().lower()}-{platform.machine().lower()}.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));raise SystemExit(0 if report['certified'] else 1)
