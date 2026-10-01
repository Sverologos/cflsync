# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Page links across commands: links are only rewritten in pages that a command writes."""

from __future__ import annotations

import json
import shutil
import unittest
from unittest.mock import patch

from cflsync import PageState, PandocRunner, SyncError
from cflsync.cli import (
    PageMoveCommand, PagePullCommand, PagePushCommand, PageRemoveCommand, PageRenameCommand, RepositoryPullCommand)
from cflsync.sync import PageChangeDetector, PageChangeStatus
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

    def _clean(self, page_id) -> bool:
        state = PageState.load(self.workarea.cache_path(page_id))
        detector = PageChangeDetector(PandocRunner())
        return detector.local_status(self.workarea.page_directory(state), state) == PageChangeStatus.UNCHANGED

    def _edit_a(self):
        path = self._path("200")
        path.write_text(path.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")

    def _push_a(self):
        self._edit_a()
        self._run(lambda: PagePushCommand().run("200"))
        return _hrefs(self.site.content["200"]["body"])


class TestRenameAndMove(PageLinkCommandTestCase):

    def test_rename_leaves_referring_pages_alone_and_push_resolves_their_stale_links(self) -> None:
        referring = self._path("200").read_bytes()

        self._run(lambda: PageRenameCommand().run("300", "B renamed"))

        self.assertEqual(self._path("200").read_bytes(), referring)
        self.assertTrue(self._clean("200"))
        self.assertIn(b"../B_300/content.md", referring)
        self.assertFalse((self.workarea.root_dir / "Root_100" / "B_300").exists())
        self.assertEqual(self._push_a(), [_url("300"), _url("400")])

    def test_move_leaves_the_moved_page_and_its_descendants_unchanged(self) -> None:
        moved = self._path("400").read_bytes()
        descendant = self._path("500").read_bytes()
        referring = self._path("200").read_bytes()

        self._run(lambda: PageMoveCommand().run("400", "200"))

        self.assertEqual(self._path("400"), self.workarea.root_dir / "Root_100/A_200/Leaf_400/content.md")
        self.assertEqual(self._path("400").read_bytes(), moved)
        self.assertEqual(self._path("500").read_bytes(), descendant)
        self.assertEqual(self._path("200").read_bytes(), referring)
        self.assertTrue(all(self._clean(page_id) for page_id in ["200", "400", "500"]))

    def test_renaming_the_root_makes_no_link_stale(self) -> None:
        self._run(lambda: PageRenameCommand().run("100", "Renamed root"))

        for page_id in ["200", "400"]:
            source = self._path(page_id).parent
            for link in self._path(page_id).read_text(encoding="utf-8").split("](")[1:]:
                with self.subTest(page_id=page_id, link=link):
                    self.assertTrue((source / link.split(")")[0]).is_file())


class TestMembershipLoss(PageLinkCommandTestCase):

    def test_a_target_removed_only_locally_stays_a_page_link(self) -> None:
        shutil.rmtree(self.workarea.root_dir / "Root_100" / "B_300")

        self.assertEqual(self._push_a(), [_url("300"), _url("400")])

    def test_page_remove_of_a_target_makes_links_to_it_broken(self) -> None:
        with patch("cflsync.cli._terminal_available", return_value=True):
            self._run(lambda: PageRemoveCommand().run("300", force=True))
        body = self.site.content["200"]["body"]

        with self.assertRaisesRegex(SyncError, r"broken page links(.|\n)*\[B\]\(\.\./B_300/content\.md\)"):
            self._push_a()

        self.assertEqual(self.site.content["200"]["body"], body)

    def test_pull_delete_after_a_remote_deletion_makes_links_to_it_broken(self) -> None:
        for page_id in ["500", "400", "300"]:
            del self.site.content[page_id]

        with patch("cflsync.cli._terminal_available", return_value=True), patch("builtins.input", return_value="yes"):
            self._run(lambda: RepositoryPullCommand().run(delete=True))

        self.assertFalse(self.workarea.cache_path("300").exists())
        with self.assertRaisesRegex(SyncError, "page '200' has broken page links"):
            self._push_a()

    def test_a_page_written_after_membership_loss_keeps_remote_urls(self) -> None:
        for page_id in ["500", "400", "300"]:
            del self.site.content[page_id]

        # A forced pull rewrites the unchanged page A; its links no longer name pages in the tree.
        self._run(lambda: RepositoryPullCommand().run(force=True, delete=True))

        markdown = self._path("200").read_text(encoding="utf-8")
        self.assertIn(f"[B]({_url('300')})", markdown)
        self.assertIn(f"[Leaf]({_url('400')})", markdown)

    def test_a_page_hidden_by_permissions_is_treated_as_deleted(self) -> None:
        self.site.fail("GET", "/wiki/api/v2/pages/300", 403, "not permitted")

        with self.assertRaisesRegex(
                SyncError,
                r"broken page links; nothing was pushed:\n  Root_100/A_200/content\.md: \[B\]\(\.\./B_300/content\.md\)$"):
            self._push_a()


class TestLookupRequests(unittest.TestCase):

    def test_page_pull_makes_at_most_two_lookups_per_distinct_target(self) -> None:
        targets = [str(page_id) for page_id in range(300, 305)]
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_page("200", "Source", parent_id="100")
        for page_id in targets:
            site.add_page(page_id, f"Target {page_id}", parent_id="100")

        def pulled_requests(body):
            site.content["200"]["body"] = body
            with temporary_workarea(root_page_id="100") as workarea:
                site.requests.clear()
                run_with_site(site, workarea, lambda: PagePullCommand().run("200"))
                return len(site.requests)

        baseline = pulled_requests(_document())
        # Each target is linked twice, through different routes.
        linked = pulled_requests(
            _document(
                *[("Target", _url(page_id)) for page_id in targets], *[
                    ("Again", f"{SITE}/wiki/pages/viewpage.action?pageId={page_id}") for page_id in targets]))

        self.assertLessEqual(linked - baseline, 2 * len(targets) + 1)


if __name__ == "__main__":
    unittest.main()
