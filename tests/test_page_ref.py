# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for resolving page command references."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from cflsync import APIError, PageRef, PageRefError, SyncError
from tests.support import FakeConfluence, example_page_state, temporary_workarea


class FakeAPI:

    def __init__(
            self,
            page_ids: Sequence[str] = (),
            pages: Sequence[SimpleNamespace] = (),
            ancestors: Mapping[str, list[SimpleNamespace]] | None = None) -> None:
        self.page_ids = list(page_ids)
        self.pages = list(pages)
        self.ancestors = dict(ancestors or {})
        self.get_page_calls: list[str] = []
        self.find_pages_by_title_calls: list[str] = []

    def get_page(self, page_id: str) -> SimpleNamespace:
        self.get_page_calls.append(page_id)
        return SimpleNamespace(id=self.page_ids.pop(0))

    def find_pages_by_title(self, title: str) -> list[SimpleNamespace]:
        self.find_pages_by_title_calls.append(title)
        return self.pages

    def page_ancestors(self, page_id: str) -> list[SimpleNamespace]:
        return self.ancestors.get(page_id, [])


class TestPageRefPaths(unittest.TestCase):

    def test_rejects_an_unmanaged_or_outside_path_without_an_api_request(self) -> None:
        with temporary_workarea() as workarea:
            unmanaged_file = workarea.root_dir / "notes.md"
            unmanaged_file.touch()
            api = FakeAPI()

            with self.assertRaises(PageRefError):
                PageRef.resolve(unmanaged_file, workarea, api)

            with TemporaryDirectory(prefix="cflsync-page-ref-") as temporary_dir:
                outside_file = Path(temporary_dir) / "content.md"
                outside_file.touch()
                with self.assertRaises(PageRefError):
                    PageRef.resolve(outside_file, workarea, api)

            self.assertEqual(api.get_page_calls, [])
            self.assertEqual(api.find_pages_by_title_calls, [])


class TestPageRefScope(unittest.TestCase):
    """Resolution against a remote tree anchored at root page 300.

    Space home 100 contains folder 200, which contains the root page 300. Below the root are page 400 with child 500,
    and folder 600 with page 700. Page 800 is outside the tree, and pages 400 and 800 share a title.
    """

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Space home")
        self.site.add_folder("200", "Folder above the root", parent_id="100")
        self.site.add_page("300", "Root", parent_id="200")
        self.site.add_page("400", "Shared title", parent_id="300")
        self.site.add_page("500", "Child", parent_id="400")
        self.site.add_folder("600", "Folder in the tree", parent_id="300")
        self.site.add_page("700", "Below a folder", parent_id="600")
        self.site.add_page("800", "Shared title", parent_id="100")
        self.site.add_page("900", "Outside", parent_id="100")

    def _resolve(self, workarea, value):
        self.site.requests.clear()
        return PageRef.resolve(value, workarea, self.site.client(), cwd=workarea.root_dir).page_id

    def test_lists_ids_and_paths_of_an_ambiguous_cached_title(self) -> None:
        with temporary_workarea(root_page_id="300") as workarea:
            for page_id, directory in [("400", "First_400"), ("500", "Second_500")]:
                state = example_page_state(page_id, title="Duplicate", directory=directory)
                state.save(workarea.cache_path(state.page.id))

            with self.assertRaisesRegex(PageRefError,
                                        r"multiple pages match cached title 'Duplicate': 400 \(First_400\), 500 \(Second_500\)"):
                self._resolve(workarea, "Duplicate")


class TestCopySourceResolution(unittest.TestCase):

    def setUp(self):
        self.site = FakeConfluence()
        self.site.add_page("100", "Root")
        self.site.add_page("200", "Shared", parent_id="100")
        self.site.add_page("900", "Shared", space_id="other")

    def _resolve(self, workarea, value):
        return PageRef.resolve_copy_source(value, workarea, self.site.client(), cwd=workarea.root_dir).page_id

    def _cache(self, workarea, page_id, title, parent_id=None, directory=None):
        state = example_page_state(page_id, title=title, parent_id=parent_id, directory=directory)
        state.save(workarea.cache_path(page_id))
        path = workarea.page_directory(state, must_exist=False)
        path.mkdir(parents=True, exist_ok=True)
        (path / "content.md").touch()
        return path

    def test_cached_identity_and_all_local_forms_win_without_remote_lookup(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._cache(workarea, "100", "Root")
            path = self._cache(workarea, "200", "Shared", "100", "300_200")
            self.site.content["200"]["title"] = "Remotely renamed"
            self.site.add_page("800", "Shared", parent_id="100")
            for ref in ["200", "Shared", path, path / "content.md", "Root_100/300_200"]:
                with self.subTest(ref=ref):
                    self.assertEqual(self._resolve(workarea, ref), "200")

            self.assertEqual(self.site.requests, [])

    def test_unique_external_id_or_title_resolves_only_for_copy(self) -> None:
        self.site.content["900"]["title"] = "External"
        with temporary_workarea(root_page_id="100") as workarea:
            for ref in ["900", "External"]:
                with self.subTest(ref=ref):
                    self.assertEqual(self._resolve(workarea, ref), "900")
                    with self.assertRaises(PageRefError):
                        PageRef.resolve(ref, workarea, self.site.client(), cwd=workarea.root_dir)

    def test_remote_ambiguity_in_either_scope_fails(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self.site.add_page("300", "Shared", parent_id="100")
            with self.assertRaisesRegex(PageRefError, "200.*300"):
                self._resolve(workarea, "Shared")

            del self.site.content["200"]
            del self.site.content["300"]
            self.site.add_page("800", "Shared", space_id="third")
            with self.assertRaisesRegex(PageRefError, "900.*800"):
                self._resolve(workarea, "Shared")

    def test_folder_ancestry_permission_and_missing_root_are_not_no_match(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self.site.add_folder("600", "Folder", parent_id="100")
            self.site.add_page("700", "Shared", parent_id="600")
            with self.assertRaisesRegex(SyncError, "below folder"):
                self._resolve(workarea, "Shared")

            self.site.fail("GET", "/wiki/api/v2/pages", 403)
            with self.assertRaises(APIError) as error:
                self._resolve(workarea, "Shared")

            self.assertEqual(error.exception.status, 403)
            del self.site.content["100"]
            with self.assertRaisesRegex(SyncError, "root page.*no longer exists"):
                self._resolve(workarea, "900")

    def test_missing_id_title_and_cross_site_url_never_route_to_another_site(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            for value in ["999", "Missing", "https://other.atlassian.net/wiki/pages/900"]:
                with self.subTest(value=value):
                    with self.assertRaises(SyncError):
                        self._resolve(workarea, value)

            self.assertTrue(all(request.path.startswith("/wiki/api/v2/") for request in self.site.requests))


# vim: set ts=4 sw=4 et tw=132:
