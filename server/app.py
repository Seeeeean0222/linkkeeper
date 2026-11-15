"""LinkKeeper HTTP server."""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .bookmarks import export_bookmarks
from .config import Settings
from .jobs import ScanJobs


ROOT = Path(__file__).resolve().parents[1]


class LinkKeeperHandler(BaseHTTPRequestHandler):
    server_version = "LinkKeeper/1.0"

    @property
    def settings(self) -> Settings:
        return self.server.settings  # type: ignore[attr-defined]

    @property
    def jobs(self) -> ScanJobs:
        return self.server.jobs  # type: ignore[attr-defined]

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(HTTPStatus.NO_CONTENT, None)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_document(
                    (ROOT / "web" / "index.html").read_text(encoding="utf-8"),
                    "text/html; charset=utf-8",
                )
                return
            if parsed.path == "/api/health":
                self._send(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "service": "拾链 LinkKeeper",
                        "workers": self.settings.workers,
                        "maxBookmarks": self.settings.max_bookmarks,
                    },
                )
                return
            match = re.match(r"^/api/scans/([a-f0-9]{18})$", parsed.path)
            if match:
                self._send(HTTPStatus.OK, self.jobs.get(match.group(1)))
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
        except KeyError:
            self._send(HTTPStatus.NOT_FOUND, {"error": "扫描任务不存在或已过期"})
        except Exception as exc:
            self.log_error("GET failed: %r", exc)
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "服务暂时不可用"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self._body()
            if parsed.path == "/api/scans":
                raw_items = payload.get("bookmarks")
                if not isinstance(raw_items, list):
                    raise ValueError("bookmarks 必须是数组")
                bookmarks = []
                for item in raw_items[: self.settings.max_bookmarks]:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not url:
                        continue
                    bookmarks.append(
                        {
                            "url": url[:2048],
                            "title": str(item.get("title") or "")[:200],
                            "folder": str(item.get("folder") or "")[:240],
                        }
                    )
                scan_id = self.jobs.start(bookmarks)
                self._send(
                    HTTPStatus.ACCEPTED,
                    {"scanId": scan_id, "total": len(bookmarks)},
                )
                return
            if parsed.path == "/api/export":
                items = payload.get("bookmarks")
                if not isinstance(items, list):
                    raise ValueError("bookmarks 必须是数组")
                safe = []
                for item in items[: self.settings.max_bookmarks]:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not url.startswith(("http://", "https://")):
                        continue
                    safe.append(
                        {
                            "url": url[:2048],
                            "title": str(item.get("title") or "")[:200],
                            "folder": str(item.get("folder") or "")[:240],
                        }
                    )
                document = export_bookmarks(safe)
                self._send_document(
                    document,
                    "text/html; charset=utf-8",
                    filename="linkkeeper-bookmarks.html",
                )
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
        except ValueError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self.log_error("POST failed: %r", exc)
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "服务暂时不可用"})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2 * 1024 * 1024:
            raise ValueError("请求体为空或过大")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 格式无效") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是对象")
        return payload

    def _send(self, status: HTTPStatus, payload: Optional[object]) -> None:
        body = b"" if payload is None else json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_document(
        self, document: str, content_type: str, filename: str = ""
    ) -> None:
        body = document.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        sys.stdout.write(
            f"[{self.log_date_time_string()}] {self.client_address[0]} "
            f"{format % args}\n"
        )


def serve(settings: Optional[Settings] = None) -> None:
    settings = settings or Settings.from_env()
    server = ThreadingHTTPServer((settings.host, settings.port), LinkKeeperHandler)
    server.settings = settings  # type: ignore[attr-defined]
    server.jobs = ScanJobs(  # type: ignore[attr-defined]
        workers=settings.workers,
        timeout_seconds=settings.timeout_seconds,
        max_bookmarks=settings.max_bookmarks,
    )
    print(f"拾链 LinkKeeper 已启动：http://{settings.host}:{settings.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
