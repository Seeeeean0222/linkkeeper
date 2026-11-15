"""In-memory asynchronous bookmark scan jobs."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from .checker import LinkChecker
from .url_tools import canonical_url


class ScanJobs:
    def __init__(
        self,
        *,
        workers: int = 10,
        timeout_seconds: float = 7.0,
        max_bookmarks: int = 300,
    ) -> None:
        self.workers = workers
        self.timeout_seconds = timeout_seconds
        self.max_bookmarks = max_bookmarks
        self._jobs = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="linkkeeper-scan"
        )

    def start(self, bookmarks: List[dict]) -> str:
        if not bookmarks:
            raise ValueError("没有可检查的网址")
        if len(bookmarks) > self.max_bookmarks:
            raise ValueError(f"单次最多检查 {self.max_bookmarks} 条网址")
        scan_id = uuid.uuid4().hex[:18]
        with self._lock:
            if len(self._jobs) >= 40:
                finished = sorted(
                    (
                        (job.get("finishedAt") or job["createdAt"], key)
                        for key, job in self._jobs.items()
                        if job["status"] in {"complete", "failed"}
                    ),
                    key=lambda item: item[0],
                )
                for _, key in finished[: len(self._jobs) - 30]:
                    self._jobs.pop(key, None)
            self._jobs[scan_id] = {
                "id": scan_id,
                "status": "queued",
                "createdAt": int(time.time()),
                "startedAt": None,
                "finishedAt": None,
                "total": len(bookmarks),
                "completed": 0,
                "results": [],
                "error": "",
            }
        self._executor.submit(self._run, scan_id, bookmarks)
        return scan_id

    def get(self, scan_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(scan_id)
            if not job:
                raise KeyError(scan_id)
            return {
                **job,
                "results": list(job["results"]),
                "progress": round(
                    job["completed"] / max(1, job["total"]) * 100, 1
                ),
            }

    def _run(self, scan_id: str, bookmarks: List[dict]) -> None:
        with self._lock:
            self._jobs[scan_id]["status"] = "running"
            self._jobs[scan_id]["startedAt"] = int(time.time())
        checker = LinkChecker(timeout_seconds=self.timeout_seconds)
        results = []
        try:
            with ThreadPoolExecutor(
                max_workers=self.workers, thread_name_prefix="linkkeeper-check"
            ) as pool:
                future_map = {
                    pool.submit(checker.check, item["url"]): item
                    for item in bookmarks
                }
                for future in as_completed(future_map):
                    item = future_map[future]
                    check = future.result()
                    result = {
                        **check.to_dict(),
                        "title": item.get("title") or check.title or check.url,
                        "pageTitle": check.title,
                        "folder": item.get("folder", ""),
                        "canonicalUrl": _safe_canonical(check.url),
                    }
                    results.append(result)
                    with self._lock:
                        state = self._jobs[scan_id]
                        state["results"].append(result)
                        state["completed"] = len(state["results"])
            summary = summarize(results)
            with self._lock:
                state = self._jobs[scan_id]
                state["status"] = "complete"
                state["finishedAt"] = int(time.time())
                state["summary"] = summary
                state["results"] = sorted(
                    results,
                    key=lambda row: (_state_order(row["state"]), row["title"].lower()),
                )
        except Exception as exc:
            with self._lock:
                state = self._jobs[scan_id]
                state["status"] = "failed"
                state["error"] = str(exc)
                state["finishedAt"] = int(time.time())


def summarize(results: list) -> dict:
    counts = {}
    for item in results:
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    duplicate_keys = {}
    for item in results:
        duplicate_keys.setdefault(item["canonicalUrl"], []).append(item["url"])
    duplicates = sum(
        len(items) - 1 for items in duplicate_keys.values() if len(items) > 1
    )
    healthy = counts.get("ok", 0)
    score = round(healthy / max(1, len(results)) * 100)
    domains = {}
    from urllib.parse import urlparse

    for item in results:
        host = urlparse(item["url"]).hostname or "未知"
        domains[host] = domains.get(host, 0) + 1
    return {
        "total": len(results),
        "healthy": healthy,
        "duplicates": duplicates,
        "attention": sum(
            counts.get(key, 0)
            for key in ("missing", "client_error", "server_error", "timeout", "unreachable", "tls_error", "error")
        ),
        "protected": counts.get("protected", 0),
        "blocked": counts.get("blocked", 0),
        "healthScore": score,
        "counts": counts,
        "topDomains": [
            {"domain": key, "count": value}
            for key, value in sorted(domains.items(), key=lambda pair: -pair[1])[:8]
        ],
    }


def _state_order(state: str) -> int:
    order = {
        "missing": 0,
        "server_error": 1,
        "client_error": 2,
        "timeout": 3,
        "unreachable": 4,
        "tls_error": 5,
        "error": 6,
        "blocked": 7,
        "protected": 8,
        "redirect": 9,
        "ok": 10,
    }
    return order.get(state, 20)


def _safe_canonical(url: str) -> str:
    try:
        return canonical_url(url)
    except ValueError:
        return url
