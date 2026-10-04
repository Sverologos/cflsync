# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for the page index that supplies page links with membership, titles, parents, and the space key."""

from __future__ import annotations

import unittest

from cflsync.api import APIError
from cflsync.sync import PageIndex
from tests.support import FakeConfluence, temporary_workarea

PAGES = "/wiki/api/v2/pages"


class PageIndexTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Child", "100")
        self.site.add_page("300", "Grandchild", "200")
        self.site.add_page("400", "Leaf", "300")
        self.site.add_page("500", "Sibling", "100")
        self.site.add_page("900", "Elsewhere")
        self.api = self.site.client()
        self.context = temporary_workarea(root_page_id="100")
        self.workarea = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def _index(self, prefill: bool) -> PageIndex:
        index = PageIndex(self.workarea, self.api, prefill=prefill)
        self.site.requests.clear()
        return index

    def _requests(self, suffix: str = "") -> list[str]:
        return [request.path for request in self.site.requests if request.path.endswith(suffix)]

    def _summary(self, page):
        return None if page is None else (page.id, page.title, page.parent_id)


class TestPrefilledPageIndex(PageIndexTestCase):

    def test_matches_titles_ignoring_case_and_refuses_duplicates(self) -> None:
        self.site.add_page("600", "Twin", "100")
        self.site.add_page("700", "twin", "500")
        index = self._index(prefill=True)

        self.assertEqual(index.find_by_title("EXAMPLE", "grandchild"), "300")
        self.assertEqual(index.find_by_title("example", "Leaf"), "400")
        self.assertIsNone(index.find_by_title("EXAMPLE", "Twin"))
        self.assertIsNone(index.find_by_title("EXAMPLE", "Elsewhere"))
        self.assertIsNone(index.find_by_title("OTHER", "Leaf"))
        self.assertEqual(self._requests(), ["/wiki/api/v2/spaces/98765"])


class TestOnDemandPageIndex(PageIndexTestCase):

    def test_a_page_below_a_folder_below_the_root_is_not_in_the_tree(self) -> None:
        self.site.add_folder("600", "Folder", "100")
        self.site.add_page("700", "Filed", "600")
        index = self._index(prefill=False)

        self.assertIsNone(index.lookup("700"))

    def test_other_errors_propagate_and_are_not_recorded(self) -> None:
        # HTTP 500 is not retried.
        self.site.fail("GET", f"{PAGES}/500", 500, "server error")
        index = self._index(prefill=False)

        with self.assertRaises(APIError):
            index.lookup("500")

        self.assertEqual(self._summary(index.lookup("500")), ("500", "Sibling", "100"))

    def test_fetches_each_page_once_and_ancestors_only_for_their_titles(self) -> None:
        index = self._index(prefill=False)

        index.lookup("400")
        self.assertEqual(self._requests(), [f"{PAGES}/400", f"{PAGES}/400/ancestors"])

        self.site.requests.clear()
        self.assertEqual(self._summary(index.lookup("300")), ("300", "Grandchild", "200"))
        self.assertEqual(self._summary(index.lookup("200")), ("200", "Child", "100"))
        self.assertEqual(self._requests(), [f"{PAGES}/300", f"{PAGES}/200"])

        # The root page is fetched once, when it is first needed.
        self.site.requests.clear()
        for page_id in ["400", "300", "200", "100"]:
            index.lookup(page_id)
        self.assertEqual(self._requests(), [f"{PAGES}/100"])

        self.site.requests.clear()
        for page_id in ["400", "300", "200", "100"]:
            index.lookup(page_id)
        self.assertEqual(self.site.requests, [])


class TestPageIndexInBothModes(PageIndexTestCase):

    def test_fetches_the_space_key_at_most_once(self) -> None:
        for prefill in [True, False]:
            with self.subTest(prefill=prefill):
                index = self._index(prefill=prefill)

                self.assertEqual((index.space_key, index.space_key), ("EXAMPLE", "EXAMPLE"))
                index.find_by_title("EXAMPLE", "Leaf")
                self.assertEqual(len(self._requests("/spaces/98765")), 1)


if __name__ == "__main__":
    unittest.main()
