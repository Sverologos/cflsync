# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Removal of a page and its subtree, remotely and locally."""

import unittest
from unittest.mock import patch

from cflsync import SyncError
from cflsync.cli import (
    InitCommand, PageCreateCommand, PagePullCommand, PageRemoveCommand, RepositoryPullCommand, RepositoryPushCommand,
    RepositoryStatusCommand)
from tests.support import FakeConfluence, run_with_site, temporary_workarea


class TestPageRemove(unittest.TestCase):
    """Removal in a tree of Root (100), with Child (200) and Other (400) below it, and Grandchild (300) below Child."""

    def setUp(self):
        self.site = self._site()

    @staticmethod
    def _site():
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_page("200", "Child", parent_id="100")
        site.add_attachment("200", "diagram.png", b"PNG")
        site.add_page("300", "Grandchild", parent_id="200")
        site.add_page("400", "Other", parent_id="100")
        return site

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea, *page_ids):
        for page_id in page_ids:
            self._run(workarea, lambda page_id=page_id: PagePullCommand().run(page_id))

    def _remove(self, workarea, page_ref, force=True, answer="yes", terminal=True):
        self.site.requests.clear()
        with patch("cflsync.cli._terminal_available", return_value=terminal):
            with patch("builtins.input", return_value=answer) as prompt:
                output = self._run(workarea, lambda: PageRemoveCommand().run(page_ref, force=force))

        self.prompts = [call.args[0] for call in prompt.call_args_list]
        return output.splitlines()

    def _edit(self, workarea, *parts):
        (workarea.root_dir.joinpath(*parts) / "content.md").write_text("# Edited\n\nLocal edit\n", encoding="utf-8")

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def _deletes(self):
        return [request.path for request in self.site.requests if request.method == "DELETE"]

    def _refused(self, workarea, page_ref, error, force=True):
        before = self._snapshot(workarea)
        with self.assertRaisesRegex(SyncError, error):
            self._remove(workarea, page_ref, force=force)

        self.assertEqual(self._snapshot(workarea), before)
        self.assertEqual(self._deletes(), [])

    def test_declining_or_a_missing_terminal_changes_nothing(self) -> None:
        for answer, terminal in [("no", True), ("yes", False)]:
            with self.subTest(answer=answer, terminal=terminal):
                self.site = self._site()
                with temporary_workarea(root_page_id="100") as workarea:
                    self._pull(workarea, "100", "200", "300")
                    before = self._snapshot(workarea)

                    if terminal:
                        self._remove(workarea, "200", force=False, answer=answer, terminal=terminal)
                    else:
                        with self.assertRaisesRegex(SyncError, "confirmation requires a terminal; use --force"):
                            self._remove(workarea, "200", force=False, answer=answer, terminal=terminal)

                    self.assertEqual(self._snapshot(workarea), before)
                    self.assertEqual(self._deletes(), [])

    def test_the_prompt_lists_descendants_and_marks_remote_only_pages_and_unmanaged_files(self) -> None:
        self.site.add_page("500", "Remote only", parent_id="200")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")
            (workarea.root_dir / "Root_100" / "Child_200" / "notes.txt").write_text("unmanaged", encoding="utf-8")

            lines = self._remove(workarea, "200", force=False)

            self.assertEqual(lines[0], "This removes page 'Child' (200) and all pages below it, remotely and locally:")
            self.assertIn("  Page '200' (Child): Root_100/Child_200; unmanaged files, which cannot be restored: notes.txt", lines)
            self.assertIn("  Page '300' (Grandchild): Root_100/Child_200/Grandchild_300", lines)
            self.assertIn("  Page '500' (Remote only): -; not present locally", lines)
            self.assertEqual(self.prompts, ["Remove page 'Child' (200) and 2 descendant pages? [y/N] "])
            self.assertEqual(sorted(self.site.content), ["100", "400"])

    def test_refuses_unsynchronized_pages_in_the_subtree_even_with_force(self) -> None:
        cases = [
            ("local", lambda workarea: self._edit(workarea, "Root_100", "Child_200", "Grandchild_300")),
            ("remote", lambda workarea: self.site.content["300"].update(version=2))]
        for name, change in cases:
            with self.subTest(change=name):
                self.site = self._site()
                with temporary_workarea(root_page_id="100") as workarea:
                    self._pull(workarea, "100", "200", "300")
                    change(workarea)

                    self._refused(workarea, "200", "page '300' has local or remote changes; remove conflicts")

    def test_refuses_a_descendant_moved_out_of_or_into_the_subtree(self) -> None:
        cases = [
            ("out", "300", "400", "page '300' was moved remotely out of the subtree of page '200'"),
            ("into", "400", "200", "page '400' was moved remotely into the subtree of page '200'")]
        for name, page_id, parent_id, error in cases:
            with self.subTest(move=name):
                self.site = self._site()
                with temporary_workarea(root_page_id="100") as workarea:
                    self._pull(workarea, "100", "200", "300", "400")
                    self.site.content[page_id].update(parent_id=parent_id)
                    self.site.content[page_id]["version"] += 1

                    self._refused(workarea, "200", error + "; run 'cflsync pull' first")

    def test_removes_the_local_copies_of_a_page_already_removed_remotely(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")
            del self.site.content["300"]
            del self.site.content["200"]

            self._remove(workarea, "200", force=False)

            self.assertEqual(self._deletes(), [])
            self.assertEqual(self.prompts, ["Remove page 'Child' (200) and 1 descendant page? [y/N] "])
            self.assertFalse((workarea.root_dir / "Root_100" / "Child_200").exists())
            self.assertEqual(sorted(workarea.page_tree().states), ["100"])

    def test_removes_the_local_copy_of_a_leaf_already_removed_remotely(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "400")
            del self.site.content["400"]

            self._remove(workarea, "400", force=False)

            self.assertEqual(self.prompts, ["Remove local copy of page 'Other' (400)? [y/N] "])
            self.assertFalse((workarea.root_dir / "Root_100" / "Other_400").exists())
            self.assertFalse(workarea.cache_path("400").exists())

    def test_local_changes_on_a_page_removed_remotely_need_force(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "400")
            self._edit(workarea, "Root_100", "Other_400")
            del self.site.content["400"]

            self._refused(
                workarea,
                "400",
                "page '400' was removed remotely but has local changes; remove conflicts; use --force",
                force=False)

            self._remove(workarea, "400", force=True)

            self.assertFalse((workarea.root_dir / "Root_100" / "Other_400").exists())

    def test_a_remote_failure_stops_the_removal_and_a_rerun_completes_it(self) -> None:
        self.site.add_page("500", "Sibling", parent_id="200")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300", "500")
            self.site.fail("DELETE", "/wiki/api/v2/pages/300", 500)

            with self.assertRaisesRegex(SyncError,
                                        r"cannot remove page '300': .*; pages removed before the failure: 'Sibling' \(500\)"):
                self._remove(workarea, "200")

            self.assertEqual(sorted(workarea.page_tree().states), ["100", "200", "300"])
            self.assertFalse((workarea.root_dir / "Root_100" / "Child_200" / "Sibling_500").exists())
            self.assertTrue((workarea.root_dir / "Root_100" / "Child_200" / "Grandchild_300" / "content.md").is_file())

            self._remove(workarea, "200")

            self.assertEqual(sorted(workarea.page_tree().states), ["100"])
            self.assertEqual(sorted(self.site.content), ["100", "400"])

    def test_refuses_on_windows_while_the_current_directory_is_inside_the_subtree(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300")
            child = workarea.root_dir / "Root_100" / "Child_200"

            # The current directory is inside the subtree exactly when it is inside the removed page's directory.
            with patch("cflsync.workarea._is_windows", return_value=True):
                with patch("cflsync.workarea._current_directory_is_inside", side_effect=lambda directory: directory == child):
                    self._refused(workarea, "200", "cannot remove a page directory while it is the current directory")

    def test_requires_a_local_managed_page(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            with self.assertRaisesRegex(SyncError, "no managed local page"):
                self._remove(workarea, "400")

    def test_removing_the_root_removes_the_whole_tree_and_leaves_an_empty_workarea(self) -> None:
        self.site.add_page("900", "Outside")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200", "300", "400")

            lines = self._remove(workarea, "100", force=False)

            self.assertEqual(
                lines[0], "This removes the root page, and with it the whole tree of this workarea, remotely and locally:")
            self.assertEqual(self.prompts, ["Remove page 'Root' (100) and 3 descendant pages? [y/N] "])
            self.assertEqual(sorted(self.site.content), ["900"])
            self.assertEqual([path.name for path in workarea.root_dir.iterdir()], [".cflsync"])
            self.assertEqual(list(workarea.cache_dir.iterdir()), [])
            self.assertEqual((workarea.root_page_id, workarea.profile), ("100", "default"))
            commands = [
                lambda: PagePullCommand().run("900"), lambda: PageCreateCommand().run("100", "New page"),
                lambda: RepositoryPullCommand().run(), lambda: RepositoryPushCommand().run(),
                lambda: RepositoryStatusCommand().run()]
            for command in commands:
                with self.assertRaisesRegex(SyncError, "root page '100' of this workarea no longer exists; .* re-anchor"):
                    self._run(workarea, command)

            # The empty workarea is re-anchored at another root, and pulled again.
            self.site.add_page("901", "New root", parent_id="900")
            self._run(workarea, lambda: InitCommand().run("901"))
            self._run(workarea, lambda: RepositoryPullCommand().run())
            self.assertEqual(workarea.root_page_id, "901")
            self.assertTrue((workarea.root_dir / "New root_901" / "content.md").is_file())


# vim: set ts=4 sw=4 et tw=132:
