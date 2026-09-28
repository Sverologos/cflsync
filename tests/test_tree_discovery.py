# Copyright (c) 2026 Sven Rosiers
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Complete remote page-tree discovery."""

import unittest

from cflsync import SyncError
from cflsync.sync import TreeDiscovery
from tests.support import FakeConfluence


class TestTreeDiscovery(unittest.TestCase):

    def test_discovers_deep_paginated_trees_breadth_first(self) -> None:
        site = FakeConfluence(page_size=1)
        site.add_page("100", "Root")
        site.add_page("200", "First", parent_id="100")
        site.add_page("300", "Second", parent_id="100")
        site.add_page("400", "Grandchild", parent_id="200")

        discovery = TreeDiscovery.discover(site.client(), "100")

        self.assertTrue(discovery.complete)
        self.assertEqual(list(discovery.pages), ["100", "200", "300", "400"])
        self.assertEqual(discovery.pages["100"].path, ("100", ))
        self.assertEqual(discovery.pages["400"].path, ("100", "200", "400"))
        self.assertEqual(discovery.pages["400"].parent_id, "200")
        self.assertEqual(
            [request.path for request in site.requests], [
                "/wiki/api/v2/pages/100", "/wiki/api/v2/pages/100/direct-children",
                "/wiki/api/v2/pages/100/direct-children?limit=250&cursor=1", "/wiki/api/v2/pages/200/direct-children",
                "/wiki/api/v2/pages/300/direct-children", "/wiki/api/v2/pages/400/direct-children"])

    def test_reports_an_inaccessible_root_as_incomplete(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.fail("GET", "/wiki/api/v2/pages/100", 403)

        discovery = TreeDiscovery.discover(site.client(), "100")

        self.assertFalse(discovery.complete)
        self.assertEqual(discovery.pages, {})
        self.assertIn("cannot access root page '100'", discovery.failures[0])
        with self.assertRaisesRegex(SyncError, "remote tree discovery is incomplete"):
            discovery.require_complete()

    def test_reports_a_failed_subtree_listing_without_inferring_its_descendants_are_absent(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_page("200", "Blocked", parent_id="100")
        site.add_page("300", "Available", parent_id="100")
        site.add_page("400", "Unknown descendant", parent_id="200")
        site.fail("GET", "/wiki/api/v2/pages/200/direct-children", 403)

        discovery = TreeDiscovery.discover(site.client(), "100")

        self.assertFalse(discovery.complete)
        self.assertEqual(list(discovery.pages), ["100", "200", "300"])
        self.assertTrue(any(failure.startswith("cannot list children of page '200'") for failure in discovery.failures))
        self.assertNotIn("400", discovery.pages)
        with self.assertRaisesRegex(SyncError, "cannot list children of page '200'"):
            discovery.require_complete()

    def test_reports_non_page_content_inside_the_tree(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_folder("200", "Folder", parent_id="100")
        site.add_page("300", "Page", parent_id="100")

        discovery = TreeDiscovery.discover(site.client(), "100")

        self.assertFalse(discovery.complete)
        self.assertEqual(list(discovery.pages), ["100", "300"])
        self.assertEqual(discovery.failures, ["page '100' has non-page child folder '200'; only pages are supported"])

    def test_reports_a_truncated_listing_as_incomplete(self) -> None:
        site = FakeConfluence(page_size=1)
        site.add_page("100", "Root")
        site.add_page("200", "First", parent_id="100")
        site.add_page("300", "Second", parent_id="100")
        site.fail("GET", "/wiki/api/v2/pages/100/direct-children?limit=250&cursor=1", 403)

        discovery = TreeDiscovery.discover(site.client(), "100")

        self.assertFalse(discovery.complete)
        self.assertEqual(list(discovery.pages), ["100"])
        self.assertTrue(any(failure.startswith("cannot list children of page '100'") for failure in discovery.failures))
