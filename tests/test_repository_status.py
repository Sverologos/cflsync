# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Repository status reporting over the complete page tree."""

import shutil
import unittest

from cflsync import PageState, SyncError
from cflsync.cli import PagePullCommand, RepositoryStatusCommand
from tests.support import FakeConfluence, run_with_site, temporary_workarea


class TestRepositoryStatus(unittest.TestCase):
    """Status of a tree of Root (100) with Alpha (200), Beta (300), Gamma (400), and Delta (500) below it."""

    def setUp(self) -> None:
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        for page_id, title in [("200", "Alpha"), ("300", "Beta"), ("400", "Gamma"), ("500", "Delta")]:
            self.site.add_page(page_id, title, parent_id="100")

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea, *page_ids) -> None:
        for page_id in page_ids:
            self._run(workarea, lambda page_id=page_id: PagePullCommand().run(page_id))

    def _status(self, workarea):
        status = []
        output = self._run(workarea, lambda: status.append(RepositoryStatusCommand().run()))
        return output.splitlines(), status[0]

    def _edit(self, workarea, page_id) -> None:
        directory = workarea.page_directory(PageState.load(workarea.cache_path(page_id)))
        (directory / "content.md").write_text("# Edited\n\nLocal edit\n", encoding="utf-8")

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_reports_every_state_parents_first(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300", "400", "500")
            self._edit(workarea, "200")
            self.site.content["300"]["version"] += 1
            self._edit(workarea, "400")
            self.site.content["400"]["version"] += 1
            del self.site.content["500"]
            self.site.add_page("600", "Epsilon", parent_id="100")

            lines, status = self._status(workarea)

            self.assertEqual(status, 0)
            self.assertEqual(lines[0], "Page '100' (Root): unchanged")
            self.assertEqual(
                sorted(lines[1:-1]), [
                    "Page '200' (Alpha): local changed", "Page '300' (Beta): remote changed", "Page '400' (Gamma): conflict",
                    "Page '500' (Delta): remote removed", "Page '600' (Epsilon): not in local"])
            self.assertEqual(
                lines[-1], "Summary: 1 not in local, 1 remote removed, 1 remote changed, 1 local changed, 1 conflict, 1 unchanged.")

    def test_reports_a_removed_page_with_local_changes(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            self._edit(workarea, "200")
            del self.site.content["200"]

            lines, status = self._status(workarea)

            self.assertEqual(status, 0)
            self.assertIn("Page '200' (Alpha): remote removed, local changed", lines)

    def test_reports_a_cached_page_with_a_missing_directory_as_not_in_local(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            shutil.rmtree(workarea.root_dir / "Root_100" / "Alpha_200")

            lines, _ = self._status(workarea)

            self.assertIn("Page '200' (Alpha): not in local", lines)

    def test_changes_nothing(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            self._edit(workarea, "200")
            self.site.content["300"]["version"] += 1
            before = self._snapshot(workarea)
            self.site.requests.clear()

            self._status(workarea)

            self.assertEqual(self._snapshot(workarea), before)
            self.assertTrue(all(request.method == "GET" for request in self.site.requests))

    def test_non_page_content_in_the_tree_fails_without_reporting_absences(self) -> None:
        self.site.add_folder("700", "Folder", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            del self.site.content["200"]

            with self.assertRaisesRegex(SyncError, "folder"):
                self._status(workarea)

    def test_failed_listing_reports_no_absences(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            self.site.fail("GET", "/wiki/api/v2/pages/100/direct-children", 403)

            with self.assertRaisesRegex(SyncError, "access was denied"):
                self._status(workarea)


# vim: set ts=4 sw=4 et tw=132:
