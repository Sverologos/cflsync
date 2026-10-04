# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for atomic page-state persistence."""

import unittest
from unittest.mock import patch

from cflsync import StateError
from tests.support import example_page_state, temporary_workarea


class TestPageStateSave(unittest.TestCase):

    def test_failed_temporary_state_write_removes_temporary_file(self) -> None:
        with temporary_workarea() as workarea:
            state = example_page_state()
            path = workarea.cache_path(state.page.id)

            with patch("cflsync.workarea.os.fsync", side_effect=OSError("injected failure")):
                with self.assertRaisesRegex(StateError, "cannot write"):
                    state.save(path)

            self.assertFalse(path.exists())
            self.assertEqual(list(workarea.cache_dir.glob(".*.tmp")), [])


# vim: set ts=4 sw=4 et tw=132:
