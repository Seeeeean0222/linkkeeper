from __future__ import annotations

import unittest

from server.bookmarks import export_bookmarks, parse_bookmarks, parse_url_lines


HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
  <DT><H3>学习资料</H3>
  <DL><p>
    <DT><A HREF="https://example.com/python?utm_source=test" ADD_DATE="1">Python 教程</A>
    <DT><H3>Web</H3>
    <DL><p>
      <DT><A HREF="https://developer.mozilla.org/">MDN &amp; Docs</A>
    </DL><p>
  </DL><p>
  <DT><A HREF="javascript:alert(1)">忽略脚本</A>
</DL><p>
"""


class BookmarkParserTests(unittest.TestCase):
    def test_parses_nested_folders_and_entities(self):
        rows = parse_bookmarks(HTML)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].title, "Python 教程")
        self.assertEqual(rows[0].folder, "学习资料")
        self.assertEqual(rows[1].title, "MDN & Docs")
        self.assertEqual(rows[1].folder, "学习资料 / Web")

    def test_parse_paste_supports_title_pipe_url(self):
        rows = parse_url_lines(
            "Python | https://python.org\nhttps://example.com\n不是网址\n"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].title, "Python")
        self.assertEqual(rows[1].folder, "粘贴导入")

    def test_export_is_netscape_compatible(self):
        document = export_bookmarks(
            [
                {
                    "title": "Example & Test",
                    "url": "https://example.com/?a=1&b=2",
                    "folder": "工具",
                }
            ]
        )
        self.assertIn("<!DOCTYPE NETSCAPE-Bookmark-file-1>", document)
        self.assertIn("Example &amp; Test", document)
        self.assertIn("https://example.com/?a=1&amp;b=2", document)


if __name__ == "__main__":
    unittest.main()
