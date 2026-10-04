# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Ancestor installation planning and execution."""

from types import SimpleNamespace
import unittest

from cflsync import PageMetadata, PageState, SyncError
from cflsync.sync import InstallationPlan
from tests.support import temporary_workarea


class PlannerAPI:
    """Small remote tree used to assert the planner's requests and decisions."""

    def __init__(self, pages, ancestors) -> None:
        self.pages = dict(pages)
        self.ancestors = dict(ancestors)
        self.ancestor_calls = []
        self.page_calls = []

    def page_ancestors(self, page_id):
        self.ancestor_calls.append(page_id)
        return self.ancestors[page_id]

    def get_page(self, page_id):
        self.page_calls.append(page_id)
        return self.pages[page_id]


def remote_page(page_id, title, parent_id):
    return SimpleNamespace(id=page_id, title=title, parent_id=parent_id)


def ancestor(page_id, content_type="page"):
    return SimpleNamespace(id=page_id, type=content_type)


def state(page_id, title, parent_id, directory):
    return PageState(PageMetadata(page_id, title, parent_id, directory, 1, "0" * 64), {})


class TestInstallationPlan(unittest.TestCase):

    def _api(self):
        pages = {
            "100": remote_page("100", "Root", None),
            "200": remote_page("200", "Child", "100"),
            "300": remote_page("300", "Leaf", "200"), }
        ancestors = {"300": [ancestor("100"), ancestor("200")]}
        return PlannerAPI(pages, ancestors)

    def test_parent_change_during_planning_requires_a_retry(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            api = self._api()
            api.pages["200"] = remote_page("200", "Child", "999")

            with self.assertRaisesRegex(SyncError, "changed while planning.*retry"):
                InstallationPlan.for_ancestors(workarea, api, "300")

            self.assertEqual(api.page_calls, ["100", "200"])
            self.assertEqual(list(workarea.cache_dir.iterdir()), [])
