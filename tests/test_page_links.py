# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for page-link conversion between Confluence page URLs and local content.md links."""

from __future__ import annotations

import unittest

from cflsync.workarea import LinkResolver, Workarea
from tests.support import FakePageIndex, example_page_state, temporary_workarea

HOST = "example.atlassian.net"


def _resolver(workarea: Workarea, index, page_id: str, directory: str) -> LinkResolver:
    return LinkResolver(workarea, HOST, page_id, directory, index)


def _cache(workarea: Workarea, page_id: str, title: str, parent_id: str | None) -> None:
    example_page_state(page_id, title, parent_id=parent_id).save(workarea.cache_path(page_id))


class TestLinkResolverToMarkdown(unittest.TestCase):

    def setUp(self) -> None:
        self.index = FakePageIndex(
            {
                "100": ("Root", None),
                "200": ("A", "100"),
                "300": ("B", "100"),
                "400": ("Leaf", "300"),
                "500": ("Deep", "400")})
        self.context = temporary_workarea(root_page_id="100")
        self.workarea = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        _cache(self.workarea, "100", "Root", None)
        _cache(self.workarea, "200", "A", "100")
        self.resolver = _resolver(self.workarea, self.index, "200", "Root_100/A_200")

    def test_converts_a_link_to_a_page_that_was_never_installed(self) -> None:
        self.assertEqual(
            self.resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/300#Notes"), "../B_300/content.md#Notes")

    def test_places_the_descendants_of_a_moved_page_below_its_new_directory(self) -> None:
        _cache(self.workarea, "300", "B", "100")
        _cache(self.workarea, "400", "Leaf", "300")
        # Page 300 is being written to a new directory after a remote rename; its cached descendants move with it.
        resolver = _resolver(self.workarea, self.index, "300", "Root_100/Renamed_300")

        self.assertEqual(resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/400"), "Leaf_400/content.md")
        self.assertEqual(resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/500"), "Leaf_400/Deep_500/content.md")
        self.assertEqual(resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/200"), "../A_200/content.md")

    def test_decodes_title_routes_with_a_literal_plus_first(self) -> None:
        index = FakePageIndex({"100": ("Root", None), "200": ("A", "100"), "300": ("A+B c", "100"), "400": ("Two words", "100")})
        resolver = _resolver(self.workarea, index, "200", "Root_100/A_200")
        cases = {
            "/wiki/display/EXAMPLE/A+B%20c": "../A%252BB c_300/content.md".replace(" ", "%20"),
            "/wiki/display/EXAMPLE/Two+words": "../Two%20words_400/content.md",
            "/wiki/display/EXAMPLE/A%2BB+c": None}
        for href, expected in cases.items():
            with self.subTest(href=href):
                self.assertEqual(resolver.to_markdown(href), expected)

    def test_keeps_links_that_are_not_page_views_of_pages_in_the_tree(self) -> None:
        for href in [
                f"https://other.atlassian.net/wiki/spaces/EXAMPLE/pages/300", f"https://{HOST}:8443/wiki/spaces/EXAMPLE/pages/300",
                f"http://{HOST}/wiki/spaces/EXAMPLE/pages/300", f"https://user@{HOST}/wiki/spaces/EXAMPLE/pages/300",
                f"//{HOST}/wiki/spaces/EXAMPLE/pages/300", f"https://{HOST}/wiki/spaces/EXAMPLE/pages/300?focusedCommentId=1",
                f"https://{HOST}/wiki/pages/viewpage.action?pageId=300&pageVersion=1",
                f"https://{HOST}/wiki/pages/viewpage.action?pageId=30x", f"https://{HOST}/wiki/spaces/EXAMPLE/pages/edit-v2/300",
                f"https://{HOST}/wiki/pages/resumedraft.action?draftId=300", f"https://{HOST}/wiki/spaces/EXAMPLE/history/300/B",
                f"https://{HOST}/wiki/x/CCCCCC", f"https://{HOST}/wiki/spaces/EXAMPLE/pages/999",
                f"https://{HOST}/wiki/display/EXAMPLE/Unknown", f"https://{HOST}/wiki/display/OTHER/B",
                f"https://{HOST}/spaces/EXAMPLE/pages/300", "../B_300/content.md", "#Notes", "mailto:someone@example.com", ""]:
            with self.subTest(href=href):
                self.assertIsNone(self.resolver.to_markdown(href))


class TestLinkResolverToADF(unittest.TestCase):

    def setUp(self) -> None:
        self.index = FakePageIndex({"100": ("Root", None), "200": ("A", "100"), "300": ("B", "100")})
        self.context = temporary_workarea(root_page_id="100")
        self.workarea = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.resolver = _resolver(self.workarea, self.index, "200", "Root_100/A_200")

    def _url(self, page_id: str, fragment: str | None = None) -> str:
        url = f"https://{HOST}/wiki/spaces/EXAMPLE/pages/{page_id}"
        return url if fragment is None else f"{url}#{fragment}"

    def test_keeps_local_links_that_are_not_page_links(self) -> None:
        for href in ["../../../x_300/content.md", "..%2FB_300/content.md", "../B_300%2Fcontent.md", "../Notes/content.md",
                     "../B_300/", "../B_300", "notes.md", "../B_300/content.md?x", "?x", "/Root_100/B_300/content.md",
                     "https://example.com/B_300/content.md", "file:///tmp/B_300/content.md", "C:/B_300/content.md", ""]:
            with self.subTest(href=href):
                self.assertIsNone(self.resolver.to_adf(href, "text"))

        self.assertEqual(self.resolver.broken, [])


if __name__ == "__main__":
    unittest.main()
