# Copyright (c) 2026 Sven Rosiers
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Remote page creation followed by the normal pull path."""

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cflsync import APIClient, PageState, Profile, SyncError
from cflsync.cli import PageCreateCommand, PagePullCommand
from tests.support import FakeConfluence, MockResponse, MockTransport, example_page_state, run_with_site, temporary_workarea
from tests.test_api_operations import attachment_fixture, page_fixture


def created_page_fixture(page_id: str = "123456", title: str = "New page") -> dict[str, object]:
    page = page_fixture(page_id, title)
    page["body"] = {"atlas_doc_format": {"value": json.dumps({"type": "doc", "version": 1, "content": []})}}

    return page


class TestPageCreate(unittest.TestCase):

    def _create(self, workarea, responses, title="New page", parent_page_ref="456789"):
        transport = MockTransport(responses)
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)
        config = SimpleNamespace(profiles={workarea.profile: Profile("example.atlassian.net", "user", "token")})
        with patch("cflsync.cli.Path.cwd", return_value=workarea.root_dir):
            with patch("cflsync.cli.Config.find", return_value=config):
                with patch("cflsync.cli.APIClient", return_value=client):
                    status = PageCreateCommand().run(parent_page_ref, title)

        return transport, status

    def _local_parent(self, workarea):
        state = example_page_state("456789", title="Parent page", directory="Parent page")
        state.save(workarea.cache_path(state.page.id))
        directory = workarea.root_dir / state.page.directory
        directory.mkdir()
        (directory / "content.md").write_text("# Parent page\n", encoding="utf-8")
        return directory

    def _pull_responses(self, page, attachments=None):
        if attachments is None:
            attachments = [attachment_fixture()]

        return [
            MockResponse.from_json(page),
            MockResponse.from_json({"results": [{
                "id": "456789",
                "type": "page"}]}),
            MockResponse.from_json(page),
            MockResponse.from_json({"results": [{
                "id": "456789",
                "type": "page"}]}),
            MockResponse.from_json({"results": attachments}), *[MockResponse(200, {}, b"PNG") for attachment in attachments], ]

    def test_rejects_invalid_titles_before_any_request(self) -> None:
        for title in ("", "  ", "two\nlines", " padded "):
            with self.subTest(title=title):
                transport = MockTransport([])
                client = APIClient("example.atlassian.net", "user", "token", transport=transport)
                with patch("cflsync.cli.APIClient", return_value=client):
                    with self.assertRaises(SyncError):
                        PageCreateCommand().run("456789", title)

                self.assertEqual(transport.requests, [])

    def test_creates_a_child_page_and_installs_it_like_a_first_pull(self) -> None:
        with temporary_workarea(root_page_id="456789") as workarea:
            parent_directory = self._local_parent(workarea)
            page = created_page_fixture()
            parent = page_fixture("456789", "Parent page")
            responses = [
                MockResponse.from_json(parent),
                MockResponse.from_json(parent),
                MockResponse.from_json(page), *self._pull_responses(page)]

            transport, status = self._create(workarea, responses)

            state = PageState.load(workarea.cache_path("123456"))
            directory = workarea.page_directory(state)
            self.assertEqual(status, 0)
            self.assertEqual(directory, parent_directory / "New page")
            self.assertEqual(state.page.title, "New page")
            self.assertEqual((directory / "content.md").read_text(), "# New page\n")
            self.assertEqual((directory / "_attachments/diagram.png").read_bytes(), b"PNG")
            create_request = transport.requests[2]
            self.assertEqual(create_request.method, "POST")
            self.assertEqual(create_request.path, "/pages")
            body = create_request.json_body()
            self.assertEqual(body["parentId"], "456789")
            self.assertEqual(body["spaceId"], "98765")
            self.assertEqual(body["title"], "New page")

    def test_failed_creation_leaves_no_local_state(self) -> None:
        with temporary_workarea(root_page_id="456789") as workarea:
            parent_directory = self._local_parent(workarea)
            parent = page_fixture("456789", "Parent page")
            responses = [
                MockResponse.from_json(parent),
                MockResponse.from_json(parent),
                MockResponse.from_json({"message": "title already exists"}, 400)]

            with self.assertRaisesRegex(SyncError, "title already exists"):
                self._create(workarea, responses)

            self.assertEqual(list(workarea.page_state_paths()), ["456789"])
            self.assertEqual(sorted(path.name for path in parent_directory.iterdir()), ["content.md"])

    def test_resolves_a_cached_parent_title_before_creation(self) -> None:
        with temporary_workarea(root_page_id="456789") as workarea:
            self._local_parent(workarea)
            page = created_page_fixture()
            parent = page_fixture("456789", "Parent page")
            responses = [MockResponse.from_json(parent), MockResponse.from_json(page), *self._pull_responses(page)]

            transport, status = self._create(workarea, responses, parent_page_ref="Parent page")

            self.assertEqual(status, 0)
            self.assertEqual(transport.requests[0].path, "/pages/456789")
            self.assertEqual(transport.requests[1].json_body()["parentId"], "456789")

    def test_resolves_a_managed_parent_directory_before_creation(self) -> None:
        with temporary_workarea(root_page_id="456789") as workarea:
            parent = page_fixture("456789", "Parent page")
            parent_state = example_page_state("456789", title="Parent page", directory="Parent page")
            parent_state.save(workarea.cache_path(parent_state.page.id))
            parent_directory = workarea.root_dir / parent_state.page.directory
            parent_directory.mkdir()
            (parent_directory / "content.md").write_text("# Parent page\n", encoding="utf-8")
            page = created_page_fixture()
            responses = [MockResponse.from_json(parent), MockResponse.from_json(page), *self._pull_responses(page)]

            transport, status = self._create(workarea, responses, parent_page_ref=str(parent_directory))

            self.assertEqual(status, 0)
            self.assertEqual(transport.requests[0].path, "/pages/456789")
            self.assertEqual(transport.requests[1].json_body()["parentId"], "456789")

    def test_failed_follow_up_pull_reports_the_created_page(self) -> None:
        with temporary_workarea(root_page_id="456789") as workarea:
            parent_directory = self._local_parent(workarea)
            page = created_page_fixture()
            parent = page_fixture("456789", "Parent page")
            responses = [
                MockResponse.from_json(parent),
                MockResponse.from_json(parent),
                MockResponse.from_json(page),
                MockResponse.from_json(page),
                MockResponse.from_json({"results": [{
                    "id": "456789",
                    "type": "page"}]}),
                MockResponse.from_json(page),
                MockResponse.from_json({"results": [{
                    "id": "456789",
                    "type": "page"}]}),
                MockResponse.from_json({"message": "attachments unavailable"}, 503),
                MockResponse.from_json({"message": "attachments unavailable"}, 503), ]

            with self.assertRaisesRegex(SyncError, "created page '123456'"):
                self._create(workarea, responses)

            self.assertEqual(list(workarea.page_state_paths()), ["456789"])
            self.assertEqual(sorted(path.name for path in parent_directory.iterdir()), ["content.md"])


class TestPageCreateInTree(unittest.TestCase):
    """Creation in a tree of Root (100) with Child (200) below it; Outside (900) is not in the tree."""

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Child", parent_id="100")
        self.site.add_page("900", "Outside")

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea, *page_ids):
        for page_id in page_ids:
            self._run(workarea, lambda: PagePullCommand().run(page_id))

    def _refused(self, workarea, parent_ref, title, error):
        self.site.requests.clear()
        with self.assertRaisesRegex(SyncError, error):
            self._run(workarea, lambda: PageCreateCommand().run(parent_ref, title))

        self.assertEqual([request.method for request in self.site.requests if request.method != "GET"], [])
        self.assertNotIn(title, [item["title"] for item in self.site.content.values()])

    def test_creates_a_page_below_a_local_parent(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")

            self._run(workarea, lambda: PageCreateCommand().run("200", "New page"))

            created = [item for item in self.site.content.values() if item["title"] == "New page"]
            self.assertEqual([item["parent_id"] for item in created], ["200"])
            self.assertTrue((workarea.root_dir / "Root" / "Child" / "New page" / "content.md").is_file())
            self.assertEqual(PageState.load(workarea.cache_path(created[0]["id"])).page.parent_id, "200")

    def test_refuses_a_parent_that_is_not_local_before_creating(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100")

            self._refused(
                workarea, "200", "New page", r"parent page 'Child' \(200\) is not present locally; run: cflsync page pull 200")

    def test_refuses_a_parent_whose_directory_is_missing_before_creating(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            shutil.rmtree(workarea.root_dir / "Root" / "Child")

            self._refused(workarea, "200", "New page", r"run: cflsync page pull --force 200")

    def test_refuses_an_existing_unmanaged_entry_before_creating(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100")
            (workarea.root_dir / "Root" / "new page").mkdir()

            self._refused(workarea, "100", "New page", "page directory 'Root/New page' already exists")

    def test_refuses_a_name_used_by_a_cached_sibling_before_creating(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")

            self._refused(workarea, "100", "child", r"a sibling page \('200'\) already uses directory 'Root/child'")

    def test_refuses_a_parent_outside_the_tree_before_creating(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100")

            self._refused(workarea, "900", "New page", "page '900' is not found in this workarea")


# vim: set ts=4 sw=4 et tw=132:
