# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Repository pull over the complete page tree."""

import json
import shutil
import unittest
from unittest.mock import patch

from cflsync import PageState, SyncError, Workarea
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

    def test_relocates_a_child_out_of_a_parent_that_left_the_tree(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self._remote_change("400", parent_id="300")
            del self.site.content["200"]

            lines, status = self._pull(workarea)

            self.assertEqual(status, 0)
            self.assertTrue((workarea.root_dir / "Root_100" / "Beta_300" / "Child_400" / "content.md").is_file())
            self.assertFalse((workarea.root_dir / "Root_100" / "Alpha_200" / "Child_400").exists())
            self.assertTrue((workarea.root_dir / "Root_100" / "Alpha_200" / "content.md").is_file())
            self.assertEqual(PageState.load(workarea.cache_path("400")).page.parent_id, "300")
            self.assertIn("Page '200' (Alpha): kept", lines[-2])

    def test_skips_local_changes_and_restores_missing_directories(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            edited = self._edit(workarea, "200")
            shutil.rmtree(workarea.root_dir / "Root_100" / "Beta_300")

            lines, status = self._pull(workarea)

            self.assertEqual(status, 0)
            self.assertIn("Page '200' (Alpha): skipped: local-changed", lines)
            self.assertIn("Page '300' (Beta): pulled", lines)
            self.assertIn("Local edit", edited.read_text(encoding="utf-8"))
            self.assertTrue((workarea.root_dir / "Root_100" / "Beta_300" / "content.md").is_file())

    def test_blocks_the_descendants_of_a_page_that_failed(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            run_with_site(self.site, workarea, lambda: PagePullCommand().run("100"))
            (workarea.root_dir / "Root_100" / "alpha_200").mkdir()

            lines, status = self._pull(workarea)

            self.assertEqual(status, 1)
            self.assertIn("Page '200' (Alpha): failed: page directory 'Root_100/Alpha_200' already exists", lines)
            self.assertIn("Page '400' (Child): blocked: parent page '200' was not pulled", lines)
            self.assertIn("Page '300' (Beta): pulled", lines)
            self.assertEqual(lines[-1], "Summary: 1 pulled, 1 unchanged, 1 blocked, 1 failed.")
            self.assertFalse(workarea.cache_path("400").exists())

    def test_a_discovery_failure_changes_nothing(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            del self.site.content["300"]
            self.site.fail("GET", "/wiki/api/v2/pages/200/direct-children", 403)
            before = self._snapshot(workarea)

            with self.assertRaisesRegex(SyncError, "access was denied"):
                self._pull(workarea)

            self.assertEqual(self._snapshot(workarea), before)


class TestRepositoryPullDelete(unittest.TestCase):
    """``pull --delete`` in a tree of Root (100) with Alpha (200) and Beta (300) below it, and Child (400) below Alpha."""

    def setUp(self) -> None:
        self.site = self._site()

    @staticmethod
    def _site():
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_page("200", "Alpha", parent_id="100")
        site.add_page("300", "Beta", parent_id="100")
        site.add_page("400", "Child", parent_id="200")
        return site

    def _run(self, workarea, command):
        return run_with_site(self.site, workarea, command)

    def _pull(self, workarea, force=False, delete=False, answer="yes", terminal=True):
        status = []
        with patch("cflsync.cli._terminal_available", return_value=terminal):
            with patch("builtins.input", return_value=answer) as prompt:
                output = self._run(workarea, lambda: status.append(RepositoryPullCommand().run(force=force, delete=delete)))

        self.prompts = [call.args[0] for call in prompt.call_args_list]
        return output.splitlines(), status[0]

    def _edit(self, workarea, page_id):
        path = workarea.page_directory(PageState.load(workarea.cache_path(page_id))) / "content.md"
        path.write_text("# Edited\n\nLocal edit\n", encoding="utf-8")

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def _remove_alpha_remotely(self):
        del self.site.content["400"]
        del self.site.content["200"]

    def test_deletes_local_copies_of_removed_pages_after_confirmation(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Root_100" / "Alpha_200" / "notes.txt").write_text("unmanaged\n", encoding="utf-8")
            self._remove_alpha_remotely()

            lines, status = self._pull(workarea, delete=True)

            self.assertEqual(status, 0)
            self.assertIn("  Page '200' (Alpha): Root_100/Alpha_200; unmanaged files, which cannot be restored: notes.txt", lines)
            self.assertIn("  Page '400' (Child): Root_100/Alpha_200/Child_400", lines)
            self.assertEqual(self.prompts, ["Delete 2 local page copies? [y/N] "])
            self.assertFalse((workarea.root_dir / "Root_100" / "Alpha_200").exists())
            self.assertEqual(sorted(workarea.page_tree().states), ["100", "300"])
            self.assertEqual(lines[-1], "Summary: 2 deleted, 2 unchanged.")

    def test_declining_or_a_missing_terminal_changes_nothing(self) -> None:
        for answer, terminal, error in [("no", True, "repository pull cancelled; nothing was changed"),
                                        ("yes", False, "confirmation requires a terminal; use --force")]:
            with self.subTest(answer=answer, terminal=terminal):
                self.site = self._site()
                with temporary_workarea(root_page_id="100") as workarea:
                    self._pull(workarea)
                    self._remove_alpha_remotely()
                    self.site.content["300"]["version"] += 1
                    before = self._snapshot(workarea)

                    with self.assertRaisesRegex(SyncError, error):
                        self._pull(workarea, delete=True, answer=answer, terminal=terminal)

                    self.assertEqual(self._snapshot(workarea), before)

    def test_a_removed_page_with_local_changes_aborts_before_any_change(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self._edit(workarea, "400")
            self._remove_alpha_remotely()
            self.site.content["300"]["version"] += 1
            before = self._snapshot(workarea)

            with self.assertRaisesRegex(SyncError, "repository pull conflicts"):
                self._pull(workarea, delete=True)

            self.assertEqual(self._snapshot(workarea), before)
            self.assertEqual(self.prompts, [])

    def test_keeps_a_parent_whose_child_could_not_be_relocated_out_of_it(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            (workarea.root_dir / "Root_100" / "Beta_300" / "child_400").mkdir()
            self.site.content["400"].update(parent_id="300")
            self.site.content["400"]["version"] += 1
            del self.site.content["200"]

            lines, status = self._pull(workarea, delete=True)

            self.assertEqual(status, 1)
            self.assertIn("Page '400' (Child): failed: page directory 'Root_100/Beta_300/Child_400' already exists", lines)
            self.assertIn("Page '200' (Alpha): blocked: its directory contains page '400', which is kept", lines)
            self.assertTrue((workarea.root_dir / "Root_100" / "Alpha_200" / "Child_400" / "content.md").is_file())
            self.assertEqual(sorted(workarea.page_tree().states), ["100", "200", "300", "400"])

    def test_removes_only_the_cache_entry_of_a_page_whose_directory_is_missing(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            del self.site.content["300"]
            shutil.rmtree(workarea.root_dir / "Root_100" / "Beta_300")

            lines, status = self._pull(workarea, delete=True)

            self.assertEqual(status, 0)
            self.assertIn("Page '300' (Beta): deleted: no longer in the tree (deleted or moved outside the root)", lines)
            self.assertFalse(workarea.cache_path("300").exists())

    def test_an_interrupted_deletion_leaves_a_valid_cache_and_completes_on_rerun(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea)
            self._remove_alpha_remotely()
            original = Workarea.remove_page
            calls = []

            def interrupted(workarea_self, state, must_exist=True):
                calls.append(state.page.id)
                if len(calls) == 2:
                    raise OSError("injected interruption")

                return original(workarea_self, state, must_exist)

            with patch.object(Workarea, "remove_page", interrupted):
                _, status = self._pull(workarea, delete=True)

            self.assertEqual((status, calls), (1, ["400", "200"]))
            self.assertEqual(sorted(workarea.page_tree().states), ["100", "200", "300"])

            lines, status = self._pull(workarea, delete=True)

            self.assertEqual(status, 0)
            self.assertFalse((workarea.root_dir / "Root_100" / "Alpha_200").exists())
            self.assertIn("Page '200' (Alpha): deleted: no longer in the tree (deleted or moved outside the root)", lines)


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

# vim: set ts=4 sw=4 et tw=132:
