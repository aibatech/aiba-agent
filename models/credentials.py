from __future__ import annotations
import base64,hashlib,os

class CredentialError(RuntimeError):pass

class CredentialCipher:
    """Authenticated encryption for provider credentials at rest."""
    def __init__(self,master_key:str|None=None):
        secret=(master_key or os.getenv('AIBA_MASTER_KEY','')).strip()
        self.available=bool(secret);self._fernet=None
        if secret:
            try:from cryptography.fernet import Fernet
            except ImportError as exc:raise CredentialError('Install cryptography to store provider credentials') from exc
            key=base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
            self._fernet=Fernet(key)
    def encrypt(self,value:str)->str:
        if not self._fernet:raise CredentialError('AIBA_MASTER_KEY is required to store API keys')
        return self._fernet.encrypt(value.encode()).decode()
    def decrypt(self,value:str|None)->str|None:
        if not value:return None
        if not self._fernet:raise CredentialError('AIBA_MASTER_KEY is required to decrypt API keys')
        try:return self._fernet.decrypt(value.encode()).decode()
        except Exception as exc:raise CredentialError('Unable to decrypt credential; check AIBA_MASTER_KEY') from exc
