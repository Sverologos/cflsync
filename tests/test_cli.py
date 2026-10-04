# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for cflsync command-line routing and expected errors."""

import unittest
from unittest.mock import patch

from cflsync.cli import (PageRenameCommand, RepositoryPullCommand, RepositoryPushCommand, RepositoryStatusCommand, main)


class TestPageCommandDispatch(unittest.TestCase):

    def test_dispatches_page_rename_arguments_to_its_command(self) -> None:
        with patch.object(PageRenameCommand, "run", return_value=0) as run:
            result = main(["cflsync", "page", "rename", "123456", "Renamed page"])

        self.assertEqual(result, 0)
        run.assert_called_once_with("123456", "Renamed page")

    def test_dispatches_repository_push(self) -> None:
        with patch.object(RepositoryPushCommand, "run", return_value=0) as run:
            result = main(["cflsync", "push", "--force"])

        self.assertEqual(result, 0)
        run.assert_called_once_with(force=True)

    def test_dispatches_repository_pull_with_delete(self) -> None:
        with patch.object(RepositoryPullCommand, "run", return_value=0) as run:
            result = main(["cflsync", "pull", "-d"])

        self.assertEqual(result, 0)
        run.assert_called_once_with(force=False, delete=True)

    def test_dispatches_repository_status(self) -> None:
        with patch.object(RepositoryStatusCommand, "run", return_value=0) as run:
            result = main(["cflsync", "status"])

        self.assertEqual(result, 0)
        run.assert_called_once_with()


# vim: set ts=4 sw=4 et tw=132:
