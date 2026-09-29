# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Workarea initialization anchored at a root page, and refusal of version-1 workareas."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cflsync import Profile, Workarea
from cflsync.cli import main
from tests.support import FakeConfluence, example_page_state, temporary_workarea


class TestInitCommand(unittest.TestCase):

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Space home")
        self.site.add_page("123456", "Root page", parent_id="100")
        self.site.add_page("200", "Duplicate", parent_id="100")
        self.site.add_page("300", "Duplicate", parent_id="100")
        self.profiles = {"default": Profile("example.atlassian.net", "user", "token")}

    def _run(self, root, arguments):
        output = StringIO()
        errors = StringIO()
        with patch("cflsync.cli.Path.cwd", return_value=root):
            with patch("cflsync.cli.Config.find", return_value=SimpleNamespace(profiles=self.profiles)):
                with patch("cflsync.cli.APIClient", return_value=self.site.client()):
                    with redirect_stdout(output), redirect_stderr(errors):
                        status = main(["cflsync", *arguments])

        return status, output.getvalue(), errors.getvalue()

    def test_anchors_a_new_workarea_at_a_page_id(self) -> None:
        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)

            status, output, errors = self._run(root, ["init", "123456"])

            self.assertEqual((status, errors), (0, ""))
            self.assertIn("anchored at page '123456' (Root page), using profile 'default'", output)
            self.assertIn("Pull the page tree with 'cflsync pull'.", output)
            workarea = Workarea.find(root)
            self.assertEqual((workarea.root_page_id, workarea.profile), ("123456", "default"))
            self.assertEqual(list(workarea.cache_dir.iterdir()), [])

    def test_anchors_a_new_workarea_at_a_page_title_with_a_named_profile(self) -> None:
        self.profiles["work"] = self.profiles.pop("default")
        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)

            status, _, errors = self._run(root, ["init", "-p", "work", "Root page"])

            self.assertEqual((status, errors), (0, ""))
            workarea = Workarea.find(root)
            self.assertEqual((workarea.root_page_id, workarea.profile), ("123456", "work"))

    def test_failures_leave_no_workarea(self) -> None:
        cases = [
            (["init", "Duplicate"], "multiple pages match title 'Duplicate': 200, 300"),
            (["init", "No such page"], "no page matches title 'No such page'"),
            (["init", "999999"], "Confluence resource was not found"),
            (["init", "-p", "missing", "123456"], "credential profile 'missing' does not exist"), ]
        for arguments, error in cases:
            with self.subTest(arguments=arguments):
                with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
                    root = Path(temporary_dir)

                    status, _, errors = self._run(root, arguments)

                    self.assertEqual(status, 1)
                    self.assertIn(error, errors)
                    self.assertEqual(list(root.iterdir()), [])

    def test_re_anchors_a_never_pulled_workarea(self) -> None:
        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)
            Workarea.init(root, "100", "work")
            (root / "notes.txt").write_text("unmanaged\n", encoding="utf-8")

            status, output, errors = self._run(root, ["init", "123456"])

            workarea = Workarea.find(root)
            self.assertEqual((status, errors), (0, ""))
            self.assertIn("Re-anchored the workarea at page '123456' (Root page), using profile 'default'", output)
            self.assertEqual((workarea.root_page_id, workarea.profile), ("123456", "default"))
            self.assertEqual((root / "notes.txt").read_text(encoding="utf-8"), "unmanaged\n")
            self.assertEqual(sorted(path.name for path in (root / ".cflsync").iterdir()), ["cache", "profile", "root"])

    def test_re_anchors_at_the_same_root_again(self) -> None:
        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)
            Workarea.init(root, "123456")

            status, _, _ = self._run(root, ["init", "123456"])

            self.assertEqual(status, 0)
            self.assertEqual(Workarea.find(root).root_page_id, "123456")

    def test_converts_an_empty_version_1_workarea(self) -> None:
        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)
            Workarea.init(root, "100")
            (root / ".cflsync" / "root").unlink()

            status, output, _ = self._run(root, ["init", "123456"])

            self.assertEqual(status, 0)
            self.assertIn("Re-anchored the workarea", output)
            self.assertEqual(Workarea.find(root).root_page_id, "123456")

    def test_refuses_to_re_anchor_a_workarea_with_cached_pages(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            example_page_state("100").save(workarea.cache_path("100"))

            status, _, errors = self._run(workarea.root_dir, ["init", "123456"])

            self.assertEqual(status, 1)
            self.assertIn("is a workarea with cached pages and cannot be re-anchored", errors)
            self.assertEqual(workarea.root_page_id, "100")

    def test_refuses_a_subdirectory_of_an_existing_workarea(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            nested = workarea.root_dir / "nested"
            nested.mkdir()

            status, _, errors = self._run(nested, ["init", "123456"])

            self.assertEqual(status, 1)
            self.assertIn("already part of a cflsync workarea", errors)
            self.assertFalse((nested / ".cflsync").exists())
            self.assertEqual(workarea.root_page_id, "100")

    def test_a_failed_lookup_leaves_an_existing_workarea_unchanged(self) -> None:
        with temporary_workarea(root_page_id="100", profile="work") as workarea:
            self.profiles["work"] = self.profiles["default"]
            before = {path.name: path.read_bytes() for path in workarea.cflsync_dir.iterdir() if path.is_file()}

            status, _, _ = self._run(workarea.root_dir, ["init", "-p", "work", "999999"])

            self.assertEqual(status, 1)
            self.assertEqual({path.name: path.read_bytes() for path in workarea.cflsync_dir.iterdir() if path.is_file()}, before)


class TestVersion1Workarea(unittest.TestCase):

    def test_every_workarea_command_refuses_a_version_1_workarea(self) -> None:
        commands = [
            ["page", "create", "123456", "New page"], ["page", "pull", "123456"], ["page", "push", "123456"],
            ["page", "status", "123456"], ["page", "rename", "123456", "Renamed"], ["page", "move", "123456", "456789"],
            ["page", "remove", "--force", "123456"], ]
        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)
            Workarea.init(root, "123456")
            (root / ".cflsync" / "root").unlink()
            for arguments in commands:
                with self.subTest(command=arguments[1]):
                    errors = StringIO()
                    with patch("cflsync.cli.Path.cwd", return_value=root):
                        with patch("cflsync.cli.Config.find", side_effect=AssertionError("credentials must not be read")):
                            with redirect_stderr(errors):
                                status = main(["cflsync", *arguments])

                    self.assertEqual(status, 1)
                    self.assertIn("is a version-1 cflsync workarea", errors.getvalue())
                    self.assertIn("cflsync init ROOT_PAGE_REF", errors.getvalue())


# vim: set ts=4 sw=4 et tw=132:
