"""Offline operator preview/confirmation for scoped runtime-record deletion."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy.erasure import OwnerErasure

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--confirm', help='Exact confirmation digest from the current preview')
    parser.add_argument('--include-backups',action='store_true',help='Review and redact attributed records from retained local backups')
    parser.add_argument('--resume',action='store_true',help='Resume the already approved interrupted operation for this owner')
    args=parser.parse_args();operation=OwnerErasure(args.data_dir,include_backups=args.include_backups)
    result=operation.resume(args.owner) if args.resume else (operation.erase(args.owner,args.confirm) if args.confirm else operation.preview(args.owner))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
