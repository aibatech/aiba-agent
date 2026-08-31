from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from onboarding import SetupManager
from config.env import load_env
from agent.loop import AgentLoop
def main():
    p=argparse.ArgumentParser(description='AIBA Agent v1.4');p.add_argument('--prompt');p.add_argument('--yes',action='store_true');p.add_argument('--serve',action='store_true');p.add_argument('--telegram',action='store_true');p.add_argument('--host');p.add_argument('--port',type=int);p.add_argument('--worker-once',action='store_true');p.add_argument('--setup',action='store_true');p.add_argument('--doctor',action='store_true');p.add_argument('--update-check',action='store_true');p.add_argument('--update-stage',action='store_true');p.add_argument('--migrate',action='store_true');p.add_argument('--backup',action='store_true');p.add_argument('--verify-backup');p.add_argument('--restore-backup');p.add_argument('--confirm-restore');args=p.parse_args()
    source_root=Path(__file__).resolve().parent;load_env(source_root/'.env')
    root=Path(os.getenv('AIBA_ROOT',source_root)).resolve();data_dir=Path(os.getenv('AIBA_DATA_DIR',root/'agent_system')).resolve()
    if args.setup or args.serve:SetupManager(root,data_dir).ensure_configuration()
    agent=AgentLoop(interactive=not bool(args.prompt or args.serve or args.telegram),auto_approve=args.yes)
    if args.setup:
        result=agent.setup.ensure_configuration();print('Open http://127.0.0.1:8765/#token='+result['api_token']);agent.close()
    elif args.doctor:print(json.dumps(agent.doctor.run(),indent=2));agent.close()
    elif args.update_check:print(json.dumps(agent.updates.check(),indent=2));agent.close()
    elif args.update_stage:print(json.dumps(agent.updates.stage(),indent=2));agent.close()
    elif args.migrate:print(json.dumps(agent.migrations.apply(),indent=2));agent.close()
    elif args.backup:print(json.dumps(agent.backups.create('manual CLI backup'),indent=2));agent.close()
    elif args.verify_backup:print(json.dumps(agent.backups.verify(args.verify_backup),indent=2));agent.close()
    elif args.restore_backup:print(json.dumps(agent.backups.restore(args.restore_backup,args.confirm_restore),indent=2));agent.close()
    elif args.serve:
        from api.server import run_server;run_server(agent,args.host,args.port)
    elif args.telegram:
        from connectors import TelegramConnector;TelegramConnector(agent).run();agent.close()
    elif args.worker_once:print('processed' if agent.worker.run_once() else 'no queued jobs')
    elif args.prompt:print(agent.handle(args.prompt))
    else:agent.run()
if __name__=='__main__':main()
