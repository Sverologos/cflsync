# Copyright (c) 2026 Sven Rosiers
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Explicit local and remote page removal behavior."""

from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cflsync import APIClient, Profile, SyncError
from cflsync.cli import PageCreateCommand, PagePullCommand, PageRemoveCommand
from tests.support import FakeConfluence, MockResponse, MockTransport, run_with_site, temporary_workarea
from tests.test_api_operations import attachment_fixture, page_fixture


class TestPageRemove(unittest.TestCase):

    def _page(self, version=17):
        page = page_fixture()
        page["version"] = {"number": version}
        page["body"] = {"atlas_doc_format": {"value": json.dumps({"type": "doc", "version": 1, "content": []})}}
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
        self._run(
            workarea, lambda: PagePullCommand().run("123456"), [
                MockResponse.from_json(page),
                MockResponse.from_json(page),
                MockResponse.from_json({"results": [attachment_fixture()]}),
                MockResponse(200, {}, b"PNG"), ])

    def _remove(self, workarea, force=True, page=None, attachments=None, delete_response=None):
        if page is None:
            page = self._page()
        if attachments is None:
            attachments = [attachment_fixture()]
        if delete_response is None:
            delete_response = MockResponse(204, {}, b"")

        responses = [
            MockResponse.from_json(page),
            MockResponse.from_json({"results": []}),
            MockResponse.from_json({"results": attachments}), delete_response, ]
        return self._run(workarea, lambda: PageRemoveCommand().run("123456", force=force), responses)

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_removes_remote_page_local_directory_and_cache(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Example page/notes.txt").write_text("unmanaged", encoding="utf-8")

            _, status, transport = self._remove(workarea)

            self.assertEqual(status, 0)
            self.assertEqual(transport.requests[-1].method, "DELETE")
            self.assertEqual(transport.requests[-1].path, "/pages/123456")
            self.assertFalse((workarea.root_dir / "Example page").exists())
            self.assertFalse(workarea.cache_path("123456").exists())

    def test_confirms_before_removing(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)

            with patch("builtins.input", return_value="yes") as confirm:
                _, status, _ = self._remove(workarea, force=False)

            self.assertEqual(status, 0)
            self.assertIn("Remove remote and local copy of page 'Example page' (123456)", confirm.call_args.args[0])
            self.assertFalse((workarea.root_dir / "Example page").exists())

    def test_declining_confirmation_changes_nothing(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            before = self._snapshot(workarea)

            with patch("builtins.input", return_value="no"):
                _, status, transport = self._remove(workarea, force=False)

            self.assertEqual(status, 0)
            self.assertEqual(self._snapshot(workarea), before)
            self.assertTrue(all(request.method == "GET" for request in transport.requests))

    def test_force_bypasses_confirmation(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)

            with patch("builtins.input", side_effect=AssertionError("unexpected confirmation")):
                _, status, _ = self._remove(workarea, force=True)

            self.assertEqual(status, 0)

    def test_removes_local_copy_when_remote_page_is_already_missing(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            responses = [MockResponse.from_json({"message": "not found"}, status=404)]

            with patch("builtins.input", return_value="yes") as confirm:
                _, status, transport = self._run(workarea, lambda: PageRemoveCommand().run("123456"), responses)

            self.assertEqual(status, 0)
            self.assertEqual([request.method for request in transport.requests], ["GET"])
            self.assertIn("local copy", confirm.call_args.args[0])
            self.assertFalse((workarea.root_dir / "Example page").exists())
            self.assertFalse(workarea.cache_path("123456").exists())

    def test_requires_a_local_managed_page(self) -> None:
        with temporary_workarea() as workarea:
            with self.assertRaisesRegex(SyncError, "no managed local page"):
                self._run(workarea, lambda: PageRemoveCommand().run("123456", force=True), [])

    def test_rejects_unsynchronized_pages_without_removing(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Example page/content.md").write_text("# Example page\n\nEdited\n", encoding="utf-8")
            before = self._snapshot(workarea)

            with self.assertRaisesRegex(SyncError, "remove conflicts"):
                self._remove(workarea)

            self.assertEqual(self._snapshot(workarea), before)

    def test_remote_delete_failure_leaves_local_state_unchanged(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            before = self._snapshot(workarea)

            with self.assertRaisesRegex(SyncError, "delete rejected"):
                self._remove(workarea, delete_response=MockResponse.from_json({"message": "delete rejected"}, status=500))

            self.assertEqual(self._snapshot(workarea), before)


class TestPageRemoveInTree(unittest.TestCase):
    """Removal in a tree of Root (100), with Child (200) below it and Grandchild (300) below Child."""

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Child", parent_id="100")
        self.site.add_page("300", "Grandchild", parent_id="200")

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea, *page_ids):
        for page_id in page_ids:
            self._run(workarea, lambda: PagePullCommand().run(page_id))

    def _remove(self, workarea, page_id):
        self.site.requests.clear()
        self._run(workarea, lambda: PageRemoveCommand().run(page_id, force=True))

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def _refused(self, workarea, page_id, error):
        before = self._snapshot(workarea)
        with self.assertRaisesRegex(SyncError, error):
            self._remove(workarea, page_id)

        self.assertEqual(self._snapshot(workarea), before)
        self.assertEqual([request.method for request in self.site.requests if request.method != "GET"], [])

    def test_removes_a_leaf_page_below_its_parent(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")

            self._remove(workarea, "300")

            self.assertNotIn("300", self.site.content)
            self.assertFalse((workarea.root_dir / "Root" / "Child" / "Grandchild").exists())
            self.assertFalse(workarea.cache_path("300").exists())
            self.assertTrue((workarea.root_dir / "Root" / "Child" / "content.md").is_file())
            self.assertEqual(workarea.page_tree().directory("200"), "Root/Child")

    def test_refuses_a_page_with_cached_children(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")

            self._refused(workarea, "200", "page '200' has 1 child page; remove it first")

    def test_refuses_a_page_with_children_that_exist_only_remotely(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")

            self._refused(workarea, "200", "page '200' has 1 child page; remove it first")

    def test_counts_cached_and_remote_children_together(self) -> None:
        self.site.add_page("400", "Other", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")

            self._refused(workarea, "100", "page '100' has 2 child pages; remove them first")

    def test_refuses_a_page_deleted_remotely_while_it_has_cached_children(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")
            del self.site.content["200"]

            self._refused(workarea, "200", "page '200' has 1 child page; remove it first")

    def test_removing_the_childless_root_leaves_an_empty_workarea(self) -> None:
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("900", "Outside")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100")

            self._remove(workarea, "100")

            self.assertNotIn("100", self.site.content)
            self.assertEqual([path.name for path in workarea.root_dir.iterdir()], [".cflsync"])
            self.assertEqual(list(workarea.cache_dir.iterdir()), [])
            self.assertEqual((workarea.root_page_id, workarea.profile), ("100", "default"))
            for command in [lambda: PagePullCommand().run("100"), lambda: PagePullCommand().run("900"),
                            lambda: PageCreateCommand().run("100", "New page")]:
                with self.assertRaisesRegex(SyncError,
                                            "root page '100' of this workarea no longer exists; to re-use this directory, delete"):
                    self._run(workarea, command)


# vim: set ts=4 sw=4 et tw=132:
