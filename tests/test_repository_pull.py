# Copyright (c) 2026 Sven Rosiers
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Repository pull over the complete page tree."""

import shutil
import unittest

from cflsync import PageState, SyncError
from cflsync.cli import PagePullCommand, RepositoryPullCommand
from tests.support import FakeConfluence, run_with_site, temporary_workarea


class TestRepositoryPull(unittest.TestCase):
    """Pulls of a tree of Root (100) with Alpha (200) and Beta (300) below it, and Child (400) below Alpha."""

    def setUp(self) -> None:
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Alpha", parent_id="100")
        self.site.add_page("300", "Beta", parent_id="100")
        self.site.add_page("400", "Child", parent_id="200")
        self.site.add_attachment("400", "diagram.png", b"PNG")

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea, force=False):
        status = []
        output = self._run(workarea, lambda: status.append(RepositoryPullCommand().run(force=force)))
        return output.splitlines(), status[0]

    def _remote_change(self, page_id, **fields):
        self.site.content[page_id].update(fields)
        self.site.content[page_id]["version"] += 1

    def _edit(self, workarea, page_id, text="Local edit"):
        path = workarea.page_directory(PageState.load(workarea.cache_path(page_id))) / "content.md"
        path.write_text(f"# Edited\n\n{text}\n", encoding="utf-8")
        return path

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_materializes_the_whole_tree_after_init(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            lines, status = self._pull(workarea)

            self.assertEqual(status, 0)
            self.assertEqual(lines[0], "Page '100' (Root): pulled")
            self.assertEqual(lines[-1], "Summary: 4 pulled.")
            self.assertEqual((workarea.root_dir / "Root" / "Alpha" / "Child" / "_attachments" / "diagram.png").read_bytes(), b"PNG")
            self.assertTrue((workarea.root_dir / "Root" / "Beta" / "content.md").is_file())
            self.assertEqual(workarea.page_tree().directory("400"), "Root/Alpha/Child")

    def test_a_second_pull_changes_nothing(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            before = self._snapshot(workarea)

            lines, status = self._pull(workarea)

            self.assertEqual((status, lines[-1]), (0, "Summary: 4 unchanged."))
            self.assertEqual(self._snapshot(workarea), before)

    def test_applies_a_remote_rename_move_and_deletion_in_one_pull(self) -> None:
        self.site.add_page("500", "Gone", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Root" / "Alpha" / "notes.txt").write_text("unmanaged\n", encoding="utf-8")
            self._remote_change("200", title="Renamed alpha")
            self._remote_change("400", parent_id="300")
            del self.site.content["500"]

            lines, status = self._pull(workarea)

            root = workarea.root_dir / "Root"
            self.assertEqual(status, 0)
            self.assertEqual((root / "Renamed alpha" / "notes.txt").read_text(encoding="utf-8"), "unmanaged\n")
            self.assertTrue((root / "Beta" / "Child" / "_attachments" / "diagram.png").is_file())
            self.assertFalse((root / "Renamed alpha" / "Child").exists())
            self.assertTrue((root / "Gone" / "content.md").is_file())
            self.assertEqual(
                lines[-2], "Page '500' (Gone): kept: no longer in the tree (deleted or moved outside the root); "
                "the local copy is unchanged")

    def test_relocates_a_child_out_of_a_parent_that_left_the_tree(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self._remote_change("400", parent_id="300")
            del self.site.content["200"]

            lines, status = self._pull(workarea)

            self.assertEqual(status, 0)
            self.assertTrue((workarea.root_dir / "Root" / "Beta" / "Child" / "content.md").is_file())
            self.assertFalse((workarea.root_dir / "Root" / "Alpha" / "Child").exists())
            self.assertTrue((workarea.root_dir / "Root" / "Alpha" / "content.md").is_file())
            self.assertEqual(PageState.load(workarea.cache_path("400")).page.parent_id, "300")
            self.assertIn("Page '200' (Alpha): kept", lines[-2])

    def test_skips_local_changes_and_restores_missing_directories(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            edited = self._edit(workarea, "200")
            shutil.rmtree(workarea.root_dir / "Root" / "Beta")

            lines, status = self._pull(workarea)

            self.assertEqual(status, 0)
            self.assertIn("Page '200' (Alpha): skipped: local-changed", lines)
            self.assertIn("Page '300' (Beta): pulled", lines)
            self.assertIn("Local edit", edited.read_text(encoding="utf-8"))
            self.assertTrue((workarea.root_dir / "Root" / "Beta" / "content.md").is_file())

    def test_refuses_conflicts_unless_forced(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            edited = self._edit(workarea, "200")
            self._remote_change("200", title="Alpha")
            self._remote_change("300", title="Beta")
            before = self._snapshot(workarea)

            with self.assertRaisesRegex(SyncError, "repository pull conflicts"):
                self._pull(workarea)

            self.assertEqual(self._snapshot(workarea), before)

            lines, status = self._pull(workarea, force=True)

            self.assertEqual(status, 0)
            self.assertEqual(edited.read_text(encoding="utf-8"), "# Alpha\n")
            self.assertEqual(lines[-1], "Summary: 4 pulled.")

    def test_blocks_the_descendants_of_a_page_that_failed(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            run_with_site(self.site, workarea, lambda: PagePullCommand().run("100"))
            (workarea.root_dir / "Root" / "alpha").mkdir()

            lines, status = self._pull(workarea)

            self.assertEqual(status, 1)
            self.assertIn("Page '200' (Alpha): failed: page directory 'Root/Alpha' already exists", lines)
            self.assertIn("Page '400' (Child): blocked: parent page '200' was not pulled", lines)
            self.assertIn("Page '300' (Beta): pulled", lines)
            self.assertEqual(lines[-1], "Summary: 1 pulled, 1 unchanged, 1 blocked, 1 failed.")
            self.assertFalse(workarea.cache_path("400").exists())

    def test_reports_a_sibling_name_clash_as_a_page_failure(self) -> None:
        self.site.add_page("500", "beta", parent_id="100")
        with temporary_workarea(root_page_id="100") as workarea:
            lines, status = self._pull(workarea)

            self.assertEqual(status, 1)
            self.assertIn("Page '500' (beta): failed: a sibling page ('300') already uses directory 'Root/beta'", lines)

    def test_completes_an_interrupted_pull_on_the_next_run(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self.site.fail("GET", "/wiki/api/v2/pages/300", 500)

            _, status = self._pull(workarea)

            self.assertEqual(status, 1)
            self.assertFalse(workarea.cache_path("300").exists())
            lines, status = self._pull(workarea)
            self.assertEqual((status, lines[-1]), (0, "Summary: 1 pulled, 3 unchanged."))
            self.assertIn("Page '300' (Beta): pulled", lines)

    def test_a_discovery_failure_changes_nothing(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            del self.site.content["300"]
            self.site.fail("GET", "/wiki/api/v2/pages/200/direct-children", 403)
            before = self._snapshot(workarea)

            with self.assertRaisesRegex(SyncError, "access was denied"):
                self._pull(workarea)

            self.assertEqual(self._snapshot(workarea), before)


# vim: set ts=4 sw=4 et tw=132:
