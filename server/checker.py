"""Concurrent, redirect-aware HTTP link checker."""

from __future__ import annotations

import re
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import unescape
from typing import Optional

from .url_tools import (
    UnsafeURLError,
    canonical_url,
    has_http_proxy,
    validate_public_url,
)


USER_AGENT = "LinkKeeper/1.0 (+local bookmark health checker)"


@dataclass
class CheckResult:
    url: str
    final_url: str
    status_code: Optional[int]
    state: str
    label: str
    title: str
    detail: str
    elapsed_ms: int
    redirected: bool

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, allow_proxy_fake_ip: bool = False) -> None:
        self.allow_proxy_fake_ip = allow_proxy_fake_ip

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(
            newurl, allow_proxy_fake_ip=self.allow_proxy_fake_ip
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class LinkChecker:
    def __init__(
        self,
        *,
        timeout_seconds: float = 7.0,
        allow_private: bool = False,
        opener: Optional[urllib.request.OpenerDirector] = None,
    ) -> None:
        self.timeout = timeout_seconds
        self.allow_private = allow_private
        self.allow_proxy_fake_ip = not allow_private and has_http_proxy()
        self.opener = opener or (
            urllib.request.build_opener()
            if allow_private
            else urllib.request.build_opener(
                SafeRedirectHandler(
                    allow_proxy_fake_ip=self.allow_proxy_fake_ip
                )
            )
        )

    def check(self, url: str) -> CheckResult:
        started = _now_ms()
        final_url = url
        try:
            if not self.allow_private:
                validate_public_url(
                    url, allow_proxy_fake_ip=self.allow_proxy_fake_ip
                )
            try:
                code, final_url, title, method = self._request(url, method="HEAD")
            except urllib.error.HTTPError as exc:
                if exc.code not in {403, 405, 501}:
                    raise
                code, final_url, title, method = self._request(url, method="GET")
            if code in {403, 405, 501}:
                code, final_url, title, method = self._request(url, method="GET")
            state, label, detail = classify_status(code)
            return CheckResult(
                url=url,
                final_url=final_url,
                status_code=code,
                state=state,
                label=label,
                title=title,
                detail=detail,
                elapsed_ms=_now_ms() - started,
                redirected=_safe_canonical(url) != _safe_canonical(final_url),
            )
        except urllib.error.HTTPError as exc:
            final_url = exc.geturl() or final_url
            state, label, detail = classify_status(exc.code)
            return self._result(url, final_url, exc.code, state, label, detail, started)
        except UnsafeURLError as exc:
            return self._result(
                url, final_url, None, "blocked", "已拦截", str(exc), started
            )
        except (socket.timeout, TimeoutError):
            return self._result(
                url, final_url, None, "timeout", "超时", "服务器未在限定时间内响应", started
            )
        except socket.gaierror:
            return self._result(
                url, final_url, None, "unreachable", "无法解析", "域名不存在或 DNS 解析失败", started
            )
        except ssl.SSLError:
            return self._result(
                url, final_url, None, "tls_error", "证书异常", "TLS/SSL 握手失败", started
            )
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            state = "timeout" if "timed out" in reason.lower() else "unreachable"
            label = "超时" if state == "timeout" else "无法访问"
            return self._result(url, final_url, None, state, label, reason[:160], started)
        except Exception as exc:
            return self._result(
                url,
                final_url,
                None,
                "error",
                "检查失败",
                f"{type(exc).__name__}: {str(exc)[:120]}",
                started,
            )

    def _request(self, url: str, *, method: str):
        request = urllib.request.Request(
            url,
            method=method,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Range": "bytes=0-65535",
            },
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            code = int(response.status)
            final_url = response.geturl()
            title = ""
            if method == "GET":
                content_type = response.headers.get("Content-Type", "")
                if "html" in content_type.lower():
                    raw = response.read(65536)
                    title = extract_title(raw, response.headers.get_content_charset())
            return code, final_url, title, method

    def _result(
        self, url, final_url, code, state, label, detail, started
    ) -> CheckResult:
        return CheckResult(
            url=url,
            final_url=final_url,
            status_code=code,
            state=state,
            label=label,
            title="",
            detail=detail,
            elapsed_ms=_now_ms() - started,
            redirected=_safe_canonical(url) != _safe_canonical(final_url),
        )


def classify_status(code: int):
    if 200 <= code < 300:
        return "ok", "正常", f"HTTP {code}"
    if 300 <= code < 400:
        return "redirect", "重定向", f"HTTP {code}"
    if code in {401, 402, 403, 407, 429, 451}:
        return "protected", "访问受限", f"HTTP {code}，可能需要登录或频率限制"
    if code in {404, 410}:
        return "missing", "已失效", f"HTTP {code}"
    if 400 <= code < 500:
        return "client_error", "请求异常", f"HTTP {code}"
    if 500 <= code < 600:
        return "server_error", "站点异常", f"HTTP {code}"
    return "unknown", "状态未知", f"HTTP {code}"


def extract_title(raw: bytes, charset: Optional[str]) -> str:
    encoding = charset or "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if not match:
        return ""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())[:160]


def _safe_canonical(url: str) -> str:
    try:
        return canonical_url(url)
    except ValueError:
        return url


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)
