# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pull decisions and rollback against a recorded HTTP transport."""

import hashlib
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cflsync import APIClient, PageState, PandocRunner, Profile, SyncError
from cflsync.sync import PageChangeDetector, PageChangeStatus
from cflsync.cli import PageMoveCommand, PagePullCommand, PageStatusCommand
from tests.support import FakeConfluence, MockResponse, MockTransport, example_page_state, run_with_site, temporary_workarea
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

    def test_first_pull_installs_content_attachments_and_private_state(self) -> None:
        with temporary_workarea() as workarea:
            transport = self._pull(workarea)
            state = PageState.load(workarea.cache_path("123456"))
            directory = workarea.page_directory(state)

            self.assertEqual((directory / "content.md").read_text(), "# Example page\n\nExample\n")
            self.assertEqual((directory / "_attachments/diagram.png").read_bytes(), b"PNG")
            self.assertEqual(state.page.content_hash, hashlib.sha256(b"# Example page\n\nExample\n").hexdigest())
            self.assertEqual(state.attachments["diagram.png"].content_hash, hashlib.sha256(b"PNG").hexdigest())
            if os.name != "nt":
                self.assertEqual(workarea.cache_path("123456").stat().st_mode & 0o777, 0o600)
            self.assertIn("/next", [request.path for request in transport.requests])

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

    def test_unchanged_and_formatting_only_changes_are_noops(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            for markdown in ["# Example page\n\nExample\n", "# Example page\n\nExample\n\n\n"]:
                with self.subTest(markdown=markdown):
                    (workarea.root_dir / "Example page_123456/content.md").write_text(markdown)
                    before = self._snapshot(workarea)
                    output = StringIO()
                    with redirect_stdout(output):
                        transport = self._pull(workarea, downloads=[])

                    self.assertEqual(self._snapshot(workarea), before)
                    self.assertEqual(len(transport.requests), 4)
                    self.assertIn("already in sync; nothing pulled", output.getvalue())

    def test_force_regenerates_unchanged_content(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            output = StringIO()
            with patch("cflsync.sync.ADFToMarkdownConverter.convert", return_value="# Example page\n\nRegenerated\n"):
                with redirect_stdout(output):
                    transport = self._pull(workarea, force=True)

            state = PageState.load(workarea.cache_path("123456"))
            markdown = (workarea.page_directory(state) / "content.md").read_bytes()
            self.assertEqual(markdown, b"# Example page\n\nRegenerated\n")
            self.assertEqual(state.page.content_hash, hashlib.sha256(markdown).hexdigest())
            self.assertEqual(len(transport.requests), 5)
            self.assertNotIn("nothing pulled", output.getvalue())

    def test_force_prefers_remote_over_local_and_concurrent_changes(self) -> None:
        for version in [17, 18]:
            with self.subTest(version=version):
                with temporary_workarea() as workarea:
                    self._pull(workarea)
                    directory = workarea.root_dir / "Example page_123456"
                    (directory / "content.md").write_bytes(b"\xffinvalid markdown")
                    (directory / "_attachments/diagram.png").write_bytes(b"edited")
                    (directory / "_attachments/local.txt").write_text("unmanaged")
                    self._pull(workarea, page=self._page(version), force=True)

                    state = PageState.load(workarea.cache_path("123456"))
                    self.assertEqual((directory / "content.md").read_text(), "# Example page\n\nExample\n")
                    self.assertEqual((directory / "_attachments/diagram.png").read_bytes(), b"PNG")
                    self.assertEqual((directory / "_attachments/local.txt").read_text(), "unmanaged")
                    self.assertEqual(state.page.version, version)

    def test_force_restores_deleted_managed_files(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            directory = workarea.root_dir / "Example page_123456"
            (directory / "content.md").unlink()
            (directory / "_attachments/diagram.png").unlink()
            self._pull(workarea, force=True)

            self.assertEqual((directory / "content.md").read_text(), "# Example page\n\nExample\n")
            self.assertEqual((directory / "_attachments/diagram.png").read_bytes(), b"PNG")

    def test_failed_force_pull_preserves_local_edits_and_cache(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Example page_123456/content.md").write_text("local edits")
            before = self._snapshot(workarea)
            with patch.object(PageState, "save", side_effect=SyncError("injected state failure")):
                with self.assertRaises(SyncError):
                    self._pull(workarea, force=True)

            self.assertEqual(self._snapshot(workarea), before)

    def test_local_and_both_sides_changes_conflict_without_mutation(self) -> None:
        for version in [17, 18]:
            for changed_file in ["content.md", "_attachments/diagram.png"]:
                with self.subTest(version=version, changed_file=changed_file):
                    with temporary_workarea() as workarea:
                        self._pull(workarea)
                        (workarea.root_dir / "Example page_123456" / changed_file).write_text("edited\n")
                        before = self._snapshot(workarea)
                        with self.assertRaisesRegex(SyncError, "conflict"):
                            self._pull(workarea, page=self._page(version), downloads=[])

                        self.assertEqual(self._snapshot(workarea), before)

    def test_remote_update_renames_and_preserves_unmanaged_files(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            source = workarea.root_dir / "Example page_123456"
            (source / "notes.txt").write_text("private notes")
            (source / "_attachments/local.txt").write_text("unmanaged")
            self._pull(workarea, page=self._page(18, "Renamed"), attachments=[])

            state = PageState.load(workarea.cache_path("123456"))
            target = workarea.page_directory(state)
            self.assertFalse(source.exists())
            self.assertEqual(state.page.directory, "Renamed_123456")
            self.assertEqual(state.page.version, 18)
            self.assertEqual(state.attachments, {})
            self.assertFalse((target / "_attachments/diagram.png").exists())
            self.assertEqual((target / "notes.txt").read_text(), "private notes")
            self.assertEqual((target / "_attachments/local.txt").read_text(), "unmanaged")

    def test_attachment_version_change_without_page_change_is_pulled(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            attachment = attachment_fixture()
            attachment["version"] = {"number": 4}
            self._pull(workarea, attachments=[attachment], downloads=[MockResponse(200, {}, b"new")])

            state = PageState.load(workarea.cache_path("123456"))
            self.assertEqual(state.page.version, 17)
            self.assertEqual(state.attachments["diagram.png"].version, 4)
            self.assertEqual((workarea.page_directory(state) / "_attachments/diagram.png").read_bytes(), b"new")

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

    def test_missing_managed_attachment_conflicts(self) -> None:
        with temporary_workarea() as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Example page_123456/_attachments/diagram.png").unlink()
            before = self._snapshot(workarea)
            with self.assertRaisesRegex(SyncError, "conflict"):
                self._pull(workarea, page=self._page(18), downloads=[])

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


class TestPagePullParent(unittest.TestCase):

    def test_records_the_remote_parent_except_for_the_root_page(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Root page")
        site.add_page("200", "Child page", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            run_with_site(site, workarea, lambda: PagePullCommand().run("100"))
            run_with_site(site, workarea, lambda: PagePullCommand().run("200"))

            self.assertIsNone(PageState.load(workarea.cache_path("100")).page.parent_id)
            self.assertEqual(PageState.load(workarea.cache_path("200")).page.parent_id, "100")


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

    def test_pulls_the_tree_top_down_into_nested_directories(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")

            self.assertTrue((workarea.root_dir / "Root_100" / "Child_200" / "Grandchild_300" / "content.md").is_file())
            self.assertEqual(
                [PageState.load(workarea.cache_path(page_id)).page.parent_id for page_id in ["100", "200", "300"]],
                [None, "100", "200"])
            self.assertEqual(workarea.page_tree().directory("300"), "Root_100/Child_200/Grandchild_300")

    def test_pulls_missing_ancestors_before_the_requested_page(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            output = run_with_site(self.site, workarea, lambda: PagePullCommand().run("300"))

            self.assertEqual(output, "Pulled parent 'Root' (100) to Root_100\nPulled parent 'Child' (200) to Root_100/Child_200\n")
            self.assertTrue((workarea.root_dir / "Root_100" / "Child_200" / "Grandchild_300" / "content.md").is_file())

    def test_restores_a_cached_ancestor_with_a_missing_directory(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            shutil.rmtree(workarea.root_dir / "Root_100" / "Child_200")

            output = run_with_site(self.site, workarea, lambda: PagePullCommand().run("300"))

            self.assertEqual(output, "Pulled parent 'Child' (200) to Root_100/Child_200\n")
            self.assertTrue((workarea.root_dir / "Root_100" / "Child_200" / "Grandchild_300" / "content.md").is_file())

    def test_relocates_a_page_renamed_remotely_with_its_subtree(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")
            (workarea.root_dir / "Root_100" / "Child_200" / "notes.txt").write_text("unmanaged\n", encoding="utf-8")
            self._remote_change("200", title="Renamed child")

            self._pull(workarea, "200")

            renamed = workarea.root_dir / "Root_100" / "Renamed child_200"
            self.assertFalse((workarea.root_dir / "Root_100" / "Child_200").exists())
            self.assertIn("# Renamed child", (renamed / "content.md").read_text(encoding="utf-8"))
            self.assertEqual((renamed / "notes.txt").read_text(encoding="utf-8"), "unmanaged\n")
            self.assertEqual(workarea.page_directory(PageState.load(workarea.cache_path("300"))), renamed / "Grandchild_300")

    def test_relocates_a_page_moved_remotely_below_another_local_parent(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300", "400")
            self._remote_change("200", parent_id="400")

            self._pull(workarea, "200")

            self.assertTrue(
                (workarea.root_dir / "Root_100" / "Other_400" / "Child_200" / "Grandchild_300" / "content.md").is_file())
            self.assertFalse((workarea.root_dir / "Root_100" / "Child_200").exists())
            self.assertEqual(PageState.load(workarea.cache_path("200")).page.parent_id, "400")

    def test_finds_a_page_moved_by_the_move_command_in_sync(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "400")
            run_with_site(self.site, workarea, lambda: PageMoveCommand().run("200", "400"))

            output = run_with_site(self.site, workarea, lambda: PagePullCommand().run("200"))

            self.assertIn("already in sync", output)
            self.assertTrue((workarea.root_dir / "Root_100" / "Other_400" / "Child_200" / "content.md").is_file())

    def test_pulls_a_new_remote_parent_before_relocating(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            self._remote_change("200", parent_id="400")

            output = run_with_site(self.site, workarea, lambda: PagePullCommand().run("200"))

            self.assertEqual(output, "Pulled parent 'Other' (400) to Root_100/Other_400\n")
            self.assertTrue((workarea.root_dir / "Root_100" / "Other_400" / "Child_200" / "content.md").is_file())

    def test_force_does_not_apply_to_cached_ancestors(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100")
            root = workarea.root_dir / "Root_100" / "content.md"
            root.write_text("# Root\n\nLocal edit\n", encoding="utf-8")

            self._pull(workarea, "300", force=True)

            self.assertEqual(root.read_text(encoding="utf-8"), "# Root\n\nLocal edit\n")

    def test_keeps_a_remote_rename_into_a_cached_sibling_title_in_its_own_directory(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "400")
            self._remote_change("400", title="child")

            self._pull(workarea, "400")

            root = workarea.root_dir / "Root_100"
            self.assertEqual(
                sorted(path.name for path in root.iterdir() if path.is_dir()), ["Child_200", "_attachments", "child_400"])
            self.assertEqual(PageState.load(workarea.cache_path("200")).page.directory, "Child_200")

    def test_pulls_a_missing_ancestor_titled_like_a_cached_sibling_into_its_own_directory(self) -> None:
        self.site.add_page("500", "CHILD", parent_id="100")
        self.site.add_page("600", "Leaf", parent_id="500")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")

            self._pull(workarea, "600")

            self.assertTrue((workarea.root_dir / "Root_100" / "CHILD_500" / "Leaf_600" / "content.md").is_file())
            self.assertEqual(PageState.load(workarea.cache_path("500")).page.directory, "CHILD_500")

    def test_pulls_a_new_page_titled_like_a_cached_sibling_into_its_own_directory(self) -> None:
        self.site.add_page("500", "CHILD", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            before = (workarea.root_dir / "Root_100" / "Child_200" / "content.md").read_bytes()

            self._pull(workarea, "500")

            self.assertTrue((workarea.root_dir / "Root_100" / "CHILD_500" / "content.md").is_file())
            self.assertEqual((workarea.root_dir / "Root_100" / "Child_200" / "content.md").read_bytes(), before)

    def test_refuses_an_unmanaged_entry_with_the_same_name(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100")
            unmanaged = workarea.root_dir / "Root_100" / "child_200"
            unmanaged.mkdir()
            (unmanaged / "notes.txt").write_text("unmanaged\n", encoding="utf-8")

            with self.assertRaisesRegex(SyncError, "page directory 'Root_100/Child_200' already exists"):
                self._pull(workarea, "200")

            self.assertEqual([path.name for path in unmanaged.iterdir()], ["notes.txt"])
            self.assertFalse(workarea.cache_path("200").exists())

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


class TestPagePullScope(unittest.TestCase):

    def test_refuses_a_page_outside_the_tree_without_changes(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Root page")
        site.add_page("200", "Outside page")
        with temporary_workarea(root_page_id="100") as workarea:
            with self.assertRaisesRegex(SyncError, "page '200' is not found in this workarea"):
                run_with_site(site, workarea, lambda: PagePullCommand().run("200"))

            self.assertEqual([path.name for path in workarea.root_dir.iterdir()], [".cflsync"])
            self.assertEqual(list(workarea.cache_dir.iterdir()), [])


class TestPagePullDirectoryNames(unittest.TestCase):

    def test_pulls_children_titled_like_reserved_entries_next_to_them(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_attachment("100", "diagram.png", b"PNG")
        site.add_page("200", "_attachments", parent_id="100")
        site.add_page("300", "content.md", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            for page_id in ["100", "200", "300"]:
                run_with_site(site, workarea, lambda: PagePullCommand().run(page_id))

            root = workarea.root_dir / "Root_100"
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["%5Fattachments_200", "_attachments", "content%2Emd_300", "content.md"])
            self.assertEqual((root / "_attachments" / "diagram.png").read_bytes(), b"PNG")
            self.assertTrue((root / "%5Fattachments_200" / "content.md").is_file())
            self.assertTrue((root / "content%2Emd_300" / "content.md").is_file())

    def test_pulls_siblings_with_the_same_title_into_distinct_directories(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_page("200", "Same title", parent_id="100")
        site.add_page("300", "Same title", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            for page_id in ["100", "200", "300"]:
                run_with_site(site, workarea, lambda: PagePullCommand().run(page_id))

            root = workarea.root_dir / "Root_100"
            self.assertEqual(
                sorted(path.name for path in root.iterdir()), ["Same title_200", "Same title_300", "_attachments", "content.md"])
            self.assertTrue((root / "Same title_200" / "content.md").is_file())
            self.assertTrue((root / "Same title_300" / "content.md").is_file())
            self.assertEqual(PageState.load(workarea.cache_path("200")).page.directory, "Same title_200")
            self.assertEqual(PageState.load(workarea.cache_path("300")).page.directory, "Same title_300")

    def test_appends_the_page_id_to_a_title_that_ends_like_a_page_id(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_page("400", "Beta_300", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            for page_id in ["100", "400"]:
                run_with_site(site, workarea, lambda: PagePullCommand().run(page_id))

            directory = workarea.root_dir / "Root_100" / "Beta_300_400"
            self.assertTrue((directory / "content.md").is_file())
            self.assertEqual(PageState.load(workarea.cache_path("400")).page.directory, "Beta_300_400")
            output = run_with_site(site, workarea, lambda: PageStatusCommand().run(str(directory)))
            self.assertIn("Page '400' (Beta_300)", output)


class TestPagePullUnicodeNames(unittest.TestCase):

    def test_pulls_a_unicode_title_into_a_directory_named_after_it(self) -> None:
        site = FakeConfluence()
        site.add_page("100", "Café — Überblick")
        site.add_page("200", "日本語のページ", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            for page_id in ["100", "200"]:
                run_with_site(site, workarea, lambda: PagePullCommand().run(page_id))

            directory = workarea.root_dir / "Café — Überblick_100" / "日本語のページ_200"
            self.assertTrue((directory / "content.md").is_file())
            output = run_with_site(site, workarea, lambda: PageStatusCommand().run(str(directory)))
            self.assertIn("Page '200' (日本語のページ)", output)


class TestPagePullPathLength(unittest.TestCase):

    def test_caps_the_directory_name_of_a_long_title(self) -> None:
        site = FakeConfluence()
        site.add_page("123456", "x" * 300)
        with temporary_workarea() as workarea:
            run_with_site(site, workarea, lambda: PagePullCommand().run("123456"))

            self.assertEqual([path.name for path in workarea.root_dir.iterdir() if path.name != ".cflsync"], ["x" * 57 + "_123456"])
            self.assertEqual(PageState.load(workarea.cache_path("123456")).page.directory, "x" * 57 + "_123456")

    @unittest.skipIf(os.name == "nt", "the error Windows reports for an over-long name component depends on its configuration")
    def test_reports_an_attachment_name_that_the_filesystem_rejects_as_too_long(self) -> None:
        site = FakeConfluence()
        site.add_page("123456", "Example page")
        site.add_attachment("123456", "x" * 300 + ".png", b"PNG")
        with temporary_workarea() as workarea:
            # The operation that reports the limit, and therefore the message prefix, depends on the system.
            with self.assertRaisesRegex(SyncError, r"path is too long for this system \(\d+ characters\)"):
                run_with_site(site, workarea, lambda: PagePullCommand().run("123456"))

            self.assertEqual(list(workarea.cache_dir.iterdir()), [])
            self.assertEqual([path.name for path in workarea.root_dir.iterdir()], [".cflsync"])


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

    def test_keeps_smart_links_opaque(self) -> None:
        card = {"type": "inlineCard", "attrs": {"url": f"{SITE}/wiki/spaces/EXAMPLE/pages/300"}}
        self.site.content["200"]["body"] = _document([card])
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "200")

            markdown = self._content(workarea, "Root_100/A_200")

        self.assertIn("``` atlas_doc_format", markdown)
        self.assertNotIn("B_300", markdown)

    def test_a_pulled_page_with_converted_links_is_unchanged_afterwards(self) -> None:
        self.site.content["200"]["body"] = _document([_link("B", f"{SITE}/wiki/spaces/EXAMPLE/pages/300")])
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "200")
            state = PageState.load(workarea.cache_path("200"))
            detector = PageChangeDetector(PandocRunner())

            self.assertEqual(detector.local_status(workarea.page_directory(state), state), PageChangeStatus.UNCHANGED)

    def test_a_target_pulled_later_lands_where_the_link_points(self) -> None:
        self.site.content["200"]["body"] = _document([_link("Leaf", f"{SITE}/wiki/spaces/EXAMPLE/pages/400")])
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "200")
            source = workarea.root_dir / "Root_100" / "A_200"
            link = re.search(r"\]\(([^)]*)\)", self._content(workarea, "Root_100/A_200")).group(1)
            self.assertFalse((source / link).exists())

            self._pull(workarea, "400")

            self.assertTrue((source / link).resolve().samefile(workarea.root_dir / "Root_100/B_300/Leaf_400/content.md"))

    def test_pulling_a_page_does_not_touch_other_pages(self) -> None:
        self.site.content["200"]["body"] = _document([_link("B", f"{SITE}/wiki/spaces/EXAMPLE/pages/300")])
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "300", "400")
            before = {path: path.read_bytes() for path in workarea.root_dir.rglob("content.md")}

            self._pull(workarea, "200")

            after = {path: path.read_bytes() for path in workarea.root_dir.rglob("content.md")}
            self.assertEqual({path: body for path, body in after.items() if path in before}, before)


# vim: set ts=4 sw=4 et tw=132:
