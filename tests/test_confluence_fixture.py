# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for the in-memory Confluence site fixture, exercised through the API client."""

import unittest

from tests.support import FakeConfluence


class TestFakeConfluencePages(unittest.TestCase):

    def test_deletes_a_leaf_page_and_its_attachments(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Page")
        site.add_attachment("100", "diagram.png", b"PNG")

        site.client().get_page("100").delete()

        self.assertEqual((site.content, site.attachments), ({}, {}))


class TestFakeConfluenceFailures(unittest.TestCase):

    def test_a_transient_failure_is_retried_by_the_client(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Page")
        site.fail("GET", "/wiki/api/v2/pages/100", 503)

        self.assertEqual(site.client().get_page("100").id, "100")
        self.assertEqual(len(site.requests), 2)

    def test_an_unmodelled_request_fails_the_test(self) -> None:
        site = FakeConfluence()

        with self.assertRaisesRegex(AssertionError, "does not model GET /wiki/rest/api/user"):
            site.client().get_user("account-123")


# vim: set ts=4 sw=4 et tw=132:
