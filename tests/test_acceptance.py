# Copyright (c) 2026 Sven Rosiers
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Offline acceptance workflow against a recorded Confluence fixture."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cflsync import APIClient, Config, Profile, TransportResponse
from cflsync.cli import main
from tests.support import FakeConfluence, RecordedRequest


def _paragraph(text: str) -> dict[str, object]:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _representative_document(file_id: str) -> dict[str, object]:
    header = _paragraph("Header")
    cell = _paragraph("Cell")
    return {
        "type":
        "doc",
        "version":
        1,
        "content": [
            {
                "type": "heading",
                "attrs": {
                    "level": 2,
                    "localId": "heading-local-id"},
                "content": [{
                    "type": "text",
                    "text": "An L2 Heading"}], }, {
                        "type":
                        "paragraph",
                        "attrs": {
                            "localId": "paragraph-local-id"},
                        "content": [
                            {
                                "type": "text",
                                "text": "A "}, {
                                    "type": "text",
                                    "text": "link",
                                    "marks": [{
                                        "type": "link",
                                        "attrs": {
                                            "href": "https://example.test",
                                            "title": ""}}], }, ], }, {
                                                "type": "paragraph"}, {
                                                    "type": "paragraph",
                                                    "content": [{
                                                        "type": "status",
                                                        "attrs": {
                                                            "text": "Done",
                                                            "color": "green"}}], }, {
                                                                "type": "extension",
                                                                "attrs": {
                                                                    "extensionType": "com.atlassian.confluence.macro.core",
                                                                    "extensionKey": "recorded-fixture"}, },
            {
                "type":
                "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [{
                            "type": "tableHeader",
                            "attrs": {
                                "colspan": 2,
                                "rowspan": 1},
                            "content": [header]}], }, {
                                "type":
                                "tableRow",
                                "content": [
                                    {
                                        "type": "tableCell",
                                        "attrs": {
                                            "colspan": 1,
                                            "rowspan": 1},
                                        "content": [cell, cell]}, {
                                            "type": "tableCell",
                                            "attrs": {
                                                "colspan": 1,
                                                "rowspan": 1},
                                            "content": [cell]}, ], }, ], }, {
                                                "type": "mediaSingle",
                                                "attrs": {
                                                    "layout": "center"},
                                                "content":
                                                [{
                                                    "type": "media",
                                                    "attrs": {
                                                        "id": file_id,
                                                        "type": "file",
                                                        "collection": ""}}], }, ], }


class RecordedAttachment:
    """One attachment held by the Confluence fixture."""

    def __init__(self, id: str, filename: str, body: bytes) -> None:
        self.id = id
        self.filename = filename
        self.file_id = f"file-{id}"
        self.download = f"/download/{id}"
        self.version = 1
        self.body = body

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.filename,
            "mediaType": "image/png",
            "fileId": self.file_id,
            "version": {
                "number": self.version},
            "_links": {
                "download": self.download}, }


class RecordedConfluenceTransport:
    """A mutable local fixture for the endpoints used by the acceptance flow."""

    page_id = "123456"
    parent_id = "456789"

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self._title = "Acceptance page"
        self._version = 1
        self._document: dict[str, object] = {"type": "doc", "version": 1, "content": []}
        self._attachments: dict[str, RecordedAttachment] = {}

    def clone(self, prefix: str | None = None) -> "RecordedConfluenceTransport":
        return self

    def make_request(
            self,
            method: str,
            path: str = "",
            parameters: Mapping[str, str] | None = None,
            headers: Mapping[str, str] | None = None,
            body: bytes | None = None) -> TransportResponse:
        self.requests.append(RecordedRequest(method, path, dict(parameters or {}), dict(headers or {}), body))
        if method == "GET" and path == f"/pages/{self.parent_id}":
            return self._json(self._parent())

        if method == "GET" and path == f"/pages/{self.parent_id}/attachments":
            return self._json({"results": []})

        if method == "POST" and path == "/pages":
            return self._create_page(body)

        if method == "GET" and path == f"/pages/{self.page_id}":
            return self._json(self._page())

        if method == "GET" and path == f"/pages/{self.page_id}/ancestors":
            return self._json({"results": [{"id": self.parent_id, "type": "page"}]})

        if method == "PUT" and path == f"/pages/{self.page_id}":
            return self._update_page(body)

        if method == "GET" and path == f"/pages/{self.page_id}/attachments":
            return self._json({"results": [item.to_json() for item in self._attachments.values()]})

        if method == "PUT" and path == f"/content/{self.page_id}/child/attachment":
            return self._create_attachment(body)

        if method == "POST" and path.startswith(f"/content/{self.page_id}/child/attachment/"):
            return self._update_attachment(path, body)

        if method == "DELETE" and path.startswith("/attachments/"):
            return self._delete_attachment(path)

        if method == "GET" and path.startswith("/download/"):
            return self._download_attachment(path)

        raise AssertionError(f"unexpected fixture request: {method} {path}")

    def set_remote_page(self, document: dict[str, object], title: str | None = None) -> None:
        """Simulate a completed remote edit without performing an HTTP request."""
        self._document = document
        if title is not None:
            self._title = title

        self._version += 1

    def remote_content(self) -> list[dict[str, object]]:
        """Return the fixture page's current ADF block content."""
        content = self._document["content"]
        if not isinstance(content, list) or not all(isinstance(block, dict) for block in content):
            raise AssertionError("fixture page content is not a list of ADF blocks")

        return content

    def attachment_file_id(self, filename: str) -> str:
        return self._attachments[filename].file_id

    def attachment_body(self, filename: str) -> bytes:
        return self._attachments[filename].body

    def _parent(self):
        return {
            "id": self.parent_id,
            "title": "Acceptance parent",
            "spaceId": "98765",
            "version": {
                "number": 1},
            "body": {
                "atlas_doc_format": {
                    "value": json.dumps({
                        "type": "doc",
                        "version": 1,
                        "content": []})}}, }

    def _page(self):
        return {
            "id": self.page_id,
            "title": self._title,
            "spaceId": "98765",
            "parentId": self.parent_id,
            "version": {
                "number": self._version},
            "body": {
                "atlas_doc_format": {
                    "value": json.dumps(self._document)}}, }

    def _create_page(self, body):
        value = self._request_json(body)
        self._title = value["title"]
        self._document = json.loads(value["body"]["value"])
        self._version = 1

        return self._json(self._page())

    def _update_page(self, body):
        value = self._request_json(body)
        if value.get("version") != {"number": self._version + 1}:
            return self._json({"message": "version conflict"}, 409)

        self._title = value["title"]
        self._document = json.loads(value["body"]["value"])
        self._version += 1

        return self._json(self._page())

    def _create_attachment(self, body):
        filename, content = self._multipart(body)
        item = RecordedAttachment(f"att-{len(self._attachments) + 1}", filename, content)
        self._attachments[filename] = item

        return self._json({"results": [item.to_json()]})

    def _update_attachment(self, path, body):
        attachment_id = path.rsplit("/", 2)[-2]
        filename, content = self._multipart(body)
        for item in self._attachments.values():
            if item.id == attachment_id:
                if item.filename != filename:
                    raise AssertionError("attachment update changed its filename")

                item.body = content
                item.version += 1
                return self._json(item.to_json())

        return self._json({"message": "missing attachment"}, 404)

    def _delete_attachment(self, path):
        attachment_id = path.rsplit("/", 1)[-1]
        for filename, item in self._attachments.items():
            if item.id == attachment_id:
                del self._attachments[filename]
                return TransportResponse(204, {}, b"")

        return self._json({"message": "missing attachment"}, 404)

    def _download_attachment(self, path):
        for item in self._attachments.values():
            if item.download == path:
                return TransportResponse(200, {"Content-Type": "image/png"}, item.body)

        return self._json({"message": "missing attachment"}, 404)

    def _request_json(self, body):
        if body is None:
            raise AssertionError("fixture request has no body")

        return json.loads(body)

    def _multipart(self, body):
        if body is None:
            raise AssertionError("fixture attachment request has no body")

        match = re.search(br'filename="([^"]+)"\r\n.*?\r\n\r\n(.*?)\r\n--cflsync-boundary', body, re.DOTALL)
        if match is None:
            raise AssertionError("fixture attachment request is not cflsync multipart data")

        return match.group(1).decode("utf-8"), match.group(2)

    def _json(self, value, status=200):
        return TransportResponse(status, {"Content-Type": "application/json"}, json.dumps(value).encode("utf-8"))


class TestRecordedAcceptanceWorkflow(unittest.TestCase):

    def _run(self, root, config, client, arguments):
        output = StringIO()
        errors = StringIO()
        with patch("cflsync.cli.Path.cwd", return_value=root):
            with patch("cflsync.cli.Config.find", return_value=config):
                with patch("cflsync.cli.APIClient", return_value=client):
                    with redirect_stdout(output), redirect_stderr(errors):
                        status = main(["cflsync", *arguments])

        return status, output.getvalue(), errors.getvalue()

    def test_runs_the_complete_offline_workflow_with_representative_documents(self) -> None:
        with TemporaryDirectory(prefix="cflsync-acceptance-") as temporary:
            root = Path(temporary)
            config = Config(root / "credentials.json")
            transport = RecordedConfluenceTransport()
            client = APIClient("fixture.invalid", "fixture", "token", transport=transport)

            with patch("builtins.input", side_effect=["fixture.invalid", "fixture@example.test"]):
                with patch("cflsync.cli.getpass", return_value="token"):
                    status, _, errors = self._run(root, config, client, ["auth"])

            self.assertEqual(status, 0)
            self.assertEqual(errors, "")
            self.assertTrue(config.path.is_file())
            self.assertEqual(self._run(root, config, client, ["init", "456789"])[0], 0)
            self.assertEqual(self._run(root, config, client, ["page", "pull", "456789"])[0], 0)
            self.assertEqual(self._run(root, config, client, ["page", "create", "456789", "Acceptance page"])[0], 0)

            status, output, errors = self._run(root, config, client, ["page", "status", transport.page_id])
            self.assertEqual(status, 0)
            self.assertEqual(errors, "")
            self.assertIn("local:  unchanged", output)
            self.assertIn("remote: unchanged", output)

            directory = root / "Acceptance parent" / "Acceptance page"
            attachments = directory / "_attachments"
            attachments.mkdir(exist_ok=True)
            (attachments / "diagram.png").write_bytes(b"fixture image")
            (directory / "content.md").write_text(
                "# Acceptance page\n\nEdited [link](https://example.test).\n\n![Diagram](_attachments/diagram.png)\n",
                encoding="utf-8",
            )

            status, _, errors = self._run(root, config, client, ["page", "push", transport.page_id])
            self.assertEqual(status, 0)
            self.assertEqual(errors, "")
            self.assertEqual(transport.remote_content()[0]["type"], "paragraph")
            self.assertEqual(transport.attachment_body("diagram.png"), b"fixture image")

            document = _representative_document(transport.attachment_file_id("diagram.png"))
            transport.set_remote_page(document, "Renamed acceptance page")
            status, _, errors = self._run(root, config, client, ["page", "pull", transport.page_id])
            self.assertEqual(status, 0)
            self.assertEqual(errors, "")

            directory = root / "Acceptance parent" / "Renamed acceptance page"
            markdown = (directory / "content.md").read_text(encoding="utf-8")
            self.assertEqual(sum(line.startswith("# ") for line in markdown.splitlines()), 1)
            self.assertIn("# Renamed acceptance page", markdown)
            self.assertIn("## An L2 Heading", markdown)
            self.assertIn("[link](https://example.test)", markdown)
            self.assertIn('cfl-type="status"', markdown)
            self.assertIn("atlas_doc_format", markdown)
            self.assertIn("<table", markdown)
            self.assertEqual((directory / "_attachments" / "diagram.png").read_bytes(), b"fixture image")

            status, output, errors = self._run(root, config, client, ["page", "status", transport.page_id])
            self.assertEqual(status, 0)
            self.assertEqual(errors, "")
            self.assertIn("Page '123456' (Renamed acceptance page)", output)
            self.assertIn("local:  unchanged", output)
            self.assertIn("remote: unchanged", output)
            self.assertTrue(transport.requests)

    def test_reports_conflicts_and_force_commands_choose_the_requested_side(self) -> None:
        with TemporaryDirectory(prefix="cflsync-acceptance-") as temporary:
            root = Path(temporary)
            config = Config(root / "credentials.json", {"default": Profile("fixture.invalid", "fixture", "token")})
            transport = RecordedConfluenceTransport()
            client = APIClient("fixture.invalid", "fixture", "token", transport=transport)
            self.assertEqual(self._run(root, config, client, ["init", "456789"])[0], 0)
            self.assertEqual(self._run(root, config, client, ["page", "pull", "456789"])[0], 0)
            self.assertEqual(self._run(root, config, client, ["page", "create", "456789", "Acceptance page"])[0], 0)

            page = root / "Acceptance parent" / "Acceptance page" / "content.md"
            page.write_text("# Acceptance page\n\nLocal pull conflict\n", encoding="utf-8")
            transport.set_remote_page({"type": "doc", "version": 1, "content": [_paragraph("Remote pull winner")]})
            status, _, errors = self._run(root, config, client, ["page", "pull", transport.page_id])
            self.assertEqual(status, 1)
            self.assertIn("pull conflicts", errors)
            self.assertIn("Local pull conflict", page.read_text(encoding="utf-8"))

            status, _, errors = self._run(root, config, client, ["page", "pull", "--force", transport.page_id])
            self.assertEqual(status, 0)
            self.assertEqual(errors, "")
            self.assertIn("Remote pull winner", page.read_text(encoding="utf-8"))

            page.write_text("# Acceptance page\n\nLocal push winner\n", encoding="utf-8")
            transport.set_remote_page({"type": "doc", "version": 1, "content": [_paragraph("Remote push conflict")]})
            status, _, errors = self._run(root, config, client, ["page", "push", transport.page_id])
            self.assertEqual(status, 1)
            self.assertIn("push conflicts", errors)

            status, _, errors = self._run(root, config, client, ["page", "push", "--force", transport.page_id])
            self.assertEqual(status, 0)
            self.assertEqual(errors, "")
            self.assertEqual(transport.remote_content(), [_paragraph("Local push winner")])


class TestLiveAcceptanceIsManualOnly(unittest.TestCase):

    def test_an_unmocked_client_cannot_reach_a_confluence_site(self) -> None:
        client = APIClient("example.atlassian.net", "user", "token")

        with self.assertRaisesRegex(RuntimeError, "must not open network connections"):
            client.get_page("123456")


class TestTreeAcceptanceWorkflow(unittest.TestCase):
    """The page-by-page workflow on a tree: Root (100) with Child (200) and Other (400), and Grandchild (300) below Child."""

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_attachment("100", "diagram.png", b"PNG")
        self.site.add_page("200", "Child", parent_id="100")
        self.site.add_page("300", "Grandchild", parent_id="200")
        self.site.add_page("400", "Other", parent_id="100")

    def _run(self, root, *arguments):
        config = Config(root / "credentials.json", {"default": Profile("fixture.invalid", "fixture", "token")})
        output = StringIO()
        errors = StringIO()
        with patch("cflsync.cli.Path.cwd", return_value=root):
            with patch("cflsync.cli.Config.find", return_value=config):
                with patch("cflsync.cli.APIClient", return_value=self.site.client()):
                    with redirect_stdout(output), redirect_stderr(errors):
                        status = main(["cflsync", *arguments])

        return status, output.getvalue(), errors.getvalue()

    def _succeeds(self, root, *arguments):
        status, output, errors = self._run(root, *arguments)
        self.assertEqual((status, errors), (0, ""), arguments)
        return output

    def test_manages_a_tree_page_by_page(self) -> None:
        with TemporaryDirectory(prefix="cflsync-acceptance-") as temporary:
            root = Path(temporary) / "workarea"
            root.mkdir()
            self._succeeds(root, "init", "Root")

            status, _, errors = self._run(root, "page", "pull", "300")
            self.assertEqual(status, 1)
            self.assertIn("parent page 'Child' (200) is not present locally; run: cflsync page pull 200", errors)

            for page_id in ["100", "200", "300", "400"]:
                self._succeeds(root, "page", "pull", page_id)

            tree = root / "Root"
            self.assertEqual((tree / "_attachments" / "diagram.png").read_bytes(), b"PNG")
            grandchild = tree / "Child" / "Grandchild"
            self.assertIn("remote: unchanged", self._succeeds(root, "page", "status", str(grandchild / "content.md")))

            self._succeeds(root, "page", "create", str(tree / "Child"), "New page")
            new_page = tree / "Child" / "New page"
            (new_page / "content.md").write_text("# New page\n\nWritten locally.\n", encoding="utf-8")
            self._succeeds(root, "page", "push", str(new_page))
            [new_page_id] = [item["id"] for item in self.site.content.values() if item["title"] == "New page"]
            self.assertIn("Written locally.", self.site.content[new_page_id]["body"])

            self._succeeds(root, "page", "rename", "200", "Renamed child")
            renamed = tree / "Renamed child"
            self.assertEqual(
                sorted(path.name for path in renamed.iterdir()), ["Grandchild", "New page", "_attachments", "content.md"])

            self._succeeds(root, "page", "move", "300", "400")
            self.assertTrue((tree / "Other" / "Grandchild" / "content.md").is_file())
            self.assertEqual(self.site.content["300"]["parent_id"], "400")

            self._succeeds(root, "page", "remove", "--force", str(renamed / "New page"))
            self.assertNotIn(new_page_id, self.site.content)
            self.assertFalse((renamed / "New page").exists())

            status, _, errors = self._run(root, "page", "remove", "--force", "100")
            self.assertEqual(status, 1)
            self.assertIn("page '100' has 2 child pages; remove them first", errors)

            for page_ref in ["100", "Renamed child", "300", "400"]:
                output = self._succeeds(root, "page", "status", page_ref)
                self.assertIn("local:  unchanged", output)
                self.assertIn("remote: unchanged", output)
                self.assertNotIn("location:", output)


# vim: set ts=4 sw=4 et tw=132:
