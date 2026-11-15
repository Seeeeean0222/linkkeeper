from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from server.checker import CheckResult
from server.jobs import ScanJobs


class FakeChecker:
    def __init__(self, **_):
        pass

    def check(self, url):
        broken = "broken" in url
        return CheckResult(
            url=url,
            final_url=url,
            status_code=404 if broken else 200,
            state="missing" if broken else "ok",
            label="已失效" if broken else "正常",
            title="页面",
            detail="HTTP 404" if broken else "HTTP 200",
            elapsed_ms=12,
            redirected=False,
        )


class JobTests(unittest.TestCase):
    @patch("server.jobs.LinkChecker", FakeChecker)
    def test_job_completes_and_summarizes_duplicates(self):
        jobs = ScanJobs(workers=2, max_bookmarks=10)
        scan_id = jobs.start(
            [
                {"url": "https://example.com/a?utm_source=x", "title": "A"},
                {"url": "https://example.com/a", "title": "A2"},
                {"url": "https://example.com/broken", "title": "B"},
            ]
        )
        deadline = time.time() + 3
        while time.time() < deadline:
            job = jobs.get(scan_id)
            if job["status"] == "complete":
                break
            time.sleep(0.03)
        self.assertEqual(job["status"], "complete")
        self.assertEqual(job["summary"]["total"], 3)
        self.assertEqual(job["summary"]["duplicates"], 1)
        self.assertEqual(job["summary"]["attention"], 1)

    def test_job_rejects_empty_and_oversized_input(self):
        jobs = ScanJobs(max_bookmarks=2)
        with self.assertRaises(ValueError):
            jobs.start([])
        with self.assertRaises(ValueError):
            jobs.start([{"url": "https://example.com"}] * 3)


if __name__ == "__main__":
    unittest.main()
