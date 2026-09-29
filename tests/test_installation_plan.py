# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Ancestor installation planning and execution."""

from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import unittest

from cflsync import PageMetadata, PageState, SyncError
from cflsync.sync import InstallationPlan, PlannedPage
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

    def test_plans_uncached_ancestors_top_down_without_changing_the_workarea(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            api = self._api()

            plan = InstallationPlan.for_ancestors(workarea, api, "300")

            self.assertEqual(
                [(item.page.id, item.directory, item.restore) for item in plan.pages], [
                    ("100", "Root", False), ("200", "Root/Child", False)])
            self.assertEqual(api.ancestor_calls, ["300"])
            self.assertEqual(api.page_calls, ["100", "200"])
            self.assertEqual(list(workarea.cache_dir.iterdir()), [])
            self.assertFalse((workarea.root_dir / "Root").exists())

    def test_restores_a_cached_missing_directory_at_its_cached_location(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            root = state("100", "Root", None, "Root")
            child = state("200", "Old child", "100", "Old child")
            root.save(workarea.cache_path(root.page.id))
            child.save(workarea.cache_path(child.page.id))
            (workarea.root_dir / "Root").mkdir()
            api = self._api()
            api.pages["200"] = remote_page("200", "Renamed child", "100")

            plan = InstallationPlan.for_ancestors(workarea, api, "300")

            self.assertEqual(
                [(item.page.id, item.directory, item.restore) for item in plan.pages], [("200", "Root/Old child", True)])

    def test_unmanaged_clash_aborts_before_any_installation(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            (workarea.root_dir / "Root").mkdir()
            api = self._api()

            with self.assertRaisesRegex(SyncError, "already exists"):
                InstallationPlan.for_ancestors(workarea, api, "300")

            self.assertEqual(list(workarea.cache_dir.iterdir()), [])
            self.assertEqual(api.page_calls, ["100"])

    def test_parent_change_during_planning_requires_a_retry(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            api = self._api()
            api.pages["200"] = remote_page("200", "Child", "999")

            with self.assertRaisesRegex(SyncError, "changed while planning.*retry"):
                InstallationPlan.for_ancestors(workarea, api, "300")

            self.assertEqual(api.page_calls, ["100", "200"])
            self.assertEqual(list(workarea.cache_dir.iterdir()), [])

    def test_executor_reports_completed_pages_after_a_partial_failure(self) -> None:
        pages = [
            PlannedPage(remote_page("100", "Root", None), None, "Root", "Root", False),
            PlannedPage(remote_page("200", "Child", "100"), "100", "Child", "Root/Child", False), ]
        plan = InstallationPlan(pages)
        installed = []

        def install(item):
            installed.append(item.page.id)
            if item.page.id == "200":
                raise SyncError("injected failure")

        output = StringIO()
        with redirect_stdout(output):
            with self.assertRaisesRegex(SyncError, r"injected failure; pages pulled before the failure: 'Root' \(100\)"):
                plan.install(install)

        self.assertEqual(installed, ["100", "200"])
        self.assertEqual(output.getvalue(), "Pulled parent 'Root' (100) to Root\n")
