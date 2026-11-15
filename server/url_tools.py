"""URL normalization, duplicate detection and SSRF policy."""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request
from typing import Iterable


TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "spm",
    "source",
}


class UnsafeURLError(ValueError):
    pass


def canonical_url(value: str, *, strip_tracking: bool = True) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持 http/https 地址")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = urllib.parse.quote(
        urllib.parse.unquote(parsed.path or "/"), safe="/:@-._~!$&'()*+,;="
    )
    if path != "/":
        path = path.rstrip("/")
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if strip_tracking:
        query_pairs = [
            (key, value)
            for key, value in query_pairs
            if not key.lower().startswith("utm_")
            and key.lower() not in TRACKING_PARAMS
        ]
    query = urllib.parse.urlencode(sorted(query_pairs), doseq=True)
    return urllib.parse.urlunsplit((scheme, netloc, path or "/", query, ""))


def duplicate_groups(urls: Iterable[str]) -> dict:
    groups = {}
    for url in urls:
        try:
            key = canonical_url(url)
        except ValueError:
            continue
        groups.setdefault(key, []).append(url)
    return {key: values for key, values in groups.items() if len(values) > 1}


def validate_public_url(
    url: str, *, allow_proxy_fake_ip: bool = False
) -> str:
    canonical_input = url.strip()
    parsed = urllib.parse.urlsplit(canonical_input)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURLError("只允许 HTTP/HTTPS")
    if parsed.username or parsed.password:
        raise UnsafeURLError("网址不能包含账号密码")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("网址缺少域名")
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    if port not in {80, 443}:
        raise UnsafeURLError("为安全起见只允许 80/443 端口")
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise UnsafeURLError("禁止访问本机地址")
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise UnsafeURLError("域名无法解析") from exc
    if not addresses:
        raise UnsafeURLError("域名没有可用地址")
    parsed_addresses = [
        ipaddress.ip_address(address.split("%", 1)[0]) for address in addresses
    ]
    fake_ip_network = ipaddress.ip_network("198.18.0.0/15")
    if (
        allow_proxy_fake_ip
        and has_http_proxy()
        and parsed_addresses
        and all(ip in fake_ip_network for ip in parsed_addresses)
    ):
        return canonical_input
    for ip in parsed_addresses:
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeURLError("禁止访问内网或保留地址")
    return canonical_input


def has_http_proxy() -> bool:
    proxies = urllib.request.getproxies()
    return bool(proxies.get("http") or proxies.get("https"))
