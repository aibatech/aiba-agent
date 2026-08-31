from __future__ import annotations
import os,sys
from pathlib import Path
from config.env import load_env
from updates import UpdateManager

def main():
    root=Path(__file__).resolve().parent;load_env(root/'.env');manager=UpdateManager(root,Path(os.getenv('AIBA_DATA_DIR',root/'agent_system')))
    result=manager.apply_staged()
    if result.get('applied'):print(f"Applied AIBA Agent {result['version']} safely. Starting updated version...")
    os.execv(sys.executable,[sys.executable,str(root/'main.py'),*sys.argv[1:]])
if __name__=='__main__':main()
