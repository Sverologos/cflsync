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

from cflsync import APIClient, PageState, SyncError, Workarea
from cflsync.cli import PageCopyCommand, PagePullCommand, _copy_source, _prepare_copy_parent, main
from cflsync.sync import PagePullOperation
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

    def test_root_and_external_sources_require_explicit_in_tree_parent(self) -> None:
        for source in ["100", "900"]:
            with self.subTest(source=source), temporary_workarea(root_page_id="100") as workarea:
                before = local_snapshot(workarea)
                with self.assertRaisesRegex(SyncError, "requires --parent"):
                    self._prepare(workarea, source_id=source)

                self.assertEqual(local_snapshot(workarea), before)
                self.assertTrue(all(request.method == "GET" for request in self.site.requests))
                self.assertEqual(self._prepare(workarea, source_id=source, parent_ref="300").id, "300")

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


class TestPageCopyRecovery(CopyTestCase):

    def _single_copy(self):
        writes = [request for request in self.site.requests if request.method != "GET"]
        self.assertEqual([(request.method, request.path) for request in writes], [("POST", "/wiki/rest/api/content/200/copy")])
        return next(page_id for page_id, page in self.site.content.items() if page["title"] == "Copy")

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
