from __future__ import annotations
import argparse,webbrowser
from pathlib import Path
from onboarding import SetupManager

def main():
    p=argparse.ArgumentParser(description='Configure AIBA Agent securely');p.add_argument('--no-browser',action='store_true');args=p.parse_args()
    root=Path(__file__).resolve().parent;setup=SetupManager(root,root/'agent_system');result=setup.ensure_configuration()
    url='http://127.0.0.1:8765/#token='+result['api_token']
    print('AIBA security configuration is ready.')
    print('Start AIBA with: python main.py --serve')
    print('Setup URL: '+url)
    if not args.no_browser:
        try:webbrowser.open(url)
        except Exception:pass
if __name__=='__main__':main()
