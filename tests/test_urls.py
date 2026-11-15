from __future__ import annotations

import unittest

from server.url_tools import (
    UnsafeURLError,
    canonical_url,
    duplicate_groups,
    validate_public_url,
)


class UrlToolsTests(unittest.TestCase):
    def test_canonical_url_removes_tracking_and_fragment(self):
        actual = canonical_url(
            "HTTPS://Example.COM:443/a/?utm_source=x&b=2&a=1#section"
        )
        self.assertEqual(actual, "https://example.com/a?a=1&b=2")

    def test_duplicate_groups_ignore_common_tracking_parameters(self):
        groups = duplicate_groups(
            [
                "https://example.com/article?utm_source=newsletter",
                "https://example.com/article?fbclid=abc",
                "https://example.com/other",
            ]
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(next(iter(groups.values()))[1].split("?")[0], "https://example.com/article")

    def test_private_and_local_targets_are_rejected(self):
        for url in (
            "http://127.0.0.1/",
            "http://localhost/",
            "http://[::1]/",
            "http://user:pass@example.com/",
            "http://example.com:8080/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_public_url(url)


if __name__ == "__main__":
    unittest.main()
