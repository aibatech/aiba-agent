"""Run HTTP load against an isolated real runtime; never touches owner data."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import threading


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--soak-seconds',type=int,default=0)
    parser.add_argument('--output',default='certification/runtime-load.json')
    args=parser.parse_args()
    if args.soak_seconds < 0: parser.error('soak-seconds must be nonnegative')
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='aiba-cert-') as tmp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'AIBA_ROOT':str(root),'AIBA_DATA_DIR':tmp,
             'AIBA_API_TOKEN':secrets.token_urlsafe(48),'AIBA_MASTER_KEY':secrets.token_urlsafe(48),
             'AIBA_WORKER_ENABLED':'false','AIBA_API_PORT':str(port),'AIBA_API_HOST':'127.0.0.1'}
        with open(Path(tmp)/'server.log','w') as log:
            process=subprocess.Popen([sys.executable,'main.py','--serve'],cwd=root,env=env,stdout=log,stderr=log)
            try:
                url=f'http://127.0.0.1:{port}/health'
                for _ in range(100):
                    if process.poll() is not None:raise RuntimeError('Isolated API exited during startup')
                    try:
                        with urllib.request.urlopen(url,timeout=1) as response:
                            if response.status==200:break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError('Isolated API startup timed out')
                output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
                command=[sys.executable,'tests/load_test.py','--url',url,'--requests','1000','--concurrency','25','--output',str(output)]
                if args.soak_seconds:command+=['--duration',str(args.soak_seconds)]
                samples=[]; stop=threading.Event(); started=time.monotonic()
                def sample_memory():
                    while not stop.is_set():
                        try:
                            lines=Path(f'/proc/{process.pid}/status').read_text().splitlines()
                            rss=next(int(line.split()[1])*1024 for line in lines if line.startswith('VmRSS:'))
                            samples.append({'seconds':round(time.monotonic()-started,2),'rss_bytes':rss})
                        except (OSError,StopIteration,ValueError):
                            pass
                        stop.wait(1)
                monitor=threading.Thread(target=sample_memory,daemon=True);monitor.start()
                try:result=subprocess.run(command,cwd=root,check=False)
                finally:stop.set();monitor.join(timeout=2)
                report=json.loads(output.read_text())
                warm=[s['rss_bytes'] for s in samples if s['seconds']>=60]
                growth=(max(warm)-min(warm)) if warm else None
                report.update(elapsed_seconds=round(time.monotonic()-started,2),
                    commit=os.getenv('GITHUB_SHA'),memory_samples=samples,
                    rss_growth_after_warmup_bytes=growth,rss_growth_budget_bytes=64*1024*1024,
                    scope='Isolated HTTP health endpoint; no live model/task or device certification')
                report['soak_passed']=bool(args.soak_seconds>=3600 and report['elapsed_seconds']>=3600
                    and result.returncode==0 and growth is not None and growth<=64*1024*1024)
                output.write_text(json.dumps(report,indent=2)+'\n')
                if args.soak_seconds>=3600 and not report['soak_passed']:return 1
                return result.returncode
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':raise SystemExit(main())
