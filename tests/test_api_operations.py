# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for typed Confluence page and attachment operations."""

import unittest

from cflsync import APIClient, APIError
from tests.support import MockResponse, MockTransport


def page_fixture(page_id: str = "123456", title: str = "Example page") -> dict[str, object]:
    return {
        "id": page_id,
        "title": title,
        "spaceId": "98765",
        "parentId": "456789",
        "version": {
            "number": 17},
        "body": {
            "atlas_doc_format": {
                "value": '{"type":"doc","version":1,"content":[]}'}}}


def attachment_fixture() -> dict[str, object]:
    return {
        "id": "att567890",
        "title": "diagram.png",
        "mediaType": "image/png",
        "fileId": "file-diagram",
        "version": {
            "number": 3},
        "_links": {
            "download": "/download/attachments/123456/diagram.png?version=3"}}


def user_fixture(account_id: str = "account-123", display_name: str | None = "Example User") -> dict[str, object]:
    return {"accountId": account_id, "email": "example.user@example.test", "displayName": display_name, "accountType": "atlassian"}


class TestAPIClientPageOperations(unittest.TestCase):

    def test_does_not_choose_between_users_with_the_same_email(self) -> None:
        first = user_fixture()
        second = user_fixture("account-456")
        transport = MockTransport([MockResponse.from_json({"results": [{"user": first}, {"user": second}]})])
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)

        self.assertIsNone(client.find_user_by_name_and_email("Example User", "example.user@example.test"))


class TestAPIClientTreeOperations(unittest.TestCase):

    def test_continues_a_full_ancestor_listing_from_its_highest_ancestor(self) -> None:
        nearest = [{"id": str(1000 + index), "type": "page"} for index in range(250)]
        nearest[0] = {"id": "900", "type": "folder"}
        higher = [{"id": "1", "type": "page"}, {"id": "2", "type": "page"}]
        transport = MockTransport([MockResponse.from_json({"results": nearest}), MockResponse.from_json({"results": higher})])
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)

        ancestors = client.page_ancestors("123456")

        self.assertEqual([ancestor.id for ancestor in ancestors[:3]], ["1", "2", "900"])
        self.assertEqual(len(ancestors), 252)
        self.assertEqual(transport.requests[1].path, "/folders/900/ancestors")

    def test_rejects_a_repeated_ancestor(self) -> None:
        transport = MockTransport([MockResponse.from_json({"results": [{"id": "123456", "type": "page"}]})])
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)

        with self.assertRaisesRegex(APIError, "more than once"):
            client.page_ancestors("123456")

    def test_rejects_continuation_past_an_unsupported_ancestor_type(self) -> None:
        nearest = [{"id": str(1000 + index), "type": "page"} for index in range(250)]
        nearest[0] = {"id": "900", "type": "whiteboard"}
        transport = MockTransport([MockResponse.from_json({"results": nearest})])
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)

        with self.assertRaisesRegex(APIError, "beyond whiteboard '900'"):
            client.page_ancestors("123456")

    def test_rejects_an_ancestor_without_a_type(self) -> None:
        transport = MockTransport([MockResponse.from_json({"results": [{"id": "100"}]})])
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)

        with self.assertRaisesRegex(APIError, "content.type"):
            client.page_ancestors("123456")

    def test_rejects_a_non_page_descendant(self) -> None:
        children = {"results": [{"id": "200", "status": "current", "title": "Folder", "type": "folder"}]}
        transport = MockTransport([MockResponse.from_json(children)])
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)

        with self.assertRaisesRegex(APIError, "contain non-page folder '200'"):
            client.page_descendants("123456")

    def test_rejects_a_repeated_descendant(self) -> None:
        root_children = {"results": [{"id": "200", "status": "current", "title": "Child", "type": "page"}]}
        child_children = {"results": [{"id": "200", "status": "current", "title": "Child", "type": "page"}]}
        transport = MockTransport([MockResponse.from_json(root_children), MockResponse.from_json(child_children)])
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)

        with self.assertRaisesRegex(APIError, "contain '200' more than once"):
            client.page_descendants("123456")


class TestAPIClientCopy(unittest.TestCase):

    def test_unusable_accepted_responses_report_uncertainty(self) -> None:
        responses = [MockResponse(200, {}, b"{"), MockResponse(200, {}, b"\xff")]
        responses += [
            MockResponse.from_json(value)
            for value in [[], None, {}, {
                "id": ""}, {
                    "id": 300}, {
                        "id": "att300"}, {
                            "id": "../300"}, {
                                "id": "٣٠٠"}]]
        for response in responses:
            with self.subTest(body=response.body):
                transport = MockTransport([response])
                client = APIClient("example.atlassian.net", "user", "token", transport=transport)
                with self.assertRaisesRegex(APIError, "outcome is uncertain.*duplicate"):
                    client.copy_page("100", "200", "New")

                self.assertEqual(len(transport.requests), 1)

    def test_native_errors_preserve_status_without_retry_or_fallback(self) -> None:
        for status in [400, 401, 403, 404, 429, 500, 502, 503, 504]:
            with self.subTest(status=status):
                transport = MockTransport([MockResponse.from_json({"message": "native failure"}, status)])
                client = APIClient("example.atlassian.net", "user", "token", transport=transport)
                with self.assertRaisesRegex(APIError, "native failure") as raised:
                    client.copy_page("100", "200", "New")

                self.assertEqual(raised.exception.status, status)
                self.assertEqual(len(transport.requests), 1)


# vim: set ts=4 sw=4 et tw=132:
