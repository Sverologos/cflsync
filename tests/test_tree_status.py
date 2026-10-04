# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tree-wide local and remote page status classification."""

import unittest

from cflsync import (
    PageChangeDetector, PageMetadata, PageState, PageStatus, PageStatusState, PandocRunner, RemoteContentRef, SyncError, TreeStatus)
from tests.support import FakeConfluence, temporary_workarea

MARKDOWN = "# Page\n\nContents\n"


class TestTreeStatus(unittest.TestCase):

    def setUp(self) -> None:
        self.detector = PageChangeDetector(PandocRunner())

    def _cache_page(self, workarea, page_id, title, parent_id, version=1, markdown=MARKDOWN, create=True):
        directory = f"{title}_{page_id}"
        state = PageState(PageMetadata(page_id, title, parent_id, directory, version, self.detector.content_hash(MARKDOWN)), {})
        state.save(workarea.cache_path(page_id))
        if create:
            target = workarea.page_directory(state, must_exist=False)
            target.mkdir(parents=True)
            (target / "content.md").write_text(markdown, encoding="utf-8")

        return state

    @staticmethod
    def _references():
        return [
            RemoteContentRef("100", "page", "Root"),
            RemoteContentRef("200", "page", "Absent local", "100"),
            RemoteContentRef("300", "page", "Remote changed", "100"),
            RemoteContentRef("400", "page", "Local changed", "100"),
            RemoteContentRef("500", "page", "Conflict", "100")]

    @staticmethod
    def _site():
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_page("200", "Absent local", "100")
        site.add_page("300", "Remote changed", "100", version=2)
        site.add_page("400", "Local changed", "100")
        site.add_page("500", "Conflict", "100", version=2)
        return site

    def test_distinguishes_absent_remote_pages_by_their_local_changes(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            states = [
                self._cache_page(workarea, "100", "Root", None),
                self._cache_page(workarea, "600", "Unchanged", "100"),
                self._cache_page(workarea, "700", "Edited", "100", markdown="# Page\n\nEdited\n"),
                self._cache_page(workarea, "800", "Missing", "100", create=False)]
            status = TreeStatus.from_pages(workarea, self._site().client(), self._references()[:1], states, self.detector)

            self.assertEqual(
                [(page.id, page.status) for page in status.pages], [
                    ("100", PageStatusState.UNCHANGED), ("600", PageStatusState.ABSENT_REMOTE),
                    ("700", PageStatusState.CONFLICT_ABSENT_REMOTE), ("800", PageStatusState.ABSENT_REMOTE)])

    def test_classifies_a_page_that_disappears_during_comparison_by_its_local_changes(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            states = [
                self._cache_page(workarea, "100", "Root", None),
                self._cache_page(workarea, "400", "Local changed", "100", markdown="# Page\n\nEdited\n")]
            site = self._site()
            del site.content["400"]

            status = TreeStatus.from_pages(
                workarea, site.client(), [self._references()[0], self._references()[3]], states, self.detector)

            self.assertEqual(status.pages[1].status, PageStatusState.CONFLICT_ABSENT_REMOTE)
            self.assertIsNone(status.pages[1].remote)

    def test_marks_a_cached_page_without_its_directory_absent_local(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            states = [
                self._cache_page(workarea, "100", "Root", None),
                self._cache_page(workarea, "200", "Absent local", "100", create=False)]

            status = TreeStatus.from_pages(workarea, self._site().client(), self._references()[:2], states, self.detector)

            self.assertEqual(
                [(page.id, page.status) for page in status.pages], [
                    ("100", PageStatusState.UNCHANGED), ("200", PageStatusState.ABSENT_LOCAL)])

    def test_rejects_duplicate_page_ids(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            references = [RemoteContentRef("100", "page", "Root"), RemoteContentRef("100", "page", "Root")]

            with self.assertRaisesRegex(SyncError, "remote page list contains page '100' more than once"):
                TreeStatus.from_pages(workarea, self._site().client(), references, [], self.detector)

    def test_rejects_a_page_hierarchy_cycle(self) -> None:
        first = PageStatus(PageStatusState.ABSENT_LOCAL, RemoteContentRef("100", "page", "First", "200"), None)
        second = PageStatus(PageStatusState.ABSENT_LOCAL, RemoteContentRef("200", "page", "Second", "100"), None)

        with self.assertRaisesRegex(SyncError, "page hierarchy contains a cycle"):
            TreeStatus([first, second])


# vim: set ts=4 sw=4 et tw=132:
