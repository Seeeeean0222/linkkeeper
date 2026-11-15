"""Parse and export browser Netscape bookmark files."""

from __future__ import annotations

import html
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urlparse


@dataclass
class Bookmark:
    title: str
    url: str
    folder: str = ""
    added: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "folder": self.folder,
            "added": self.added,
        }


class NetscapeBookmarkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bookmarks: List[Bookmark] = []
        self._folders: List[str] = []
        self._dl_has_folder: List[bool] = []
        self._pending_folder: Optional[str] = None
        self._in_h3 = False
        self._h3_buffer: List[str] = []
        self._anchor: Optional[dict] = None
        self._anchor_buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs_dict = dict(attrs)
        if tag.lower() == "dl":
            pushed = bool(self._pending_folder) and bool(self._dl_has_folder)
            self._dl_has_folder.append(pushed)
            if pushed:
                self._folders.append(self._pending_folder or "")
                self._pending_folder = None
        elif tag.lower() == "h3":
            self._in_h3 = True
            self._h3_buffer = []
        elif tag.lower() == "a" and attrs_dict.get("href"):
            self._anchor = {
                "href": attrs_dict.get("href", ""),
                "add_date": attrs_dict.get("add_date", ""),
            }
            self._anchor_buffer = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "h3" and self._in_h3:
            self._pending_folder = _clean_text("".join(self._h3_buffer)) or "未命名分类"
            self._in_h3 = False
        elif lowered == "a" and self._anchor is not None:
            url = self._anchor["href"].strip()
            if _is_web_url(url):
                title = _clean_text("".join(self._anchor_buffer))
                self.bookmarks.append(
                    Bookmark(
                        title=title or urlparse(url).hostname or url,
                        url=url,
                        folder=" / ".join(self._folders),
                        added=self._anchor["add_date"],
                    )
                )
            self._anchor = None
        elif lowered == "dl" and self._dl_has_folder:
            if self._dl_has_folder.pop() and self._folders:
                self._folders.pop()

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._h3_buffer.append(data)
        if self._anchor is not None:
            self._anchor_buffer.append(data)


def parse_bookmarks(document: str) -> List[Bookmark]:
    parser = NetscapeBookmarkParser()
    parser.feed(document)
    parser.close()
    unique = []
    seen = set()
    for item in parser.bookmarks:
        key = (item.url, item.title)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def parse_url_lines(text: str) -> List[Bookmark]:
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "|" in line:
            title, url = [part.strip() for part in line.split("|", 1)]
        else:
            title, url = "", line
        if not _is_web_url(url):
            continue
        rows.append(Bookmark(title=title or url, url=url, folder="粘贴导入"))
    return rows


def export_bookmarks(bookmarks: List[dict], title: str = "拾链整理结果") -> str:
    grouped = {}
    for item in bookmarks:
        folder = item.get("folder") or "未分类"
        grouped.setdefault(folder, []).append(item)
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        f"<TITLE>{html.escape(title)}</TITLE>",
        f"<H1>{html.escape(title)}</H1>",
        "<DL><p>",
    ]
    for folder, rows in grouped.items():
        lines.append(f'  <DT><H3>{html.escape(folder)}</H3>')
        lines.append("  <DL><p>")
        for item in rows:
            line = (
                f'    <DT><A HREF="{html.escape(item["url"], quote=True)}">'
                f'{html.escape(item.get("title") or item["url"])}</A>'
            )
            lines.append(line)
        lines.append("  </DL><p>")
    lines.extend(["</DL><p>", ""])
    return "\n".join(lines)


def _is_web_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())
