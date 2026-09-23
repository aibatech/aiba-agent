import socket, threading, unittest
from security.egress_proxy import EgressDenied, PinnedEgressProxy, resolve_pinned

class BrowserEgressTests(unittest.TestCase):
    def test_rebinding_private_answer_is_denied_at_connection_layer(self):
        calls={"n":0}
        def resolver(host,port,type=socket.SOCK_STREAM):
            calls["n"]+=1
            ip="93.184.216.34" if calls["n"]==1 else "127.0.0.1"
            return [(socket.AF_INET,socket.SOCK_STREAM,6,"",(ip,port))]
        self.assertEqual(resolve_pinned("rebind.test",443,resolver),"93.184.216.34")
        with self.assertRaises(EgressDenied):
            resolve_pinned("rebind.test",443,resolver)

    def test_proxy_is_loopback_only_and_ephemeral(self):
        p=PinnedEgressProxy(lambda h,p,type=socket.SOCK_STREAM: [(socket.AF_INET,socket.SOCK_STREAM,6,"",("93.184.216.34",p))])
        url=p.start()
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        p.close()

if __name__=="__main__":unittest.main()
