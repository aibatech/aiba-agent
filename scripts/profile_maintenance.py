"""Offline backup/restore and explicit legacy memory attribution."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.backup import BackupManager
from privacy.legacy import LegacyMemoryReview

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-dir',required=True);p.add_argument('--skills-dir')
    p.add_argument('operation',choices=['backup','verify','restore','legacy-preview','legacy-assign'])
    p.add_argument('--backup-id');p.add_argument('--confirm');p.add_argument('--database',default='memory.db');p.add_argument('--assignments',help='JSON file mapping reviewed record IDs to exact owner IDs')
    a=p.parse_args()
    if a.operation.startswith('legacy'):
        review=LegacyMemoryReview(a.data_dir,a.database)
        result=review.preview() if a.operation=='legacy-preview' else review.assign(json.loads(Path(a.assignments).read_text()),a.confirm)
    else:
        backups=BackupManager(Path(a.data_dir),Path(a.skills_dir) if a.skills_dir else None)
        result=backups.create() if a.operation=='backup' else backups.verify(a.backup_id) if a.operation=='verify' else backups.restore(a.backup_id,a.confirm)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
