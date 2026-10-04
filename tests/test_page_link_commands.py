# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Page links across commands: links are only rewritten in pages that a command writes."""

from __future__ import annotations

import json
import unittest

from cflsync import PageState
from cflsync.cli import (PageRenameCommand, RepositoryPullCommand)
from tests.support import FakeConfluence, run_with_site, temporary_workarea

SITE = "https://example.atlassian.net"


def _url(page_id: str) -> str:
    return f"{SITE}/wiki/spaces/EXAMPLE/pages/{page_id}"


def _document(*links: tuple[str, str]) -> str:
    """Return an ADF body with one paragraph per (text, href) link."""
    return json.dumps(
        {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{
                        "type": "text",
                        "text": text,
                        "marks": [{
                            "type": "link",
                            "attrs": {
                                "href": href}}]}]} for text, href in links]})


def _hrefs(body: str) -> list[str]:
    hrefs = []

    def walk(node):
        if isinstance(node, dict):
            hrefs.extend(mark["attrs"]["href"] for mark in node.get("marks", []) if mark.get("type") == "link")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(body))
    return hrefs


class PageLinkCommandTestCase(unittest.TestCase):
    """A tree of Root (100) with A (200) and B (300) below it, Leaf (400) below B, and Deep (500) below Leaf.

    A links to B and Leaf; Leaf links to A.
    """

    def setUp(self) -> None:
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "A", parent_id="100", body=_document(("B", _url("300")), ("Leaf", _url("400"))))
        self.site.add_page("300", "B", parent_id="100")
        self.site.add_page("400", "Leaf", parent_id="300", body=_document(("A", _url("200"))))
        self.site.add_page("500", "Deep", parent_id="400")
        self.context = temporary_workarea(root_page_id="100")
        self.workarea = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self._run(lambda: RepositoryPullCommand().run())

    def _run(self, command):
        return run_with_site(self.site, self.workarea, command)

    def _path(self, page_id):
        return self.workarea.page_directory(PageState.load(self.workarea.cache_path(page_id))) / "content.md"


class TestRenameAndMove(PageLinkCommandTestCase):

    def test_renaming_the_root_makes_no_link_stale(self) -> None:
        self._run(lambda: PageRenameCommand().run("100", "Renamed root"))

        for page_id in ["200", "400"]:
            source = self._path(page_id).parent
            for link in self._path(page_id).read_text(encoding="utf-8").split("](")[1:]:
                with self.subTest(page_id=page_id, link=link):
                    self.assertTrue((source / link.split(")")[0]).is_file())


class TestMembershipLoss(PageLinkCommandTestCase):

    def test_a_page_written_after_membership_loss_keeps_remote_urls(self) -> None:
        for page_id in ["500", "400", "300"]:
            del self.site.content[page_id]

        # A forced pull rewrites the unchanged page A; its links no longer name pages in the tree.
        self._run(lambda: RepositoryPullCommand().run(force=True, delete=True))

        markdown = self._path("200").read_text(encoding="utf-8")
        self.assertIn(f"[B]({_url('300')})", markdown)
        self.assertIn(f"[Leaf]({_url('400')})", markdown)


if __name__ == "__main__":
    unittest.main()
