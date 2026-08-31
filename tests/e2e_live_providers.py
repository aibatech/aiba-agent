"""Opt-in live-provider certification. Never runs or spends credits without an explicit provider list."""
import argparse,json,os,tempfile
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--providers',required=True,help='Comma-separated provider kinds explicitly authorized for live calls');args=parser.parse_args()
    requested=[x.strip() for x in args.providers.split(',') if x.strip()]
    models={'openai':('OPENAI_API_KEY',os.getenv('AIBA_TEST_OPENAI_MODEL','gpt-4.1-mini')),'anthropic':('ANTHROPIC_API_KEY',os.getenv('AIBA_TEST_ANTHROPIC_MODEL','claude-3-5-haiku-latest')),'google':('GEMINI_API_KEY',os.getenv('AIBA_TEST_GEMINI_MODEL','gemini-2.0-flash')),'openrouter':('OPENROUTER_API_KEY',os.getenv('AIBA_TEST_OPENROUTER_MODEL','openai/gpt-4.1-mini'))}
    unknown=[x for x in requested if x not in models]
    if unknown:raise SystemExit(f'Unsupported live certification providers: {unknown}')
    from models.management import ProviderStore
    from models.provider import build_managed_provider
    results=[]
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.setdefault('AIBA_MASTER_KEY','live-test-only-master-key-that-is-at-least-32-characters')
        store=ProviderStore(Path(tmp)/'providers.db')
        for kind in requested:
            env,model_id=models[kind];key=os.getenv(env)
            if not key:results.append({'provider':kind,'passed':False,'reason':f'{env} missing'});continue
            provider_id=store.add_provider(kind,kind,api_key_env=env);model={'model_id':model_id};provider=store.get_provider(provider_id)
            try:
                response=build_managed_provider(provider,model,key).complete([{'role':'user','content':'Reply with exactly AIBA_LIVE_OK'}],[])
                text=response.get('response','') if isinstance(response,dict) else str(response);passed='AIBA_LIVE_OK' in text;results.append({'provider':kind,'passed':passed,'response':text[:120]})
            except Exception as exc:results.append({'provider':kind,'passed':False,'reason':f'{type(exc).__name__}: {exc}'})
    print(json.dumps(results,indent=2));raise SystemExit(0 if results and all(x['passed'] for x in results) else 1)
if __name__=='__main__':main()
