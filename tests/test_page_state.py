# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for typed page synchronization state and the cached page tree."""

import hashlib
import unittest

from cflsync import AttachmentMetadata, PageMetadata, PageState, StateError
from cflsync.workarea import PageTree
from tests.support import example_page_state

PAGE_HASH = hashlib.sha256(b"page").hexdigest()


def page_metadata(id="123456", title="Example page", parent_id=None, directory="Example page_123456", content_hash=PAGE_HASH):
    return PageMetadata(id, title, parent_id, directory, 17, content_hash)


class TestPageStateSerialization(unittest.TestCase):

    def test_metadata_constructor_rejects_an_invalid_content_hash(self) -> None:
        with self.assertRaises(StateError):
            page_metadata(content_hash="not-a-hash")

    def test_metadata_rejects_an_invalid_parent_id(self) -> None:
        for parent_id in ["", "abc", "12 3"]:
            with self.subTest(parent_id=parent_id):
                with self.assertRaisesRegex(StateError, "page.parent_id"):
                    page_metadata(parent_id=parent_id)

    def test_metadata_requires_a_single_directory_name(self) -> None:
        for directory in [".", "..", "Parent/Child", "Parent\\Child", "../outside", "Nul\x00name"]:
            with self.subTest(directory=directory):
                with self.assertRaisesRegex(StateError, "single directory name"):
                    page_metadata(directory=directory)

    def test_attachment_metadata_accepts_an_opaque_remote_id(self) -> None:
        attachment_hash = hashlib.sha256(b"attachment").hexdigest()
        attachment = AttachmentMetadata(id="att1843529704", version=1, content_hash=attachment_hash)

        self.assertEqual(attachment.id, "att1843529704")
        with self.assertRaises(StateError):
            AttachmentMetadata(id="att 1843529704", version=1, content_hash=attachment_hash)

    def test_rejects_states_written_by_cflsync_0_4_or_earlier(self) -> None:
        for state_format in [1, 2]:
            with self.subTest(format=state_format):
                value = example_page_state().to_json()
                value["format"] = state_format

                with self.assertRaisesRegex(
                        StateError, f"state format {state_format} was written by cflsync 0.4 or earlier.*push its local changes"):
                    PageState.from_json(value)

    def test_rejects_a_newer_state_format(self) -> None:
        value = example_page_state().to_json()
        value["format"] = 4

        with self.assertRaisesRegex(StateError, "unsupported state format 4"):
            PageState.from_json(value)

    def test_requires_the_parent_id_field(self) -> None:
        page = example_page_state().page.to_json()
        del page["parent_id"]

        with self.assertRaisesRegex(StateError, "page.parent_id is required"):
            PageState.from_json({"format": 3, "page": page, "attachments": {}})


class TestPageTree(unittest.TestCase):

    def _states(self, *pages):
        return {page_id: example_page_state(page_id, title, parent_id=parent_id) for page_id, title, parent_id in pages}

    def test_accepts_an_empty_cache(self) -> None:
        tree = PageTree({}, "1")

        with self.assertRaisesRegex(StateError, "page '1' is not cached"):
            tree.directory("1")

    def test_rejects_broken_chains(self) -> None:
        cases = [
            ((("1", "Root", None), ("3", "Grandchild", "2")), "cached parent page '2' of page '3' is missing"),
            ((("2", "Child", "1"), ), "cached parent page '1' of page '2' is missing"),
            ((("1", "Root", None), ("2", "Other root", None)), "page '2' has no parent but is not the root page '1'"),
            ((("1", "Root", "9"), ("9", "Above root", None)), "root page '1' must not have a cached parent"),
            ((("1", "Root", None), ("2", "First", "3"), ("3", "Second", "2")), "the cached parents of page '2' form a cycle"), ]
        for pages, error in cases:
            with self.subTest(error=error):
                with self.assertRaisesRegex(StateError, error):
                    PageTree(self._states(*pages), "1")


# vim: set ts=4 sw=4 et tw=132:
