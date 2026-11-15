from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server.checker import LinkChecker, classify_status


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):  # noqa: N802
        if self.path == "/head405":
            self.send_response(405)
            self.end_headers()
            return
        self._reply()

    def do_GET(self):  # noqa: N802
        self._reply()

    def _reply(self):
        if self.path == "/ok":
            body = b"<html><head><title>Working page</title></head></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/missing":
            self.send_response(404)
            self.end_headers()
        elif self.path == "/protected":
            self.send_response(403)
            self.end_headers()
        else:
            self.send_response(500)
            self.end_headers()

    def log_message(self, *args):
        pass


class CheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.checker = LinkChecker(timeout_seconds=2, allow_private=True)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_successful_page(self):
        result = self.checker.check(self.url("/ok"))
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.status_code, 200)

    def test_redirect_is_followed(self):
        result = self.checker.check(self.url("/redirect"))
        self.assertEqual(result.state, "ok")
        self.assertTrue(result.final_url.endswith("/ok"))
        self.assertTrue(result.redirected)

    def test_missing_and_protected_are_distinct(self):
        missing = self.checker.check(self.url("/missing"))
        protected = self.checker.check(self.url("/protected"))
        self.assertEqual(missing.state, "missing")
        self.assertEqual(protected.state, "protected")

    def test_head_405_falls_back_to_get(self):
        result = self.checker.check(self.url("/head405"))
        self.assertEqual(result.status_code, 500)

    def test_status_classification(self):
        self.assertEqual(classify_status(204)[0], "ok")
        self.assertEqual(classify_status(404)[0], "missing")
        self.assertEqual(classify_status(429)[0], "protected")
        self.assertEqual(classify_status(503)[0], "server_error")


if __name__ == "__main__":
    unittest.main()
