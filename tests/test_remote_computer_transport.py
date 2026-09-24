import unittest
from computer.remote_transport import RemoteNodeTransport, RemoteNodeRequestVerifier, sign_request, verify_request

class RemoteNodeTransportTests(unittest.TestCase):
    def test_signature_binds_method_path_body_nonce_and_time(self):
        token="x"*40; body=b'{"action":"screen"}'; ts=1000; nonce="n1"
        sig=sign_request(token,"POST","/v1/action",body,ts,nonce)
        self.assertTrue(verify_request(token,"POST","/v1/action",body,ts,nonce,sig,now=1000))
        self.assertFalse(verify_request(token,"POST","/v1/action",b"{}",ts,nonce,sig,now=1000))
        self.assertFalse(verify_request(token,"POST","/v1/action",body,ts,"n2",sig,now=1000))
        self.assertFalse(verify_request(token,"POST","/v1/action",body,ts,nonce,sig,now=1200))

    def test_server_verifier_rejects_nonce_replay(self):
        token="x"*40;body=b'{}';ts=1000;nonce="once";sig=sign_request(token,"POST","/v1/action",body,ts,nonce);v=RemoteNodeRequestVerifier(token)
        self.assertTrue(v.verify("POST","/v1/action",body,str(ts),nonce,sig,now=1000))
        self.assertFalse(v.verify("POST","/v1/action",body,str(ts),nonce,sig,now=1000))

    def test_transport_requires_https_and_strong_token(self):
        with self.assertRaises(ValueError):RemoteNodeTransport("http://node.test","x"*40)
        with self.assertRaises(ValueError):RemoteNodeTransport("https://node.test","short")

if __name__=="__main__":unittest.main()
