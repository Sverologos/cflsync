# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for API client transport behavior."""

import unittest

from cflsync import APIClient, TransportError
from tests.support import MockResponse


class TestAPIClientTransport(unittest.TestCase):

    def test_retries_transient_transport_failures_for_reads(self) -> None:

        class FlakyTransport:

            def __init__(self) -> None:
                self.calls = 0

            def clone(self, prefix=None):
                return self

            def make_request(self, method, path="", parameters=None, headers=None, body=None):
                self.calls += 1
                if self.calls == 1:
                    raise TransportError("injected connection failure")

                return MockResponse.from_json({"id": "123456"})

        transport = FlakyTransport()
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)

        self.assertEqual(client.make_request("GET", "/pages/123456").status, 200)
        self.assertEqual(transport.calls, 2)


# vim: set ts=4 sw=4 et tw=132:
