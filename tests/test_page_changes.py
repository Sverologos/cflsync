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


# vim: set ts=4 sw=4 et tw=132:
