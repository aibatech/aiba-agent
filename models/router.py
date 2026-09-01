from __future__ import annotations
import time
from .provider import LocalProvider,OpenAIProvider,OpenAICompatibleProvider,AnthropicProvider,OllamaProvider,ProviderError
class ModelRouter:
    @staticmethod
    def build(name,model):
        return {'local':LocalProvider,'openai':OpenAIProvider,'openai_compatible':OpenAICompatibleProvider,'anthropic':AnthropicProvider,'ollama':OllamaProvider}[name](model)
    def __init__(self,primary,fallback,retries=2):self.primary=primary;self.fallback=fallback;self.retries=retries
    def complete(self,messages,tools):
        errors=[]
        for provider in (self.primary,self.fallback):
            for attempt in range(self.retries+1):
                try:return provider.complete(messages,tools)
                except ProviderError as e:errors.append(f'{provider.name}: {e}'); time.sleep(0.05*(attempt+1))
        raise ProviderError('; '.join(errors))
