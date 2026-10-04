# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Explicit page title and directory rename behavior."""

from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cflsync import APIClient, PageState, Profile, SyncError
from cflsync.cli import PagePullCommand, PageRenameCommand
from tests.support import (EMPTY_DOCUMENT, FakeConfluence, MockResponse, MockTransport, run_with_site, temporary_workarea)
from tests.test_api_operations import attachment_fixture, page_fixture


class TestPageRename(unittest.TestCase):

    def _page(self, version=17, title="Example page"):
        page = page_fixture(title=title)
        page["version"] = {"number": version}
        page["body"] = {
            "atlas_doc_format": {
                "value":
                json.dumps(
                    {
                        "type": "doc",
                        "version": 1,
                        "content": [{
                            "type": "paragraph",
                            "content": [{
                                "type": "text",
                                "text": "Example"}]}]})}}

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

    def _pull(self, workarea):
        page = self._page()
        responses = [
            MockResponse.from_json(page),
            MockResponse.from_json(page),
            MockResponse.from_json({"results": [attachment_fixture()]}),
            MockResponse(200, {}, b"PNG"), ]
        self._run(workarea, lambda: PagePullCommand().run("123456"), responses)

    def _rename(self, workarea, title, page=None, attachments=None, updated=None):
        if page is None:
            page = self._page()
        if attachments is None:
            attachments = [attachment_fixture()]
        if updated is None:
            updated = self._page(page["version"]["number"] + 1, title)

        return self._run(
            workarea, lambda: PageRenameCommand().run("123456", title), [
                MockResponse.from_json(page),
                MockResponse.from_json(page),
                MockResponse.from_json({"results": attachments}),
                MockResponse.from_json(updated), ])

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_rejects_unsynchronized_local_or_remote_pages_without_mutation(self) -> None:
        for local, version in [(True, 17), (False, 18)]:
            with self.subTest(local=local, version=version):
                with temporary_workarea() as workarea:
                    self._pull(workarea)
                    if local:
                        (workarea.root_dir / "Example page_123456/content.md").write_text(
                            "# Example page\n\nEdited\n", encoding="utf-8")
                    before = self._snapshot(workarea)

                    with self.assertRaisesRegex(SyncError, "rename conflicts"):
                        self._rename(workarea, "Renamed page", page=self._page(version))

                    self.assertEqual(self._snapshot(workarea), before)

    def test_rejects_a_windows_current_directory_before_remote_update(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            before = self._snapshot(workarea)
            responses = [
                MockResponse.from_json(self._page()),
                MockResponse.from_json(self._page()),
                MockResponse.from_json({"results": [attachment_fixture()]}), ]

            with patch("cflsync.workarea._is_windows", return_value=True):
                with patch("cflsync.workarea._current_directory_is_inside", return_value=True):
                    with self.assertRaisesRegex(SyncError, "current directory"):
                        self._run(workarea, lambda: PageRenameCommand().run("123456", "Renamed page"), responses)

            self.assertEqual(self._snapshot(workarea), before)


class TestPageRenameInTree(unittest.TestCase):
    """Renames in a tree of Root (100), with Child (200) and Other (400) below it, and Grandchild (300) below Child."""

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Child", parent_id="100", body=EMPTY_DOCUMENT)
        self.site.add_page("300", "Grandchild", parent_id="200")
        self.site.add_page("400", "Other", parent_id="100")

    def _pull(self, workarea, *page_ids):
        for page_id in page_ids:
            run_with_site(self.site, workarea, lambda: PagePullCommand().run(page_id))

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_failed_cache_write_restores_the_subtree_and_reports_the_remote_rename(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")
            before = self._snapshot(workarea)

            with patch.object(PageState, "save", side_effect=SyncError("injected state failure")):
                with self.assertRaisesRegex(SyncError,
                                            "renamed page '200' remotely but could not update local state: injected state failure; "
                                            "run: cflsync page pull 200"):
                    run_with_site(self.site, workarea, lambda: PageRenameCommand().run("200", "Renamed child"))

            self.assertEqual(self._snapshot(workarea), before)
            self.assertEqual(self.site.content["200"]["title"], "Renamed child")

            self._pull(workarea, "200")

            self.assertTrue((workarea.root_dir / "Root_100" / "Renamed child_200" / "Grandchild_300" / "content.md").is_file())
            self.assertEqual(PageState.load(workarea.cache_path("200")).page.title, "Renamed child")


# vim: set ts=4 sw=4 et tw=132:
