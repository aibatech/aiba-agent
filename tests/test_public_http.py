"""Real transport control flow; only DNS and socket/HTTP boundaries are mocked."""
import io
import socket
import unittest
from unittest.mock import patch, MagicMock
from security.public_http import fetch_public, resolve_target, PinnedHTTPS, PinnedHTTP


def dns(host, port, **kwargs):
    ip='127.0.0.1' if host=='private.test' else '93.184.216.34'
    return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,port))]


class PublicHTTPTests(unittest.TestCase):
    def response(self, status=200, body=b'evidence', headers=None):
        res=MagicMock(status=status);data=io.BytesIO(body)
        res.getheader.side_effect=lambda key,default=None:(headers or {}).get(key,default)
        res.read1.side_effect=data.read
        return res

    def test_private_redirect_is_rejected_before_connecting(self):
        with patch('security.public_http.socket.getaddrinfo',side_effect=dns),patch('security.public_http.PinnedHTTPS') as cls:
            cls.return_value.getresponse.return_value=self.response(302,headers={'Location':'http://private.test/secret'})
            with self.assertRaises(ValueError):fetch_public('https://public.test')
            self.assertEqual(cls.call_count,1);cls.return_value.close.assert_called_once()

    def test_connect_uses_validated_ip_and_tls_original_hostname(self):
        with patch('security.public_http.socket.create_connection') as connect:
            http=PinnedHTTP('public.test',80,'93.184.216.34',5)
            http.connect();connect.assert_called_with(('93.184.216.34',80),5)
            tls=PinnedHTTPS('public.test',443,'93.184.216.34',5)
            with patch.object(tls._context,'wrap_socket',return_value=MagicMock()) as wrap:
                tls.connect();connect.assert_called_with(('93.184.216.34',443),5)
                self.assertEqual(wrap.call_args.kwargs['server_hostname'],'public.test')

    def test_empty_mixed_private_and_credential_targets_fail_closed(self):
        for addresses in [[],dns('private.test',80),dns('public.test',80)+dns('private.test',80)]:
            with patch('security.public_http.socket.getaddrinfo',return_value=addresses):
                with self.assertRaises(ValueError):resolve_target('https://public.test')
        for url in ['file:///etc/passwd','https://user:pass@public.test','https://public.test:invalid']:
            with self.assertRaises(ValueError):resolve_target(url)

    def test_stream_and_declared_sizes_and_compression_are_bounded(self):
        for headers,body in [({},b'x'*11),({'Content-Length':'11'},b''),({'Content-Encoding':'gzip'},b'x'),({'Content-Length':'10'},b'x')]:
            with patch('security.public_http.socket.getaddrinfo',side_effect=dns),patch('security.public_http.PinnedHTTPS') as cls:
                cls.return_value.getresponse.return_value=self.response(body=body,headers=headers)
                with self.assertRaises(ValueError):fetch_public('https://public.test',max_bytes=10)
                cls.return_value.close.assert_called_once()

    def test_redirect_limit_and_header_minimization(self):
        with patch('security.public_http.socket.getaddrinfo',side_effect=dns),patch('security.public_http.PinnedHTTPS') as cls:
            cls.return_value.getresponse.return_value=self.response(302,headers={'Location':'/again'})
            with self.assertRaises(ValueError):fetch_public('https://public.test')
            self.assertEqual(cls.call_count,6)
        with patch('security.public_http.socket.getaddrinfo',side_effect=dns),patch('security.public_http.PinnedHTTPS') as cls:
            cls.return_value.getresponse.return_value=self.response()
            status,body=fetch_public('https://public.test/path?x=1',{'Authorization':'private','Cookie':'private','Host':'private.test'})
            self.assertEqual((status,body),(200,'evidence'))
            headers=cls.return_value.request.call_args.kwargs['headers']
            self.assertNotIn('Authorization',headers);self.assertNotIn('Cookie',headers);self.assertNotIn('Host',headers)
