# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for Markdown to ADF conversion."""

import json
import unittest
from types import SimpleNamespace

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
                                                "type": "hardBreak"}, {
                                                    "type": "text",
                                                    "text": "after the break"},
                    ], }, {
                        "type": "heading",
                        "attrs": {
                            "level": 2},
                        "content": [{
                            "type": "text",
                            "text": "Heading"}]}, {
                                "type": "blockquote",
                                "content": [{
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

    def test_maps_a_time_element_to_utc_midnight_and_ignores_its_text(self) -> None:
        for text in ("April 1, 2026", "changed text", ""):
            with self.subTest(text=text):
                document = MarkdownToADFConverter(PandocRunner()).convert(f'On <time datetime="2026-04-01">{text}</time>\n')

                self.assertEqual(
                    document["content"][0], {
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": "On "}, {
                                "type": "date",
                                "attrs": {
                                    "timestamp": "1775001600000"}}]})

    def test_round_trips_a_date(self) -> None:
        source = {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{
                    "type": "date",
                    "attrs": {
                        "timestamp": "1775001600000"}}]}]}
        pandoc = PandocRunner()

        markdown = ADFToMarkdownConverter(pandoc).convert(source)
        document = MarkdownToADFConverter(pandoc).convert(markdown)

        self.assertEqual(markdown, '<time datetime="2026-04-01">April 1, 2026</time>\n')
        self.assertEqual(document, source)

    def test_pushes_a_date_off_utc_midnight_at_utc_midnight_of_its_utc_date(self) -> None:
        pandoc = PandocRunner()
        source = {"type": "doc", "version": 1, "content": [_paragraph({"type": "date", "attrs": {"timestamp": "1775086200000"}})]}

        document = MarkdownToADFConverter(pandoc).convert(ADFToMarkdownConverter(pandoc).convert(source))

        self.assertEqual(document["content"], [_paragraph({"type": "date", "attrs": {"timestamp": "1775001600000"}})])

    def test_rejects_date_spans_of_earlier_releases(self) -> None:
        for markdown in ('<span cfl-type="date">2026-04-01[Europe/Brussels]</span>\n', '<span cfl-type="date">2026-04-01</span>\n',
                         '<span cfl-type="date" cfl-timestamp="1775001600000">April 1</span>\n'):
            with self.subTest(markdown=markdown):
                with self.assertRaisesRegex(ConversionError, "date spans are no longer supported"):
                    MarkdownToADFConverter(PandocRunner()).convert(markdown)

    def test_rejects_invalid_time_elements(self) -> None:
        cases = {
            "<time>April 1</time>\n": "YYYY-MM-DD",
            '<time datetime="2026-4-1">April 1</time>\n': "YYYY-MM-DD",
            '<time datetime="2026-04-01T10:00">April 1</time>\n': "YYYY-MM-DD",
            '<time datetime="2026-02-30">February 30</time>\n': "not a calendar date",
            '<time datetime="2026-04-01">April 1\n': "not closed",
            '**<time datetime="2026-04-01">April 1</time>**\n': "unsupported marks", }
        for markdown, message in cases.items():
            with self.subTest(markdown=markdown):
                with self.assertRaisesRegex(ConversionError, message):
                    MarkdownToADFConverter(PandocRunner()).convert(markdown)

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
        links = RecordingLinks({"c.md": self.URL})

        document = MarkdownToADFConverter(PandocRunner(), links=links).convert("[`code`](c.md)\n")

        self.assertEqual(links.calls, [("c.md", "")])
        self.assertEqual(
            document["content"],
            [_paragraph(_text("code", {
                "type": "link",
                "attrs": {
                    "href": self.URL,
                    "title": ""}}, {"type": "code"}))])

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

EMPTY_PARAGRAPH = {"type": "paragraph", "content": []}


class TestMarkdownToADFEmptyListItems(unittest.TestCase):
    """A list item holding only an empty paragraph is written as a bare marker and converts back to the same item."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_round_trips_empty_items_in_every_position(self) -> None:
        a, b = _list_item(_paragraph(_text("a"))), _list_item(_paragraph(_text("b")))
        empty = _list_item({"type": "paragraph"})
        expected_empty = _list_item(EMPTY_PARAGRAPH)
        cases = {
            "last": ({
                "type": "bulletList",
                "content": [a, empty]}, [a, expected_empty]),
            "first": ({
                "type": "bulletList",
                "content": [empty, a]}, [expected_empty, a]),
            "only": ({
                "type": "bulletList",
                "content": [empty]}, [expected_empty]),
            "ordered middle": ({
                "type": "orderedList",
                "attrs": {
                    "order": 4},
                "content": [a, empty, b]}, [a, expected_empty, b]), }
        for name, (block, expected_items) in cases.items():
            with self.subTest(position=name):
                _, document = self._round_trip([block])

                self.assertEqual(document, [{**block, "content": expected_items}])

    def test_restores_the_empty_paragraph_before_a_nested_list(self) -> None:
        nested = {"type": "bulletList", "content": [_list_item(_paragraph(_text("n")))]}
        block = {"type": "bulletList", "content": [_list_item({"type": "paragraph"}, nested)]}

        markdown, document = self._round_trip([block])

        self.assertEqual(markdown, "- \n  - n\n")
        self.assertEqual(document, [{"type": "bulletList", "content": [_list_item(EMPTY_PARAGRAPH, nested)]}])

    def test_reads_bare_markers_without_trailing_space(self) -> None:
        document = MarkdownToADFConverter(self.pandoc).convert("- a\n-\n- b\n")

        self.assertEqual(
            document["content"], [
                {
                    "type": "bulletList",
                    "content": [
                        _list_item(_paragraph(_text("a"))),
                        _list_item(EMPTY_PARAGRAPH),
                        _list_item(_paragraph(_text("b")))]}])

    def test_round_trips_empty_items_in_html_table_cells(self) -> None:
        a = _list_item(_paragraph(_text("a")))
        cell = {
            "type": "tableCell",
            "attrs": {},
            "content": [{
                "type": "bulletList",
                "content": [a, _list_item({"type": "paragraph"})]},
                        _paragraph(_text("z"))]}

        markdown, document = self._round_trip([{"type": "table", "content": [{"type": "tableRow", "content": [cell]}]}])

        self.assertIn("<li></li>", markdown)
        self.assertEqual(
            document[0]["content"][-1]["content"][0]["content"],
            [{
                "type": "bulletList",
                "content": [a, _list_item(EMPTY_PARAGRAPH)]},
             _paragraph(_text("z"))])


def _code_block(text, language=None):
    return {"type": "codeBlock", "attrs": {"language": language} if language else {}, "content": [_text(text)]}


LIST_ITEM_SECOND_BLOCKS = {
    "paragraph": _paragraph(_text("b")),
    "code block without language": _code_block("select 1"),
    "code block with language": _code_block("select 1", "sql"),
    "pipe table": {
        "type":
        "table",
        "content": [
            {
                "type": "tableRow",
                "content": [_cell("tableHeader", [_paragraph(_text("h"))])]}, {
                    "type": "tableRow",
                    "content": [_cell("tableCell", [_paragraph(_text("c"))])]}]},
    "nested list": {
        "type": "bulletList",
        "content": [_list_item(_paragraph(_text("n")))]},
    "nested list with an empty first item": {
        "type": "bulletList",
        "content": [_list_item(EMPTY_PARAGRAPH), _list_item(_paragraph(_text("n")))]},
    "nested ordered list from 1": {
        "type": "orderedList",
        "attrs": {
            "order": 1},
        "content": [_list_item(_paragraph(_text("n")))]},
    "nested ordered list from 3": {
        "type": "orderedList",
        "attrs": {
            "order": 3},
        "content": [_list_item(_paragraph(_text("n")))]},
    "nested ordered list with an empty first item": {
        "type": "orderedList",
        "attrs": {
            "order": 1},
        "content": [_list_item(EMPTY_PARAGRAPH), _list_item(_paragraph(_text("n")))]},
    "heading": {
        "type": "heading",
        "attrs": {
            "level": 3},
        "content": [_text("h")]},
    "blockquote": {
        "type": "blockquote",
        "content": [_paragraph(_text("q"))]},
    "rule": {
        "type": "rule"},
    "panel": {
        "type": "panel",
        "attrs": {
            "panelType": "warning"},
        "content": [_paragraph(_text("p"))]}, }


class TestMarkdownToADFListItemBlocks(unittest.TestCase):
    """A block after the first paragraph of a list item converts back as a separate block, not as paragraph text."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_round_trips_every_block_after_the_first_paragraph(self) -> None:
        for name, second in LIST_ITEM_SECOND_BLOCKS.items():
            for list_type in ("bulletList", "orderedList"):
                with self.subTest(block=name, list=list_type):
                    item = _list_item(_paragraph(_text("a")), second)
                    _, document = self._round_trip([{"type": list_type, "content": [item]}])

                    content = document[0]["content"][0]["content"]
                    self.assertEqual([block["type"] for block in content], ["paragraph", second["type"]])
                    self.assertEqual(content[0], _paragraph(_text("a")))

    def test_round_trips_in_a_nested_list(self) -> None:
        inner = {"type": "bulletList", "content": [_list_item(_paragraph(_text("a")), _paragraph(_text("b")))]}
        block = {"type": "bulletList", "content": [_list_item(_paragraph(_text("n")), inner)]}

        _, document = self._round_trip([block])

        self.assertEqual(document, [block])

    def test_writes_the_list_loose_when_a_block_would_continue_the_paragraph(self) -> None:
        block = {
            "type":
            "bulletList",
            "content": [
                _list_item(_paragraph(_text("x"))),
                _list_item(_paragraph(_text("a")), _code_block("select 1")),
                _list_item(_paragraph(_text("y")))]}

        markdown, document = self._round_trip([block])

        self.assertEqual(markdown, "- x\n\n- a\n\n      select 1\n\n- y\n")
        self.assertEqual(document[0]["content"][1]["content"][1], {"type": "codeBlock", "content": [_text("select 1")]})

    def test_keeps_the_list_tight_when_the_next_block_ends_the_paragraph(self) -> None:
        cases = {
            "code block with language":
            ([_list_item(_paragraph(_text("a")), _code_block("select 1", "sql"))], "- a\n  ``` sql\n  select 1\n  ```\n"),
            "nested list": ([_list_item(_paragraph(_text("a")), LIST_ITEM_SECOND_BLOCKS["nested list"])], "- a\n  - n\n"),
            "single paragraphs": ([_list_item(_paragraph(_text("a"))),
                                   _list_item(_paragraph(_text("b")))], "- a\n- b\n"), }
        for name, (items, expected) in cases.items():
            with self.subTest(case=name):
                markdown, _ = self._round_trip([{"type": "bulletList", "content": items}])

                self.assertEqual(markdown, expected)


def _bullet_list(*texts):
    return {"type": "bulletList", "content": [_list_item(_paragraph(_text(text))) for text in texts]}


def _ordered_list(*texts):
    return {"type": "orderedList", "attrs": {"order": 1}, "content": [_list_item(_paragraph(_text(text))) for text in texts]}


def _task_list(text):
    return {"type": "taskList", "content": [{"type": "taskItem", "attrs": {"state": "TODO"}, "content": [_text(text)]}]}


PLAIN_CODE = {"type": "codeBlock", "content": [_text("select 1")]}
SEPARATED_BLOCKS = {
    "code block after a list": [_bullet_list("a"), PLAIN_CODE],
    "bullet list after a bullet list": [_bullet_list("a"), _bullet_list("b")],
    "ordered list after an ordered list": [_ordered_list("a"), _ordered_list("b")],
    "task list after a task list": [_task_list("a"), _task_list("b")],
    "task list after a bullet list": [_bullet_list("a"), _task_list("b")],
    "code block after a code block": [PLAIN_CODE, {
        "type": "codeBlock",
        "content": [_text("select 2")]}], }


class TestMarkdownToADFBlockSeparators(unittest.TestCase):
    """Blocks that Markdown would read as one are written with an empty HTML comment between them."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_round_trips_separated_blocks_in_every_position(self) -> None:
        for name, (first, second) in SEPARATED_BLOCKS.items():
            for separated_by_empty_paragraph in (False, True):
                blocks = [first, EMPTY_PARAGRAPH, second] if separated_by_empty_paragraph else [first, second]
                positions = {
                    "top level": ([*blocks], lambda document: document),
                    "list item": (
                        [{
                            "type": "bulletList",
                            "content": [_list_item(_paragraph(_text("n")),
                                                   *blocks)]}], lambda document: document[0]["content"][0]["content"][1:]),
                    "blockquote": ([{
                        "type": "blockquote",
                        "content": [*blocks]}], lambda document: document[0]["content"]),
                    "html table cell": (
                        [
                            {
                                "type": "table",
                                "content":
                                [{
                                    "type": "tableRow",
                                    "content": [_cell("tableCell", [*blocks, _paragraph(_text("z"))])]}]}],
                        lambda document: document[0]["content"][-1]["content"][0]["content"][:-1]), }
                for position, (content, inner) in positions.items():
                    with self.subTest(blocks=name, empty_paragraph=separated_by_empty_paragraph, position=position):
                        _, document = self._round_trip(content)

                        self.assertEqual(inner(document), [first, second])

    def test_writes_an_empty_comment_between_separated_blocks(self) -> None:
        markdown, _ = self._round_trip([_bullet_list("a"), EMPTY_PARAGRAPH, _bullet_list("b")])

        self.assertEqual(markdown, "- a\n\n<!-- -->\n\n- b\n")

    def test_writes_no_separator_between_lists_of_different_kinds(self) -> None:
        markdown, document = self._round_trip([_ordered_list("a"), _bullet_list("b")])

        self.assertEqual(markdown, "1.  a\n\n- b\n")
        self.assertEqual(document, [_ordered_list("a"), _bullet_list("b")])

    def test_ignores_every_comment_only_block(self) -> None:
        for comment in ("<!-- -->", "<!-- note -->", "<!--\nnote\n-->", "<!---->"):
            with self.subTest(comment=comment):
                document = MarkdownToADFConverter(self.pandoc).convert(f"- a\n\n{comment}\n\n- b\n")

                self.assertEqual(document["content"], [_bullet_list("a"), _bullet_list("b")])

    def test_ignores_comments_between_blocks_of_html_table_cells(self) -> None:
        markdown = "<table>\n<tbody>\n<tr>\n<td><p>a</p>\n<!-- note -->\n<p>b</p></td>\n</tr>\n</tbody>\n</table>\n"

        document = MarkdownToADFConverter(self.pandoc).convert(markdown)

        self.assertEqual(
            document["content"][0]["content"][0]["content"][0]["content"],
            [_paragraph(_text("a")), _paragraph(_text("b"))])

    def test_rejects_a_comment_inside_a_paragraph(self) -> None:
        with self.assertRaises(ConversionError):
            MarkdownToADFConverter(self.pandoc).convert("a <!-- note --> b\n")

    def test_rejects_a_raw_block_with_more_than_one_comment(self) -> None:
        with self.assertRaisesRegex(ConversionError, "raw content other than an HTML table"):
            MarkdownToADFConverter(self.pandoc).convert("<!-- a --><div>b</div>\n")


def _link(href):
    return {"type": "link", "attrs": {"href": href}}


class TestMarkdownToADFCodeLinks(unittest.TestCase):
    """Code inside a link converts to text with link and code marks, the only mark ADF combines with code."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_round_trips_code_in_a_link(self) -> None:
        link = {"type": "link", "attrs": {"href": "https://a.test/x", "title": ""}}
        # In HTML table cells, Pandoc moves spaces at the edges of link text outside the link, so only the top-level case
        # has linked spaces.
        top = _paragraph(_text("see "), _text("a ", link), _text("x", link, {"type": "code"}), _text(" b", link))
        in_cell = _paragraph(_text("see "), _text("x", link, {"type": "code"}), _text(" now"))
        cases = {
            "top level": ([top], top, lambda document: document[0]),
            "html table cell": (
                [
                    {
                        "type": "table",
                        "content": [{
                            "type": "tableRow",
                            "content": [_cell("tableCell", [in_cell, _paragraph(_text("z"))])]}]}], in_cell,
                lambda document: document[0]["content"][-1]["content"][0]["content"][0]), }
        for name, (content, expected, inner) in cases.items():
            with self.subTest(position=name):
                _, document = self._round_trip(content)

                self.assertEqual(inner(document), expected)

    def test_writes_code_inside_the_link(self) -> None:
        markdown, _ = self._round_trip([_paragraph(_text("x", _link("https://a.test/x"), {"type": "code"}))])

        self.assertEqual(markdown, "[`x`](https://a.test/x)\n")

    def test_rejects_code_with_other_marks(self) -> None:
        for markdown in ("**`x`**\n", "*`x`*\n", "[**`x`**](https://a.test/x)\n"):
            with self.subTest(markdown=markdown):
                with self.assertRaisesRegex(ConversionError, "Pandoc code has unsupported marks"):
                    MarkdownToADFConverter(self.pandoc).convert(markdown)


NBSP = " "
EM, STRONG, STRIKE, CODE = {"type": "em"}, {"type": "strong"}, {"type": "strike"}, {"type": "code"}


class TestMarkdownToADFMarkEdgeWhitespace(unittest.TestCase):
    """Whitespace at the edges of emphasis, strong, and strike text is written outside the delimiters, without the mark."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_moves_edge_whitespace_out_of_the_mark(self) -> None:
        cases = {
            "em before code": (
                [_text(f"a{NBSP}", EM), _text("x", CODE),
                 _text(f"{NBSP}b", EM)], [_text("a", EM),
                                          _text(NBSP), _text("x", CODE),
                                          _text(NBSP), _text("b", EM)]),
            "strong before text": ([_text(f"a{NBSP}", STRONG), _text("b")], [_text("a", STRONG),
                                                                             _text(f"{NBSP}b")]),
            "strike after text": ([_text("a"), _text(f"{NBSP}b", STRIKE)], [_text(f"a{NBSP}"),
                                                                            _text("b", STRIKE)]),
            "both edges, several characters": (
                [_text("a"), _text(f"{NBSP} b c {NBSP}", EM, STRONG),
                 _text("d")], [_text(f"a{NBSP} "), _text("b c", EM, STRONG),
                               _text(f" {NBSP}d")]),
            "space before non-breaking space": ([_text("a"), _text(f" {NBSP}b", EM)], [_text(f"a {NBSP}"),
                                                                                       _text("b", EM)]),
            "whitespace only": ([_text("a"), _text(NBSP, EM), _text("b")], [_text(f"a{NBSP}b")]),
            "adjacent marks": ([_text(f"a{NBSP}", EM), _text("b", STRONG)], [_text("a", EM),
                                                                             _text(NBSP),
                                                                             _text("b", STRONG)]), }
        for name, (content, expected) in cases.items():
            with self.subTest(case=name):
                _, document = self._round_trip([_paragraph(*content)])

                self.assertEqual(document, [_paragraph(*expected)])

    def test_keeps_outer_marks_on_the_moved_whitespace(self) -> None:
        link = {"type": "link", "attrs": {"href": "https://a.test/x", "title": ""}}
        underline = {"type": "underline"}

        _, document = self._round_trip([_paragraph(_text(f"a{NBSP}", EM, link), _text(f"c{NBSP}", EM, underline), _text("d"))])

        self.assertEqual(
            document,
            [_paragraph(_text("a", link, EM), _text(NBSP, link), _text("c", underline, EM), _text(NBSP, underline), _text("d"))])

    def test_writes_the_whitespace_outside_the_delimiters(self) -> None:
        markdown, _ = self._round_trip([_paragraph(_text(f"a{NBSP}", EM), _text("x", CODE))])

        self.assertEqual(markdown, f"*a*{NBSP}`x`\n")

    def test_round_trips_in_an_html_table_cell(self) -> None:
        cell = _cell("tableCell", [_paragraph(_text(f"a{NBSP}", EM), _text("x", CODE)), _paragraph(_text("z"))])

        _, document = self._round_trip([{"type": "table", "content": [{"type": "tableRow", "content": [cell]}]}])

        self.assertEqual(
            document[0]["content"][-1]["content"][0]["content"][0], _paragraph(_text("a", EM), _text(NBSP), _text("x", CODE)))


HARD_BREAK = {"type": "hardBreak"}


class TestMarkdownToADFTrailingHardBreaks(unittest.TestCase):
    """A hard break at the end of a block has no Markdown form; it is dropped instead of being pushed as a backslash."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_drops_hard_breaks_at_the_end_of_a_block(self) -> None:
        task = lambda *content: {
            "type": "taskList",
            "content": [{
                "type": "taskItem",
                "attrs": {
                    "state": "TODO"},
                "content": list(content)}]}
        heading = lambda *content: {"type": "heading", "attrs": {"level": 2}, "content": list(content)}
        cases = {
            "paragraph": ([_paragraph(_text("a"), HARD_BREAK)], [_paragraph(_text("a"))]),
            "several breaks and spaces": ([_paragraph(_text("a "), HARD_BREAK, _text(" "), HARD_BREAK)], [_paragraph(_text("a"))]),
            "list item": ([_bullet_list_of(_paragraph(_text("a"), HARD_BREAK))], [_bullet_list_of(_paragraph(_text("a")))]),
            "heading": ([heading(_text("h"), HARD_BREAK)], [heading(_text("h"))]),
            "task item": ([task(_text("t"), HARD_BREAK)], [task(_text("t"))]),
            "break only": (
                [_paragraph(_text("a")), _paragraph(HARD_BREAK),
                 _paragraph(_text("b"))], [_paragraph(_text("a")), _paragraph(_text("b"))]), }
        for name, (content, expected) in cases.items():
            with self.subTest(block=name):
                markdown, document = self._round_trip(content)

                self.assertNotIn("\\", markdown)
                self.assertEqual(document, expected)

    def test_keeps_hard_breaks_inside_a_block(self) -> None:
        paragraph = _paragraph(HARD_BREAK, _text("a"), HARD_BREAK, _text("b"))

        _, document = self._round_trip([paragraph])

        self.assertEqual(document, [paragraph])

    def test_drops_a_trailing_hard_break_in_an_html_table_cell(self) -> None:
        cell = _cell("tableCell", [_paragraph(_text("a"), HARD_BREAK), _paragraph(_text("z"))])

        _, document = self._round_trip([{"type": "table", "content": [{"type": "tableRow", "content": [cell]}]}])

        self.assertEqual(document[0]["content"][-1]["content"][0]["content"], [_paragraph(_text("a")), _paragraph(_text("z"))])


def _bullet_list_of(*blocks):
    return {"type": "bulletList", "content": [_list_item(*blocks)]}


class TestMarkdownToADFAttachmentPaths(unittest.TestCase):
    """Attachment paths are percent-encoded, so every attachment filename converts back to the same media."""

    NAMES = ("Pasted image 20260601.png", "a)b (1).png", "café.png", "plan v2.pdf")

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _media(self):
        return MediaResolver((name, f"file-{number}") for number, name in enumerate(self.NAMES))

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc, self._media()).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc, self._media(), "contentId-1").convert(markdown)["content"]

    @staticmethod
    def _media_node(number, name):
        return {"type": "media", "attrs": {"type": "file", "id": f"file-{number}", "collection": "contentId-1", "alt": name}}

    def test_round_trips_images_and_attachment_links(self) -> None:
        for number, name in enumerate(self.NAMES):
            media = self._media_node(number, name)
            if name.endswith(".pdf"):
                block = _paragraph(_text("see "), {**media, "type": "mediaInline"})
            else:
                block = {"type": "mediaSingle", "attrs": {"layout": "center"}, "content": [media]}
            for position, content, inner in (("top level", [block], lambda document: document[0]),
                                             ("html table cell", [{"type": "table", "content":
                                                                   [{"type": "tableRow", "content":
                                                                     [_cell("tableCell", [block, _paragraph(_text("z"))])]}]}],
                                              lambda document: document[0]["content"][-1]["content"][0]["content"][0])):
                with self.subTest(name=name, position=position):
                    _, document = self._round_trip(content)

                    self.assertEqual(inner(document), block)

    def test_writes_the_encoded_path(self) -> None:
        markdown, _ = self._round_trip(
            [{
                "type": "mediaSingle",
                "attrs": {
                    "layout": "center"},
                "content": [self._media_node(0, "x")]}])

        self.assertEqual(markdown, "![x](_attachments/Pasted%20image%2020260601.png)\n")

    def test_reads_unencoded_paths_of_earlier_releases(self) -> None:
        document = MarkdownToADFConverter(self.pandoc, self._media(), "contentId-1").convert("![c](_attachments/café.png)\n")

        self.assertEqual(document["content"][0]["content"][0]["attrs"]["id"], "file-2")

    def test_reads_angle_bracket_paths(self) -> None:
        markdown = "![p](<_attachments/Pasted image 20260601.png>)\n"

        document = MarkdownToADFConverter(self.pandoc, self._media(), "contentId-1").convert(markdown)

        self.assertEqual(document["content"][0]["content"][0]["attrs"]["id"], "file-0")


class TestMarkdownToADFBareURLs(unittest.TestCase):
    """URL-shaped text is not autolinked: it converts back as written, inside and outside links."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_round_trips_link_text_that_is_another_url(self) -> None:
        text = _text("https://a.test/pages/1/Title", _link("https://a.test/pages/1"))

        markdown, document = self._round_trip([_paragraph(text)])

        self.assertEqual(markdown, "[https://a.test/pages/1/Title](https://a.test/pages/1)\n")
        self.assertEqual(
            document, [
                _paragraph(
                    _text(
                        "https://a.test/pages/1/Title", {
                            "type": "link",
                            "attrs": {
                                "href": "https://a.test/pages/1",
                                "title": ""}}))])

    def test_keeps_url_shaped_text_as_text(self) -> None:
        for text in ("see https://a.test/x now", "see www.a.test now", "mail a@b.test now"):
            with self.subTest(text=text):
                _, document = self._round_trip([_paragraph(_text(text))])

                self.assertEqual(document, [_paragraph(_text(text))])

    def test_reads_angle_bracket_autolinks_as_links(self) -> None:
        document = MarkdownToADFConverter(self.pandoc).convert("<https://a.test/x>\n")

        self.assertEqual(
            document["content"],
            [_paragraph(_text("https://a.test/x", {
                "type": "link",
                "attrs": {
                    "href": "https://a.test/x",
                    "title": ""}}))])


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
        markdown = '<table>\n<tbody>\n<tr>\n<td><p>Press <kbd>Ctrl</kbd></p>\n<p>second</p></td>\n</tr>\n</tbody>\n</table>\n'

        with self.assertRaises(ConversionError):
            MarkdownToADFConverter(self.pandoc).convert(markdown)

    def test_rejects_a_span_in_a_cell_that_is_not_a_cflsync_span(self) -> None:
        markdown = '<table>\n<tbody>\n<tr>\n<td><p><span class="note">x</span></p>\n<p>second</p></td>\n</tr>\n</tbody>\n</table>\n'

        with self.assertRaisesRegex(ConversionError, "only emoji and cflsync spans"):
            MarkdownToADFConverter(self.pandoc).convert(markdown)


# vim: set ts=4 sw=4 et tw=132:
