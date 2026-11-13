"""Live read-only retrieval rehearsal. Never substitutes mocks or search tools."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import hashlib
import json
import platform
from datetime import datetime,timezone
from tools.web import WebTools


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='certification/live-web.json')
    parser.add_argument('--research',action='store_true',help='Require actual search-provider discovery and grounded extraction')
    args=parser.parse_args()
    target='https://github.com/aibatech/aiba-agent'
    result=WebTools().web_extract([target],limit_per_page=20000)
    pages=(result.output or {}).get('pages',[])
    page=pages[0] if pages else {}
    text=page.get('text','')
    passed=bool(result.ok and result.verified and page.get('status')==200 and 'aiba-agent' in text.lower())
    report={'schema_version':1,'observed_at':datetime.now(timezone.utc).isoformat(),
            'python':platform.python_version(),'target':target,'mocked':False,
            'criteria':{'http_status':200,'nonempty_text':True,'contains':'aiba-agent'},
            'passed':passed,'status':page.get('status'), 'text_chars':len(text),
            'text_sha256':hashlib.sha256(text.encode()).hexdigest() if text else None,
            'error':result.error if not result.ok else None,
            'scope':'One live public page; does not certify search ranking or general research quality'}
    if args.research:
        query='Python pathlib official documentation'
        research=WebTools().web_search(query,deep=True,max_sources=2,include_domains=['docs.python.org'])
        sources=(research.output or {}).get('sources',[])
        search_passed=bool(research.ok and research.verified and sources and
                          all(s['domain']=='docs.python.org' and 'pathlib' in s.get('text','').lower() for s in sources))
        report['research']={'query':query,'passed':search_passed,'criteria':{'allowed_domain':'docs.python.org','required_text':'pathlib','minimum_sources':1},
                            'sources':[{'url':s['url'],'status':s['status'],'text_sha256':hashlib.sha256(s.get('text','').encode()).hexdigest()} for s in sources],
                            'error':research.error if not search_passed else None}
        passed=passed and search_passed;report['passed']=passed
        report['scope']='Live extraction plus official-document discovery and source grounding; no universal ranking-quality claim'
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
