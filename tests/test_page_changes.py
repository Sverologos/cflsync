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
from tests.support import temporary_workarea

MARKDOWN = "# Example page\n\nExample\n"
ATTACHMENT = b"PNG"
# Pure Pandoc canonical forms and SHA-256 values captured before writer tag compaction.
LEGACY_EXPAND = "# Example page\n\n<details>\n\n<summary>T</summary>\n\nx\n\n</details>\n"
COMPACT_EXPAND = "# Example page\n\n<details>\n<summary>T</summary>\n\nx\n\n</details>\n"
LEGACY_EXPAND_HASH = "60f6beaa4d71901fd68518800ef791ca63e72ef456c84286bf7a6f39a9e783ff"
COMPACT_EXPAND_HASH = "852287e77fc69890b9e7bc1e14cefde6e0f5a80d1b095f74fe4634638106f32b"


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

    def test_keeps_fixed_hashes_for_legacy_and_compact_tag_spacing(self) -> None:
        pandoc = PandocRunner()
        for markdown, expected_hash in ((LEGACY_EXPAND, LEGACY_EXPAND_HASH), (COMPACT_EXPAND, COMPACT_EXPAND_HASH)):
            with self.subTest(markdown=markdown):
                self.assertEqual(pandoc.pandoc_to_gfm(pandoc.gfm_to_pandoc(markdown)), markdown)
                self.assertEqual(self.inspector.content_hash(markdown), expected_hash)

        self.assertNotEqual(LEGACY_EXPAND_HASH, COMPACT_EXPAND_HASH)

    def test_legacy_and_compact_files_are_unchanged_against_their_own_cache(self) -> None:
        for markdown, expected_hash in ((LEGACY_EXPAND, LEGACY_EXPAND_HASH), (COMPACT_EXPAND, COMPACT_EXPAND_HASH)):
            with self.subTest(markdown=markdown), temporary_workarea() as workarea:
                directory, state = self._page(workarea)
                (directory / "content.md").write_text(markdown, encoding="utf-8")
                state.page.content_hash = expected_hash
                state.save(workarea.cache_path("123456"))
                cached = PageState.load(workarea.cache_path("123456"))
                self.assertEqual(self.inspector.local_status(directory, cached), PageChangeStatus.UNCHANGED)

    def test_manual_tag_spacing_edit_is_a_local_change(self) -> None:
        with temporary_workarea() as workarea:
            directory, state = self._page(workarea)
            state.page.content_hash = LEGACY_EXPAND_HASH
            (directory / "content.md").write_text(LEGACY_EXPAND, encoding="utf-8")
            self.assertEqual(self.inspector.local_status(directory, state), PageChangeStatus.UNCHANGED)
            (directory / "content.md").write_text(COMPACT_EXPAND, encoding="utf-8")
            self.assertEqual(self.inspector.local_status(directory, state), PageChangeStatus.CHANGED)

    def test_ignores_a_remote_duplicate_of_a_managed_attachment(self) -> None:
        duplicate = remote_attachment(attachment_id="att111111", version=1)
        cases = [
            ("duplicate after", [remote_attachment(), duplicate], []), ("duplicate before", [duplicate,
                                                                                             remote_attachment()], []),
            ("managed one deleted", [duplicate], ["diagram.png"]), ]
        for name, attachments, expected in cases:
            with self.subTest(case=name):
                with temporary_workarea() as workarea:
                    _, state = self._page(workarea)
                    _, attachment_changes = self.inspector.remote_changes(remote_page(), attachments, state)

                    self.assertEqual(attachment_changes, expected)

    def test_reports_absent_local_and_remote_representations(self) -> None:
        with temporary_workarea() as workarea:
            directory, state = self._page(workarea)

            self.assertEqual(self.inspector.local_status(directory, None), PageChangeStatus.ABSENT)
            self.assertEqual(self.inspector.local_status(directory / "missing", state), PageChangeStatus.ABSENT)
            self.assertEqual(self.inspector.remote_status(None, [], state), PageChangeStatus.ABSENT)
            self.assertEqual(self.inspector.remote_status(remote_page(), [remote_attachment()], None), PageChangeStatus.CHANGED)

    def test_discovers_html_image_targets_without_managing_code_examples_or_invalid_paths(self) -> None:
        markdown = '<figure data-type="media-single">\n\n' \
            '<img src="_attachments/new%20image.png" width="640" />\n\n</figure>\n\n' \
            '<table><tr><td><img src="_attachments/a&amp;b.png" /></td></tr></table>\n\n' \
            '<!-- <img src="_attachments/comment.png" /> -->\n\n' \
            '```html\n<img src="_attachments/example.png" />\n```\n\n' \
            '<img src="_attachments/../escape.png" />\n'
        self.assertEqual(self.inspector.referenced_attachments(markdown), ["new image.png", "new%20image.png", "a&b.png"])


# vim: set ts=4 sw=4 et tw=132:
