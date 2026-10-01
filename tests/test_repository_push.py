# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Repository push ordering, reporting, and failure handling."""

import shutil
import unittest

from cflsync import PageState, SyncError
from cflsync.cli import PagePullCommand, RepositoryPushCommand
from tests.support import FakeConfluence, run_with_site, temporary_workarea


class TestRepositoryPush(unittest.TestCase):

    def setUp(self) -> None:
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Alpha", parent_id="100")
        self.site.add_page("300", "Beta", parent_id="100")

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea) -> None:
        for page_id in ["100", "200", "300"]:
            self._run(workarea, lambda page_id=page_id: PagePullCommand().run(page_id))

    def _push(self, workarea, force=False):
        status = []
        output = self._run(workarea, lambda: status.append(RepositoryPushCommand().run(force=force)))
        return output, status[0]

    def _edit(self, workarea, page_id, markdown) -> None:
        state = PageState.load(workarea.cache_path(page_id))
        directory = workarea.page_directory(state)
        (directory / "content.md").write_text(markdown, encoding="utf-8")

    def test_pushes_local_changes_and_skips_remote_only_changes(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self._edit(workarea, "200", "# Alpha\n\nEdited\n")
            self.site.content["300"]["version"] += 1
            self.site.requests.clear()

            output, status = self._push(workarea)

            lines = output.splitlines()
            self.assertEqual(status, 0)
            self.assertEqual(lines[0], "Page '100' (Root): unchanged")
            self.assertEqual(lines[1], "Page '200' (Alpha): pushed")
            self.assertEqual(lines[2], "Page '300' (Beta): skipped: remote-changed")
            self.assertEqual(lines[3], "Summary: 1 pushed, 1 unchanged, 1 skipped.")
            self.assertIn("Edited", self.site.content["200"]["body"])
            self.assertEqual(self.site.content["300"]["version"], 2)

    def test_refuses_all_pushes_when_a_conflict_exists(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self._edit(workarea, "200", "# Alpha\n\nEdited\n")
            self._edit(workarea, "300", "# Beta\n\nConflicting edit\n")
            self.site.content["300"]["version"] += 1

            with self.assertRaisesRegex(SyncError, "repository push conflicts"):
                self._push(workarea)

            self.assertNotIn("Edited", self.site.content["200"]["body"])

    def test_pushes_parents_before_children(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self.site.add_page("400", "Grandchild", parent_id="200")
            for page_id in ["100", "200", "400"]:
                self._run(workarea, lambda page_id=page_id: PagePullCommand().run(page_id))
            self._edit(workarea, "100", "# Root\n\nEdited root\n")
            self._edit(workarea, "200", "# Alpha\n\nEdited child\n")
            self._edit(workarea, "400", "# Grandchild\n\nEdited grandchild\n")
            self.site.requests.clear()

            _, status = self._push(workarea)

            self.assertEqual(status, 0)
            self.assertEqual(
                [request.path for request in self.site.requests if request.method == "PUT" and "/pages/" in request.path],
                ["/wiki/api/v2/pages/100", "/wiki/api/v2/pages/200", "/wiki/api/v2/pages/400"])

    def test_skips_missing_directories_and_ignores_uncached_directories(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            shutil.rmtree(workarea.root_dir / "Root_100" / "Alpha_200")
            (workarea.root_dir / "Notes").mkdir()

            output, status = self._push(workarea)

            self.assertEqual(status, 0)
            self.assertIn("Page '200' (Alpha): skipped: absent-local", output)
            self.assertNotIn("Notes", output)
            self.assertIn("Summary: 2 unchanged, 1 skipped.", output)

    def test_force_pushes_over_remote_changes(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self._edit(workarea, "200", "# Alpha\n\nEdited locally\n")
            self.site.content["200"]["body"] = '{"type":"doc","version":1,"content":[]}'
            self.site.content["200"]["version"] += 1

            output, status = self._push(workarea, force=True)

            self.assertEqual(status, 0)
            self.assertIn("Page '200' (Alpha): pushed", output)
            self.assertIn("Edited locally", self.site.content["200"]["body"])
            self.assertEqual(PageState.load(workarea.cache_path("200")).page.version, 3)

    def test_continues_after_a_page_refused_for_broken_page_links(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self._edit(workarea, "200", "# Alpha\n\n[Gone](../Gone_999/content.md)\n")
            self._edit(workarea, "300", "# Beta\n\n[Alpha](../Alpha_200/content.md)\n")

            output, status = self._push(workarea)

            self.assertEqual(status, 1)
            self.assertIn("Page '200' (Alpha): failed: page '200' has broken page links; nothing was pushed:", output)
            self.assertIn("Page '300' (Beta): pushed", output)
            self.assertNotIn("Gone", self.site.content["200"]["body"])
            self.assertIn("https://example.atlassian.net/wiki/spaces/EXAMPLE/pages/200", self.site.content["300"]["body"])
