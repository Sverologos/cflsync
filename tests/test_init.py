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

from cflsync import Profile
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

    def test_refuses_to_re_anchor_a_workarea_with_cached_pages(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            example_page_state("100").save(workarea.cache_path("100"))

            status, _, errors = self._run(workarea.root_dir, ["init", "123456"])

            self.assertEqual(status, 1)
            self.assertIn("is a workarea with cached pages and cannot be re-anchored", errors)
            self.assertEqual(workarea.root_page_id, "100")


# vim: set ts=4 sw=4 et tw=132:
