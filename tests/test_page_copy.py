# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Page copy eligibility, installation, native outcomes, and recovery tests."""

from copy import deepcopy
from contextlib import redirect_stderr
import errno
from io import StringIO
import json
import shutil
import unittest
from unittest.mock import patch

from cflsync import APIClient, APIError, PageState, SyncError, Workarea
from cflsync.cli import PageCopyCommand, PagePullCommand, _copy_source, _prepare_copy_parent, main
from cflsync.sync import PageChangeDetector, PageChangeStatus, PagePullOperation
from cflsync.convert import PandocRunner
from tests.support import FakeConfluence, LostCopyResponseTransport, MockResponse, run_with_site, temporary_workarea


def local_snapshot(workarea):
    return {
        path.relative_to(workarea.root_dir).as_posix(): path.read_bytes()
        for path in workarea.root_dir.rglob("*") if path.is_file()}


class CopyTestCase(unittest.TestCase):

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page(
            "200",
            "Source",
            parent_id="100",
            body=json.dumps(
                {
                    "type": "doc",
                    "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": "Original"}]}]}))
        self.site.add_page("300", "Missing destination", parent_id="100")
        self.site.add_page("900", "External", space_id="other")
        self.site.add_attachment("200", "file.txt", b"original", "att1")

    def _pull(self, workarea, page_id="200"):
        run_with_site(self.site, workarea, lambda: PagePullCommand().run(page_id))
        self.site.requests.clear()

    def _source(self, workarea, ref="200"):
        result = []
        run_with_site(self.site, workarea, lambda: result.append(_copy_source(workarea, self.site.client(), ref)))
        return result[0]

    def _refused(self, workarea, message="synchronize the source first", ref="200"):
        local = local_snapshot(workarea)
        remote = deepcopy((self.site.content, self.site.attachments))
        with self.assertRaisesRegex(SyncError, message):
            self._source(workarea, ref)

        self.assertEqual(local_snapshot(workarea), local)
        self.assertEqual((self.site.content, self.site.attachments), remote)
        self.assertTrue(all(request.method == "GET" for request in self.site.requests))
        self.assertFalse((workarea.root_dir / "Root_100" / "Missing destination_300").exists())

    def _copy(self, workarea, source="200", title="Copy", parent=None):
        return run_with_site(self.site, workarea, lambda: self.assertEqual(PageCopyCommand().run(source, title, parent), 0))


class TestCopySourceEligibility(CopyTestCase):

    def test_unchanged_source_is_eligible_and_unmanaged_files_are_ignored(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            directory = workarea.root_dir / "Root_100" / "Source_200"
            (directory / "notes.txt").write_text("unmanaged")
            (directory / "_attachments" / "unreferenced-local.txt").write_text("unmanaged")
            before = local_snapshot(workarea)

            page, in_tree = self._source(workarea)

            self.assertEqual(page.id, "200")
            self.assertTrue(in_tree)
            self.assertEqual(local_snapshot(workarea), before)

    def test_local_content_heading_and_attachment_changes_are_refused(self) -> None:
        for change in ["content", "heading", "attachment", "removed-attachment", "new-attachment", "both"]:
            with self.subTest(change=change), temporary_workarea(root_page_id="100") as workarea:
                self._pull(workarea)
                directory = workarea.root_dir / "Root_100" / "Source_200"
                content = directory / "content.md"
                if change in {"content", "both"}:
                    content.write_text(content.read_text() + "\nLocal edit\n")
                elif change == "heading":
                    content.write_text(content.read_text().replace("# Source", "# Edited"))
                elif change == "attachment":
                    (directory / "_attachments" / "file.txt").write_bytes(b"edited")
                elif change == "removed-attachment":
                    (directory / "_attachments" / "file.txt").unlink()
                elif change == "new-attachment":
                    (directory / "_attachments" / "new.txt").write_bytes(b"new")
                    content.write_text(content.read_text() + "\n[New](_attachments/new.txt)\n")

                if change == "both":
                    self.site.content["200"]["version"] += 1

                self._refused(workarea)

    def test_remote_title_version_parent_and_attachment_changes_are_refused(self) -> None:
        for change in ["title", "version", "parent", "attachment", "removed-attachment", "new-attachment"]:
            with self.subTest(change=change), temporary_workarea(root_page_id="100") as workarea:
                # Reset the remote source between cases, without modifying its version for the parent test.
                self.site.content["200"].update(title="Source", version=1, parent_id="100")
                self.site.attachments.clear()
                self.site.add_attachment("200", "file.txt", b"original", "att1")
                self._pull(workarea)
                if change == "title":
                    self.site.content["200"]["title"] = "Renamed"
                elif change == "version":
                    self.site.content["200"]["version"] += 1
                elif change == "parent":
                    self.site.content["200"]["parent_id"] = "300"
                elif change == "attachment":
                    self.site.attachments["att1"]["version"] += 1
                elif change == "removed-attachment":
                    del self.site.attachments["att1"]
                elif change == "new-attachment":
                    self.site.add_attachment("200", "new.txt", b"new")

                self._refused(workarea)

    def test_missing_local_content_directory_and_baseline_require_sync(self) -> None:
        for missing in ["content", "directory", "baseline"]:
            with self.subTest(missing=missing), temporary_workarea(root_page_id="100") as workarea:
                self._pull(workarea)
                if missing == "content":
                    (workarea.root_dir / "Root_100" / "Source_200" / "content.md").unlink()
                elif missing == "directory":
                    shutil.rmtree(workarea.root_dir / "Root_100" / "Source_200")
                else:
                    workarea.cache_path("200").unlink()

                message = "pull it first" if missing == "baseline" else "synchronize the source first"
                self._refused(workarea, message)

    def test_unpulled_in_tree_source_is_not_automatically_installed(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._refused(workarea, "pull it first")
            self.assertEqual(list(workarea.page_state_paths()), [])

    def test_cached_source_moved_outside_or_missing_is_not_external_fallback(self) -> None:
        for change in ["moved", "missing"]:
            with self.subTest(change=change), temporary_workarea(root_page_id="100") as workarea:
                self.site.add_page("200", "Source", parent_id="100")
                self._pull(workarea)
                if change == "moved":
                    self.site.content["200"]["parent_id"] = "900"
                else:
                    del self.site.content["200"]

                self._refused(workarea, ref="Source")

    def test_remote_denial_and_invalid_cache_propagate_without_mutation(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self.site.fail("GET", "/wiki/api/v2/pages/200", 403)
            self._refused(workarea, "access was denied")
            workarea.cache_path("200").write_text("invalid JSON")
            self._refused(workarea, "invalid JSON")

    def test_external_source_needs_no_baseline_and_root_parent_is_normalized(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            page, in_tree = self._source(workarea, "900")
            self.assertEqual(page.id, "900")
            self.assertFalse(in_tree)
            self.assertEqual(list(workarea.page_state_paths()), [])
            self.site.add_folder("50", "Folder above root")
            self.site.content["100"]["parent_id"] = "50"
            self._pull(workarea, "100")

            page, in_tree = self._source(workarea, "100")

            self.assertEqual(page.id, "100")
            self.assertTrue(in_tree)


class TestCopyDestinationPreparation(CopyTestCase):

    def _prepare(self, workarea, source_id="200", parent_ref=None):
        result = []
        run_with_site(
            self.site, workarea, lambda: result.append(
                _prepare_copy_parent(
                    workarea, self.site.client(),
                    self.site.client().get_page(source_id),
                    self.site.client().get_page(source_id).id != "900", parent_ref, PagePullOperation())))
        return result[0]

    def test_uses_default_parent_and_allows_source_and_descendant_parents(self) -> None:
        self.site.add_page("400", "Descendant", parent_id="200")
        for ref, expected in [(None, "100"), ("200", "200"), ("400", "400")]:
            with self.subTest(ref=ref), temporary_workarea(root_page_id="100") as workarea:
                self._pull(workarea)
                parent = self._prepare(workarea, parent_ref=ref)
                self.assertEqual(parent.id, expected)
                self.assertTrue(workarea.cache_path(expected).is_file())

    def test_root_and_external_sources_require_explicit_in_tree_parent(self) -> None:
        for source in ["100", "900"]:
            with self.subTest(source=source), temporary_workarea(root_page_id="100") as workarea:
                before = local_snapshot(workarea)
                with self.assertRaisesRegex(SyncError, "requires --parent"):
                    self._prepare(workarea, source_id=source)

                self.assertEqual(local_snapshot(workarea), before)
                self.assertTrue(all(request.method == "GET" for request in self.site.requests))
                self.assertEqual(self._prepare(workarea, source_id=source, parent_ref="300").id, "300")

    def test_missing_parent_chain_installs_top_down_in_empty_workarea(self) -> None:
        self.site.add_page("400", "Deep parent", parent_id="300")
        with temporary_workarea(root_page_id="100") as workarea:
            parent = self._prepare(workarea, source_id="900", parent_ref="400")

            self.assertEqual(parent.id, "400")
            self.assertTrue(
                (workarea.root_dir / "Root_100" / "Missing destination_300" / "Deep parent_400" / "content.md").is_file())
            self.assertEqual(set(workarea.page_state_paths()), {"100", "300", "400"})

    def test_dirty_cached_ancestors_are_kept_and_missing_directories_restored(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "300")
            root_content = workarea.root_dir / "Root_100" / "content.md"
            root_content.write_text(root_content.read_text() + "\nLocal parent edit\n")
            before = root_content.read_bytes()
            shutil.rmtree(workarea.root_dir / "Root_100" / "Missing destination_300")

            self._prepare(workarea, source_id="900", parent_ref="300")

            self.assertEqual(root_content.read_bytes(), before)
            self.assertTrue((workarea.root_dir / "Root_100" / "Missing destination_300" / "content.md").is_file())

    def test_cached_parent_moved_outside_tree_is_refused_before_installation(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "300")
            self.site.content["300"]["parent_id"] = "900"
            before = local_snapshot(workarea)
            for ref in ["300", "Missing destination", workarea.root_dir / "Root_100" / "Missing destination_300"]:
                with self.subTest(ref=ref):
                    with self.assertRaisesRegex(SyncError, "destination parent.*not in"):
                        self._prepare(workarea, source_id="900", parent_ref=ref)

                    self.assertEqual(local_snapshot(workarea), before)

    def test_outside_missing_folder_and_folder_ancestry_parents_fail_read_only(self) -> None:
        self.site.add_folder("600", "Folder", parent_id="100")
        self.site.add_page("700", "Below folder", parent_id="600")
        for ref in ["900", "999", "600", "700"]:
            with self.subTest(ref=ref), temporary_workarea(root_page_id="100") as workarea:
                before = local_snapshot(workarea)
                with self.assertRaises(SyncError):
                    self._prepare(workarea, source_id="900", parent_ref=ref)

                self.assertEqual(local_snapshot(workarea), before)
                self.assertTrue(all(request.method == "GET" for request in self.site.requests))

    def test_unmanaged_ancestor_clash_aborts_whole_plan_and_partial_failure_keeps_parents(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            (workarea.root_dir / "Root_100").mkdir()
            before = local_snapshot(workarea)
            with self.assertRaisesRegex(SyncError, "already exists"):
                self._prepare(workarea, source_id="900", parent_ref="300")

            self.assertEqual(local_snapshot(workarea), before)
            self.assertEqual(list(workarea.page_state_paths()), [])

        with temporary_workarea(root_page_id="100") as workarea:
            for _ in range(2):
                self.site.fail("GET", "/wiki/api/v2/pages/300/attachments", 503)

            with self.assertRaisesRegex(SyncError, "pages pulled before the failure.*Root"):
                self._prepare(workarea, source_id="900", parent_ref="300")

            self.assertEqual(list(workarea.page_state_paths()), ["100"])
            self.assertTrue((workarea.root_dir / "Root_100" / "content.md").is_file())
            self.assertTrue(all(request.method == "GET" for request in self.site.requests))


class TestPageCopySuccess(CopyTestCase):

    def test_sibling_copy_installs_its_own_valid_baseline_and_preserves_source(self) -> None:
        self.site.add_page("400", "Source child", parent_id="200")
        self.site.content["200"].update(
            labels=["label"], properties={"app": 1}, restrictions={"read": ["user"]}, custom_content=["app"], comments=["comment"])
        self.site.attachments["att1"]["version"] = 3
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            local = local_snapshot(workarea)
            remote = deepcopy((self.site.content, self.site.attachments))

            output = self._copy(workarea)

            created = next(key for key in self.site.content if key not in remote[0])
            copied = self.site.content[created]
            self.assertEqual((copied["parent_id"], copied["version"], copied["labels"]), ("100", 1, ["label"]))
            self.assertEqual(output, f"Copied page 'Copy' ({created}) to Root_100/Copy_{created}\n")
            for key, value in remote[0].items():
                self.assertEqual(self.site.content[key], value)

            for path, data in local.items():
                self.assertEqual(local_snapshot(workarea)[path], data)

            self.assertEqual(len(self.site.content), len(remote[0]) + 1)
            state = PageState.load(workarea.cache_path(created))
            page = self.site.client().get_page(created)
            detector = PageChangeDetector(PandocRunner())
            self.assertEqual(detector.local_status(workarea.page_directory(state), state), PageChangeStatus.UNCHANGED)
            self.assertEqual(detector.remote_status(page, page.attachments(), state), PageChangeStatus.UNCHANGED)
            self.assertNotEqual(state.attachments["file.txt"].id, "att1")
            self.assertEqual(state.attachments["file.txt"].version, 1)
            self.assertTrue(all(request.method == "GET" or request.path.endswith("/copy") for request in self.site.requests))
            self.assertEqual(sum(request.method == "POST" for request in self.site.requests), 1)

    def test_a_copy_keeps_its_page_links_to_the_original_targets_as_local_links(self) -> None:
        link = {"type": "link", "attrs": {"href": "https://example.atlassian.net/wiki/spaces/EXAMPLE/pages/300#Top"}}
        self.site.content["200"]["body"] = json.dumps(
            {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{
                        "type": "text",
                        "text": "Destination",
                        "marks": [link]}]}]})
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            remote = set(self.site.content)

            self._copy(workarea)

            created = next(key for key in self.site.content if key not in remote)
            markdown = (workarea.root_dir / "Root_100" / f"Copy_{created}" / "content.md").read_text(encoding="utf-8")
            self.assertIn("[Destination](../Missing%20destination_300/content.md#Top)", markdown)

    def test_all_source_and_explicit_parent_reference_forms(self) -> None:
        for source_form in ["id", "title", "directory", "content"]:
            for parent_form in ["id", "title", "directory", "content"]:
                with self.subTest(source=source_form, parent=parent_form), temporary_workarea(root_page_id="100") as workarea:
                    self._pull(workarea)
                    source_dir = workarea.root_dir / "Root_100" / "Source_200"
                    parent_dir = workarea.root_dir / "Root_100"
                    source = {
                        "id": "200",
                        "title": "Source",
                        "directory": str(source_dir),
                        "content": str(source_dir / "content.md")}[source_form]
                    parent = {
                        "id": "100",
                        "title": "Root",
                        "directory": str(parent_dir),
                        "content": str(parent_dir / "content.md")}[parent_form]

                    output = self._copy(workarea, source=source, parent=parent)

                    self.assertIn("to Root_100/Copy_", output)

    def test_root_source_and_source_descendant_explicit_parents(self) -> None:
        self.site.add_page("400", "Descendant", parent_id="200")
        for source, parent in [("100", "100"), ("200", "200"), ("200", "400")]:
            with self.subTest(source=source, parent=parent), temporary_workarea(root_page_id="100") as workarea:
                self._pull(workarea)
                self.site.requests.clear()

                self._copy(workarea, source=source, parent=parent)

                created_id = self.site.requests[[request.method for request in self.site.requests].index("POST")]
                self.assertEqual(created_id.json_body()["destination"]["value"], parent)
                self.assertEqual(sum(request.method == "POST" for request in self.site.requests), 1)

    def test_cross_space_external_source_in_empty_workarea_pulls_parent_and_copy(self) -> None:
        self.site.content["900"]["labels"] = ["external"]
        self.site.add_attachment("900", "external.txt", b"external")
        with temporary_workarea(root_page_id="100") as workarea:
            output = self._copy(workarea, source="External", parent="300")

            self.assertIn("Pulled parent 'Root'", output)
            self.assertIn("Pulled parent 'Missing destination'", output)
            self.assertIn("to Root_100/Missing destination_300/Copy_", output)
            state = next(state for state in workarea.page_tree().states.values() if state.page.title == "Copy")
            self.assertEqual(self.site.content[state.page.id]["space_id"], "98765")
            self.assertEqual(self.site.content[state.page.id]["labels"], ["external"])
            self.assertEqual((workarea.page_directory(state) / "_attachments" / "external.txt").read_bytes(), b"external")

    def test_native_disambiguation_uses_actual_title_and_ignores_requested_name_clash(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Root_100" / "Copy").mkdir()
            self.site.copy_titles = ["Copy (2)"]

            output = self._copy(workarea)

            self.assertIn("Copied page 'Copy (2)'", output)
            page_id = next(key for key, value in self.site.content.items() if value["title"] == "Copy (2)")
            self.assertIn(f"to Root_100/Copy %282%29_{page_id}", output)
            self.assertTrue((workarea.root_dir / "Root_100" / f"Copy %282%29_{page_id}" / "content.md").is_file())

    def test_invalid_title_and_dirty_source_precede_destination_installation(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            for title in ["", " New", "New ", "New\nTitle", "New\tTitle"]:
                with self.subTest(title=title), self.assertRaisesRegex(SyncError, "page title"):
                    self._copy(workarea, title=title, parent="300")

            self.assertEqual(self.site.requests, [])
            self._pull(workarea)
            path = workarea.root_dir / "Root_100" / "Source_200" / "content.md"
            path.write_text(path.read_text() + "\nEdit\n")
            before = local_snapshot(workarea)
            with self.assertRaisesRegex(SyncError, "synchronize the source first"):
                self._copy(workarea, parent="300")

            self.assertEqual(local_snapshot(workarea), before)
            self.assertFalse(workarea.cache_path("300").exists())
            self.assertTrue(all(request.method == "GET" for request in self.site.requests))


class TestPageCopyRecovery(CopyTestCase):

    def _single_copy(self):
        writes = [request for request in self.site.requests if request.method != "GET"]
        self.assertEqual([(request.method, request.path) for request in writes], [("POST", "/wiki/rest/api/content/200/copy")])
        return next(page_id for page_id, page in self.site.content.items() if page["title"] == "Copy")

    def test_native_rejection_keeps_installed_ancestors_without_workarounds(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self.site.fail("POST", "/wiki/rest/api/content/200/copy", 403, "restricted parent")
            with self.assertRaisesRegex(SyncError, "200.*300.*access was denied.*restricted parent"):
                self._copy(workarea, parent="300")

            self.assertTrue(workarea.cache_path("300").is_file())
            self.assertFalse(any(page["title"] == "Copy" for page in self.site.content.values()))
            self.assertEqual(
                [(r.method, r.path) for r in self.site.requests if r.method != "GET"], [
                    ("POST", "/wiki/rest/api/content/200/copy")])

    def test_lost_or_unusable_accepted_response_reports_uncertainty_without_recopy(self) -> None:
        for response in [None, MockResponse.from_json({}), MockResponse(200, {}, b"not JSON")]:
            with self.subTest(response=response), temporary_workarea(root_page_id="100") as workarea:
                self.setUp()
                self._pull(workarea)
                before = local_snapshot(workarea)
                api = APIClient(
                    "example.atlassian.net",
                    "user",
                    "token",
                    transport=LostCopyResponseTransport(self.site, "/wiki/api/v2", response))
                with patch.object(self.site, "client", return_value=api):
                    with self.assertRaisesRegex(SyncError, "outcome is uncertain.*duplicate") as error:
                        self._copy(workarea)

                self.assertNotIn("run: cflsync page pull", str(error.exception))
                self._single_copy()
                self.assertEqual(local_snapshot(workarea), before)
                self.assertEqual(len(self.site.content), 5)

    def test_post_copy_read_scope_download_and_content_failures_keep_recovery_id(self) -> None:
        for failure in ["read", "scope", "attachments", "download", "adf", "conversion"]:
            with self.subTest(failure=failure), temporary_workarea(root_page_id="100") as workarea:
                self.setUp()
                self._pull(workarea)
                before = local_snapshot(workarea)
                original_copy = self.site._copy_page

                def copy_with_failure(source, request):
                    response = original_copy(source, request)
                    page_id = json.loads(response.body)["id"]
                    paths = {
                        "read": f"/wiki/api/v2/pages/{page_id}",
                        "attachments": f"/wiki/api/v2/pages/{page_id}/attachments",
                        "download": f"/wiki/download/attachments/{page_id}/file.txt"}
                    if failure in paths:
                        for _ in range(2):
                            self.site.fail("GET", paths[failure], 503)
                    elif failure == "scope":
                        self.site.content[page_id]["parent_id"] = "900"
                    elif failure == "adf":
                        self.site.content[page_id]["body"] = "["
                    else:
                        self.site.content[page_id]["body"] = json.dumps({"type": "doc", "version": 1, "content": [None]})

                    return response

                with patch.object(self.site, "_copy_page", side_effect=copy_with_failure):
                    with self.assertRaisesRegex(SyncError, "copied page.*remotely.*run: cflsync page pull") as error:
                        self._copy(workarea)

                page_id = self._single_copy()
                self.assertIn(f"run: cflsync page pull {page_id}", str(error.exception))
                self.assertFalse(workarea.cache_path(page_id).exists())
                self.assertEqual(local_snapshot(workarea), before)
                self.site.content[page_id].update(parent_id="100", body=self.site.content["200"]["body"])
                self._pull(workarea, page_id)
                self.assertTrue(workarea.cache_path(page_id).is_file())

    def test_staging_installation_and_cache_failures_roll_back_and_allow_pull_recovery(self) -> None:
        for failure in ["staging", "unicode", "path-length", "installation", "cache"]:
            with self.subTest(failure=failure), temporary_workarea(root_page_id="100") as workarea:
                self.setUp()
                self._pull(workarea)
                before = local_snapshot(workarea)
                if failure == "cache":
                    target, attribute, cause = PageState, "save", OSError("cache write failed")
                elif failure == "installation":
                    target, attribute, cause = Workarea, "replace_page", OSError("installation failed")
                elif failure == "unicode":
                    target, attribute, cause = Workarea, "stage_page", UnicodeError("encoding failure")
                elif failure == "path-length":
                    target, attribute, cause = Workarea, "stage_page", OSError(errno.ENAMETOOLONG, "too long", "long/path")
                else:
                    target, attribute, cause = Workarea, "stage_page", OSError("staging failed")

                with patch.object(target, attribute, side_effect=cause):
                    with self.assertRaisesRegex(SyncError, "copied page.*remotely.*run: cflsync page pull") as error:
                        self._copy(workarea)

                page_id = self._single_copy()
                self.assertIn(f"cflsync page pull {page_id}", str(error.exception))
                if failure == "path-length":
                    self.assertIn("path is too long", str(error.exception))

                self.assertEqual(local_snapshot(workarea), before)
                self.assertFalse((workarea.root_dir / "Root_100" / f"Copy_{page_id}").exists())
                self.assertFalse(any(path.name.startswith(".cflsync-stage-") for path in workarea.root_dir.iterdir()))
                self._pull(workarea, page_id)
                self.assertTrue(workarea.cache_path(page_id).is_file())

    def test_actual_title_unmanaged_clash_preserves_entry_and_reports_id(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self.site.copy_titles = ["Copy (2)"]
            # The fake site assigns the next sequential ID to the copy.
            clash = workarea.root_dir / "Root_100" / f"copy %282%29_{self.site.peek_next_id()}"
            clash.write_bytes(b"unmanaged")
            with self.assertRaisesRegex(SyncError, "copied page.*remotely.*already exists.*page pull") as error:
                self._copy(workarea)

            page_id = next(key for key, value in self.site.content.items() if value["title"] == "Copy (2)")
            self.assertIn(f"cflsync page pull {page_id}", str(error.exception))
            self.assertEqual(clash.read_bytes(), b"unmanaged")
            self.assertFalse(workarea.cache_path(page_id).exists())
            self.assertEqual(sum(request.method == "POST" for request in self.site.requests), 1)
            clash.unlink()
            self._pull(workarea, page_id)
            self.assertTrue(workarea.cache_path(page_id).is_file())

    def test_cli_failure_returns_nonzero_without_traceback(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self.site.fail("POST", "/wiki/rest/api/content/200/copy", 403)
            result = []
            with redirect_stderr(StringIO()) as errors:
                run_with_site(self.site, workarea, lambda: result.append(main(["cflsync", "page", "copy", "200", "Copy"])))

            self.assertEqual(result, [1])
            self.assertIn("access was denied", errors.getvalue())
            self.assertNotIn("Traceback", errors.getvalue())

    def test_local_case_unicode_truncation_and_reserved_names_use_normal_suffixes(self) -> None:
        for title in ["source", "_attachments", "A" * 100, "Re\u0301sume\u0301"]:
            with self.subTest(title=title), temporary_workarea(root_page_id="100") as workarea:
                self.setUp()
                self._pull(workarea)
                if title.startswith("Re"):
                    self.site.add_page("400", "R\u00e9sum\u00e9", parent_id="100")
                    self._pull(workarea, "400")

                self._copy(workarea, title=title)
                state = next(state for state in workarea.page_tree().states.values() if state.page.title == title)
                self.assertLessEqual(len(state.page.directory), 64)
                self.assertTrue(workarea.page_directory(state).is_dir())
                self.assertTrue(state.page.directory.endswith("_" + state.page.id))


# vim: set ts=4 sw=4 et tw=132:
