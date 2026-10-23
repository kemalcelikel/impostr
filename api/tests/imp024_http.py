"""Standard-library HTTP client for the disposable joined fixture only.

Fixed loopback origin, no environment proxy, redirects, retries or shared TCP
connection. A locked CookieJar retains the real login across concurrent requests;
the lock is never held during HTTP I/O or streaming.
"""

from __future__ import annotations

import http.client
import json as json_module
import socket
from contextlib import contextmanager
from http.cookiejar import CookieJar
from http.cookies import SimpleCookie
from threading import RLock, Timer
from urllib.parse import urlsplit
from urllib.request import Request

MAX_BODY = 2 * 1024 * 1024
MAX_LINE = 1024 * 1024
MAX_STREAM = 8 * 1024 * 1024


class TransportError(Exception):
    def __init__(self):
        super().__init__("Fixture HTTP transport unavailable")


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body

    def json(self):
        return json_module.loads(self.body)


class Stream:
    def __init__(self, response):
        self.status_code = response.status
        self.response = response

    def iter_lines(self):
        total = 0
        try:
            while True:
                line = self.response.readline(MAX_LINE + 1)
                if not line:
                    return
                total += len(line)
                if len(line) > MAX_LINE or total > MAX_STREAM:
                    raise TransportError()
                yield line.rstrip(b"\r\n").decode("utf-8")
        except (OSError, http.client.HTTPException, UnicodeError) as error:
            raise TransportError() from error


class Cookies:
    def __init__(self, client):
        self.client = client

    def get(self, name, default=None):
        with self.client.lock:
            request = Request(self.client.base_url + "/")
            self.client.jar.add_cookie_header(request)
            cookies = SimpleCookie(request.get_header("Cookie", ""))
            return cookies[name].value if name in cookies else default


class Client:
    def __init__(self, base_url, timeout=5):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not 0 < timeout <= 10
        ):
            raise ValueError("Fixture loopback origin required")
        self.base_url = base_url
        self.port = parsed.port
        self.timeout = timeout
        self.jar = CookieJar()
        self.lock = RLock()
        self.connections = set()
        self.closed = False
        self.cookies = Cookies(self)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)

    @contextmanager
    def _open(self, method, path, *, json=None, headers=None, lifetime=None):
        parsed = urlsplit(path)
        if (
            method not in ("GET", "POST", "PUT", "DELETE")
            or not path.startswith("/")
            or path.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
        ):
            raise ValueError("Fixture relative request required")
        body = None if json is None else json_module.dumps(json, allow_nan=False).encode()
        if body is not None and len(body) > MAX_BODY:
            raise ValueError("Fixture request bound")
        request = Request(self.base_url + path, data=body, headers=headers or {}, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        guard = None
        response = None
        with self.lock:
            if self.closed:
                raise TransportError()
            self.jar.add_cookie_header(request)
            self.connections.add(connection)
        try:
            connection.connect()
            owned_socket = connection.sock

            def expire():
                try:
                    owned_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            guard = Timer(lifetime or self.timeout, expire)
            guard.daemon = True
            guard.start()
            connection.request(method, path, body, dict(request.header_items()))
            response = connection.getresponse()
            with self.lock:
                self.jar.extract_cookies(response, request)
            yield response
        except (OSError, http.client.HTTPException) as error:
            raise TransportError() from error
        finally:
            if guard is not None:
                guard.cancel()
            if response is not None:
                response.close()
            connection.close()
            with self.lock:
                self.connections.discard(connection)

    def request(self, method, path, **kwargs):
        with self._open(method, path, **kwargs) as response:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise TransportError()
            return Response(response.status, body)

    @contextmanager
    def stream(self, method, path):
        with self._open(method, path, lifetime=35) as response:
            yield Stream(response)

    def close(self):
        with self.lock:
            self.closed = True
            connections = list(self.connections)
            self.jar.clear()
        for connection in connections:
            connection.close()
