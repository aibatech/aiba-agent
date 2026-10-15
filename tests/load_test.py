"""Dependency-free HTTP concurrency/soak gate for a running AIBA instance."""
import argparse,concurrent.futures,json,math,threading,time,urllib.request
from collections import Counter
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8765/health');p.add_argument('--requests',type=int,default=1000);p.add_argument('--concurrency',type=int,default=25);p.add_argument('--duration',type=int,default=0);p.add_argument('--p95-ms',type=float,default=500);p.add_argument('--output');args=p.parse_args()
    if args.requests<1 or args.concurrency<1 or args.duration<0:p.error('requests/concurrency must be positive and duration nonnegative')
    histogram=Counter();errors=[];error_count=0;successes=0;maximum=0.0;lock=threading.Lock();deadline=time.monotonic()+args.duration if args.duration else None
    def once(_):
        nonlocal error_count,successes,maximum
        started=time.monotonic()
        try:
            with urllib.request.urlopen(args.url,timeout=10) as r:
                if r.status!=200:raise RuntimeError(f'HTTP {r.status}')
        except Exception as exc:
            with lock:
                error_count+=1
                if len(errors)<5:errors.append(type(exc).__name__)
        else:
            latency=(time.monotonic()-started)*1000
            with lock:
                successes+=1;maximum=max(maximum,latency)
                histogram[min(60000,math.ceil(latency))]+=1
    total=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        while total<args.requests or (deadline and time.monotonic()<deadline):
            batch=min(args.concurrency,args.requests-total) if not deadline else args.concurrency
            list(pool.map(once,range(batch)));total+=batch
            if not deadline and total>=args.requests:break
    def percentile(fraction):
        if not successes:return None
        target=math.ceil(successes*fraction);count=0
        for bucket,frequency in sorted(histogram.items()):
            count+=frequency
            if count>=target:return bucket
    p95=percentile(.95)
    result={'requests':total,'successes':successes,'errors':error_count,'sample_errors':errors,
            'p50_ms':percentile(.50),'p95_ms':p95,'max_ms':maximum if successes else None,
            'percentile_resolution_ms':1,'percentile_overflow_bucket_ms':60000}
    rendered=json.dumps(result,indent=2);print(rendered)
    if args.output:Path(args.output).write_text(rendered+'\n',encoding='utf-8')
    raise SystemExit(0 if error_count==0 and p95 is not None and p95<=args.p95_ms else 1)
if __name__=='__main__':main()
