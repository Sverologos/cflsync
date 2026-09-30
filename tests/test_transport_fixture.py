# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for mock API transport fixtures."""

import json
import unittest

from tests.support import MockResponse, MockTransport, RecordedRequest
from cflsync import UrllibTransport


class TestCopyTransportContext(unittest.TestCase):

    def test_v1_clone_preserves_configured_host_credentials_and_opener(self) -> None:
        transport = UrllibTransport("example.atlassian.net", "user", "token", "/wiki/api/v2")
        clone = transport.clone("/wiki/rest/api")

        self.assertEqual(
            clone._request_url("/content/100/copy", None), "https://example.atlassian.net/wiki/rest/api/content/100/copy")
        self.assertEqual(clone._request_headers(None), transport._request_headers(None))
        self.assertIs(clone._opener, transport._opener)
        self.assertEqual(transport.base_url(), "https://example.atlassian.net/wiki/api/v2")


class TestMockTransport(unittest.TestCase):

    def test_records_a_request_and_returns_the_queued_response(self) -> None:
        response = MockResponse.from_json({"id": "123"})
        transport = MockTransport(iter([response]))

        actual_response = transport.make_request("GET", "/pages/123", headers={"Accept": "application/json"})

        self.assertEqual(actual_response, response)
        self.assertEqual(json.loads(actual_response.body), {"id": "123"})
        self.assertEqual(
            transport.requests,
            [RecordedRequest(method="GET", path="/pages/123", parameters={}, headers={"Accept": "application/json"}, body=None)])


# vim: set ts=4 sw=4 et tw=132:
