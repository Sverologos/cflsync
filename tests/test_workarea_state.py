# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for state-backed workarea operations."""

import errno
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cflsync import PageState, StateError, SyncError, Workarea
from cflsync.workarea import filesystem_error_message
from tests.support import FakePageIndex, example_page_state, temporary_workarea


class TestWorkareaPageStates(unittest.TestCase):

    def test_enumerates_all_page_state_paths_by_numeric_page_id(self) -> None:
        with temporary_workarea() as workarea:
            first = example_page_state("9", "First page")
            second = example_page_state("10", "Second page")
            second.save(workarea.cache_path(second.page.id))
            first.save(workarea.cache_path(first.page.id))

            paths = workarea.page_state_paths()

            self.assertEqual(list(paths), ["9", "10"])
            self.assertEqual({page_id: PageState.load(path) for page_id, path in paths.items()}, {"9": first, "10": second})

    def test_rejects_a_malformed_cache_entry(self) -> None:
        with temporary_workarea() as workarea:
            (workarea.cache_dir / "not-a-page.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(StateError):
                workarea.page_state_paths()


class TestWorkareaInitialization(unittest.TestCase):

    def test_failed_profile_write_leaves_no_partial_workarea(self) -> None:
        original_open = Path.open

        def fail_profile_open(path, *args, **kwargs):
            if path.name == "profile":
                raise OSError("injected profile write failure")

            return original_open(path, *args, **kwargs)

        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)
            with patch.object(Path, "open", fail_profile_open):
                with self.assertRaisesRegex(Workarea.Error, "cannot initialise"):
                    Workarea.init(root, "123456")

            self.assertFalse((root / ".cflsync").exists())
            self.assertFalse(any(path.name.startswith(".cflsync-init-") for path in root.iterdir()))

    def test_records_the_root_page_and_profile(self) -> None:
        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)

            Workarea.init(root, "789012", "work")

            workarea = Workarea.find(root)
            self.assertEqual((workarea.root_page_id, workarea.profile), ("789012", "work"))
            self.assertEqual((root / ".cflsync" / "root").read_text(encoding="utf-8"), "789012\n")
            self.assertEqual((root / ".cflsync" / "version").read_text(encoding="utf-8"), "3\n")
            self.assertEqual(workarea.version, 3)
            self.assertEqual(list(workarea.cache_dir.iterdir()), [])

    def test_failed_root_write_leaves_no_partial_workarea(self) -> None:
        original_open = Path.open

        def fail_root_open(path, *args, **kwargs):
            if path.name == "root":
                raise OSError("injected root write failure")

            return original_open(path, *args, **kwargs)

        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)
            with patch.object(Path, "open", fail_root_open):
                with self.assertRaisesRegex(Workarea.Error, "cannot initialise"):
                    Workarea.init(root, "123456")

            self.assertEqual(list(root.iterdir()), [])

    def test_rejects_a_non_numeric_root_page_id(self) -> None:
        with TemporaryDirectory(prefix="cflsync-init-") as temporary_dir:
            root = Path(temporary_dir)
            for root_page_id in ["", "12a", "１２"]:
                with self.subTest(root_page_id=root_page_id):
                    with self.assertRaisesRegex(Workarea.Error, "root page ID must be numeric"):
                        Workarea.init(root, root_page_id)

            self.assertEqual(list(root.iterdir()), [])

    def test_refuses_to_initialise_below_any_existing_workarea(self) -> None:
        with temporary_workarea() as workarea:
            (workarea.cflsync_dir / "root").unlink()
            nested = workarea.root_dir / "nested"
            nested.mkdir()

            with self.assertRaisesRegex(Workarea.Error, "already part of a cflsync workarea"):
                Workarea.init(nested, "789012")

            self.assertFalse((nested / ".cflsync").exists())

    def test_re_anchors_an_empty_workarea_of_any_version_at_its_root(self) -> None:
        for version in [1, 2, 3]:
            with self.subTest(version=version):
                with temporary_workarea(profile="old") as workarea:
                    # Version 1 has neither a root nor a version file; version 2, written by cflsync 0.4, has no
                    # version file.
                    if version < 3:
                        (workarea.cflsync_dir / "version").unlink()
                    if version == 1:
                        (workarea.cflsync_dir / "root").unlink()

                    reanchored = Workarea.init(workarea.root_dir, "789012", "new")

                    self.assertEqual(reanchored.root_dir, workarea.root_dir)
                    self.assertEqual((reanchored.root_page_id, reanchored.profile), ("789012", "new"))
                    self.assertEqual(reanchored.version, 3)
                    self.assertEqual(
                        sorted(path.name for path in workarea.cflsync_dir.iterdir()), ["cache", "profile", "root", "version"])
                    self.assertEqual(Workarea.find(workarea.root_dir).root_dir, workarea.root_dir)

    def test_refuses_to_re_anchor_a_workarea_with_cached_pages(self) -> None:
        with temporary_workarea() as workarea:
            example_page_state().save(workarea.cache_path("123456"))

            with self.assertRaisesRegex(Workarea.Error, "cached pages and cannot be re-anchored"):
                Workarea.init(workarea.root_dir, "789012")

            self.assertEqual(workarea.root_page_id, "123456")

    def test_a_failed_file_replacement_leaves_the_previous_anchor(self) -> None:
        with temporary_workarea() as workarea:
            with patch("cflsync.workarea.os.replace", side_effect=OSError("injected failure")):
                with self.assertRaisesRegex(Workarea.Error, "cannot re-anchor workarea"):
                    Workarea.init(workarea.root_dir, "789012", "new")

            self.assertEqual((workarea.root_page_id, workarea.profile), ("123456", "default"))
            self.assertEqual(sorted(path.name for path in workarea.cflsync_dir.iterdir()), ["cache", "profile", "root", "version"])


class TestWorkareaFormat(unittest.TestCase):

    def test_refuses_a_version_1_workarea_without_a_root_page(self) -> None:
        with temporary_workarea() as workarea:
            (workarea.cflsync_dir / "root").unlink()

            with self.assertRaisesRegex(Workarea.Error, "is a version-1 cflsync workarea.*'cflsync init ROOT_PAGE_REF'"):
                Workarea.find(workarea.root_dir)

    def test_reports_a_missing_root_before_a_missing_version(self) -> None:
        with temporary_workarea() as workarea:
            (workarea.cflsync_dir / "root").unlink()
            (workarea.cflsync_dir / "version").unlink()

            with self.assertRaisesRegex(Workarea.Error, "is a version-1 cflsync workarea"):
                Workarea.find(workarea.root_dir)

    def test_refuses_a_workarea_created_by_cflsync_0_4(self) -> None:
        with temporary_workarea() as workarea:
            (workarea.cflsync_dir / "version").unlink()

            with self.assertRaisesRegex(Workarea.Error,
                                        "created by cflsync 0.4 or earlier.*push its local changes.*'cflsync init ROOT_PAGE_REF'"):
                Workarea.find(workarea.root_dir)

    def test_refuses_an_unsupported_workarea_version(self) -> None:
        cases = [
            ("2\n", "workarea version 2, which this version of cflsync does not support; push its local changes"),
            ("4\n", "workarea version 4 and was created by a newer version of cflsync"),
            ("abc\n", "must contain one workarea version number"), ("", "must contain one workarea version number"),
            ("3\n3\n", "must contain one workarea version number"), ]
        for content, message in cases:
            with self.subTest(content=content):
                with temporary_workarea() as workarea:
                    (workarea.cflsync_dir / "version").write_text(content, encoding="utf-8")

                    with self.assertRaisesRegex(Workarea.Error, message):
                        Workarea.find(workarea.root_dir)

    def test_refuses_an_invalid_root_file(self) -> None:
        for content in ["", "\n", "abc\n", "12 34\n", "12\n34\n"]:
            with self.subTest(content=content):
                with temporary_workarea() as workarea:
                    (workarea.cflsync_dir / "root").write_text(content, encoding="utf-8")

                    with self.assertRaisesRegex(Workarea.Error, "must contain one numeric page ID"):
                        Workarea.find(workarea.root_dir)

    def test_finds_the_workarea_from_a_nested_directory(self) -> None:
        with temporary_workarea() as workarea:
            nested = workarea.root_dir / "Page" / "Child"
            nested.mkdir(parents=True)

            self.assertEqual(Workarea.find(nested).root_dir, workarea.root_dir)


class TestWorkareaPageDirectory(unittest.TestCase):

    def test_returns_an_existing_managed_page_directory(self) -> None:
        with temporary_workarea() as workarea:
            state = example_page_state()
            page_directory = workarea.root_dir / state.page.directory
            page_directory.mkdir()
            (page_directory / "content.md").write_text("# Example page\n", encoding="utf-8")

            self.assertEqual(workarea.page_directory(state), page_directory)

    def test_rejects_a_missing_page_directory_or_page_file(self) -> None:
        with temporary_workarea() as workarea:
            state = example_page_state()

            with self.assertRaises(Workarea.Error):
                workarea.page_directory(state)

            page_directory = workarea.root_dir / state.page.directory
            page_directory.mkdir()
            with self.assertRaises(Workarea.Error):
                workarea.page_directory(state)


class TestWorkareaPageTree(unittest.TestCase):

    def test_refuses_a_cached_directory_that_does_not_end_in_its_page_id(self) -> None:
        for directory in ["Child", "Child_234567", "Child_1234567"]:
            with self.subTest(directory=directory):
                with temporary_workarea() as workarea:
                    for state in [example_page_state(), example_page_state("234567", "Other", parent_id="123456"),
                                  example_page_state("345678", "Child", directory, "123456")]:
                        state.save(workarea.cache_path(state.page.id))

                    with self.assertRaisesRegex(StateError,
                                                f"cached page '345678' has directory '{directory}', which does not end in its "
                                                "page ID '_345678'"):
                        workarea.page_tree()


class TestWorkareaPageLocation(unittest.TestCase):

    def setUp(self) -> None:
        self.index = FakePageIndex(
            {
                "100": ("Root", None),
                "200": ("Child", "100"),
                "300": ("Grandchild", "200"),
                "400": ("Leaf", "300")})

    def _cache(self, workarea, page_id, title, parent_id, directory=None):
        example_page_state(page_id, title, directory, parent_id).save(workarea.cache_path(page_id))

    def test_returns_the_cached_directory_of_a_cached_page(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._cache(workarea, "100", "Root", None)
            self._cache(workarea, "200", "Child", "100")

            self.assertEqual(workarea.page_location("200", self.index), "Root_100/Child_200")
            self.assertEqual(self.index.lookups, [])

    def test_places_an_uncached_page_below_its_cached_parent(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._cache(workarea, "100", "Root", None)
            self._cache(workarea, "200", "Child", "100")

            self.assertEqual(workarea.page_location("300", self.index), "Root_100/Child_200/Grandchild_300")

    def test_places_an_uncached_chain_below_its_nearest_cached_ancestor(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._cache(workarea, "100", "Root", None)

            self.assertEqual(workarea.page_location("400", self.index), "Root_100/Child_200/Grandchild_300/Leaf_400")

    def test_names_an_uncached_root_after_its_title_and_id(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self.assertEqual(workarea.page_location("100", self.index), "Root_100")
            self.assertEqual(workarea.page_location("300", self.index), "Root_100/Child_200/Grandchild_300")

    def test_keeps_the_cached_directory_after_a_remote_rename_or_move(self) -> None:
        index = FakePageIndex({"100": ("Root", None), "200": ("Renamed", "300"), "300": ("Other", "100"), "400": ("Leaf", "200")})
        with temporary_workarea(root_page_id="100") as workarea:
            self._cache(workarea, "100", "Root", None)
            self._cache(workarea, "200", "Child", "100")

            self.assertEqual(workarea.page_location("200", index), "Root_100/Child_200")
            self.assertEqual(workarea.page_location("400", index), "Root_100/Child_200/Leaf_400")

    def test_refuses_a_page_outside_the_tree(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._cache(workarea, "100", "Root", None)

            with self.assertRaisesRegex(SyncError, "page '900' is not in this workarea's tree"):
                workarea.page_location("900", self.index)

    def test_refuses_a_cycle_of_remote_parents(self) -> None:
        index = FakePageIndex({"100": ("Root", None), "200": ("A", "300"), "300": ("B", "200")})
        with temporary_workarea(root_page_id="100") as workarea:
            with self.assertRaisesRegex(SyncError, "form a cycle"):
                workarea.page_location("200", index)


class TestWorkareaSafePaths(unittest.TestCase):

    def test_rejects_a_traversal_page_directory(self) -> None:
        with temporary_workarea() as workarea:
            with self.assertRaises(Workarea.Error):
                workarea.page_directory_path("../outside")

    def test_rejects_a_missing_page_state(self) -> None:
        with temporary_workarea() as workarea:
            with self.assertRaises(StateError):
                PageState.load(workarea.cache_path("123456"))

    def test_enumerates_duplicate_page_directory_assignments(self) -> None:
        with temporary_workarea() as workarea:
            # Enumeration does not validate directories, so the second page's directory need not end in its ID.
            first = example_page_state("123456", directory="Shared page_123456")
            second = example_page_state("234567", directory="Shared page_123456")
            first.save(workarea.cache_path(first.page.id))
            second.save(workarea.cache_path(second.page.id))

            self.assertEqual(list(workarea.page_state_paths()), ["123456", "234567"])

    def test_rejects_an_existing_title_directory_before_mutation(self) -> None:
        with temporary_workarea() as workarea:
            state = example_page_state()
            target = workarea.root_dir / state.page.directory
            target.mkdir()
            before = sorted(workarea.root_dir.iterdir())

            with self.assertRaises(Workarea.Error):
                workarea.page_directory_target(state.page.id, state.page.parent_id, state.page.directory)

            self.assertEqual(sorted(workarea.root_dir.iterdir()), before)

    def test_rejects_an_existing_directory_that_differs_only_in_unicode_normalization(self) -> None:
        with temporary_workarea() as workarea:
            (workarea.root_dir / "Cafe\u0301_123456").mkdir()

            with self.assertRaisesRegex(Workarea.Error, "already exists"):
                workarea.page_directory_target("123456", None, workarea.page_directory_name("Café", "123456"))

    def test_rejects_an_existing_title_directory_with_different_case(self) -> None:
        with temporary_workarea() as workarea:
            state = example_page_state()
            target = workarea.root_dir / "example page_123456"
            target.mkdir()

            with self.assertRaisesRegex(Workarea.Error, "already exists"):
                workarea.page_directory_target(state.page.id, state.page.parent_id, state.page.directory)


class TestWorkareaMaterialization(unittest.TestCase):

    def test_derives_safe_deterministic_page_directory_names(self) -> None:
        with temporary_workarea() as workarea:
            self.assertEqual(workarea.page_directory_name("Example page", "123"), "Example page_123")
            self.assertEqual(workarea.page_directory_name("Example/page", "123"), "Example%2Fpage_123")
            self.assertEqual(workarea.page_directory_name(".", "123"), "%2E_123")
            self.assertEqual(workarea.page_directory_name("CON", "123"), "%43ON_123")
            self.assertEqual(workarea.page_directory_name("lpt9", "123"), "%6Cpt9_123")
            self.assertEqual(workarea.page_directory_name("Example ", "123"), "Example%20_123")
            self.assertEqual(
                workarea.page_directory_name("Example/page", "123"), workarea.page_directory_name("Example/page", "123"))

    def test_appends_the_suffix_to_a_title_that_already_ends_in_digits(self) -> None:
        with temporary_workarea() as workarea:
            self.assertEqual(workarea.page_directory_name("Beta_300", "400"), "Beta_300_400")

    def test_keeps_a_13_digit_suffix_intact_after_a_long_title(self) -> None:
        with temporary_workarea() as workarea:
            name = workarea.page_directory_name("Long title " * 10, "1234567890123")

            self.assertLessEqual(len(name), 64)
            self.assertTrue(name.endswith("_1234567890123"))
            self.assertEqual(name, ("Long title " * 10)[:50] + "_1234567890123")

    def test_names_of_titles_differing_only_in_case_differ_by_page_id(self) -> None:
        with temporary_workarea() as workarea:
            first = workarea.page_directory_name("Release notes", "100")
            second = workarea.page_directory_name("release notes", "200")

            self.assertNotEqual(first.casefold(), second.casefold())

    def test_recovers_the_page_id_from_a_directory_name(self) -> None:
        with temporary_workarea() as workarea:
            cases = [
                ("Beta_300_400", "400"), ("Release notes_123457", "123457"), ("Release notes", None), ("x_", None), ("_123", "123"),
            ]
            for name, expected in cases:
                with self.subTest(name=name):
                    self.assertEqual(workarea.page_id_from_directory_name(name), expected)

    def test_keeps_printable_unicode_characters_and_escapes_others(self) -> None:
        with temporary_workarea() as workarea:
            cases = [
                ("Café — Überblick", "Café — Überblick"), ("日本語のページ", "日本語のページ"), ("IT Standard · Loki", "IT Standard · Loki"),
                ("zero\u200bwidth", "zero%E2%80%8Bwidth"), ("no\u00a0break", "no%C2%A0break"), ("Cafe\u0301", "Café"),
                ("Sven's Test Space", "Sven%27s Test Space"), ]
            for title, expected in cases:
                with self.subTest(title=title):
                    self.assertEqual(workarea.page_directory_name(title, "123"), expected + "_123")

    def test_caps_names_at_64_characters_between_characters(self) -> None:
        with temporary_workarea() as workarea:
            # The suffix "_1" leaves 62 characters for the title.
            cases = [
                ("x" * 62, "x" * 62), ("x" * 63, "x" * 62), ("é" * 70, "é" * 62), ("x" * 60 + "/tail", "x" * 60),
                ("x" * 61 + " tail", "x" * 61), ("x" * 58 + "—tail", "x" * 58 + "—tai"), ("_" + "x" * 70, "%5F" + "x" * 59), ]
            for title, expected in cases:
                with self.subTest(title=title):
                    self.assertEqual(workarea.page_directory_name(title, "1"), expected + "_1")

    def test_keeps_the_suffix_within_the_limit(self) -> None:
        with temporary_workarea() as workarea:
            self.assertEqual(workarea.page_directory_name("Release notes", "1843628507"), "Release notes_1843628507")
            self.assertEqual(workarea.page_directory_name("x" * 70, "1843628507"), "x" * 53 + "_1843628507")
            self.assertEqual(workarea.page_directory_name("x" * 59 + " tail", "123"), "x" * 59 + "_123")

    def test_keeps_names_within_255_utf8_bytes(self) -> None:
        with temporary_workarea() as workarea:
            name = workarea.page_directory_name("😀" * 70, "1")

            self.assertEqual(name, "😀" * 62 + "_1")
            self.assertLessEqual(len(name.encode("utf-8")), 255)

    def test_escapes_a_leading_underscore_and_never_names_the_content_file(self) -> None:
        with temporary_workarea() as workarea:
            cases = [
                ("_attachments", "%5Fattachments"), ("_Draft notes", "%5FDraft notes"), ("__init__", "%5F_init__"),
                ("snake_case_title", "snake_case_title"), ("%5Fliteral", "%255Fliteral"), ("content.md", "content%2Emd"), ]
            for title, expected in cases:
                with self.subTest(title=title):
                    self.assertEqual(workarea.page_directory_name(title, "123"), expected + "_123")

    @unittest.skipIf(os.name == "nt", "the error Windows reports for an over-long name component depends on its configuration")
    def test_reports_a_name_that_the_filesystem_rejects_as_too_long(self) -> None:
        with temporary_workarea() as workarea:
            directory = "x" * 300
            staging = workarea.stage_page(directory, "# Example\n", {})

            # Which operation meets the limit first depends on the system: on Linux, checking for an existing target
            # raises the OSError itself; on macOS, the check passes and installing the directory fails.
            with self.assertRaises((OSError, Workarea.Error)) as context:
                workarea.install_page(staging, directory)

            self.assertRegex(filesystem_error_message(context.exception), r"path is too long for this system \(\d+ characters\)")
            self.assertTrue(staging.is_dir())

    def test_writes_page_markdown_with_lf_newlines(self) -> None:
        with temporary_workarea() as workarea:
            staging = workarea.stage_page("Example page", "# Example\n\nText\n", {})

            self.assertEqual((staging / "content.md").read_bytes(), b"# Example\n\nText\n")

    def test_windows_rejects_renaming_the_current_page_directory(self) -> None:
        with temporary_workarea() as workarea:
            source = workarea.root_dir / "Example page"
            source.mkdir()
            (source / "content.md").write_text("previous\n", encoding="utf-8")
            (source / "_attachments").mkdir()
            staging = workarea.stage_page("Renamed", "replacement\n", {})
            original_cwd = os.getcwd()
            os.chdir(source)
            try:
                with patch("cflsync.workarea._is_windows", return_value=True):
                    with self.assertRaisesRegex(Workarea.Error, "run cflsync from outside"):
                        with workarea.replace_page(staging, "Renamed", source):
                            pass
            finally:
                os.chdir(original_cwd)

            self.assertTrue(source.is_dir())
            self.assertEqual((source / "content.md").read_text(encoding="utf-8"), "previous\n")

    def test_stages_and_installs_one_complete_page(self) -> None:
        with temporary_workarea() as workarea:
            staging = workarea.stage_page("Example page", "# Example\n", {"diagram.png": b"PNG", "report.xlsx": b"XLSX"})

            self.assertEqual((staging / "content.md").read_text(encoding="utf-8"), "# Example\n")
            self.assertEqual((staging / "_attachments" / "diagram.png").read_bytes(), b"PNG")
            self.assertFalse((workarea.root_dir / "Example page").exists())

            target = workarea.install_page(staging, "Example page")

            self.assertEqual(target, workarea.root_dir / "Example page")
            self.assertEqual((target / "_attachments" / "report.xlsx").read_bytes(), b"XLSX")

    def test_rejects_collisions_and_staging_failure_without_target_mutation(self) -> None:
        with temporary_workarea() as workarea:
            target = workarea.root_dir / "Example page"
            target.mkdir()
            (target / "content.md").write_text("previous\n", encoding="utf-8")
            before = (target / "content.md").read_text(encoding="utf-8")
            staging = workarea.stage_page("Example page", "replacement\n", {})

            with self.assertRaises(Workarea.Error):
                workarea.install_page(staging, "Example page")

            self.assertEqual((target / "content.md").read_text(encoding="utf-8"), before)

            with self.assertRaises(Workarea.Error):
                workarea.stage_page("Other page", "content", {"../unsafe": b"x"})

            self.assertFalse((workarea.root_dir / "Other page").exists())

    def test_interrupted_staging_removes_hidden_directory(self) -> None:
        with temporary_workarea() as workarea:
            write_text = Path.write_text

            def interrupt_write(path, text, *args, **kwargs):
                if any(part.startswith(".cflsync-stage-") for part in path.parts):
                    raise KeyboardInterrupt()

                return write_text(path, text, *args, **kwargs)

            with patch.object(Path, "write_text", interrupt_write):
                with self.assertRaises(KeyboardInterrupt):
                    workarea.stage_page("Example page", "# Example\n", {})

            self.assertFalse((workarea.root_dir / "Example page").exists())
            self.assertFalse(any(path.name.startswith(".cflsync-stage-") for path in workarea.root_dir.iterdir()))

    def test_replaces_a_complete_page_directory(self) -> None:
        with temporary_workarea() as workarea:
            target = workarea.root_dir / "Example page"
            target.mkdir()
            (target / "content.md").write_text("previous\n", encoding="utf-8")
            (target / "_attachments").mkdir()
            directory_inode = target.stat().st_ino
            attachment_inode = (target / "_attachments").stat().st_ino
            staging = workarea.stage_page("Example page", "replacement\n", {"new.txt": b"new"})

            workarea.install_page(staging, "Example page", replace=True)

            self.assertEqual((target / "content.md").read_text(encoding="utf-8"), "replacement\n")
            self.assertEqual((target / "_attachments" / "new.txt").read_bytes(), b"new")
            self.assertEqual(target.stat().st_ino, directory_inode)
            self.assertEqual((target / "_attachments").stat().st_ino, attachment_inode)

    def test_repull_preserves_current_directory_and_unmanaged_files(self) -> None:
        for name in ["Example page", "Renamed"]:
            with self.subTest(name=name):
                with temporary_workarea() as workarea:
                    source = workarea.root_dir / "Example page"
                    source.mkdir()
                    (source / "content.md").write_text("previous\n")
                    (source / "notes.txt").write_text("notes\n")
                    attachments = source / "_attachments"
                    attachments.mkdir()
                    (attachments / "old.txt").write_text("old\n")
                    source_inode = source.stat().st_ino
                    attachment_inode = attachments.stat().st_ino
                    notes_inode = (source / "notes.txt").stat().st_ino
                    staging = workarea.stage_page(name, "replacement\n", {"new.txt": b"new"})
                    original_cwd = os.getcwd()
                    os.chdir(source)
                    try:
                        if os.name == "nt" and name != source.name:
                            with self.assertRaisesRegex(Workarea.Error, "run cflsync from outside"):
                                with workarea.replace_page(staging, name, source, ["old.txt", "new.txt"]):
                                    pass

                            self.assertEqual(os.getcwd(), str(source))
                        else:
                            with workarea.replace_page(staging, name, source, ["old.txt", "new.txt"]):
                                self.assertEqual(os.getcwd(), str(workarea.root_dir / name))

                            self.assertEqual(os.getcwd(), str(workarea.root_dir / name))
                    finally:
                        os.chdir(original_cwd)

                    if os.name == "nt" and name != source.name:
                        self.assertEqual((source / "content.md").read_text(), "previous\n")
                        self.assertTrue((source / "_attachments/old.txt").exists())
                        self.assertFalse((source / "_attachments/new.txt").exists())
                        continue

                    target = workarea.root_dir / name
                    self.assertEqual(target.stat().st_ino, source_inode)
                    self.assertEqual((target / "_attachments").stat().st_ino, attachment_inode)
                    self.assertEqual((target / "notes.txt").stat().st_ino, notes_inode)
                    self.assertEqual((target / "content.md").read_text(), "replacement\n")
                    self.assertFalse((target / "_attachments/old.txt").exists())
                    self.assertEqual((target / "_attachments/new.txt").read_bytes(), b"new")

    def test_failed_commit_restores_files_and_directory_name(self) -> None:
        for name in ["Example page", "Renamed"]:
            with self.subTest(name=name):
                with temporary_workarea() as workarea:
                    source = workarea.root_dir / "Example page"
                    source.mkdir()
                    (source / "content.md").write_text("previous\n")
                    (source / "_attachments").mkdir()
                    (source / "_attachments/old.txt").write_bytes(b"old")
                    inode = source.stat().st_ino
                    staging = workarea.stage_page(name, "replacement\n", {"new.txt": b"new"})
                    with self.assertRaisesRegex(RuntimeError, "commit failed"):
                        with workarea.replace_page(staging, name, source, ["old.txt", "new.txt"]):
                            raise RuntimeError("commit failed")

                    self.assertEqual(source.stat().st_ino, inode)
                    self.assertEqual((source / "content.md").read_text(), "previous\n")
                    self.assertEqual((source / "_attachments/old.txt").read_bytes(), b"old")
                    self.assertFalse((source / "_attachments/new.txt").exists())


class WindowsPathLengthError(OSError):
    """An OSError as Windows reports an over-long path, on any platform."""

    winerror = 206


class TestFilesystemErrorMessage(unittest.TestCase):

    def test_names_the_longer_path_of_a_path_length_error(self) -> None:
        error = OSError(errno.ENAMETOOLONG, "File name too long", "short", None, "much/longer/path")

        self.assertEqual(
            filesystem_error_message(error),
            "path is too long for this system (16 characters): 'much/longer/path'; on Windows, enable long path support")

    def test_recognizes_the_windows_path_length_error(self) -> None:
        error = WindowsPathLengthError(errno.ENOENT, "The filename or extension is too long", "C:/workarea/page")

        self.assertIn("path is too long for this system (16 characters)", filesystem_error_message(error))

    def test_describes_a_path_length_error_without_a_path(self) -> None:
        error = OSError(errno.ENAMETOOLONG, "File name too long")

        self.assertEqual(filesystem_error_message(error), f"a path is too long for this system: {error}")

    def test_leaves_other_errors_unchanged(self) -> None:
        for error in [OSError(errno.EACCES, "Permission denied", "page"), UnicodeError("invalid byte")]:
            with self.subTest(error=error):
                self.assertEqual(filesystem_error_message(error), str(error))


class TestWorkareaRelocation(unittest.TestCase):

    def _page_directory(self, workarea, directory):
        path = workarea.root_dir.joinpath(*directory.split("/"))
        path.mkdir(parents=True)
        (path / "content.md").write_text("previous\n", encoding="utf-8")
        (path / "_attachments").mkdir()
        return path

    def test_moves_a_page_directory_with_its_contents(self) -> None:
        with temporary_workarea() as workarea:
            source = self._page_directory(workarea, "Old parent/Page")
            self._page_directory(workarea, "Old parent/Page/Child")
            (source / "notes.txt").write_text("unmanaged\n", encoding="utf-8")
            self._page_directory(workarea, "New parent")

            target = workarea.relocate(source, "New parent/Page")

            self.assertEqual(target, workarea.root_dir / "New parent" / "Page")
            self.assertFalse(source.exists())
            self.assertEqual((target / "notes.txt").read_text(encoding="utf-8"), "unmanaged\n")
            self.assertTrue((target / "Child" / "content.md").is_file())

    def test_relocation_moves_the_directory_back_when_the_block_fails(self) -> None:
        with temporary_workarea() as workarea:
            source = self._page_directory(workarea, "Page")
            (workarea.root_dir / "Parent").mkdir()

            with workarea.relocation(source, "Parent/Page") as target:
                self.assertTrue((target / "content.md").is_file())

            self.assertFalse(source.exists())
            with self.assertRaisesRegex(RuntimeError, "block failed"):
                with workarea.relocation(target, "Page"):
                    raise RuntimeError("block failed")

            self.assertTrue((target / "content.md").is_file())
            self.assertFalse(source.exists())

    def test_moving_to_the_same_directory_changes_nothing(self) -> None:
        with temporary_workarea() as workarea:
            source = self._page_directory(workarea, "Page")

            self.assertEqual(workarea.relocate(source, "Page"), source)
            self.assertTrue((source / "content.md").is_file())

    def test_refuses_a_directory_assigned_to_another_cached_page(self) -> None:
        with temporary_workarea() as workarea:
            self._page_directory(workarea, "Root_123456")
            source = self._page_directory(workarea, "Root_123456/Page_345678")
            for state in [example_page_state(title="Root"), example_page_state("234567", "Target", parent_id="123456")]:
                state.save(workarea.cache_path(state.page.id))

            with self.assertRaisesRegex(Workarea.Error, "'Root_123456/target_234567' is assigned to page '234567'"):
                workarea.relocate(source, "Root_123456/target_234567")

            self.assertTrue(source.is_dir())

    def test_refuses_an_existing_sibling_that_differs_only_in_case(self) -> None:
        with temporary_workarea() as workarea:
            source = self._page_directory(workarea, "Page")
            (workarea.root_dir / "Parent" / "target").mkdir(parents=True)

            with self.assertRaisesRegex(Workarea.Error, "'Parent/Target' already exists"):
                workarea.relocate(source, "Parent/Target")

            self.assertTrue(source.is_dir())

    def test_windows_refuses_to_move_the_current_directory(self) -> None:
        with temporary_workarea() as workarea:
            source = self._page_directory(workarea, "Page")
            original_cwd = os.getcwd()
            os.chdir(source)
            try:
                with patch("cflsync.workarea._is_windows", return_value=True):
                    with self.assertRaisesRegex(Workarea.Error, "run cflsync from outside"):
                        workarea.relocate(source, "Renamed")
            finally:
                os.chdir(original_cwd)

            self.assertTrue(source.is_dir())

    def test_reports_a_rename_that_the_filesystem_rejects_as_too_long(self) -> None:
        with temporary_workarea() as workarea:
            source = self._page_directory(workarea, "Page")
            target = str(workarea.root_dir / "Renamed")
            error = OSError(errno.ENAMETOOLONG, "File name too long", str(source), None, target)

            with patch("cflsync.workarea.os.rename", side_effect=error):
                with self.assertRaisesRegex(Workarea.Error, "cannot move page directory: path is too long for this system"):
                    workarea.relocate(source, "Renamed")


class TestWorkareaNestedPageDirectories(unittest.TestCase):

    def _page_directory(self, workarea, directory):
        path = workarea.root_dir.joinpath(*directory.split("/"))
        path.mkdir(parents=True)
        (path / "content.md").write_text("previous\n", encoding="utf-8")
        (path / "_attachments").mkdir()
        return path

    def test_resolves_a_nested_page_directory(self) -> None:
        with temporary_workarea() as workarea:
            path = self._page_directory(workarea, "Root/Child/Grandchild")

            self.assertEqual(workarea.page_directory_path("Root/Child/Grandchild"), path)

    def test_rejects_malformed_relative_page_directories(self) -> None:
        with temporary_workarea() as workarea:
            for directory in ["/Root", "Root/", "Root//Child", "Root/./Child", "Root/../Child", "../Root", "."]:
                with self.subTest(directory=directory):
                    with self.assertRaisesRegex(Workarea.Error, "relative path of directory names"):
                        workarea.page_directory_path(directory)

    @unittest.skipIf(os.name == "nt", "creating symbolic links needs extra privileges on Windows")
    def test_rejects_a_nested_directory_that_escapes_through_a_symbolic_link(self) -> None:
        with TemporaryDirectory() as outside:
            with temporary_workarea() as workarea:
                (workarea.root_dir / "Root").symlink_to(outside, target_is_directory=True)

                with self.assertRaisesRegex(Workarea.Error, "outside the workarea"):
                    workarea.page_directory_path("Root/Child")

    def test_stages_and_installs_a_nested_page(self) -> None:
        with temporary_workarea() as workarea:
            self._page_directory(workarea, "Root")
            staging = workarea.stage_page("Root/Child", "# Child\n", {"diagram.png": b"PNG"})

            target = workarea.install_page(staging, "Root/Child")

            self.assertEqual(target, workarea.root_dir / "Root" / "Child")
            self.assertEqual((target / "content.md").read_text(encoding="utf-8"), "# Child\n")
            self.assertEqual((target / "_attachments/diagram.png").read_bytes(), b"PNG")

    def test_renames_a_nested_page_directory_within_its_parent(self) -> None:
        with temporary_workarea() as workarea:
            source = self._page_directory(workarea, "Root/Old")
            (source / "notes.txt").write_text("unmanaged\n", encoding="utf-8")
            staging = workarea.stage_page("Root/New", "replacement\n", {}, source=source)

            with workarea.replace_page(staging, "Root/New", source) as target:
                pass

            self.assertEqual(target, workarea.root_dir / "Root" / "New")
            self.assertFalse(source.exists())
            self.assertEqual((target / "content.md").read_text(encoding="utf-8"), "replacement\n")
            self.assertEqual((target / "notes.txt").read_text(encoding="utf-8"), "unmanaged\n")

    def test_rejects_a_previous_directory_outside_the_workarea(self) -> None:
        with TemporaryDirectory() as outside:
            with temporary_workarea() as workarea:
                staging = workarea.stage_page("Root", "replacement\n", {})

                with self.assertRaisesRegex(Workarea.Error, "previous page directory must be inside the workarea"):
                    with workarea.replace_page(staging, "Root", Path(outside).resolve()):
                        pass


# vim: set ts=4 sw=4 et tw=132:
