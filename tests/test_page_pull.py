# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pull decisions and rollback against a recorded HTTP transport."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cflsync import APIClient, Profile, SyncError
from cflsync.cli import PagePullCommand
from tests.support import FakeConfluence, MockResponse, MockTransport, run_with_site, temporary_workarea
from tests.test_api_operations import attachment_fixture, page_fixture, user_fixture


class TestPagePull(unittest.TestCase):

    def _page(self, version=17, title="Example page"):
        page = page_fixture(title=title)
        page["version"] = {"number": version}
        document = {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": "Example"}]}]}
        page["body"] = {"atlas_doc_format": {"value": json.dumps(document)}}

        return page

    def _pull(self, workarea, page=None, attachments=None, downloads=None, user_responses=(), force=False):
        if page is None:
            page = self._page()

        if attachments is None:
            attachments = [attachment_fixture()]

        if downloads is None:
            downloads = [MockResponse(200, {}, b"PNG") for attachment in attachments]

        responses = [MockResponse.from_json(page), MockResponse.from_json(page)]
        # Exercise actual pagination, including an empty final page.
        responses.append(MockResponse.from_json({"results": attachments, "_links": {"next": "/next"}}))
        responses.append(MockResponse.from_json({"results": []}))
        responses.extend(user_responses)
        responses.extend(downloads)
        transport = MockTransport(responses)
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)
        config = SimpleNamespace(profiles={workarea.profile: Profile("example.atlassian.net", "user", "token")})
        with patch("cflsync.cli.Path.cwd", return_value=workarea.root_dir):
            with patch("cflsync.cli.Config.find", return_value=config):
                with patch("cflsync.cli.APIClient", return_value=client):
                    self.assertEqual(PagePullCommand().run("123456", force=force), 0)

        self.assertTrue(all(request.method == "GET" for request in transport.requests))

        return transport

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_pull_writes_a_mailto_link_for_a_mention_with_an_email_address(self) -> None:
        with temporary_workarea() as workarea:
            page = self._page()
            page["body"] = {
                "atlas_doc_format": {
                    "value":
                    json.dumps(
                        {
                            "type":
                            "doc",
                            "version":
                            1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{
                                        "type": "mention",
                                        "attrs": {
                                            "id": "account-123",
                                            "text": "@Example User"}}]}]})}}

            transport = self._pull(workarea, page, attachments=[], user_responses=[MockResponse.from_json(user_fixture())])

            self.assertEqual(
                (workarea.root_dir / "Example page_123456/content.md").read_text(),
                "# Example page\n\n[Example User](mailto:example.user@example.test)\n")
            user_request = transport.requests[-1]
            self.assertEqual(user_request.path, "/user")
            self.assertEqual(user_request.parameters, {"accountId": "account-123"})

    def test_title_and_unmanaged_attachment_collisions_leave_files_unchanged(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Occupied_123456").mkdir()
            before = self._snapshot(workarea)
            with self.assertRaises(SyncError):
                self._pull(workarea, page=self._page(18, "Occupied"))

            self.assertEqual(self._snapshot(workarea), before)
            (workarea.root_dir / "Example page_123456/_attachments/local.txt").write_text("unmanaged")
            attachment = attachment_fixture()
            attachment["title"] = "local.txt"
            before = self._snapshot(workarea)
            with self.assertRaisesRegex(SyncError, "unmanaged"):
                self._pull(workarea, page=self._page(18), attachments=[attachment])

            self.assertEqual(self._snapshot(workarea), before)

    def test_download_and_conversion_failures_leave_previous_state_unchanged(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            before = self._snapshot(workarea)
            with self.assertRaises(SyncError):
                self._pull(workarea, page=self._page(18), downloads=[MockResponse(500, {}, b"failed")])

            self.assertEqual(self._snapshot(workarea), before)
            invalid = self._page(18)
            invalid["body"] = {"atlas_doc_format": {"value": "{"}}
            with self.assertRaises(SyncError):
                self._pull(workarea, page=invalid, downloads=[])

            self.assertEqual(self._snapshot(workarea), before)

    def test_failed_staging_write_leaves_previous_state_unchanged(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            before = self._snapshot(workarea)
            write_bytes = Path.write_bytes

            def fail_write(path, data):
                if any(part.startswith(".cflsync-stage-") for part in path.parts):
                    raise OSError("injected staging write failure")

                return write_bytes(path, data)

            with patch.object(Path, "write_bytes", fail_write):
                with self.assertRaises(SyncError):
                    self._pull(workarea, page=self._page(18))

            self.assertEqual(self._snapshot(workarea), before)

    def test_invalid_manifests_fail_before_download_or_mutation(self) -> None:
        unsafe = attachment_fixture()
        unsafe["title"] = "../outside"
        for manifest in [[unsafe], [attachment_fixture(), attachment_fixture()]]:
            with self.subTest(manifest=manifest):
                with temporary_workarea() as workarea:
                    before = self._snapshot(workarea)
                    with self.assertRaises(SyncError):
                        self._pull(workarea, attachments=manifest, downloads=[])

                    self.assertEqual(self._snapshot(workarea), before)

    def test_failed_install_or_state_write_rolls_back_first_pull_update_and_rename(self) -> None:
        for existing in [False, True]:
            for title in ["Example page", "Renamed"]:
                for failure in ["install", "state"]:
                    with self.subTest(existing=existing, title=title, failure=failure):
                        with temporary_workarea() as workarea:
                            if existing:
                                self._pull(workarea)

                            before = self._snapshot(workarea)
                            replace = os.replace

                            def fail_replace(source, target):
                                target = Path(target)
                                if failure == "state" and target == workarea.cache_path("123456"):
                                    raise OSError("injected state write failure")

                                if failure == "install" and any(part.startswith(".cflsync-stage-") for part in Path(source).parts):
                                    raise OSError("injected install failure")

                                return replace(source, target)

                            with patch("cflsync.workarea.os.replace", side_effect=fail_replace):
                                with self.assertRaises(SyncError):
                                    self._pull(workarea, page=self._page(18, title))

                            self.assertEqual(self._snapshot(workarea), before)


class TestPagePullNesting(unittest.TestCase):
    """Pulls in a tree of Root (100), with Child (200) and Other (400) below it, and Grandchild (300) below Child."""

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Child", parent_id="100")
        self.site.add_page("300", "Grandchild", parent_id="200")
        self.site.add_page("400", "Other", parent_id="100")

    def _pull(self, workarea, *page_ids, force=False):
        for page_id in page_ids:
            run_with_site(self.site, workarea, lambda: PagePullCommand().run(page_id, force=force))

    def _remote_change(self, page_id, **fields):
        self.site.content[page_id].update(fields)
        self.site.content[page_id]["version"] += 1

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_force_relocates_and_overwrites_local_changes(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            (workarea.root_dir / "Root_100" / "Child_200" / "content.md").write_text("# Child\n\nLocal edit\n", encoding="utf-8")
            self._remote_change("200", title="Renamed child")

            with self.assertRaisesRegex(SyncError, "pull conflicts"):
                self._pull(workarea, "200")

            self._pull(workarea, "200", force=True)

            content = (workarea.root_dir / "Root_100" / "Renamed child_200" / "content.md").read_text(encoding="utf-8")
            self.assertEqual(content, "# Renamed child\n")


def _link(text, href):
    return {"type": "text", "text": text, "marks": [{"type": "link", "attrs": {"href": href}}]}


def _document(*paragraphs):
    """Return an ADF body with one paragraph per list of inline nodes."""
    return json.dumps(
        {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": list(inlines)} for inlines in paragraphs]})


SITE = "https://example.atlassian.net"


class TestPagePullLinks(unittest.TestCase):
    """Page links in pulled pages, in a tree of Root (100) with A (200) and B (300) below it, and Leaf (400) below B.

    Page 900 is outside the tree.
    """

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "A", parent_id="100")
        self.site.add_page("300", "B", parent_id="100", body=_document([_link("Leaf", f"{SITE}/wiki/spaces/EXAMPLE/pages/400")]))
        self.site.add_page("400", "Leaf", parent_id="300")
        self.site.add_page("900", "Outside")

    def _pull(self, workarea, *page_ids):
        for page_id in page_ids:
            run_with_site(self.site, workarea, lambda: PagePullCommand().run(page_id))

    def _content(self, workarea, directory):
        return (workarea.root_dir / directory / "content.md").read_text(encoding="utf-8")

    def test_converts_links_to_pages_in_the_tree_and_keeps_all_others(self) -> None:
        links = {
            "installed": f"{SITE}/wiki/spaces/EXAMPLE/pages/300",
            "never installed": f"{SITE}/wiki/spaces/EXAMPLE/pages/400/Leaf",
            "outside": f"{SITE}/wiki/spaces/EXAMPLE/pages/900",
            "unreachable": f"{SITE}/wiki/spaces/EXAMPLE/pages/999",
            "short": f"{SITE}/wiki/x/CCCCCC",
            "edit": f"{SITE}/wiki/spaces/EXAMPLE/pages/edit-v2/300",
            "version": f"{SITE}/wiki/pages/viewpage.action?pageId=300&pageVersion=1",
            "title": f"{SITE}/wiki/display/EXAMPLE/Leaf",
            "fragment": f"{SITE}/wiki/spaces/EXAMPLE/pages/300#A%20b+Überblick"}
        self.site.content["200"]["body"] = _document(*[[_link(text, href)] for text, href in links.items()])
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "300", "200")

            markdown = self._content(workarea, "Root_100/A_200")

        self.assertIn("[installed](../B_300/content.md)", markdown)
        self.assertIn("[never installed](../B_300/Leaf_400/content.md)", markdown)
        for text in ["outside", "unreachable", "short", "edit", "version"]:
            self.assertIn(f"[{text}]({links[text]})", markdown)
        self.assertIn("[title](../B_300/Leaf_400/content.md)", markdown)
        self.assertIn("[fragment](../B_300/content.md#A%20b+Überblick)", markdown)


# vim: set ts=4 sw=4 et tw=132:
