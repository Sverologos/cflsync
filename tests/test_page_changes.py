# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Local and remote change inspection against a cached page state."""

import hashlib
from types import SimpleNamespace
import unittest

from cflsync import AttachmentMetadata, PageChangeDetector, PageChangeStatus, PageMetadata, PageState, PandocRunner
from cflsync.sync import _media_ids, unique_attachments
from tests.support import temporary_workarea

MARKDOWN = "# Example page\n\nExample\n"
ATTACHMENT = b"PNG"


def remote_page(version=17, title="Example page"):
    return SimpleNamespace(id="123456", title=title, version=version)


def remote_attachment(filename="diagram.png", attachment_id="att987654", version=3):
    return SimpleNamespace(filename=filename, id=attachment_id, version=version, file_id=None)


class TestPageChangeDetector(unittest.TestCase):

    def setUp(self) -> None:
        self.inspector = PageChangeDetector(PandocRunner())

    def _page(self, workarea):
        """Install a page whose local files, cache, and remote metadata all agree."""
        state = PageState(
            PageMetadata("123456", "Example page", None, "Example page", 17, self.inspector.content_hash(MARKDOWN)),
            {"diagram.png": AttachmentMetadata("att987654", 3,
                                               hashlib.sha256(ATTACHMENT).hexdigest())})
        directory = workarea.root_dir / "Example page"
        (directory / "_attachments").mkdir(parents=True)
        (directory / "content.md").write_text(MARKDOWN, encoding="utf-8")
        (directory / "_attachments/diagram.png").write_bytes(ATTACHMENT)

        return directory, state

    def _statuses(self, directory, state, page=None, attachments=None):
        if page is None:
            page = remote_page()

        if attachments is None:
            attachments = [remote_attachment()]

        return self.inspector.local_status(directory, state), self.inspector.remote_status(page, attachments, state)

    def test_hashes_formatting_only_differences_identically(self) -> None:
        equivalent = "# Example page\n\n\nExample\n\n"

        self.assertEqual(self.inspector.content_hash(MARKDOWN), self.inspector.content_hash(equivalent))
        self.assertNotEqual(self.inspector.content_hash(MARKDOWN), self.inspector.content_hash("# Example page\n\nEdited\n"))

    def test_reports_no_change_when_all_three_agree(self) -> None:
        with temporary_workarea() as workarea:
            statuses = self._statuses(*self._page(workarea))

            self.assertEqual(statuses, (PageChangeStatus.UNCHANGED, PageChangeStatus.UNCHANGED))

    def test_reports_local_page_edits_and_removal(self) -> None:
        for content in ["# Example page\n\nEdited\n", None]:
            with self.subTest(content=content):
                with temporary_workarea() as workarea:
                    directory, state = self._page(workarea)
                    if content is None:
                        (directory / "content.md").unlink()
                    else:
                        (directory / "content.md").write_text(content, encoding="utf-8")

                    local, remote = self._statuses(directory, state)

                    self.assertEqual((local, remote), (PageChangeStatus.CHANGED, PageChangeStatus.UNCHANGED))

    def test_reports_changed_and_missing_managed_attachments_by_name(self) -> None:
        for edit in ["bytes", "remove"]:
            with self.subTest(edit=edit):
                with temporary_workarea() as workarea:
                    directory, state = self._page(workarea)
                    path = directory / "_attachments/diagram.png"
                    if edit == "bytes":
                        path.write_bytes(b"edited")
                    else:
                        path.unlink()

                    page_changed, attachments_changed = self.inspector.local_changes(directory, state)

                    self.assertEqual(attachments_changed, ["diagram.png"])
                    self.assertFalse(page_changed)

    def test_ignores_unreferenced_local_files(self) -> None:
        with temporary_workarea() as workarea:
            directory, state = self._page(workarea)
            (directory / "_attachments/notes.txt").write_text("unmanaged")
            (directory / "scratch.md").write_text("unmanaged")

            local, _ = self._statuses(directory, state)

            self.assertEqual(local, PageChangeStatus.UNCHANGED)

    def test_reports_a_referenced_new_attachment_as_a_local_change(self) -> None:
        with temporary_workarea() as workarea:
            directory, state = self._page(workarea)
            (directory / "_attachments/added.png").write_bytes(b"ADDED")
            (directory / "_attachments/ignored.png").write_bytes(b"IGNORED")
            markdown = f"{MARKDOWN}\n![Added](_attachments/added.png)\n"
            (directory / "content.md").write_text(markdown, encoding="utf-8")
            state.page.content_hash = self.inspector.content_hash(markdown)

            page_changed, attachments_changed = self.inspector.local_changes(directory, state)

            self.assertEqual(attachments_changed, ["added.png"])
            self.assertFalse(page_changed)

    def test_ignores_references_without_a_local_file_or_a_safe_name(self) -> None:
        for reference in ["_attachments/absent.png", "_attachments/../escape.png", "https://example.test/remote.png"]:
            with self.subTest(reference=reference):
                with temporary_workarea() as workarea:
                    directory, state = self._page(workarea)
                    markdown = f"{MARKDOWN}\n![Linked]({reference})\n"
                    (directory / "content.md").write_text(markdown, encoding="utf-8")
                    state.page.content_hash = self.inspector.content_hash(markdown)

                    _, attachments_changed = self.inspector.local_changes(directory, state)

                    self.assertEqual(attachments_changed, [])

    def test_lists_referenced_attachment_names(self) -> None:
        markdown = "[Report](_attachments/report.pdf) ![Diagram](_attachments/diagram.png) [Other](https://example.test)\n"

        self.assertEqual(self.inspector.referenced_attachments(markdown), ["report.pdf", "diagram.png"])

    def test_lists_decoded_and_written_names_of_encoded_paths(self) -> None:
        markdown = "![Pasted](_attachments/Pasted%20image.png) [Raw](_attachments/caf%C3%A9.pdf) [Plain](_attachments/a(1).png)\n"

        self.assertEqual(
            self.inspector.referenced_attachments(markdown),
            ["Pasted image.png", "Pasted%20image.png", "café.pdf", "caf%C3%A9.pdf", "a(1).png"])

    def test_detects_a_new_attachment_with_an_encoded_path(self) -> None:
        with temporary_workarea() as workarea:
            directory, state = self._page(workarea)
            (directory / "_attachments").mkdir(exist_ok=True)
            (directory / "_attachments" / "Pasted image.png").write_bytes(b"png")
            markdown = f"{MARKDOWN}\n![Pasted](_attachments/Pasted%20image.png)\n"
            (directory / "content.md").write_text(markdown, encoding="utf-8")
            state.page.content_hash = self.inspector.content_hash(markdown)

            _, attachments_changed = self.inspector.local_changes(directory, state)

            self.assertEqual(attachments_changed, ["Pasted image.png"])

    def test_reports_remote_page_version_and_title_changes(self) -> None:
        for page in [remote_page(version=18), remote_page(title="Renamed page")]:
            with self.subTest(version=page.version, title=page.title):
                with temporary_workarea() as workarea:
                    _, remote = self._statuses(*self._page(workarea), page=page)

                    self.assertEqual(remote, PageChangeStatus.CHANGED)

    def test_reports_remote_attachment_updates_deletions_and_additions(self) -> None:
        cases = [
            ("updated", [remote_attachment(version=4)], ["diagram.png"]),
            ("replaced", [remote_attachment(attachment_id="att111111")], ["diagram.png"]), ("deleted", [], ["diagram.png"]),
            ("added", [remote_attachment(), remote_attachment("report.pdf", "att222222", 1)], ["report.pdf"]), ]
        for name, attachments, expected in cases:
            with self.subTest(case=name):
                with temporary_workarea() as workarea:
                    _, state = self._page(workarea)
                    _, attachment_changes = self.inspector.remote_changes(remote_page(), attachments, state)

                    self.assertEqual(attachment_changes, expected)

    def test_ignores_a_remote_duplicate_of_a_managed_attachment(self) -> None:
        duplicate = remote_attachment(attachment_id="att111111", version=1)
        cases = [
            ("duplicate after", [remote_attachment(), duplicate], []),
            ("duplicate before", [duplicate, remote_attachment()], []),
            ("managed one deleted", [duplicate], ["diagram.png"]), ]
        for name, attachments, expected in cases:
            with self.subTest(case=name):
                with temporary_workarea() as workarea:
                    _, state = self._page(workarea)
                    _, attachment_changes = self.inspector.remote_changes(remote_page(), attachments, state)

                    self.assertEqual(attachment_changes, expected)

    def test_reports_both_sides_when_each_changed(self) -> None:
        with temporary_workarea() as workarea:
            directory, state = self._page(workarea)
            (directory / "content.md").write_text("# Example page\n\nEdited\n", encoding="utf-8")

            statuses = self._statuses(directory, state, page=remote_page(version=18))

            self.assertEqual(statuses, (PageChangeStatus.CHANGED, PageChangeStatus.CHANGED))

    def test_reports_absent_local_and_remote_representations(self) -> None:
        with temporary_workarea() as workarea:
            directory, state = self._page(workarea)

            self.assertEqual(self.inspector.local_status(directory, None), PageChangeStatus.ABSENT)
            self.assertEqual(self.inspector.local_status(directory / "missing", state), PageChangeStatus.ABSENT)
            self.assertEqual(self.inspector.remote_status(None, [], state), PageChangeStatus.ABSENT)
            self.assertEqual(self.inspector.remote_status(remote_page(), [remote_attachment()], None), PageChangeStatus.CHANGED)


class TestUniqueAttachments(unittest.TestCase):
    """Of attachments sharing a filename, one is managed; the others are left out."""

    def setUp(self) -> None:
        self.first = SimpleNamespace(filename="a.png", id="att1", file_id="file-1")
        self.second = SimpleNamespace(filename="a.png", id="att2", file_id="file-2")
        self.other = SimpleNamespace(filename="b.png", id="att3", file_id="file-3")

    def test_keeps_the_first_listed_without_a_preference(self) -> None:
        self.assertEqual(unique_attachments([self.first, self.other, self.second]), ([self.first, self.other], [self.second]))

    def test_keeps_the_attachment_of_the_first_matching_preference(self) -> None:
        attachments = [self.first, self.second, self.other]

        self.assertEqual(unique_attachments(attachments, {"file-2"}, {"att1"}), ([self.second, self.other], [self.first]))
        self.assertEqual(unique_attachments(attachments, {"file-9"}, {"att2"}), ([self.second, self.other], [self.first]))

    def test_keeps_an_attachment_id_listed_twice_for_validation(self) -> None:
        again = SimpleNamespace(filename="a.png", id="att1", file_id="file-1")

        self.assertEqual(unique_attachments([self.first, again]), ([self.first, again], []))


class TestMediaIds(unittest.TestCase):

    def test_collects_media_ids_and_skips_non_string_types(self) -> None:
        document = {"type": "doc", "content": [
            {"type": "extension", "attrs": {"parameters": {"type": {"value": "x"}, "list": [{"type": ["y"]}]}}},
            {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "file-1"}}]},
            {"type": "paragraph", "content": [{"type": "mediaInline", "attrs": {"id": "file-2"}}]}]}

        self.assertEqual(_media_ids(document), {"file-1", "file-2"})


# vim: set ts=4 sw=4 et tw=132:
