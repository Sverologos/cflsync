# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for managed attachment path resolution."""

import unittest

from cflsync import MediaResolutionError, MediaResolver


class TestMediaResolver(unittest.TestCase):

    def test_resolves_attachment_ids_and_paths(self) -> None:
        resolver = MediaResolver([("diagram.png", "987654"), ("report.xlsx", "456789")])

        self.assertEqual(resolver.path_for("987654"), "_attachments/diagram.png")
        self.assertEqual(resolver.path_for("456789"), "_attachments/report.xlsx")
        self.assertEqual(resolver.id_for("_attachments/diagram.png"), "987654")
        self.assertEqual(resolver.id_for("_attachments/report.xlsx"), "456789")

    def test_percent_encodes_paths_as_page_links(self) -> None:
        names = {
            "Pasted image x.png": "Pasted%20image%20x.png",
            "a)b (1).png": "a%29b%20%281%29.png",
            "café.png": "caf%C3%A9.png",
            "100%.png": "100%25.png"}
        resolver = MediaResolver((name, str(number)) for number, name in enumerate(names))

        for number, (name, encoded) in enumerate(names.items()):
            with self.subTest(name=name):
                self.assertEqual(resolver.path_for(str(number)), f"_attachments/{encoded}")
                self.assertEqual(resolver.id_for(f"_attachments/{encoded}"), str(number))

    def test_resolves_unencoded_paths_of_earlier_releases(self) -> None:
        resolver = MediaResolver([("café.png", "1"), ("a(1).png", "2"), ("a%20b.png", "3"), ("100%.png", "4")])

        for path, attachment_id in (("_attachments/café.png", "1"), ("_attachments/a(1).png", "2"), ("_attachments/a%20b.png", "3"),
                                    ("_attachments/100%.png", "4")):
            with self.subTest(path=path):
                self.assertEqual(resolver.id_for(path), attachment_id)

    def test_prefers_the_decoded_filename(self) -> None:
        resolver = MediaResolver([("a b.png", "1"), ("a%20b.png", "2")])

        self.assertEqual(resolver.id_for(resolver.path_for("1")), "1")
        self.assertEqual(resolver.id_for(resolver.path_for("2")), "2")
        self.assertEqual(resolver.id_for("_attachments/a%20b.png"), "1")

    def test_rejects_ambiguous_and_unsafe_manifest_entries(self) -> None:
        with self.assertRaisesRegex(MediaResolutionError, "filename.*ambiguous"):
            MediaResolver([("diagram.png", "987654"), ("diagram.png", "456789")])

        with self.assertRaisesRegex(MediaResolutionError, "ID.*ambiguous"):
            MediaResolver([("first.png", "987654"), ("second.png", "987654")])

        with self.assertRaisesRegex(MediaResolutionError, "unsafe"):
            MediaResolver([("../diagram.png", "987654")])

    def test_rejects_unmanaged_and_traversal_paths(self) -> None:
        resolver = MediaResolver([("diagram.png", "987654")])

        with self.assertRaisesRegex(MediaResolutionError, "not managed"):
            resolver.path_for("456789")

        with self.assertRaisesRegex(MediaResolutionError, "not managed"):
            resolver.id_for("_attachments/missing.png")

        for path in ("_attachments/../diagram.png", "../_attachments/diagram.png", "/_attachments/diagram.png"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(MediaResolutionError, "outside _attachments"):
                    resolver.id_for(path)


# vim: set ts=4 sw=4 et tw=132:
