"""Bounded public HTTP retrieval with DNS-pinned connections and TLS verification.

Does not inherit proxy settings: a proxy would resolve destinations outside this
validator's control. Browser/Playwright traffic has a separate trust boundary.
"""
from __future__ import annotations
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5


def resolve_target(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Public HTTP(S) URL without credentials required')
    host = parsed.hostname.encode('idna').decode('ascii')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError('Destination did not resolve')
    ips = [item[4][0] for item in addresses]
    if any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('Non-public destination denied')
    return parsed, host, port, ips[0]


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def fetch_public(url, headers=None, *, timeout=25, max_bytes=MAX_BYTES):
    deadline = time.monotonic() + timeout
    for hop in range(MAX_REDIRECTS + 1):
        parsed, host, port, address = resolve_target(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Public retrieval deadline exceeded')
        cls = PinnedHTTPS if parsed.scheme == 'https' else PinnedHTTP
        connection = cls(host, port, address, remaining)
        try:
            # No caller-supplied cookies, credentials, Host or forwarding headers.
            safe_headers = {'User-Agent': 'AIBA-Agent/1.7', 'Accept-Encoding': 'identity'}
            for key, value in (headers or {}).items():
                if key.casefold() in {'accept', 'accept-language'}:
                    safe_headers[key] = value
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            connection.request('GET', path, headers=safe_headers)
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader('Location')
                if not location or hop == MAX_REDIRECTS:
                    raise ValueError('Invalid or excessive redirect chain')
                url = urljoin(url, location)
                continue  # Next hop is validated and pinned independently.
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('Unsupported response encoding')
            length = response.getheader('Content-Length')
            if length is not None and (int(length) < 0 or int(length) > max_bytes):
                raise ValueError('Response exceeds retrieval limit')
            chunks = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Public retrieval deadline exceeded')
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, max_bytes - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError('Response exceeds retrieval limit')
                chunks.append(chunk)
            if length is not None and size != int(length):
                raise ValueError('Truncated response body')
            return response.status, b''.join(chunks).decode('utf-8', errors='replace')
        finally:
            connection.close()
    raise ValueError('Redirect limit exceeded')
