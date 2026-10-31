"""Explicit operator attribution of reviewed legacy/shared memories; never inferred."""
import hashlib,json
from pathlib import Path
from sqlite_utils import connect
from operations.maintenance import ProfileLease

class LegacyMemoryReview:
    def __init__(self,data_dir,database='memory.db'):
        self.root=Path(data_dir).resolve()
        if Path(database).name!=database or not database.endswith('.db'):raise ValueError('Use a profile database filename')
        self.path=self.root/database
        if self.path.is_symlink() or not self.path.is_file():raise ValueError('Existing regular database required')

    def _rows(self,db):
        rows=db.execute("SELECT id,content,source_path,metadata FROM memories WHERE owner='shared' OR owner IS NULL ORDER BY id").fetchall()
        return [{'id':r[0],'content':r[1],'source_path':r[2],'metadata':r[3]} for r in rows]

    def preview(self):
        with connect(self.path) as db:rows=self._rows(db)
        return {'records':rows,'confirmation':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),
                'warning':'These records may be genuinely shared. Assign only after reviewing provenance; this operation never guesses ownership.'}

    def assign(self,assignments,confirmation):
        if not isinstance(assignments,dict) or not assignments:raise ValueError('Explicit record-to-owner mapping required')
        with ProfileLease(self.root),connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE');rows=self._rows(db)
            if confirmation!=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest():raise ValueError('Legacy inventory changed; review again')
            by_id={r['id']:r for r in rows}
            if len({int(key) for key in assignments})!=len(assignments):raise ValueError('Duplicate record identifiers')
            for key,owner in assignments.items():
                mid=int(key)
                if mid not in by_id or not isinstance(owner,str) or not owner.strip() or owner=='shared':raise ValueError('Unknown record or invalid explicit owner')
                if json.loads(by_id[mid]['metadata']).get('fact_key'):raise ValueError('Fact-linked legacy records require explicit conflict resolution first')
                db.execute('UPDATE memories SET owner=? WHERE id=?',(owner,mid))
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_embeddings'").fetchone():db.execute('DELETE FROM memory_embeddings WHERE memory_id=?',(mid,))
        return {'assigned':len(assignments)}
