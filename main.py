from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from config.env import load_env
from onboarding import SetupManager
from agent.loop import AgentLoop


def _maybe_capability_cli(argv: list[str] | None = None) -> int | None:
    """If the user typed ``aiba tools|nodes|mcp|sessions|subagents``, route to
    the Phase 11 capability-management CLI and return its exit code. Otherwise
    return None so main() falls through to the legacy flat-flag surface."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"tools", "nodes", "mcp", "sessions", "subagents"}:
        from cli.capability import dispatch
        return dispatch(argv)
    return None


def main():
    routed = _maybe_capability_cli()
    if routed is not None:
        raise SystemExit(routed)
    p=argparse.ArgumentParser(description='AIBA Agent v1.5')
    p.add_argument('--prompt');p.add_argument('--yes',action='store_true')
    p.add_argument('--serve',action='store_true');p.add_argument('--telegram',action='store_true')
    p.add_argument('--host');p.add_argument('--port',type=int)
    p.add_argument('--worker-once',action='store_true');p.add_argument('--setup',action='store_true')
    p.add_argument('--doctor',action='store_true');p.add_argument('--verify',action='store_true')
    p.add_argument('--live-provider',action='store_true',help='with --verify, also run a harmless live provider request')
    p.add_argument('--update-check',action='store_true');p.add_argument('--update-stage',action='store_true')
    p.add_argument('--backup',action='store_true');p.add_argument('--migrate',action='store_true')
    p.add_argument('--verify-backup');p.add_argument('--restore-backup');p.add_argument('--confirm-restore')
    p.add_argument('--computer-pair',action='store_true',help='Pair a local computer node for opt-in desktop control')
    p.add_argument('--computer-name',default='local-computer',help='Node name used when pairing')
    p.add_argument('--computer-status',action='store_true',help='Show computer-node pairing/enable/budget status')
    p.add_argument('--computer-enable',action='store_true',help='Enable desktop control once a node is paired')
    p.add_argument('--computer-disable',action='store_true',help='Disable desktop control')
    p.add_argument('--computer-stop',action='store_true',help='Emergency-stop desktop control')
    p.add_argument('--computer-reset-budget',action='store_true',help='Reset the desktop action budget')
    args=p.parse_args()
    source_root=Path(__file__).resolve().parent;load_env(source_root/'.env')
    # `aiba --verify` tests the *live* service over HTTP; it must NOT spin up a second AgentLoop.
    if args.verify:
        from diagnostics.verify import main as verify_main
        raise SystemExit(verify_main(['--live-provider'] if args.live_provider else []))
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
    elif args.computer_pair:
        cap=['screen','mouse','keyboard','scroll','open_url']
        token=agent.computer_node.pair(args.computer_name, capabilities=cap)
        print(json.dumps({'paired':True,'node':args.computer_name,
                          'store':str(agent.computer_node.store_path),
                          'node_token_use_once':token,
                          'next':'run aiba --computer-enable then enable the desktop_* permission entries'}))
        agent.close()
    elif args.computer_status:
        try:
            print(json.dumps(agent.computer_node.status(),indent=2))
        except Exception as exc:
            print(json.dumps({'error':str(exc)}))
        agent.close()
    elif args.computer_enable:
        try:
            agent.computer_node.enable();print(json.dumps({'enabled':agent.computer_node.enabled}))
        except Exception as exc:
            print(json.dumps({'error':str(exc)}))
        agent.close()
    elif args.computer_disable:
        agent.computer_node.disable();print(json.dumps({'enabled':agent.computer_node.enabled}));agent.close()
    elif args.computer_stop:
        agent.computer_node.emergency_stop();print(json.dumps({'emergency_stopped':True}));agent.close()
    elif args.computer_reset_budget:
        agent.computer_node.reset_budget();print(json.dumps(agent.computer_node.budget_status()));agent.close()
    elif args.serve:
        from api.server import run_server;run_server(agent,args.host,args.port)
    elif args.telegram:
        from connectors import TelegramConnector;TelegramConnector(agent).run();agent.close()
    elif args.worker_once:print('processed' if agent.worker.run_once() else 'no queued jobs')
    elif args.prompt:print(agent.handle(args.prompt))
    else:agent.run()
if __name__=='__main__':main()
