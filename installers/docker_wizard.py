from __future__ import annotations
import os,secrets,shutil,subprocess,time,webbrowser
from pathlib import Path
from config.env import quote_env

def fail(message,fix):print(f'\nERROR: {message}\nFIX: {fix}');raise SystemExit(1)
def main():
    root=Path(__file__).resolve().parents[1];os.chdir(root);print('\nAIBA Agent Docker Installation Wizard')
    if not shutil.which('docker'):fail('Docker was not found.','Install Docker Desktop (Windows/macOS) or Docker Engine plus Compose (Linux), start it, and run this wizard again.')
    check=subprocess.run(['docker','info'],capture_output=True,text=True)
    if check.returncode:fail('Docker is installed but not running.',check.stderr.strip() or 'Start Docker and try again.')
    compose=subprocess.run(['docker','compose','version'],capture_output=True,text=True)
    if compose.returncode:fail('Docker Compose is unavailable.','Update Docker Desktop or install the Docker Compose plugin.')
    env=root/'.env';values={}
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):values[line.split('=',1)[0]]=line.split('=',1)[1]
    token=values.get('AIBA_API_TOKEN','').strip('"') or secrets.token_urlsafe(48);master=values.get('AIBA_MASTER_KEY','').strip('"') or secrets.token_urlsafe(48)
    env.write_text(f'AIBA_API_TOKEN={quote_env(token)}\nAIBA_MASTER_KEY={quote_env(master)}\nAIBA_PROVIDER=local\nAIBA_FALLBACK_PROVIDER=local\n',encoding='utf-8')
    print('Building and starting AIBA...')
    result=subprocess.run(['docker','compose','-f','deployment/docker-compose.yml','--env-file','.env','up','--build','-d'])
    if result.returncode:fail('The AIBA container did not start.','Run `docker compose -f deployment/docker-compose.yml logs` and review the reported error.')
    print('Waiting for the dashboard...')
    import urllib.request
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/ready',timeout=2) as response:
                if response.status==200:break
        except Exception:time.sleep(1)
    else:
        subprocess.run(['docker','compose','-f','deployment/docker-compose.yml','logs','--tail','100']);fail('The container started but AIBA did not become ready.','Review the logs above and run the dashboard diagnosis after correcting the reported issue.')
    url='http://127.0.0.1:8765/#token='+token;webbrowser.open(url);print('AIBA Agent is ready at http://127.0.0.1:8765')
if __name__=='__main__':main()
