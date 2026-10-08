# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Push decisions, uploads, and partial-failure behavior."""

from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cflsync import APIClient, PageChangeDetector, PageChangeStatus, PageState, PandocRunner, Profile, SyncError
from cflsync.cli import PagePullCommand, PagePushCommand, PageStatusCommand
from tests.support import FakeConfluence, MockResponse, MockTransport, run_with_site, temporary_workarea
from tests.test_api_operations import attachment_fixture, page_fixture, user_fixture


def adf_body(text="Example"):
    document = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}

    return {"atlas_doc_format": {"value": json.dumps(document)}}


class TestPagePush(unittest.TestCase):

    def _page(self, version=17, title="Example page"):
        page = page_fixture(title=title)
        page["version"] = {"number": version}
        page["body"] = adf_body()

        return page

    def _run(self, workarea, command, responses):
        transport = MockTransport(responses)
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)
        config = SimpleNamespace(profiles={workarea.profile: Profile("example.atlassian.net", "user", "token")})
        output = StringIO()
        with patch("cflsync.cli.Path.cwd", return_value=workarea.root_dir):
            with patch("cflsync.cli.Config.find", return_value=config):
                with patch("cflsync.cli.APIClient", return_value=client):
                    with redirect_stdout(output):
                        status = command()

        return output.getvalue(), status, transport

    def _pull(self, workarea, attachments=None):
        if attachments is None:
            attachments = [attachment_fixture()]

        page = self._page()
        responses = [
            MockResponse.from_json(page),
            MockResponse.from_json(page),
            MockResponse.from_json({"results": attachments}), *[MockResponse(200, {}, b"PNG") for attachment in attachments], ]
        self._run(workarea, lambda: PagePullCommand().run("123456"), responses)

    def _push(self, workarea, responses, force=False):
        return self._run(workarea, lambda: PagePushCommand().run("123456", force=force), responses)

    def _push_responses(self, page=None, attachments=None, uploads=(), updated=None, after=None):
        """Queue resolve, fetch, manifest, uploads, refreshed manifest, and page update."""
        if page is None:
            page = self._page()

        if attachments is None:
            attachments = [attachment_fixture()]

        if after is None:
            after = attachments

        if updated is None:
            updated = self._page(version=page["version"]["number"] + 1)

        return [
            MockResponse.from_json(page),
            MockResponse.from_json(page),
            MockResponse.from_json({"results": attachments}), *uploads,
            MockResponse.from_json({"results": after}),
            MockResponse.from_json(updated), ]

    def _edit(self, workarea, markdown="# Example page\n\nEdited\n"):
        (workarea.root_dir / "Example page_123456/content.md").write_text(markdown, encoding="utf-8")

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_resolves_a_mailto_link_to_a_mention_when_pushing(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            self._edit(workarea, "# Example page\n\n[Example User](mailto:example.user@example.test)\n")
            responses = self._push_responses()
            responses.insert(-1, MockResponse.from_json({"results": [{"user": user_fixture()}]}))

            _, status, transport = self._push(workarea, responses)

            document = json.loads(transport.requests[-1].json_body()["body"]["value"])
            lookup = transport.requests[-2]
            self.assertEqual(status, 0)
            self.assertEqual(lookup.path, "/search/user")
            self.assertEqual(lookup.parameters, {"cql": 'user.fullname~"Example User"'})
            self.assertEqual(
                document["content"][0]["content"], [{
                    "type": "mention",
                    "attrs": {
                        "id": "account-123",
                        "text": "@Example User"}}])

    def test_deletes_only_previously_managed_removed_attachments(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            directory = workarea.root_dir / "Example page_123456"
            (directory / "_attachments/diagram.png").unlink()
            (directory / "_attachments/unmanaged.png").write_bytes(b"KEEP")
            self._edit(workarea)

            _, _, transport = self._push(workarea, self._push_responses() + [MockResponse(204, {}, b"")])

            deletes = [request.path for request in transport.requests if request.method == "DELETE"]
            state = PageState.load(workarea.cache_path("123456"))
            self.assertEqual(deletes, ["/attachments/att567890"])
            self.assertEqual(dict(state.attachments), {})
            self.assertTrue((directory / "_attachments/unmanaged.png").is_file())

    def test_updates_and_deletes_only_the_managed_one_of_duplicate_attachments(self) -> None:
        duplicate = attachment_fixture()
        duplicate.update({"id": "att111111", "fileId": "file-duplicate", "_links": {"download": "/download/duplicate"}})
        attachments = [attachment_fixture(), duplicate]
        for change in ("edited", "removed"):
            with self.subTest(change=change):
                with temporary_workarea() as workarea:
                    self._pull(workarea, attachments)
                    path = workarea.root_dir / "Example page_123456/_attachments/diagram.png"
                    if change == "edited":
                        path.write_bytes(b"EDITED")
                        responses = self._push_responses(
                            attachments=attachments, uploads=[MockResponse.from_json(attachment_fixture())])
                    else:
                        path.unlink()
                        responses = self._push_responses(attachments=attachments) + [MockResponse(204, {}, b"")]
                    self._edit(workarea)

                    _, _, transport = self._push(workarea, responses)

                    writes = [
                        (request.method, request.path) for request in transport.requests if request.method in {"POST", "DELETE"}]
                    state = PageState.load(workarea.cache_path("123456"))
                    if change == "edited":
                        self.assertEqual(writes, [("POST", "/content/123456/child/attachment/att567890/data")])
                        self.assertEqual(state.attachments["diagram.png"].id, "att567890")
                    else:
                        self.assertEqual(writes, [("DELETE", "/attachments/att567890")])
                        self.assertEqual(dict(state.attachments), {})

    def test_rejects_a_page_without_a_cache_entry(self) -> None:
        with temporary_workarea() as workarea:
            with self.assertRaisesRegex(SyncError, "not managed"):
                self._push(workarea, [MockResponse.from_json(self._page())])


class TestPagePushInTree(unittest.TestCase):
    """Pushes in a tree of Root (100) with Child (200) below it."""

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Child", parent_id="100")

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea):
        for page_id in ["100", "200"]:
            self._run(workarea, lambda: PagePullCommand().run(page_id))

    def test_uploads_new_images_referenced_by_figures_and_html_table_cells(self) -> None:
        figure = '<figure data-type="media-single" data-width="400" data-width-type="pixel">\n' \
            '<img src="_attachments/new%20%26%20image.png" width="800" height="600" alt="New" />\n' \
            '<figcaption>Caption</figcaption>\n</figure>\n'
        legacy = '<figure data-type="media-single" data-width="400" data-width-type="pixel">\n\n' \
            '<img src="_attachments/new%20%26%20image.png" width="800" height="600" alt="New" />\n\n' \
            '<figcaption>\n\nCaption\n\n</figcaption>\n\n</figure>\n'
        joined = '<figure data-type="media-single" data-width="400" data-width-type="pixel">\n\n' \
            '<img src="_attachments/new%20%26%20image.png" width="800" height="600" alt="New" />\n\n' \
            '<figcaption>\n\nCaption\n\n</figcaption>\n</figure>\n'
        # HTML cells contain HTML caption paragraphs, not the blank-separated Markdown body used outside a table.
        table_joined = '<table><tr><td><figure data-type="media-single" data-width="400" data-width-type="pixel">\n' \
            '<img src="_attachments/new%20%26%20image.png" width="800" height="600" alt="New" />\n' \
            '<figcaption>\n<p>Caption</p>\n</figcaption>\n</figure>\n</td></tr></table>\n'
        markups = (figure, legacy, joined, '<table><tr><td>' + figure + '</td></tr></table>\n', table_joined)
        for markup in markups:
            with self.subTest(markup=markup), temporary_workarea(root_page_id="100") as workarea:
                self.site = FakeConfluence()
                self.site.add_page("100", "Root")
                self.site.add_page("200", "Child", parent_id="100")
                self._pull(workarea)
                directory = workarea.root_dir / "Root_100" / "Child_200"
                (directory / "_attachments" / "new & image.png").write_bytes(b"NEW IMAGE")
                (directory / "content.md").write_text('# Child\n\n' + markup, encoding="utf-8")

                self._run(workarea, lambda: PagePushCommand().run("200"))

                writes = [(request.method, request.path) for request in self.site.requests if request.method != "GET"]
                self.assertEqual(
                    writes, [("PUT", "/wiki/rest/api/content/200/child/attachment"), ("PUT", "/wiki/api/v2/pages/200")])
                attachment = next(iter(self.site.attachments.values()))
                self.assertEqual(attachment["filename"], "new & image.png")
                self.assertEqual(attachment["body"], b"NEW IMAGE")
                document = json.loads(self.site.content["200"]["body"])
                image = document["content"][0]
                if image["type"] == "table":
                    image = image["content"][0]["content"][0]["content"][0]
                self.assertEqual(image["attrs"], {"layout": "center", "width": 400, "widthType": "pixel"})
                self.assertEqual(
                    image["content"][0]["attrs"], {
                        "type": "file",
                        "id": attachment["file_id"],
                        "collection": "contentId-200",
                        "alt": "New",
                        "width": 800,
                        "height": 600})
                self.assertEqual(image["content"][1], {"type": "caption", "content": [{"type": "text", "text": "Caption"}]})
                state = PageState.load(workarea.cache_path("200"))
                self.assertIn("new & image.png", state.attachments)

    def test_push_uploads_new_images_before_sending_normalized_or_retained_geometry(self) -> None:
        cases = (
            ('![New](_attachments/new%20%26%20image.png)\n', {
                "layout": "center"}, {}, [{
                    "type": "text",
                    "text": "New"}]), (
                        '![**Caption**](_attachments/new%20%26%20image.png)\n', {
                            "layout": "center"}, {}, [{
                                "type": "text",
                                "text": "Caption",
                                "marks": [{
                                    "type": "strong"}]}]),
            (
                '<figure data-type="media-single" data-width="400" data-width-type="pixel">\n\n'
                '<img src="_attachments/new%20%26%20image.png" width="800.25" height="600.75" alt="New" />\n\n</figure>\n', {
                    "layout": "center",
                    "width": 400,
                    "widthType": "pixel"}, {
                        "alt": "New",
                        "width": 800.25,
                        "height": 600.75}, None))
        for markup, display, dimensions, caption in cases:
            with self.subTest(markup=markup), temporary_workarea(root_page_id="100") as workarea:
                self.site = FakeConfluence()
                self.site.add_page("100", "Root")
                self.site.add_page("200", "Child", parent_id="100")
                self._pull(workarea)
                directory = workarea.root_dir / "Root_100" / "Child_200"
                (directory / "_attachments" / "new & image.png").write_bytes(b"NEW IMAGE")
                (directory / "content.md").write_text('# Child\n\n' + markup, encoding="utf-8")

                self._run(workarea, lambda: PagePushCommand().run("200"))

                writes = [request for request in self.site.requests if request.method != "GET"]
                self.assertEqual(
                    [(request.method, request.path) for request in writes], [
                        ("PUT", "/wiki/rest/api/content/200/child/attachment"), ("PUT", "/wiki/api/v2/pages/200")])
                attachment = next(iter(self.site.attachments.values()))
                self.assertEqual(attachment["filename"], "new & image.png")
                self.assertEqual(attachment["body"], b"NEW IMAGE")
                # Inspect the outgoing API payload, not simulated dimension restoration by Confluence.
                payload = json.loads(writes[-1].body or b"")
                self.assertEqual(payload["body"]["representation"], "atlas_doc_format")
                document = json.loads(payload["body"]["value"])
                self.assertEqual(
                    document["content"], [
                        {
                            "type":
                            "mediaSingle",
                            "attrs":
                            display,
                            "content": [
                                {
                                    "type": "media",
                                    "attrs": {
                                        "type": "file",
                                        "id": attachment["file_id"],
                                        "collection": "contentId-200",
                                        **dimensions}}, *([] if caption is None else [{
                                            "type": "caption",
                                            "content": caption}])]}])
                state = PageState.load(workarea.cache_path("200"))
                self.assertIn("new & image.png", state.attachments)

    def test_caption_edit_updates_adf_and_preserves_no_op_pushes(self) -> None:
        detector = PageChangeDetector(PandocRunner())
        for original_caption in (None, "Original caption"):
            with self.subTest(caption=original_caption), temporary_workarea(root_page_id="100") as workarea:
                self.site = FakeConfluence()
                self.site.add_page("100", "Root")
                self.site.add_page("200", "Child", parent_id="100")
                attachment_id = self.site.add_attachment("200", "diagram.png", b"PNG")
                media_attrs = {
                    "type": "file",
                    "id": self.site.attachments[attachment_id]["file_id"],
                    "collection": "contentId-200",
                    "alt": "Independent alt",
                    "width": 400,
                    "height": 300}
                content: list[dict] = [{"type": "media", "attrs": media_attrs}]
                if original_caption is not None:
                    content.append({"type": "caption", "content": [{"type": "text", "text": original_caption}]})
                image = {
                    "type": "mediaSingle",
                    "attrs": {
                        "layout": "center",
                        "width": 400,
                        "widthType": "pixel"},
                    "content": content}
                body = json.dumps({"type": "doc", "version": 1, "content": [image]})
                self.site.content["200"]["body"] = body
                self._pull(workarea)
                directory = workarea.root_dir / "Root_100" / "Child_200"
                path = directory / "content.md"
                self.assertEqual(
                    path.read_text(encoding="utf-8"),
                    f'# Child\n\n![{original_caption or "Independent alt"}](_attachments/diagram.png)\n')
                self.site.requests.clear()
                self._run(workarea, lambda: PagePushCommand().run("200"))
                self.assertTrue(all(request.method == "GET" for request in self.site.requests))
                self.assertEqual(self.site.content["200"]["body"], body)

                edited = '# Child\n\n![**Edited caption**](_attachments/diagram.png)\n'
                path.write_text(edited, encoding="utf-8")
                self.site.requests.clear()
                self._run(workarea, lambda: PagePushCommand().run("200"))
                writes = [request for request in self.site.requests if request.method != "GET"]
                self.assertEqual([(request.method, request.path) for request in writes], [("PUT", "/wiki/api/v2/pages/200")])
                document = json.loads(json.loads(writes[0].body or b"")["body"]["value"])
                self.assertEqual(
                    document["content"], [
                        {
                            "type":
                            "mediaSingle",
                            "attrs": {
                                "layout": "center"},
                            "content": [
                                {
                                    "type": "media",
                                    "attrs": {
                                        "type": "file",
                                        "id": media_attrs["id"],
                                        "collection": "contentId-200"}}, {
                                            "type": "caption",
                                            "content": [{
                                                "type": "text",
                                                "text": "Edited caption",
                                                "marks": [{
                                                    "type": "strong"}]}]}]}])
                state = PageState.load(workarea.cache_path("200"))
                self.assertEqual(state.page.content_hash, detector.content_hash(edited))
                self.assertEqual(detector.local_status(directory, state), PageChangeStatus.UNCHANGED)
                version = self.site.content["200"]["version"]
                self.site.requests.clear()
                self._run(workarea, lambda: PagePushCommand().run("200"))
                self.assertTrue(all(request.method == "GET" for request in self.site.requests))
                self.assertEqual(self.site.content["200"]["version"], version)

    def test_refuses_to_push_over_a_remote_rename_even_with_force(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Root_100" / "Child_200" / "content.md").write_text("# Child\n\nEdited\n", encoding="utf-8")
            self.site.content["200"]["title"] = "Renamed child"
            self.site.content["200"]["version"] += 1
            body = self.site.content["200"]["body"]

            with self.assertRaisesRegex(SyncError, "push conflicts"):
                self._run(workarea, lambda: PagePushCommand().run("200"))

            with self.assertRaisesRegex(SyncError, "title heading does not match the page title 'Renamed child'"):
                self._run(workarea, lambda: PagePushCommand().run("200", force=True))

            self.assertEqual((self.site.content["200"]["title"], self.site.content["200"]["body"]), ("Renamed child", body))
            output = self._run(workarea, lambda: PageStatusCommand().run("200"))
            self.assertIn("location: moves from 'Root_100/Child_200' to 'Root_100/Renamed child_200' on pull", output)


SITE = "https://example.atlassian.net"


def _hrefs(body: str) -> list[str]:
    """Return the link targets of an ADF body, in document order."""
    hrefs = []

    def walk(node):
        if isinstance(node, dict):
            hrefs.extend(mark["attrs"]["href"] for mark in node.get("marks", []) if mark.get("type") == "link")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(body))
    return hrefs


class TestPagePushLinks(unittest.TestCase):
    """Page links in pushed pages, in a tree of Root (100) with A (200) and B (300) below it, and Leaf (400) below B.

    Page 900 is outside the tree.
    """

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "A", parent_id="100")
        self.site.add_page("300", "B", parent_id="100")
        self.site.add_page("400", "Leaf", parent_id="300")
        self.site.add_page("900", "Outside")

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea, *page_ids):
        for page_id in page_ids:
            self._run(workarea, lambda page_id=page_id: PagePullCommand().run(page_id))

    def _push(self, workarea, markdown, force=False):
        (workarea.root_dir / "Root_100" / "A_200" / "content.md").write_text(f"# A\n\n{markdown}", encoding="utf-8")
        self._run(workarea, lambda: PagePushCommand().run("200", force=force))
        return _hrefs(self.site.content["200"]["body"])

    def test_refuses_before_uploading_attachments(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            attachments = workarea.root_dir / "Root_100" / "A_200" / "_attachments"
            (attachments / "new.txt").write_bytes(b"new")
            self.site.requests.clear()

            with self.assertRaisesRegex(SyncError, "broken page links"):
                self._push(workarea, "[new.txt](_attachments/new.txt) [Outside](../Outside_900/content.md)\n")

        self.assertEqual(self.site.attachments, {})
        self.assertEqual([request for request in self.site.requests if request.method != "GET"], [])


# vim: set ts=4 sw=4 et tw=132:
