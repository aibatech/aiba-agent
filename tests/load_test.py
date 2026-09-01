"""Dependency-free HTTP concurrency/soak gate for a running AIBA instance."""
import argparse,concurrent.futures,json,statistics,time,urllib.request
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8765/health');p.add_argument('--requests',type=int,default=1000);p.add_argument('--concurrency',type=int,default=25);p.add_argument('--duration',type=int,default=0);p.add_argument('--p95-ms',type=float,default=500);p.add_argument('--output');args=p.parse_args()
    latencies=[];errors=[];deadline=time.monotonic()+args.duration if args.duration else None
    def once(_):
        started=time.monotonic()
        try:
            with urllib.request.urlopen(args.url,timeout=10) as r:
                if r.status!=200:raise RuntimeError(f'HTTP {r.status}')
        except Exception as exc:errors.append(str(exc))
        else:latencies.append((time.monotonic()-started)*1000)
    total=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        while total<args.requests or (deadline and time.monotonic()<deadline):
            batch=min(args.concurrency,args.requests-total) if not deadline else args.concurrency
            list(pool.map(once,range(batch)));total+=batch
            if not deadline and total>=args.requests:break
    ordered=sorted(latencies);p95=ordered[max(0,int(len(ordered)*.95)-1)] if ordered else float('inf');result={'requests':total,'successes':len(latencies),'errors':len(errors),'sample_errors':errors[:5],'p50_ms':statistics.median(latencies) if latencies else None,'p95_ms':p95,'max_ms':max(latencies) if latencies else None};rendered=json.dumps(result,indent=2);print(rendered)
    if args.output:Path(args.output).write_text(rendered+'\n',encoding='utf-8')
    raise SystemExit(0 if not errors and p95<=args.p95_ms else 1)
if __name__=='__main__':main()
