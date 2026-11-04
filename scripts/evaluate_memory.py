"""Run the versioned memory corpus with the actual local SentenceTransformer."""
import argparse,hashlib,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memory.semantic import LocalEmbedder
from memory.retrieval import RetrievalEngine
from memory.vault import MemoryVault


def evaluate(corpus,embedder):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);vault=MemoryVault(root/'memory.db',root/'vault');ids={};stale=set()
        for item in corpus['memories']:
            ids[item['key']]=vault.add(item['content'],owner=item['owner'],fact_key=item.get('fact_key'))
        for item in corpus['memories']:
            if item.get('deleted'):
                vault.remove(ids[item['key']],as_user=item['owner']);stale.add(ids[item['key']])
        from sqlite_utils import connect
        with connect(vault.db_path) as db:stale.update(r[0] for r in db.execute('SELECT old_id FROM memory_supersessions'))
        results=[];leaks=stale_hits=budget_errors=0
        for case in corpus['queries']:
            engine=RetrievalEngine(vault,scope=case['owner'],embedder=embedder,char_budget=corpus['char_budget'])
            rows=engine.retrieve(case['text'],3);found=[r['id'] for r in rows];expected={ids[k] for k in case['expected']}
            ranks=[i+1 for i,mid in enumerate(found) if mid in expected]
            leaks+=sum(r['owner']!=case['owner'] for r in rows)
            stale_hits+=len(stale.intersection(found))
            budget_errors+=len(json.dumps(rows,default=str))>corpus['char_budget']
            results.append({'owner':case['owner'],'query':case['text'],'recall_at_3':len(expected.intersection(found))/len(expected),'rr_at_3':1/min(ranks) if ranks else 0,'retrieved_ids':found})
        metrics={'recall_at_3':sum(r['recall_at_3'] for r in results)/len(results),
                 'mrr_at_3':sum(r['rr_at_3'] for r in results)/len(results),'owner_leaks':leaks,'stale_hits':stale_hits,'budget_violations':budget_errors}
        limits=corpus['thresholds']
        passed=all(metrics[k]>=limits[k] for k in ('recall_at_3','mrr_at_3')) and all(metrics[k]==limits[k] for k in ('owner_leaks','stale_hits','budget_violations'))
        return {'metrics':metrics,'cases':results,'passed':passed}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',default=os.getenv('AIBA_MEMORY_EMBEDDING_MODEL',''))
    parser.add_argument('--corpus',default=str(Path(__file__).resolve().parents[1]/'benchmarks/memory/v1.json'))
    parser.add_argument('--output',required=True)
    args=parser.parse_args();path=Path(args.corpus);corpus=json.loads(path.read_text())
    report={'corpus_version':corpus['version'],'corpus_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'thresholds':corpus['thresholds'],'passed':False}
    try:
        if not args.model or not Path(args.model).is_dir():raise RuntimeError('Missing reviewed local SentenceTransformer model directory: supply --model PATH and install .[semantic]')
        model=Path(args.model).resolve();hashes=[]
        for file in sorted(model.rglob('*')):
            if file.is_symlink():raise RuntimeError('Model artifact symlinks are unsupported')
            if file.is_file():
                digest=hashlib.sha256()
                with file.open('rb') as stream:
                    while chunk:=stream.read(1024*1024):digest.update(chunk)
                hashes.append((file.relative_to(model).as_posix(),digest.hexdigest()))
        revision=hashlib.sha256(json.dumps(hashes).encode()).hexdigest();os.environ['AIBA_MEMORY_EMBEDDING_REVISION']=revision
        embedder=LocalEmbedder(str(model))
        import importlib.metadata
        report.update(model_id=embedder.model_id,model_files=hashes,sentence_transformers_version=importlib.metadata.version('sentence-transformers'))
        report.update(evaluate(corpus,embedder));report['status']='passed' if report['passed'] else 'failed'
    except (RuntimeError,ImportError,ValueError,OSError) as exc:
        report.update(status='blocked',blocker=str(exc))
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='cases' and k!='model_files'},indent=2))
    return 0 if report['passed'] else 2

if __name__=='__main__':raise SystemExit(main())
