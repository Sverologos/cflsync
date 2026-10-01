# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for page-link conversion between Confluence page URLs and local content.md links."""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from urllib.parse import quote, unquote

from cflsync.workarea import LinkResolver, Workarea
from tests.support import FakePageIndex, example_page_state, temporary_workarea

FIXTURES = Path(__file__).parent / "fixtures" / "links"
HOST = "example.atlassian.net"


def _resolver(workarea: Workarea, index, page_id: str, directory: str) -> LinkResolver:
    return LinkResolver(workarea, HOST, page_id, directory, index)


def _cache(workarea: Workarea, page_id: str, title: str, parent_id: str | None) -> None:
    example_page_state(page_id, title, parent_id=parent_id).save(workarea.cache_path(page_id))


class TestLinkResolverRoutes(unittest.TestCase):
    """Every recorded Confluence route is converted only if it denotes a page view or a page title."""

    TARGET_TITLE = "cflsync fixture target A+B & 50% Ünïcode"

    def test_converts_only_page_view_and_title_routes_from_the_fixtures(self) -> None:
        routes = json.loads((FIXTURES / "routes.json").read_text(encoding="utf-8"))["routes"]
        index = FakePageIndex(
            {
                "100": ("Root page", None),
                "110": ("Existing page", "100"),
                "200": ("cflsync link fixtures", "100"),
                "300": (self.TARGET_TITLE, "200")})
        with temporary_workarea(root_page_id="100") as workarea:
            resolver = _resolver(workarea, index, "110", "Root page_100/Existing page_110")
            for route in routes:
                with self.subTest(url=route["url"]):
                    target = route.get("resolves_to") or route["page_id"]
                    result = resolver.to_markdown(route["url"])
                    if route["kind"] not in {"page-view", "title-view"}:
                        self.assertIsNone(result)
                        continue

                    # Source and target both lie directly or indirectly below the root directory.
                    location = workarea.page_location(target, index)
                    expected = "../" + "/".join(quote(part, safe="") for part in location.split("/")[1:])
                    expected += "/content.md"
                    if route["fragment"] is not None:
                        expected += f"#{route['fragment']}"

                    self.assertEqual(result, expected)


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

    def test_converts_a_link_to_an_installed_page(self) -> None:
        _cache(self.workarea, "300", "B", "100")

        self.assertEqual(self.resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/300"), "../B_300/content.md")

    def test_converts_a_link_to_a_page_that_was_never_installed(self) -> None:
        self.assertEqual(
            self.resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/300#Notes"), "../B_300/content.md#Notes")

    def test_places_a_partly_installed_chain_below_its_nearest_cached_ancestor(self) -> None:
        _cache(self.workarea, "300", "B", "100")

        self.assertEqual(
            self.resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/500"), "../B_300/Leaf_400/Deep_500/content.md")

    def test_places_the_descendants_of_a_moved_page_below_its_new_directory(self) -> None:
        _cache(self.workarea, "300", "B", "100")
        _cache(self.workarea, "400", "Leaf", "300")
        # Page 300 is being written to a new directory after a remote rename; its cached descendants move with it.
        resolver = _resolver(self.workarea, self.index, "300", "Root_100/Renamed_300")

        self.assertEqual(resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/400"), "Leaf_400/content.md")
        self.assertEqual(resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/500"), "Leaf_400/Deep_500/content.md")
        self.assertEqual(resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/200"), "../A_200/content.md")

    def test_converts_a_link_to_an_uncached_root(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            resolver = _resolver(workarea, self.index, "200", "Root_100/A_200")

            self.assertEqual(resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/100"), "../content.md")

    def test_converts_a_link_to_the_page_itself(self) -> None:
        self.assertEqual(self.resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/200"), "content.md")
        self.assertEqual(self.resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/200#Notes"), "#Notes")

    def test_identifies_the_page_by_id_whatever_the_space_segment(self) -> None:
        for space in ["OTHERKEY", "98304"]:
            with self.subTest(space=space):
                self.assertEqual(
                    self.resolver.to_markdown(f"https://{HOST}/wiki/spaces/{space}/pages/300/Some+slug"), "../B_300/content.md")

    def test_accepts_site_root_relative_links_and_the_view_page_route(self) -> None:
        for href in ["/wiki/spaces/EXAMPLE/pages/300", f"https://{HOST}/wiki/pages/viewpage.action?pageId=300",
                     "/wiki/pages/viewpage.action?pageId=300", f"https://{HOST.upper()}:443/wiki/spaces/EXAMPLE/pages/300"]:
            with self.subTest(href=href):
                self.assertEqual(self.resolver.to_markdown(href), "../B_300/content.md")

    def test_resolves_title_routes(self) -> None:
        cases = {
            f"https://{HOST}/wiki/display/EXAMPLE/B": "../B_300/content.md",
            f"https://{HOST}/wiki/display/example/b#Top": "../B_300/content.md#Top",
            "/wiki/display/EXAMPLE/Leaf": "../B_300/Leaf_400/content.md"}
        for href, expected in cases.items():
            with self.subTest(href=href):
                self.assertEqual(self.resolver.to_markdown(href), expected)

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

    def test_copies_fragments_unchanged(self) -> None:
        for fragment in ["Notes", "Message-Reference", "a%20b", "A+B", "Überblick–café", "UPPER", "", "x#y?z"]:
            with self.subTest(fragment=fragment):
                self.assertEqual(
                    self.resolver.to_markdown(f"https://{HOST}/wiki/spaces/EXAMPLE/pages/300#{fragment}"),
                    f"../B_300/content.md#{fragment}")


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

    def test_converts_a_link_to_a_page_in_the_tree(self) -> None:
        self.assertEqual(self.resolver.to_adf("../B_300/content.md#Notes", "B"), self._url("300", "Notes"))
        self.assertEqual(self.resolver.to_adf("../B_300/content.md", "B"), self._url("300"))
        self.assertEqual(self.resolver.broken, [])

    def test_converts_a_link_to_the_page_itself(self) -> None:
        self.assertEqual(self.resolver.to_adf("content.md", "self"), self._url("200"))
        self.assertEqual(self.resolver.to_adf("content.md#Top", "self"), self._url("200", "Top"))

    def test_keeps_fragment_only_links(self) -> None:
        self.assertIsNone(self.resolver.to_adf("#Notes", "Notes"))

    def test_resolves_a_stale_path_by_the_page_id(self) -> None:
        self.assertEqual(self.resolver.to_adf("../../Old title_300/content.md#Notes", "B"), self._url("300", "Notes"))

    def test_uses_the_space_key_of_the_index(self) -> None:
        index = FakePageIndex({"100": ("Root", None), "200": ("A", "100"), "300": ("B", "100")}, space_key="MY SPACE")
        resolver = _resolver(self.workarea, index, "200", "Root_100/A_200")

        self.assertEqual(resolver.to_adf("../B_300/content.md", "B"), f"https://{HOST}/wiki/spaces/MY%20SPACE/pages/300")

    def test_keeps_local_links_that_are_not_page_links(self) -> None:
        for href in ["../../../x_300/content.md", "..%2FB_300/content.md", "../B_300%2Fcontent.md", "../Notes/content.md",
                     "../B_300/", "../B_300", "notes.md", "../B_300/content.md?x", "?x", "/Root_100/B_300/content.md",
                     "https://example.com/B_300/content.md", "file:///tmp/B_300/content.md", "C:/B_300/content.md", ""]:
            with self.subTest(href=href):
                self.assertIsNone(self.resolver.to_adf(href, "text"))

        self.assertEqual(self.resolver.broken, [])

    def test_records_links_to_pages_outside_the_tree(self) -> None:
        self.assertIsNone(self.resolver.to_adf("../Gone_900/content.md", "Gone"))
        self.assertEqual(self.resolver.to_adf("../B_300/content.md", "B"), self._url("300"))
        self.assertIsNone(self.resolver.to_adf("../../Other_901/content.md#x", "Other"))

        self.assertEqual(self.resolver.broken, [("Gone", "../Gone_900/content.md"), ("Other", "../../Other_901/content.md#x")])


class TestLinkResolverRoundTrip(unittest.TestCase):

    def test_a_converted_link_resolves_back_to_the_same_page(self) -> None:
        titles = ["Two words", "Version 1.2", "C#", "What?", "Überblick – café", "50%", "~tilde"]
        pages = {"100": ("Root", None), "200": ("Source", "100")}
        for number, title in enumerate(titles, start=300):
            pages[str(number)] = (title, "100")

        index = FakePageIndex(pages)
        with temporary_workarea(root_page_id="100") as workarea:
            resolver = _resolver(workarea, index, "200", "Root_100/Source_200")
            for page_id, (title, _) in pages.items():
                if page_id in {"100", "200"}:
                    continue

                with self.subTest(title=title):
                    url = f"https://{HOST}/wiki/spaces/EXAMPLE/pages/{page_id}#Section"
                    link = resolver.to_markdown(url)
                    self.assertIsNotNone(link)
                    self.assertEqual(unquote(link.split("#")[0].split("/")[1]), workarea.page_directory_name(title, page_id))
                    self.assertEqual(resolver.to_adf(link, title), url)


if __name__ == "__main__":
    unittest.main()
