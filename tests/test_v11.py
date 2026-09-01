import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from models.credentials import CredentialCipher,CredentialError
from models.management import ProviderStore,PROVIDER_PRESETS
from models.intelligent_router import IntelligentRouter,classify_task

class FakeAdapter:
    def __init__(self,result=None,error=None,tokens=None):self.result=result or {'type':'final','response':'ok'};self.error=error;self.last_usage=tokens or {'prompt_tokens':100,'completion_tokens':50}
    def complete(self,messages,tools):
        if self.error:raise RuntimeError(self.error)
        return self.result

class V11Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=ProviderStore(Path(self.tmp.name)/'providers.db',CredentialCipher('test-master-key'))
    def tearDown(self):self.tmp.cleanup()
    def test_all_major_provider_presets_exist(self):
        expected={'openai','anthropic','google','xai','openrouter','groq','mistral','deepseek','together','perplexity','azure_openai','aws_bedrock','ollama','lmstudio','custom'}
        self.assertTrue(expected.issubset(PROVIDER_PRESETS))
    def test_credentials_encrypt_and_never_list_plaintext(self):
        i=self.store.add_provider('Primary','openai',api_key='super-secret')
        listed=self.store.get_provider(i)
        self.assertTrue(listed['has_api_key']);self.assertNotIn('api_key',listed)
        self.assertEqual(self.store.get_key(i),'super-secret')
        self.assertNotIn(b'super-secret',(Path(self.tmp.name)/'providers.db').read_bytes())
    def test_missing_master_key_rejects_stored_secret(self):
        store=ProviderStore(Path(self.tmp.name)/'other.db',CredentialCipher(''))
        with self.assertRaises(CredentialError):store.add_provider('X','openai',api_key='secret')
    def test_models_rules_and_cost_routing(self):
        p=self.store.add_provider('OpenAI','openai');expensive=self.store.add_model(p,'quality','Quality',['text','tools'],price_input=10,price_output=20);cheap=self.store.add_model(p,'cheap','Cheap',['text','tools'],price_input=.1,price_output=.2)
        self.store.set_rule('default','cost',['text','tools'])
        self.assertEqual(IntelligentRouter(self.store).candidates()[0]['id'],cheap)
    def test_failover_health_and_usage(self):
        p1=self.store.add_provider('One','openai',priority=1);p2=self.store.add_provider('Two','openai',priority=2)
        self.store.add_model(p1,'bad',capabilities=['text','tools']);self.store.add_model(p2,'good',capabilities=['text','tools'])
        router=IntelligentRouter(self.store);calls=[]
        def factory(provider,model,key):calls.append(model['model_id']);return FakeAdapter(error='down') if model['model_id']=='bad' else FakeAdapter()
        with patch('models.intelligent_router.build_managed_provider',side_effect=factory):result=router.complete([{'role':'user','content':'hello'}],[])
        self.assertEqual(result['response'],'ok');self.assertEqual(calls,['bad','good']);self.assertEqual(self.store.usage_summary()['totals']['requests'],2)
    def test_classifier(self):
        self.assertEqual(classify_task([{'role':'user','content':'Debug this Python API'}]),'coding')

if __name__=='__main__':unittest.main()
