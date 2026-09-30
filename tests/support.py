# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reusable fixtures for cflsync tests."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
import hashlib
from io import StringIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qsl, quote, unquote, urlsplit

from cflsync import APIClient, AttachmentMetadata, PageMetadata, PageState, Profile, TransportError, TransportResponse, Workarea


@contextmanager
def temporary_workarea(profile: str = "default", root_page_id: str = "123456") -> Iterator[Workarea]:
    """Yield an initialized workarea rooted in a directory removed on exit."""
    with TemporaryDirectory(prefix="cflsync-test-") as temporary_dir:
        root = Path(temporary_dir)
        yield Workarea.init(root, root_page_id, profile)


def example_page_state(
        page_id: str = "123456",
        title: str = "Example page",
        directory: str = "Example page",
        parent_id: str | None = None) -> PageState:
    """Return a valid state for tests that need persisted state; by default, the fixture workarea's root page."""
    return PageState(
        page=PageMetadata(
            id=page_id,
            title=title,
            parent_id=parent_id,
            directory=directory,
            version=17,
            content_hash=hashlib.sha256(b"page").hexdigest()),
        attachments={
            "diagram.png": AttachmentMetadata(id="att987654", version=3, content_hash=hashlib.sha256(b"attachment").hexdigest())})


@dataclass(frozen=True)
class RecordedRequest:
    """A request received by :class:`MockTransport` or :class:`FakeConfluence`."""

    method: str
    path: str
    parameters: dict[str, str]
    headers: dict[str, str]
    body: bytes | None

    def json_body(self) -> Any:
        """Decode this request's JSON body, failing the test when it has none."""
        if self.body is None:
            raise AssertionError(f"{self.method} {self.path} has no body")

        return json.loads(self.body)


class MockResponse(TransportResponse):
    """A response returned by :class:`MockTransport`."""

    @classmethod
    def from_json(cls, value: object, status: int = 200) -> "MockResponse":
        return cls(status=status, headers={"Content-Type": "application/json"}, body=json.dumps(value).encode())


class MockTransport:
    """Queue responses and record requests for API-client tests."""

    def __init__(self, responses: Iterable[TransportResponse] = ()) -> None:
        self.requests: list[RecordedRequest] = []
        self.clone_prefixes: list[str | None] = []
        self._responses = deque(responses)

    def enqueue(self, response: TransportResponse) -> None:
        self._responses.append(response)

    def clone(self, prefix: str | None = None) -> "MockTransport":
        self.clone_prefixes.append(prefix)
        return self

    def make_request(
            self,
            method: str,
            path: str = "",
            parameters: Mapping[str, str] | None = None,
            headers: Mapping[str, str] | None = None,
            body: bytes | None = None) -> TransportResponse:
        self.requests.append(RecordedRequest(method, path, dict(parameters or {}), dict(headers or {}), body))
        if not self._responses:
            raise AssertionError(f"unexpected request: {method} {path}")

        return self._responses.popleft()


EMPTY_DOCUMENT = json.dumps({"type": "doc", "version": 1, "content": []})

COPY_FLAGS = {
    "copyAttachments": True,
    "copyLabels": True,
    "copyPermissions": False,
    "copyProperties": False,
    "copyCustomContents": False}


def copy_source_document() -> dict[str, Any]:
    """Return the sanitized, recorded native media-copy fixture."""
    return json.loads((Path(__file__).parent / "fixtures" / "page_copy" / "source-adf.json").read_text(encoding="utf-8"))


def run_with_site(site: FakeConfluence, workarea: Workarea, command: Callable[[], object]) -> str:
    """Run a command in *workarea*, with its API requests served by *site*, and return its standard output."""
    config = SimpleNamespace(profiles={workarea.profile: Profile("example.atlassian.net", "user", "token")})
    output = StringIO()
    with patch("cflsync.cli.Path.cwd", return_value=workarea.root_dir):
        with patch("cflsync.cli.Config.find", return_value=config):
            with patch("cflsync.cli.APIClient", return_value=site.client()):
                with redirect_stdout(output):
                    command()

    return output.getvalue()


class FakeConfluence:
    """An in-memory Confluence site serving the requests that :class:`APIClient` sends.

    Tests arrange the remote tree with :meth:`add_page`, :meth:`add_folder`, and :meth:`add_attachment`, inject
    failures with :meth:`fail`, and inspect :attr:`content`, :attr:`attachments`, and :attr:`requests` afterwards.
    Content and attachments are plain dictionaries keyed by ID. A request that the fake does not model fails the test
    instead of returning a guessed response.
    """

    def __init__(self, page_size: int = 250) -> None:
        self.page_size = page_size
        self.content: dict[str, dict[str, Any]] = {}
        self.attachments: dict[str, dict[str, Any]] = {}
        self.requests: list[RecordedRequest] = []
        self._failures = {}
        self._next_id = 900000
        # Tests select observed native outcomes; this is not a title-numbering policy.
        self.copy_titles: list[str] = []

    def client(self) -> APIClient:
        """Return an API client whose requests this site serves."""
        return APIClient("example.atlassian.net", "user", "token", transport=FakeTransport(self, "/wiki/api/v2"))

    def add_page(
            self,
            page_id: str,
            title: str,
            parent_id: str | None = None,
            body: str = EMPTY_DOCUMENT,
            version: int = 1,
            space_id: str = "98765") -> None:
        self.content[page_id] = {
            "type": "page",
            "id": page_id,
            "title": title,
            "parent_id": parent_id,
            "body": body,
            "version": version,
            "space_id": space_id,
            "labels": [],
            "restrictions": {},
            "properties": {},
            "custom_content": [],
            "comments": []}

    def add_folder(self, folder_id: str, title: str, parent_id: str | None = None, space_id: str = "98765") -> None:
        self.content[folder_id] = {"type": "folder", "id": folder_id, "title": title, "parent_id": parent_id, "space_id": space_id}

    def add_attachment(self, page_id: str, filename: str, body: bytes, attachment_id: str | None = None, version: int = 1) -> str:
        """Attach *body* to a page and return the attachment ID."""
        if attachment_id is None:
            attachment_id = f"att{self._new_id()}"

        self.attachments[attachment_id] = {
            "id": attachment_id,
            "page_id": page_id,
            "filename": filename,
            "body": body,
            "version": version,
            "file_id": f"file-{attachment_id}"}
        return attachment_id

    def fail(self, method: str, path: str, status: int, message: str = "injected failure") -> None:
        """Answer the next *method* request for *path* with an error.

        *path* is relative to the site and includes any query string that is part of the request path, as in a
        pagination link: for example ``/wiki/api/v2/pages/123456``. Repeated calls queue further failures.
        """
        self._failures.setdefault((method, path), []).append((status, message))

    def handle(
            self, method: str, path: str, parameters: Mapping[str, str] | None, headers: Mapping[str, str] | None,
            body: bytes | None) -> TransportResponse:
        """Record one request relative to the site and return its response."""
        self.requests.append(RecordedRequest(method, path, dict(parameters or {}), dict(headers or {}), body))
        failures = self._failures.get((method, path))
        if failures:
            status, message = failures.pop(0)
            return MockResponse.from_json({"message": message}, status)

        split = urlsplit(path)
        query = dict(parse_qsl(split.query))
        query.update(parameters or {})
        parts = [unquote(part) for part in split.path.strip("/").split("/")]
        if parts[:3] == ["wiki", "api", "v2"]:
            response = self._v2(method, parts[3:], query, body)
        elif parts[:3] == ["wiki", "rest", "api"]:
            response = self._v1(method, parts[3:], body)
        elif parts[:3] == ["wiki", "download", "attachments"] and len(parts) == 5 and method == "GET":
            response = self._download(parts[3], parts[4])
        else:
            response = None

        if response is None:
            raise AssertionError(f"FakeConfluence does not model {method} {path}")

        return response

    def _v2(self, method, parts, query, body):
        if parts == ["pages"] and method == "GET":
            return self._find_pages(query)

        if parts == ["pages"] and method == "POST":
            return self._create_page(json.loads(body))

        if len(parts) == 2 and parts[0] == "pages":
            if method == "GET":
                return self._get_page(parts[1])

            if method == "PUT":
                return self._update_page(parts[1], json.loads(body))

            if method == "DELETE":
                return self._delete_page(parts[1])

        if len(parts) == 3 and parts[0] in ("pages", "folders") and parts[2] == "ancestors" and method == "GET":
            return self._ancestors(parts[0][:-1], parts[1], query)

        if len(parts) == 3 and parts[0] == "pages" and parts[2] == "direct-children" and method == "GET":
            return self._children(parts[1], query)

        if len(parts) == 3 and parts[0] == "pages" and parts[2] == "attachments" and method == "GET":
            return self._list_attachments(parts[1], query)

        if len(parts) == 2 and parts[0] == "attachments" and method == "DELETE":
            return self._delete_attachment(parts[1])

        return None

    def _v1(self, method, parts, body):
        if len(parts) == 3 and parts[0] == "content" and parts[2] == "copy" and method == "POST":
            return self._copy_page(parts[1], json.loads(body))

        if len(parts) == 4 and parts[0] == "content" and parts[2:] == ["child", "attachment"] and method == "PUT":
            return self._create_attachment(parts[1], body)

        if len(parts) == 6 and parts[0] == "content" and parts[2:4] == ["child", "attachment"] and parts[5] == "data":
            if method == "POST":
                return self._update_attachment(parts[1], parts[4], body)

        return None

    def _copy_page(self, source_id, request):
        for flag, expected in COPY_FLAGS.items():
            if request.get(flag) is not expected:
                raise AssertionError(f"FakeConfluence only models copy with {flag}={expected}")

        destination = request["destination"]
        if destination["type"] != "parent_page":
            raise AssertionError("FakeConfluence only models page-parent copying")

        source = self._page(source_id)
        parent = self._page(destination["value"])
        if source is None or parent is None:
            return self._not_found()

        page_id = str(self._new_id())
        title = request["pageTitle"]
        if self.copy_titles:
            title = self.copy_titles.pop(0)

        self.add_page(page_id, title, parent["id"], space_id=parent["space_id"])
        self.content[page_id]["labels"] = deepcopy(source["labels"])
        file_ids = {}
        for attachment in list(self.attachments.values()):
            if attachment["page_id"] == source_id:
                new_id = self.add_attachment(page_id, attachment["filename"], attachment["body"])
                file_ids[attachment["file_id"]] = self.attachments[new_id]["file_id"]

        document = json.loads(source["body"])

        def remap(node):
            if isinstance(node, dict):
                attrs = node.get("attrs", {})
                if node.get("type") in {"media", "mediaInline"} and attrs.get("id") in file_ids:
                    attrs["id"] = file_ids[attrs["id"]]
                    attrs["collection"] = f"contentId-{page_id}"

                for value in node.values():
                    remap(value)
            elif isinstance(node, list):
                for value in node:
                    remap(value)

        remap(document)
        self.content[page_id]["body"] = json.dumps(document)
        return MockResponse.from_json({"id": page_id, "type": "page", "title": title, "version": {"number": 1}})

    def _find_pages(self, query):
        pages = [
            self._page_json(item) for item in self.content.values() if item["type"] == "page" and item["title"] == query["title"]]
        return MockResponse.from_json({"results": pages})

    def _get_page(self, page_id):
        page = self._page(page_id)
        if page is None:
            return self._not_found()

        return MockResponse.from_json(self._page_json(page))

    def _create_page(self, request):
        parent = self._page(request["parentId"])
        if parent is None:
            return MockResponse.from_json({"message": "parent page not found"}, 400)

        page_id = str(self._new_id())
        self.add_page(page_id, request["title"], parent["id"], request["body"]["value"], 1, request["spaceId"])
        return MockResponse.from_json(self._page_json(self.content[page_id]))

    def _update_page(self, page_id, request):
        page = self._page(page_id)
        if page is None:
            return self._not_found()

        if request["version"]["number"] != page["version"] + 1:
            return MockResponse.from_json({"message": "version must be incremented"}, 409)

        parent_id = request.get("parentId", page["parent_id"])
        if parent_id != page["parent_id"]:
            if parent_id not in self.content:
                return MockResponse.from_json({"message": "parent not found"}, 400)

            if parent_id == page_id or page_id in self._ancestor_ids(parent_id):
                return MockResponse.from_json({"message": "invalid hierarchy"}, 400)

        page["title"] = request["title"]
        page["body"] = request["body"]["value"]
        page["parent_id"] = parent_id
        page["version"] += 1
        return MockResponse.from_json(self._page_json(page))

    def _delete_page(self, page_id):
        if self._page(page_id) is None:
            return self._not_found()

        # Confluence's handling of children of a deleted page is unverified, so tests must not rely on it.
        if any(item["parent_id"] == page_id for item in self.content.values()):
            raise AssertionError(f"FakeConfluence does not model deleting page '{page_id}', which has children")

        del self.content[page_id]
        for attachment_id in [key for key, attachment in self.attachments.items() if attachment["page_id"] == page_id]:
            del self.attachments[attachment_id]

        return TransportResponse(204, {}, b"")

    def _ancestors(self, content_type, content_id, query):
        item = self.content.get(content_id)
        if item is None or item["type"] != content_type:
            return self._not_found()

        limit = int(query.get("limit", "25"))
        if limit > 250:
            return MockResponse.from_json({"message": "limit is too large"}, 400)

        # Confluence returns the nearest ancestors, highest first, without a next link.
        ancestors = [
            {
                "id": ancestor_id,
                "type": self.content[ancestor_id]["type"]} for ancestor_id in self._ancestor_ids(content_id)]
        return MockResponse.from_json({"results": ancestors[-limit:]})

    def _children(self, page_id, query):
        if self._page(page_id) is None:
            return self._not_found()

        children = []
        for position, item in enumerate(item for item in self.content.values() if item["parent_id"] == page_id):
            children.append(
                {
                    "id": item["id"],
                    "status": "current",
                    "title": item["title"],
                    "type": item["type"],
                    "childPosition": position})

        return self._listing(children, query, f"/wiki/api/v2/pages/{page_id}/direct-children")

    def _list_attachments(self, page_id, query):
        if self._page(page_id) is None:
            return self._not_found()

        attachments = [self._attachment_json(item) for item in self.attachments.values() if item["page_id"] == page_id]
        return self._listing(attachments, query, f"/wiki/api/v2/pages/{page_id}/attachments")

    def _create_attachment(self, page_id, body):
        if self._page(page_id) is None:
            return self._not_found()

        filename, content = self._multipart_file(body)
        for attachment in self.attachments.values():
            if attachment["page_id"] == page_id and attachment["filename"] == filename:
                return MockResponse.from_json({"message": "attachment already exists"}, 400)

        attachment_id = self.add_attachment(page_id, filename, content)
        return MockResponse.from_json({"results": [self._attachment_json(self.attachments[attachment_id])]})

    def _update_attachment(self, page_id, attachment_id, body):
        attachment = self.attachments.get(attachment_id)
        if attachment is None or attachment["page_id"] != page_id:
            return self._not_found()

        _, content = self._multipart_file(body)
        attachment["body"] = content
        attachment["version"] += 1
        return MockResponse.from_json(self._attachment_json(attachment))

    def _delete_attachment(self, attachment_id):
        if attachment_id not in self.attachments:
            return self._not_found()

        del self.attachments[attachment_id]
        return TransportResponse(204, {}, b"")

    def _download(self, page_id, filename):
        for attachment in self.attachments.values():
            if attachment["page_id"] == page_id and attachment["filename"] == filename:
                return TransportResponse(200, {"Content-Type": "application/octet-stream"}, attachment["body"])

        return self._not_found()

    def _listing(self, items, query, path):
        limit = int(query.get("limit", "25"))
        if limit > 250:
            return MockResponse.from_json({"message": "limit is too large"}, 400)

        start = int(query.get("cursor", "0"))
        end = start + min(limit, self.page_size)
        result = {"results": items[start:end]}
        if end < len(items):
            result["_links"] = {"next": f"{path}?limit={limit}&cursor={end}"}

        return MockResponse.from_json(result)

    def _page(self, page_id):
        item = self.content.get(page_id)
        if item is None or item["type"] != "page":
            return None

        return item

    def _ancestor_ids(self, content_id):
        ancestors = []
        parent_id = self.content[content_id]["parent_id"]
        while parent_id is not None:
            ancestors.insert(0, parent_id)
            parent_id = self.content[parent_id]["parent_id"]

        return ancestors

    def _page_json(self, page):
        value = {
            "id": page["id"],
            "status": "current",
            "title": page["title"],
            "spaceId": page["space_id"],
            "version": {
                "number": page["version"]},
            "body": {
                "atlas_doc_format": {
                    "value": page["body"]}}}
        if page["parent_id"] is not None:
            value["parentId"] = page["parent_id"]
            value["parentType"] = self.content[page["parent_id"]]["type"]

        return value

    def _attachment_json(self, attachment):
        return {
            "id": attachment["id"],
            "title": attachment["filename"],
            "mediaType": "application/octet-stream",
            "fileId": attachment["file_id"],
            "version": {
                "number": attachment["version"]},
            "_links": {
                "download": f"/download/attachments/{attachment['page_id']}/{quote(attachment['filename'])}"}}

    def _multipart_file(self, body):
        # APIClient sends one file part followed by a minorEdit part; see cflsync.api._multipart_body.
        header, _, rest = body.partition(b"\r\n\r\n")
        filename = re.search(rb'filename="([^"]*)"', header).group(1).decode("utf-8")
        content, _, _ = rest.partition(b"\r\n--")
        return filename, content

    def _not_found(self):
        return MockResponse.from_json({"message": "not found"}, 404)

    def _new_id(self):
        self._next_id += 1
        return self._next_id


class FakeTransport:
    """A :class:`Transport` that sends requests to a :class:`FakeConfluence` site."""

    def __init__(self, site: FakeConfluence, prefix: str) -> None:
        self._site = site
        self._prefix = prefix

    def clone(self, prefix: str | None = None) -> "FakeTransport":
        if prefix is None:
            prefix = self._prefix

        return FakeTransport(self._site, prefix)

    def make_request(
            self,
            method: str,
            path: str = "",
            parameters: Mapping[str, str] | None = None,
            headers: Mapping[str, str] | None = None,
            body: bytes | None = None) -> TransportResponse:
        return self._site.handle(method, f"{self._prefix}{path}", parameters, headers, body)


class LostCopyResponseTransport(FakeTransport):
    """Execute native copy, then lose or replace its response, preserving cloned prefixes."""

    def __init__(self, site: FakeConfluence, prefix: str, response: TransportResponse | None = None) -> None:
        super().__init__(site, prefix)
        self._response = response

    def clone(self, prefix: str | None = None) -> "LostCopyResponseTransport":
        if prefix is None:
            prefix = self._prefix

        return LostCopyResponseTransport(self._site, prefix, self._response)

    def make_request(self, method, path="", parameters=None, headers=None, body=None) -> TransportResponse:
        result = super().make_request(method, path, parameters, headers, body)
        if method == "POST" and path.endswith("/copy"):
            if self._response is None:
                raise TransportError("copy response lost")

            return self._response

        return result


# vim: set ts=4 sw=4 et tw=132:
