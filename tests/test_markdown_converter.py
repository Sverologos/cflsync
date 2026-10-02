# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for Markdown to ADF conversion."""

import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cflsync import ADFToMarkdownConverter, ConversionError, MarkdownToADFConverter, MediaResolver, PandocRunner


class RecordingPandoc:

    def __init__(self, pandoc):
        self.pandoc = pandoc
        self.markdown = None

    def gfm_to_pandoc(self, markdown):
        self.markdown = markdown
        return self.pandoc


class PandocBridge:

    def pandoc_to_gfm(self, pandoc):
        self.pandoc = pandoc
        return "source"

    def gfm_to_pandoc(self, markdown):
        return self.pandoc


def _cell(cell_type, blocks, colspan=1, rowspan=1):
    return {"type": cell_type, "attrs": {"colspan": colspan, "rowspan": rowspan}, "content": blocks}


def pandoc_document(blocks):
    return {"pandoc-api-version": list(PandocRunner.API_VERSION), "meta": {}, "blocks": blocks}


class TestMarkdownToADFConverter(unittest.TestCase):

    def test_maps_direct_blocks_and_inlines(self) -> None:
        pandoc = RecordingPandoc(
            pandoc_document(
                [
                    {
                        "t":
                        "Para",
                        "c": [
                            {
                                "t": "Str",
                                "c": "plain"}, {
                                    "t": "Space"}, {
                                        "t": "Str",
                                        "c": "text"}, {
                                            "t": "Strong",
                                            "c": [{
                                                "t": "Str",
                                                "c": "strong"}]}, {
                                                    "t": "Emph",
                                                    "c": [{
                                                        "t": "Str",
                                                        "c": "emphasis"}]}, {
                                                            "t": "Strikeout",
                                                            "c": [{
                                                                "t": "Str",
                                                                "c": "struck"}]}, {
                                                                    "t": "Code",
                                                                    "c": [["", [], []], "code"]},
                            {
                                "t": "Link",
                                "c": [["", [], []], [{
                                    "t": "Str",
                                    "c": "link"}], ["https://example.test", ""]]}, {
                                        "t": "LineBreak"}, ], }, {
                                            "t": "Header",
                                            "c": [2, ["", [], []], [{
                                                "t": "Str",
                                                "c": "Heading"}]]}, {
                                                    "t": "BlockQuote",
                                                    "c": [{
                                                        "t": "Para",
                                                        "c": [{
                                                            "t": "Str",
                                                            "c": "Quote"}]}]}, {
                                                                "t": "BulletList",
                                                                "c": [[{
                                                                    "t": "Plain",
                                                                    "c": [{
                                                                        "t": "Str",
                                                                        "c": "Item"}]}]]},
                    {
                        "t": "OrderedList",
                        "c": [[3, {
                            "t": "Decimal"}, {
                                "t": "Period"}], [[{
                                    "t": "Plain",
                                    "c": [{
                                        "t": "Str",
                                        "c": "Third"}]}]]]}, {
                                            "t": "CodeBlock",
                                            "c": [["", ["python"], []], "print(1)"]}, {
                                                "t": "HorizontalRule"}, ]))

        document = MarkdownToADFConverter(pandoc).convert("source")

        self.assertEqual(pandoc.markdown, "source")
        self.assertEqual(
            document, {
                "type":
                "doc",
                "version":
                1,
                "content": [
                    {
                        "type":
                        "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "plain text"}, {
                                    "type": "text",
                                    "text": "strong",
                                    "marks": [{
                                        "type": "strong"}]}, {
                                            "type": "text",
                                            "text": "emphasis",
                                            "marks": [{
                                                "type": "em"}]}, {
                                                    "type": "text",
                                                    "text": "struck",
                                                    "marks": [{
                                                        "type": "strike"}]}, {
                                                            "type": "text",
                                                            "text": "code",
                                                            "marks": [{
                                                                "type": "code"}]},
                            {
                                "type": "text",
                                "text": "link",
                                "marks": [{
                                    "type": "link",
                                    "attrs": {
                                        "href": "https://example.test",
                                        "title": ""}}], }, {
                                            "type": "hardBreak"}, ], }, {
                                                "type": "heading",
                                                "attrs": {
                                                    "level": 2},
                                                "content": [{
                                                    "type": "text",
                                                    "text": "Heading"}]},
                    {
                        "type": "blockquote",
                        "content": [{
                            "type": "paragraph",
                            "content": [{
                                "type": "text",
                                "text": "Quote"}]}]}, {
                                    "type":
                                    "bulletList",
                                    "content": [
                                        {
                                            "type": "listItem",
                                            "content": [{
                                                "type": "paragraph",
                                                "content": [{
                                                    "type": "text",
                                                    "text": "Item"}]}]}],
                                }, {
                                    "type":
                                    "orderedList",
                                    "attrs": {
                                        "order": 3},
                                    "content": [
                                        {
                                            "type": "listItem",
                                            "content": [{
                                                "type": "paragraph",
                                                "content": [{
                                                    "type": "text",
                                                    "text": "Third"}]}]}], }, {
                                                        "type": "codeBlock",
                                                        "attrs": {
                                                            "language": "python"},
                                                        "content": [{
                                                            "type": "text",
                                                            "text": "print(1)"}]}, {
                                                                "type": "rule"}, ], },
        )

    def test_maps_gfm_task_lists_without_local_ids(self) -> None:
        document = MarkdownToADFConverter(PandocRunner()).convert("- [ ] Parent\n  - [x] Child\n")

        self.assertEqual(
            document, {
                "type":
                "doc",
                "version":
                1,
                "content": [
                    {
                        "type":
                        "taskList",
                        "content": [
                            {
                                "type": "taskItem",
                                "attrs": {
                                    "state": "TODO"},
                                "content": [{
                                    "type": "text",
                                    "text": "Parent"}]}, {
                                        "type":
                                        "taskList",
                                        "content": [
                                            {
                                                "type": "taskItem",
                                                "attrs": {
                                                    "state": "DONE"},
                                                "content": [{
                                                    "type": "text",
                                                    "text": "Child"}]}]}]}]})

    def test_maps_gfm_alerts_to_canonical_panels(self) -> None:
        markdown = """\
> [!NOTE]
> Note content.

> [!TIP]
> Tip content.

> [!IMPORTANT]
> Important content.

> [!WARNING]
> Warning content.

> [!CAUTION]
> Caution content.
"""

        document = MarkdownToADFConverter(PandocRunner()).convert(markdown)

        self.assertEqual(
            document["content"], [
                {
                    "type": "panel",
                    "attrs": {
                        "panelType": "note"},
                    "content": [{
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": "Note content."}]}]}, {
                                "type": "panel",
                                "attrs": {
                                    "panelType": "tip"},
                                "content": [{
                                    "type": "paragraph",
                                    "content": [{
                                        "type": "text",
                                        "text": "Tip content."}]}]},
                {
                    "type": "panel",
                    "attrs": {
                        "panelType": "info"},
                    "content": [{
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": "Important content."}]}]}, {
                                "type": "panel",
                                "attrs": {
                                    "panelType": "warning"},
                                "content": [{
                                    "type": "paragraph",
                                    "content": [{
                                        "type": "text",
                                        "text": "Warning content."}]}]}, {
                                            "type": "panel",
                                            "attrs": {
                                                "panelType": "error"},
                                            "content": [
                                                {
                                                    "type": "paragraph",
                                                    "content": [{
                                                        "type": "text",
                                                        "text": "Caution content."}]}]}, ])

    def test_decodes_an_opaque_marker(self) -> None:
        node = {
            "type": "panel",
            "attrs": {
                "panelType": "info"},
            "content": [{
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": "Info"}]}], }
        pandoc = RecordingPandoc(pandoc_document([{"t": "CodeBlock", "c": [["", ["atlas_doc_format"], []], json.dumps(node)]}]))

        document = MarkdownToADFConverter(pandoc).convert("source")

        self.assertEqual(document["content"], [node])

    def test_round_trips_supported_adf(self) -> None:
        source = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type":
                    "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Text"}, {
                                "type": "text",
                                "text": "strong",
                                "marks": [{
                                    "type": "strong"}]}, {
                                        "type": "text",
                                        "text": "code",
                                        "marks": [{
                                            "type": "code"}]}, {
                                                "type": "hardBreak"}, ], }, {
                                                    "type": "heading",
                                                    "attrs": {
                                                        "level": 2},
                                                    "content": [{
                                                        "type": "text",
                                                        "text": "Heading"}]}, {
                                                            "type": "blockquote",
                                                            "content":
                                                            [{
                                                                "type": "paragraph",
                                                                "content": [{
                                                                    "type": "text",
                                                                    "text": "Quote"}]}]},
                {
                    "type":
                    "bulletList",
                    "content":
                    [{
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [{
                                "type": "text",
                                "text": "Item"}]}]}], },
                {
                    "type":
                    "orderedList",
                    "attrs": {
                        "order": 3},
                    "content":
                    [{
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [{
                                "type": "text",
                                "text": "Third"}]}]}], }, {
                                    "type": "codeBlock",
                                    "attrs": {
                                        "language": "python"},
                                    "content": [{
                                        "type": "text",
                                        "text": "print(1)"}]}, {
                                            "type": "rule"}, ], }
        pandoc = PandocBridge()

        markdown = ADFToMarkdownConverter(pandoc).convert(source)
        document = MarkdownToADFConverter(pandoc).convert(markdown)

        self.assertEqual(document, source)

    def test_round_trips_tables_through_pipe_and_html_representations(self) -> None:
        pandoc = PandocRunner()
        forward = ADFToMarkdownConverter(pandoc)
        reverse = MarkdownToADFConverter(pandoc)
        paragraph = {"type": "paragraph", "content": [{"type": "text", "text": "Cell"}]}
        simple = {
            "type":
            "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [_cell("tableHeader", [paragraph])]}, {
                        "type": "tableRow",
                        "content": [_cell("tableCell", [paragraph])]}]}
        complex_table = {
            "type":
            "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [_cell("tableHeader", [paragraph], colspan=2)]}, {
                        "type": "tableRow",
                        "content": [_cell("tableCell", [paragraph, paragraph]),
                                    _cell("tableCell", [paragraph])]}]}

        for name, table in (("pipe", simple), ("html", complex_table)):
            with self.subTest(representation=name):
                source = {"type": "doc", "version": 1, "content": [table]}
                markdown = forward.convert(source)

                self.assertEqual(markdown.lstrip().startswith("<table"), name == "html")
                self.assertEqual(reverse.convert(markdown), source)

    def test_accepts_the_heading_identifiers_that_reading_gfm_assigns(self) -> None:
        document = MarkdownToADFConverter(PandocRunner()).convert("## An L2 Heading\n\nText\n")

        self.assertEqual(
            document["content"][0], {
                "type": "heading",
                "attrs": {
                    "level": 2},
                "content": [{
                    "type": "text",
                    "text": "An L2 Heading"}]})

    def test_keeps_the_unicode_text_of_an_emoji_shortcode(self) -> None:
        document = MarkdownToADFConverter(PandocRunner()).convert("Nice :smile: day\n")

        self.assertEqual(
            document["content"][0], {
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": "Nice \U0001F604 day"}]})

    def test_maps_a_raw_html_status_through_pandoc(self) -> None:
        document = MarkdownToADFConverter(PandocRunner()).convert(
            'Before <span cfl-type="status" style="background-color: green">Done &amp; ready</span> after\n')

        self.assertEqual(
            document["content"][0], {
                "type":
                "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Before "}, {
                            "type": "status",
                            "attrs": {
                                "text": "Done & ready",
                                "color": "green"}}, {
                                    "type": "text",
                                    "text": " after"}]})

    def test_maps_raw_html_underline_through_pandoc(self) -> None:
        document = MarkdownToADFConverter(PandocRunner()).convert('<u>**Underlined and bold**</u>\n')

        self.assertEqual(
            document["content"][0], {
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": "Underlined and bold",
                    "marks": [{
                        "type": "underline"}, {
                            "type": "strong"}]}]})

    def test_round_trips_an_underline(self) -> None:
        source = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type": "paragraph",
                    "content":
                    [{
                        "type": "text",
                        "text": "Underlined and bold",
                        "marks": [{
                            "type": "underline"}, {
                                "type": "strong"}]}]}]}
        pandoc = PandocRunner()
        markdown = ADFToMarkdownConverter(pandoc).convert(source)

        self.assertEqual(markdown, '<u>**Underlined and bold**</u>\n')
        self.assertEqual(MarkdownToADFConverter(pandoc).convert(markdown), source)

    def test_round_trips_an_underlined_link(self) -> None:
        source = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type":
                    "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Underlined link",
                            "marks":
                            [{
                                "type": "link",
                                "attrs": {
                                    "href": "https://example.test",
                                    "title": ""}}, {
                                        "type": "underline"}]}]}]}
        pandoc = PandocRunner()
        markdown = ADFToMarkdownConverter(pandoc).convert(source)

        self.assertEqual(markdown, '[<u>Underlined link</u>](https://example.test)\n')
        self.assertEqual(MarkdownToADFConverter(pandoc).convert(markdown), source)

    def test_maps_raw_html_subsup_through_pandoc(self) -> None:
        document = MarkdownToADFConverter(PandocRunner()).convert('H<sub>2</sub>O and x<sup>2</sup>\n')

        self.assertEqual(
            document["content"][0], {
                "type":
                "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "H"}, {
                            "type": "text",
                            "text": "2",
                            "marks": [{
                                "type": "subsup",
                                "attrs": {
                                    "type": "sub"}}]}, {
                                        "type": "text",
                                        "text": "O and x"}, {
                                            "type": "text",
                                            "text": "2",
                                            "marks": [{
                                                "type": "subsup",
                                                "attrs": {
                                                    "type": "sup"}}]}]})

    def test_round_trips_subsup_marks(self) -> None:
        source = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type":
                    "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "H"}, {
                                "type": "text",
                                "text": "2",
                                "marks": [{
                                    "type": "subsup",
                                    "attrs": {
                                        "type": "sub"}}]}, {
                                            "type": "text",
                                            "text": "O and x"}, {
                                                "type": "text",
                                                "text": "2",
                                                "marks": [{
                                                    "type": "subsup",
                                                    "attrs": {
                                                        "type": "sup"}}, {
                                                            "type": "strong"}]}]}]}
        pandoc = PandocRunner()
        markdown = ADFToMarkdownConverter(pandoc).convert(source)

        self.assertEqual(markdown, 'H<sub>2</sub>O and x<sup>**2**</sup>\n')
        self.assertEqual(MarkdownToADFConverter(pandoc).convert(markdown), source)

    def test_round_trips_a_status(self) -> None:
        source = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type": "paragraph",
                    "content":
                    [{
                        "type": "text",
                        "text": "State: "}, {
                            "type": "status",
                            "attrs": {
                                "text": "Done",
                                "color": "green"}}]}]}
        pandoc = PandocRunner()
        markdown = ADFToMarkdownConverter(pandoc).convert(source)
        document = MarkdownToADFConverter(pandoc).convert(markdown)

        self.assertEqual(document, source)

    def test_preserves_a_timestamp_date_through_pandoc(self) -> None:
        timestamp = "1775001600000"
        document = MarkdownToADFConverter(
            PandocRunner()).convert(f'<span cfl-type="date" cfl-timestamp="{timestamp}">changed text</span>\n')

        self.assertEqual(
            document["content"][0], {
                "type": "paragraph",
                "content": [{
                    "type": "date",
                    "attrs": {
                        "timestamp": timestamp}}]})

    def test_maps_a_symbolic_time_zone_date_through_pandoc(self) -> None:
        zone_name = "Europe/Brussels"
        calendar_date = "2026-04-01"
        timestamp = str(int(datetime(2026, 4, 1, tzinfo=ZoneInfo(zone_name)).timestamp() * 1000))
        document = MarkdownToADFConverter(PandocRunner()).convert(f'<span cfl-type="date">{calendar_date}[{zone_name}]</span>\n')

        self.assertEqual(
            document["content"][0], {
                "type": "paragraph",
                "content": [{
                    "type": "date",
                    "attrs": {
                        "timestamp": timestamp}}]})

    def test_maps_a_date_without_a_symbolic_time_zone_in_the_local_zone(self) -> None:
        zone_name = "Europe/Brussels"
        calendar_date = "2026-04-01"
        timestamp = str(int(datetime(2026, 4, 1, tzinfo=ZoneInfo(zone_name)).timestamp() * 1000))
        with patch("cflsync.convert._local_zone_name", return_value=zone_name):
            document = MarkdownToADFConverter(PandocRunner()).convert(f'<span cfl-type="date">{calendar_date}</span>\n')

        self.assertEqual(
            document["content"][0], {
                "type": "paragraph",
                "content": [{
                    "type": "date",
                    "attrs": {
                        "timestamp": timestamp}}]})

    def test_round_trips_a_date(self) -> None:
        zone_name = "Europe/Brussels"
        timestamp = str(int(datetime(2026, 4, 1, tzinfo=ZoneInfo(zone_name)).timestamp() * 1000))
        source = {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{
                    "type": "date",
                    "attrs": {
                        "timestamp": timestamp}}]}]}
        pandoc = PandocRunner()
        with patch("cflsync.convert._local_zone_name", return_value=zone_name):
            markdown = ADFToMarkdownConverter(pandoc).convert(source)
        document = MarkdownToADFConverter(pandoc).convert(markdown)

        self.assertEqual(document, source)

    def test_maps_a_raw_html_mention_through_pandoc(self) -> None:
        document = MarkdownToADFConverter(PandocRunner()).convert(
            '<span cfl-type="mention" cfl-id="account-123" cfl-access-level="SITE" '
            'cfl-user-type="DEFAULT">@Example User</span>\n')

        self.assertEqual(
            document["content"][0], {
                "type":
                "paragraph",
                "content": [
                    {
                        "type": "mention",
                        "attrs": {
                            "id": "account-123",
                            "text": "@Example User",
                            "accessLevel": "SITE",
                            "userType": "DEFAULT"}}]})

    def test_maps_a_mailto_link_to_a_uniquely_resolved_mention(self) -> None:
        calls = []

        def lookup(display_name, email):
            calls.append((display_name, email))
            return SimpleNamespace(account_id="account-123")

        document = MarkdownToADFConverter(
            PandocRunner(), mention_lookup=lookup).convert("[Example User](mailto:example.user@example.test)\n")

        self.assertEqual(calls, [("Example User", "example.user@example.test")])
        self.assertEqual(
            document["content"][0], {
                "type": "paragraph",
                "content": [{
                    "type": "mention",
                    "attrs": {
                        "id": "account-123",
                        "text": "@Example User"}}]})

    def test_keeps_a_mailto_link_when_mention_resolution_has_no_match(self) -> None:
        document = MarkdownToADFConverter(
            PandocRunner(), mention_lookup=lambda *_: None).convert("[Example User](mailto:example.user@example.test)\n")

        self.assertEqual(
            document["content"][0], {
                "type":
                "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Example User",
                        "marks": [{
                            "type": "link",
                            "attrs": {
                                "href": "mailto:example.user@example.test",
                                "title": ""}}]}]})

    def test_round_trips_a_mention(self) -> None:
        source = {
            "type":
            "doc",
            "version":
            1,
            "content":
            [{
                "type": "paragraph",
                "content": [{
                    "type": "mention",
                    "attrs": {
                        "id": "account-123",
                        "text": "@Example User"}}]}]}
        pandoc = PandocRunner()
        markdown = ADFToMarkdownConverter(pandoc).convert(source)
        document = MarkdownToADFConverter(pandoc).convert(markdown)

        self.assertEqual(document, source)

    def test_rejects_a_mention_without_an_account_id(self) -> None:
        with self.assertRaisesRegex(ConversionError, "non-empty account ID"):
            MarkdownToADFConverter(PandocRunner()).convert('<span cfl-type="mention">@Example User</span>\n')

    def test_rejects_a_date_with_an_invalid_symbolic_time_zone(self) -> None:
        with self.assertRaisesRegex(ConversionError, "YYYY-MM-DD"):
            MarkdownToADFConverter(PandocRunner()).convert('<span cfl-type="date">2026-04-01[Not/AZone]</span>\n')

    def test_rejects_a_status_with_an_unsupported_css_color(self) -> None:
        with self.assertRaisesRegex(ConversionError, "unsupported attributes"):
            MarkdownToADFConverter(PandocRunner()).convert('<span cfl-type="status" style="background-color: orange">Done</span>\n')

    def test_rejects_an_unclosed_underline(self) -> None:
        with self.assertRaisesRegex(ConversionError, "underline is not closed"):
            MarkdownToADFConverter(PandocRunner()).convert('<u>text\n')

    def test_rejects_an_unclosed_superscript(self) -> None:
        with self.assertRaisesRegex(ConversionError, "superscript is not closed"):
            MarkdownToADFConverter(PandocRunner()).convert('<sup>text\n')

    def test_rejects_a_span_that_is_not_an_emoji(self) -> None:
        pandoc = RecordingPandoc(
            pandoc_document([{
                "t": "Para",
                "c": [{
                    "t": "Span",
                    "c": [["", ["footnote"], []], [{
                        "t": "Str",
                        "c": "text"}]]}]}]))

        with self.assertRaisesRegex(ConversionError, "only emoji and cflsync spans"):
            MarkdownToADFConverter(pandoc).convert("source")

    def test_rejects_raw_html_that_is_not_a_table(self) -> None:
        pandoc = RecordingPandoc(pandoc_document([{"t": "RawBlock", "c": ["html", "<div>text</div>"]}]))

        with self.assertRaisesRegex(ConversionError, "HTML table"):
            MarkdownToADFConverter(pandoc).convert("source")

    def test_round_trips_media_through_the_attachment_manifest(self) -> None:
        media = MediaResolver([("diagram.png", "file-1"), ("report.pdf", "file-2")])
        source = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type":
                    "mediaSingle",
                    "attrs": {
                        "layout": "center"},
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                "type": "file",
                                "id": "file-1",
                                "collection": "contentId-123456",
                                "alt": "A diagram"}}]},
                {
                    "type":
                    "mediaSingle",
                    "attrs": {
                        "layout": "center"},
                    "content":
                    [{
                        "type": "media",
                        "attrs": {
                            "type": "external",
                            "url": "https://example.test/logo.png",
                            "alt": "logo.png"}}]}]}
        pandoc = PandocBridge()

        markdown = ADFToMarkdownConverter(pandoc, media).convert(source)
        document = MarkdownToADFConverter(pandoc, media, "contentId-123456").convert(markdown)

        self.assertEqual(document, source)

    def _mixed_paragraph(self, url):
        return RecordingPandoc(
            pandoc_document(
                [
                    {
                        "t": "Para",
                        "c": [{
                            "t": "Str",
                            "c": "text"}, {
                                "t": "Space"}, {
                                    "t": "Image",
                                    "c": [["", [], []], [], [url, ""]]}]}]))

    def test_inline_file_round_trip_uses_destination_file_id_not_local_url(self) -> None:
        media = MediaResolver([("report.pdf", "copied-file-id")])
        source = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{
                        "type": "mediaInline",
                        "attrs": {
                            "id": "copied-file-id",
                            "collection": "contentId-300"}}]}]}
        pandoc = PandocRunner()

        markdown = ADFToMarkdownConverter(pandoc, media).convert(source)
        uploaded = MarkdownToADFConverter(pandoc, media, "contentId-300").convert(markdown)

        self.assertIn("[report.pdf](_attachments/report.pdf)", markdown)
        attrs = uploaded["content"][0]["content"][0]["attrs"]
        self.assertEqual((attrs["id"], attrs["collection"]), ("copied-file-id", "contentId-300"))
        self.assertEqual(uploaded["content"][0]["content"][0]["type"], "mediaInline")

    def test_maps_an_image_beside_other_content_to_inline_media(self) -> None:
        pandoc = self._mixed_paragraph("_attachments/diagram.png")

        document = MarkdownToADFConverter(pandoc, MediaResolver([("diagram.png", "file-1")]), "contentId-123456").convert("source")

        self.assertEqual(
            document["content"][0]["content"][1], {
                "type": "mediaInline",
                "attrs": {
                    "type": "file",
                    "id": "file-1",
                    "collection": "contentId-123456"}})

    def test_rejects_an_inline_image_outside_the_attachments_directory(self) -> None:
        pandoc = self._mixed_paragraph("https://example.test/logo.png")

        with self.assertRaisesRegex(ConversionError, "managed attachment"):
            MarkdownToADFConverter(pandoc, MediaResolver([("diagram.png", "file-1")]), "contentId-123456").convert("source")

    def test_round_trips_inline_media(self) -> None:
        pandoc = PandocRunner()
        media = MediaResolver([("diagram.png", "file-1")])
        source = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type":
                    "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Before "}, {
                                "type": "mediaInline",
                                "attrs": {
                                    "type": "file",
                                    "id": "file-1",
                                    "collection": "contentId-123456",
                                    "alt": "diagram.png"}}, {
                                        "type": "text",
                                        "text": " after."}]}]}

        markdown = ADFToMarkdownConverter(pandoc, media).convert(source)

        self.assertEqual(markdown, "Before ![diagram.png](_attachments/diagram.png) after.\n")
        self.assertEqual(MarkdownToADFConverter(pandoc, media, "contentId-123456").convert(markdown), source)

    def test_rejects_malformed_or_misplaced_opaque_markers(self) -> None:
        malformed = RecordingPandoc(pandoc_document([{"t": "CodeBlock", "c": [["", ["atlas_doc_format"], []], "not json"]}]))
        misplaced = RecordingPandoc(
            pandoc_document([{
                "t": "CodeBlock",
                "c": [["", ["atlas_doc_format"], []], '{"type":"text","text":"inline"}']}]))
        altered = RecordingPandoc(
            pandoc_document([{
                "t": "CodeBlock",
                "c": [["", ["atlas_doc_format", "python"], []], '{"type":"panel"}']}]))

        with self.assertRaisesRegex(ConversionError, "invalid JSON"):
            MarkdownToADFConverter(malformed).convert("source")

        with self.assertRaisesRegex(ConversionError, "block context"):
            MarkdownToADFConverter(misplaced).convert("source")

        with self.assertRaisesRegex(ConversionError, "unsupported attributes"):
            MarkdownToADFConverter(altered).convert("source")


class RecordingLinks:
    """A link resolver that maps chosen targets and records every call with its text."""

    def __init__(self, replacements=None):
        self.replacements = replacements or {}
        self.calls = []

    def to_adf(self, href, text):
        self.calls.append((href, text))
        return self.replacements.get(href)


def _link_marks(node):
    """Yield (text, link attributes) for every linked text node below *node*."""
    if isinstance(node, dict):
        for mark in node.get("marks", []):
            if mark.get("type") == "link":
                yield node.get("text"), mark["attrs"]

        for value in node.values():
            yield from _link_marks(value)
    elif isinstance(node, list):
        for value in node:
            yield from _link_marks(value)


class TestMarkdownToADFLinkResolution(unittest.TestCase):

    URL = "https://example.test/wiki/spaces/K/pages/300"

    def test_replaces_a_link_target_and_keeps_its_text_and_title(self) -> None:
        links = RecordingLinks({"../B_300/content.md#Notes": self.URL + "#Notes"})

        document = MarkdownToADFConverter(PandocRunner(), links=links).convert('[Read B](../B_300/content.md#Notes "About B")\n')

        self.assertEqual(list(_link_marks(document)), [("Read B", {"href": self.URL + "#Notes", "title": "About B"})])
        self.assertEqual(links.calls, [("../B_300/content.md#Notes", "Read B")])

    def test_keeps_a_link_target_when_the_resolver_returns_none(self) -> None:
        links = RecordingLinks()

        document = MarkdownToADFConverter(PandocRunner(), links=links).convert("[Notes](notes.md)\n")

        self.assertEqual(list(_link_marks(document)), [("Notes", {"href": "notes.md", "title": ""})])

    def test_converts_unchanged_without_a_resolver(self) -> None:
        document = MarkdownToADFConverter(PandocRunner()).convert("[B](../B_300/content.md)\n")

        self.assertEqual(list(_link_marks(document)), [("B", {"href": "../B_300/content.md", "title": ""})])

    def test_passes_plain_link_text_and_an_empty_text_for_formatted_links(self) -> None:
        links = RecordingLinks()

        MarkdownToADFConverter(PandocRunner(), links=links).convert("[Plain text](a.md) [**Bold**](b.md)\n")

        self.assertEqual(links.calls, [("a.md", "Plain text"), ("b.md", "")])

    def test_passes_an_empty_text_for_code_link_content(self) -> None:
        # ADF cannot combine code and link marks, so the link itself is refused, as without a resolver.
        links = RecordingLinks()

        with self.assertRaisesRegex(ConversionError, "Pandoc code has unsupported marks"):
            MarkdownToADFConverter(PandocRunner(), links=links).convert("[`code`](c.md)\n")

        self.assertEqual(links.calls, [("c.md", "")])

    def test_replaces_link_targets_in_formatted_links(self) -> None:
        links = RecordingLinks({"../B_300/content.md": self.URL})

        document = MarkdownToADFConverter(PandocRunner(), links=links).convert("[**Bold** link](../B_300/content.md)\n")

        self.assertEqual({attrs["href"] for _, attrs in _link_marks(document)}, {self.URL})

    def test_replaces_link_targets_in_pipe_and_html_tables(self) -> None:
        links = RecordingLinks({"../B_300/content.md": self.URL})
        pipe = "| Head |\n| --- |\n| [Cell](../B_300/content.md) |\n"
        html = '<table><tbody><tr><td><p><a href="../B_300/content.md">Cell</a></p></td></tr></tbody></table>\n'
        for name, markdown in (("pipe", pipe), ("html", html)):
            with self.subTest(table=name):
                links.calls.clear()

                document = MarkdownToADFConverter(PandocRunner(), links=links).convert(markdown)

                self.assertEqual(list(_link_marks(document)), [("Cell", {"href": self.URL, "title": ""})])
                self.assertEqual(links.calls, [("../B_300/content.md", "Cell")])

    def test_does_not_pass_links_in_opaque_adf_fences(self) -> None:
        links = RecordingLinks({"../B_300/content.md": self.URL})
        paragraph = {
            "type": "paragraph",
            "content": [{
                "type": "text",
                "text": "B",
                "marks": [{
                    "type": "link",
                    "attrs": {
                        "href": "../B_300/content.md"}}]}]}
        markdown = "```atlas_doc_format\n" + json.dumps(paragraph) + "\n```\n"

        document = MarkdownToADFConverter(PandocRunner(), links=links).convert(markdown)

        self.assertEqual(list(_link_marks(document)), [("B", {"href": "../B_300/content.md"})])
        self.assertEqual(links.calls, [])

    def test_does_not_pass_images_or_attachment_links(self) -> None:
        links = RecordingLinks()
        media = MediaResolver([("diagram.png", "file-1"), ("report.pdf", "file-2")])

        MarkdownToADFConverter(
            PandocRunner(), media, "contentId-1",
            links=links).convert("![A diagram](_attachments/diagram.png)\n\n[report.pdf](_attachments/report.pdf)\n")

        self.assertEqual(links.calls, [])


class TestMarkdownToADFSoftBreaks(unittest.TestCase):
    """A line wrapped within a paragraph converts like a space, as the GFM writer and renderers treat it."""

    def _convert(self, markdown, links=None):
        media = MediaResolver([("diagram.png", "file-1"), ("chart.png", "file-2")])
        return MarkdownToADFConverter(PandocRunner(), media, "contentId-123456", links=links).convert(markdown)

    def test_joins_a_wrapped_paragraph_with_a_space(self) -> None:
        document = self._convert("Wrapped\nparagraph\n")

        self.assertEqual(document["content"], [{"type": "paragraph", "content": [{"type": "text", "text": "Wrapped paragraph"}]}])

    def test_converts_wrapped_content_like_spaced_content(self) -> None:
        cases = {
            "marked text": ("**bold\ntext** after\n", "**bold text** after\n"),
            "image description": ("![A\ndiagram](_attachments/diagram.png)\n", "![A diagram](_attachments/diagram.png)\n"),
            "image group": (
                "![A](_attachments/diagram.png)\n![B](_attachments/chart.png)\n",
                "![A](_attachments/diagram.png) ![B](_attachments/chart.png)\n"),
            "task marker": ("- ☐\n  task\n", "- ☐ task\n"),
            "HTML table cell": (
                "<table><tbody><tr><td><p>a\nb</p></td></tr></tbody></table>\n",
                "<table><tbody><tr><td><p>a b</p></td></tr></tbody></table>\n"), }
        for name, (wrapped, spaced) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self._convert(wrapped), self._convert(spaced))

    def test_passes_wrapped_link_text_to_the_resolver_with_a_space(self) -> None:
        links = RecordingLinks()

        self._convert("[link\ntext](a.md)\n", links)

        self.assertEqual(links.calls, [("a.md", "link text")])


def _text(text, *marks):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)

    return node


def _paragraph(*content):
    return {"type": "paragraph", "content": list(content)}


def _list_item(*blocks):
    return {"type": "listItem", "content": list(blocks)}


STATUS = {"type": "status", "attrs": {"text": "OPEN", "color": "green"}}
UNDERLINE = {"type": "underline"}
SUPERSCRIPT = {"type": "subsup", "attrs": {"type": "sup"}}

# Constructs whose Markdown form is raw HTML or that Pandoc's HTML reader represents differently from its GFM reader, each
# alone and in the nested positions a table cell admits.
HTML_CELL_CONSTRUCTS = {
    "underline": _paragraph(_text("u", UNDERLINE)),
    "subscript": _paragraph(_text("s", {
        "type": "subsup",
        "attrs": {
            "type": "sub"}})),
    "superscript": _paragraph(_text("s", SUPERSCRIPT)),
    "strong underline": _paragraph(_text("bu", {"type": "strong"}, UNDERLINE)),
    "status": _paragraph(STATUS),
    "date": _paragraph({
        "type": "date",
        "attrs": {
            "timestamp": "1767225600000"}}),
    "mention": _paragraph({
        "type": "mention",
        "attrs": {
            "id": "account-2",
            "text": "@Bob",
            "accessLevel": "CONTAINER"}}),
    "status in a heading": {
        "type": "heading",
        "attrs": {
            "level": 3},
        "content": [_text("Heading "), STATUS]},
    "status in a nested bullet list": {
        "type": "bulletList",
        "content":
        [_list_item(_paragraph(STATUS), {
            "type": "bulletList",
            "content": [_list_item(_paragraph(_text("c", UNDERLINE)))]})]},
    "ordered list": {
        "type": "orderedList",
        "attrs": {
            "order": 1},
        "content": [_list_item(_paragraph(_text("a")))]},
    "ordered list from 3 with superscript": {
        "type": "orderedList",
        "attrs": {
            "order": 3},
        "content": [_list_item(_paragraph(_text("a", SUPERSCRIPT)))]},
    "nested task list with status": {
        "type":
        "taskList",
        "content": [
            {
                "type": "taskItem",
                "attrs": {
                    "state": "TODO"},
                "content": [_text("todo "), STATUS]}, {
                    "type": "taskList",
                    "content": [{
                        "type": "taskItem",
                        "attrs": {
                            "state": "DONE"},
                        "content": [_text("done")]}]}]},
    "code block with language": {
        "type": "codeBlock",
        "attrs": {
            "language": "python"},
        "content": [_text("if a < b:\n    pass")]},
    "code block in a list item": {
        "type":
        "bulletList",
        "content":
        [_list_item(_paragraph(_text("a")), {
            "type": "codeBlock",
            "attrs": {
                "language": "sql"},
            "content": [_text("select 1")]})]},
    "status in a blockquote": {
        "type": "blockquote",
        "content": [_paragraph(STATUS)]},
    "status in a panel": {
        "type": "panel",
        "attrs": {
            "panelType": "warning"},
        "content": [_paragraph(STATUS)]}, }


class TestMarkdownToADFHTMLTableCells(unittest.TestCase):
    """Content of a table written as HTML converts back as it does outside a table."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_converts_cell_content_as_outside_a_table(self) -> None:
        for name, block in HTML_CELL_CONSTRUCTS.items():
            with self.subTest(construct=name):
                _, expected = self._round_trip([block])
                cell = {"type": "tableCell", "attrs": {}, "content": [block, _paragraph(_text("second"))]}
                markdown, document = self._round_trip([{"type": "table", "content": [{"type": "tableRow", "content": [cell]}]}])

                self.assertIn("<table>", markdown)
                self.assertEqual(document[0]["content"][-1]["content"][0]["content"], [*expected, _paragraph(_text("second"))])

    def test_writes_code_blocks_in_cells_without_syntax_highlighting(self) -> None:
        block = HTML_CELL_CONSTRUCTS["code block with language"]
        cell = {"type": "tableCell", "attrs": {}, "content": [block, _paragraph(_text("second"))]}

        markdown, _ = self._round_trip([{"type": "table", "content": [{"type": "tableRow", "content": [cell]}]}])

        self.assertIn('<pre class="python"><code>if a &lt; b:\n    pass</code></pre>', markdown)
        self.assertNotIn("sourceCode", markdown)

    def test_reads_syntax_highlighted_code_blocks_written_by_earlier_releases(self) -> None:
        markdown = (
            '<table>\n<tbody>\n<tr>\n<td><div class="sourceCode" id="cb1"><pre class="sourceCode python">'
            '<code class="sourceCode python"><span id="cb1-1"><a href="#cb1-1" aria-hidden="true" tabindex="-1"></a>'
            '<span class="bu">print</span>(<span class="dv">1</span>)</span></code></pre></div>\n<p>second</p></td>\n'
            '</tr>\n</tbody>\n</table>\n')

        document = MarkdownToADFConverter(self.pandoc).convert(markdown)

        self.assertEqual(
            document["content"][0]["content"][-1]["content"][0]["content"],
            [{
                "type": "codeBlock",
                "attrs": {
                    "language": "python"},
                "content": [_text("print(1)")]},
             _paragraph(_text("second"))])

    def test_rejects_raw_html_in_cells_that_has_no_adf_form(self) -> None:
        markdown = '<table>\n<tbody>\n<tr>\n<td><p>On <time datetime="2026-01-01">1 January</time></p>\n<p>second</p></td>\n</tr>\n</tbody>\n</table>\n'

        with self.assertRaises(ConversionError):
            MarkdownToADFConverter(self.pandoc).convert(markdown)

    def test_rejects_a_span_in_a_cell_that_is_not_a_cflsync_span(self) -> None:
        markdown = '<table>\n<tbody>\n<tr>\n<td><p><span class="note">x</span></p>\n<p>second</p></td>\n</tr>\n</tbody>\n</table>\n'

        with self.assertRaisesRegex(ConversionError, "only emoji and cflsync spans"):
            MarkdownToADFConverter(self.pandoc).convert(markdown)


# vim: set ts=4 sw=4 et tw=132:
