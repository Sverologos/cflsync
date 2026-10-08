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
from cflsync.convert import STATUS_COLORS


class RecordingPandoc:

    def __init__(self, pandoc):
        self.pandoc = pandoc
        self.markdown = None

    def gfm_to_pandoc(self, markdown):
        self.markdown = markdown
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
                        "panelType": "info"},
                    "content": [{
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": "Note content."}]}]}, {
                                "type": "panel",
                                "attrs": {
                                    "panelType": "success"},
                                "content": [{
                                    "type": "paragraph",
                                    "content": [{
                                        "type": "text",
                                        "text": "Tip content."}]}]},
                {
                    "type": "panel",
                    "attrs": {
                        "panelType": "note"},
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

        with self.assertRaisesRegex(ConversionError, "only emoji, colour, highlight, status, and cflsync spans"):
            MarkdownToADFConverter(pandoc).convert("source")

    def test_rejects_raw_html_that_is_not_a_table(self) -> None:
        pandoc = RecordingPandoc(pandoc_document([{"t": "RawBlock", "c": ["html", "<div>text</div>"]}]))

        with self.assertRaisesRegex(ConversionError, "HTML table"):
            MarkdownToADFConverter(pandoc).convert("source")

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

    def test_passes_plain_link_text_and_an_empty_text_for_formatted_links(self) -> None:
        links = RecordingLinks()

        MarkdownToADFConverter(PandocRunner(), links=links).convert("[Plain text](a.md) [**Bold**](b.md)\n")

        self.assertEqual(links.calls, [("a.md", "Plain text"), ("b.md", "")])


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
TEXT_COLOUR = {"type": "textColor", "attrs": {"color": "#Ab1234"}}
HIGHLIGHT = {"type": "backgroundColor", "attrs": {"color": "#F8E6A0"}}

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
    "text colour": _paragraph(_text("colour", TEXT_COLOUR)),
    "highlight": _paragraph(_text("highlight", HIGHLIGHT)),
    "formatted colours": _paragraph(_text("both", TEXT_COLOUR, HIGHLIGHT, UNDERLINE, {"type": "strong"})),
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


class TestMarkdownToADFBlockSeparators(unittest.TestCase):
    """Blocks that Markdown would read as one are written with an empty HTML comment between them."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        return markdown, MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_writes_an_empty_comment_between_separated_blocks(self) -> None:
        markdown, _ = self._round_trip([_bullet_list("a"), EMPTY_PARAGRAPH, _bullet_list("b")])

        self.assertEqual(markdown, "- a\n\n<!-- -->\n\n- b\n")

    def test_writes_no_separator_between_lists_of_different_kinds(self) -> None:
        markdown, document = self._round_trip([_ordered_list("a"), _bullet_list("b")])

        self.assertEqual(markdown, "1.  a\n\n- b\n")
        self.assertEqual(document, [_ordered_list("a"), _bullet_list("b")])

    def test_ignores_comments_between_blocks_of_html_table_cells(self) -> None:
        markdown = "<table>\n<tbody>\n<tr>\n<td><p>a</p>\n<!-- note -->\n<p>b</p></td>\n</tr>\n</tbody>\n</table>\n"

        document = MarkdownToADFConverter(self.pandoc).convert(markdown)

        self.assertEqual(
            document["content"][0]["content"][0]["content"][0]["content"],
            [_paragraph(_text("a")), _paragraph(_text("b"))])

    def test_rejects_a_comment_inside_a_paragraph(self) -> None:
        with self.assertRaises(ConversionError):
            MarkdownToADFConverter(self.pandoc).convert("a <!-- note --> b\n")


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
    def _media_node(number, name) -> dict:
        return {"type": "media", "attrs": {"type": "file", "id": f"file-{number}", "collection": "contentId-1", "alt": name}}

    def test_writes_the_encoded_path(self) -> None:
        markdown, _ = self._round_trip(
            [{
                "type": "mediaSingle",
                "attrs": {
                    "layout": "center"},
                "content": [self._media_node(0, "x")]}])

        self.assertEqual(markdown, "![x](_attachments/Pasted%20image%2020260601.png)\n")

    def test_writes_a_single_image_as_an_image_whatever_its_file_name(self) -> None:
        media = self._media_node(3, "plan v2.pdf")
        block = {"type": "mediaSingle", "attrs": {"layout": "center"}, "content": [media]}

        markdown, document = self._round_trip([block])
        group_markdown, _ = self._round_trip([{"type": "mediaGroup", "content": [media]}])

        self.assertEqual(markdown, "![plan v2.pdf](_attachments/plan%20v2.pdf)\n")
        self.assertEqual(
            document, [
                {
                    "type":
                    "mediaSingle",
                    "attrs": {
                        "layout": "center"},
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                key: value
                                for key, value in media["attrs"].items() if key != "alt"}}, {
                                    "type": "caption",
                                    "content": [_text("plan v2.pdf")]}]}])
        self.assertEqual(group_markdown, "[plan v2.pdf](_attachments/plan%20v2.pdf)\n")

    def test_labels_media_without_alt_text_with_the_decoded_filename(self) -> None:
        for number, name in enumerate(self.NAMES):
            attrs = {"type": "file", "id": f"file-{number}", "collection": "contentId-1"}
            media = {"type": "media", "attrs": attrs}
            labelled = {"type": "media", "attrs": {**attrs, "alt": name}}
            block: dict[str, object]
            if name.endswith(".pdf"):
                block = {"type": "mediaGroup", "content": [media]}
                pushed = _paragraph({"type": "mediaInline", "attrs": labelled["attrs"]})
            else:
                block = {"type": "mediaSingle", "attrs": {"layout": "center"}, "content": [media]}
                pushed = {
                    "type": "mediaSingle",
                    "attrs": {
                        "layout": "center"},
                    "content": [media, {
                        "type": "caption",
                        "content": [_text(name)]}]}
            with self.subTest(name=name):
                markdown, document = self._round_trip([block])

                self.assertIn(f"[{name}](_attachments/", markdown.replace("\\", ""))
                self.assertEqual(document, [pushed])


class TestMarkdownToADFHTMLTableCells(unittest.TestCase):
    """Content of a table written as HTML converts back as it does outside a table."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        content = MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]
        assert isinstance(content, list)
        return markdown, content

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


def _column(width, *blocks):
    return {"type": "layoutColumn", "attrs": {"width": width}, "content": list(blocks)}


def _layout(*columns, breakout=None):
    node = {"type": "layoutSection", "content": list(columns)}
    if breakout is not None:
        node["marks"] = [{"type": "breakout", "attrs": breakout}]
    return node


class TestLayouts(unittest.TestCase):
    """Layout sections are written as twg's HTML form with a generic type around Markdown column bodies."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _markdown(self, content):
        return ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})

    def _adf(self, markdown):
        return MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_round_trips_a_layout_with_breakout_and_column_widths(self) -> None:
        layout = _layout(
            _column(49.99, _bullet_list("a", "b")),
            _column(50.0, _bullet_list("c"), _paragraph(_text("d"))),
            breakout={
                "mode": "wide",
                "width": 1800})
        content = [_paragraph(_text("before")), layout, _paragraph(_text("after"))]

        markdown = self._markdown(content)

        self.assertEqual(
            markdown, "before\n\n"
            '<section data-type="layout-section" data-breakout="wide" data-breakout-width="1800">\n'
            '<div data-type="column" data-width="49.99">\n\n- a\n- b\n\n</div>\n'
            '<div data-type="column" data-width="50">\n\n- c\n\nd\n\n</div>\n</section>\n\nafter\n')
        self.assertEqual(self._adf(markdown), content)

    def test_round_trips_layouts_without_breakout_and_with_an_empty_column(self) -> None:
        cases = {
            "single column": [_layout(_column(100.0, _paragraph(_text("x"))))],
            "empty column": [_layout(_column(50.0, EMPTY_PARAGRAPH), _column(50.0, _paragraph(_text("y"))))],
            "full width without width": [_layout(_column(100.0, _paragraph(_text("z"))), breakout={"mode": "full-width"})],
            "two layouts": [_layout(_column(100.0, _paragraph(_text("a")))),
                            _layout(_column(100.0, _paragraph(_text("b"))))], }
        for name, content in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self._adf(self._markdown(content)), content)

    def test_reads_twg_section_types_local_ids_and_tags_without_blank_lines(self) -> None:
        markdown = (
            '<section data-local-id="s" data-type="layout-two-equal">\n<div data-type="column" data-width="50">\n\nx\n\n'
            '</div>\n<div data-local-id="c" data-type="column" data-width="50">\n\ny\n\n</div>\n</section>\n')

        self.assertEqual(
            self._adf(markdown), [_layout(_column(50.0, _paragraph(_text("x"))), _column(50.0, _paragraph(_text("y"))))])

    def test_reads_legacy_and_joined_layout_tag_lines(self) -> None:
        expected = [_layout(_column(50.0, _paragraph(_text("a"))), _column(50.0, _paragraph(_text("b"))))]
        fixtures = (
            '<section data-type="layout-section">\n\n<div data-type="column" data-width="50">\n\na\n\n</div>\n\n'
            '<div data-type="column" data-width="50">\n\nb\n\n</div>\n\n</section>\n',
            '<section data-type="layout-section">\n<div data-type="column" data-width="50">\n\na\n\n</div>\n'
            '<div data-type="column" data-width="50">\n\nb\n\n</div>\n</section>\n')
        for markdown in fixtures:
            with self.subTest(markdown=markdown):
                self.assertEqual(self._adf(markdown), expected)

    def test_keeps_a_layout_with_unsupported_attributes_opaque(self) -> None:
        layout = _layout(_column(100.0, _paragraph(_text("x"))))
        layout["attrs"] = {"unknown": True}

        markdown = self._markdown([layout])

        self.assertIn("``` atlas_doc_format", markdown)
        self.assertEqual(self._adf(markdown), [layout])

    def test_rejects_malformed_layouts(self) -> None:
        column = '<div data-type="column" data-width="50">\n\nx\n\n</div>\n\n'
        cases = {
            "not closed": ('<section data-type="layout-section">\n\n' + column, "not closed with </section>"),
            "column not closed":
            ('<section data-type="layout-section">\n\n<div data-type="column" data-width="50">\n\nx\n', "column is not closed"),
            "content outside a column":
            ('<section data-type="layout-section">\n\nx\n\n' + column + "</section>\n", "must be inside a column"),
            "no columns": ('<section data-type="layout-section">\n\n</section>\n', "has no columns"),
            "column outside a section": (column, "outside a layout section"),
            "nested section": (
                '<section data-type="layout-section">\n\n<div data-type="column" data-width="50">\n\n'
                '<section data-type="layout-section">\n\n', "cannot be nested"),
            "inside a list item": ('- a\n\n  <section data-type="layout-section">\n', "only at the top level"),
            "invalid width": (
                '<section data-type="layout-section">\n\n<div data-type="column" data-width="0">\n\nx\n\n'
                "</div>\n\n</section>\n", "data-width between 0 and 100"),
            "unsupported attribute":
            ('<section data-type="layout-section" style="x">\n\n' + column + "</section>\n", "unsupported attribute 'style'"),
            "breakout width without mode": (
                '<section data-type="layout-section" data-breakout-width="1800">\n\n' + column + "</section>\n",
                "without data-breakout"), }
        for name, (markdown, message) in cases.items():
            with self.subTest(case=name):
                with self.assertRaisesRegex(ConversionError, message):
                    self._adf(markdown)


def _panel(panel_type, *content, **attrs):
    return {"type": "panel", "attrs": {"panelType": panel_type, **attrs}, "content": list(content)}


CUSTOM_PANEL_ATTRS = {"panelIcon": ":dart:", "panelColor": "#F4F5F7", "panelIconId": "1f3af", "panelIconText": "🎯"}


class TestPanels(unittest.TestCase):
    """Panels are GFM alerts where an alert holds them, and twg's <div data-type="panel-TYPE"> otherwise."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _markdown(self, content):
        return ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})

    def _adf(self, markdown):
        return MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_maps_panel_types_one_to_one_to_alerts(self) -> None:
        alerts = {"info": "NOTE", "note": "IMPORTANT", "success": "TIP", "warning": "WARNING", "error": "CAUTION"}
        for panel_type, alert in alerts.items():
            with self.subTest(panel_type=panel_type):
                content = [_panel(panel_type, _paragraph(_text("x")))]

                markdown = self._markdown(content)

                self.assertEqual(markdown, f"> [!{alert}]\n> x\n")
                self.assertEqual(self._adf(markdown), content)

    def test_writes_custom_tip_and_coloured_panels_as_twg_divs(self) -> None:
        custom = _panel("custom", _paragraph(_text('a & "<b>"')), _bullet_list("i"), **CUSTOM_PANEL_ATTRS)
        cases = {
            "custom": (
                [custom], '<div data-type="panel-custom" data-icon=":dart:" data-color="#F4F5F7" data-icon-id="1f3af" '
                'data-icon-text="🎯">\n\na & "\\<b\\>"\n\n- i\n\n</div>\n'),
            "tip": ([_panel("tip", _paragraph(_text("x")))], '<div data-type="panel-tip">\n\nx\n\n</div>\n'),
            "coloured info": (
                [_panel("info", _paragraph(_text("x")),
                        panelColor='a"b')], '<div data-type="panel-info" data-color="a&quot;b">\n\nx\n\n</div>\n'),
            "empty": (
                [_panel("custom", EMPTY_PARAGRAPH,
                        panelColor="#F4F5F7")], '<div data-type="panel-custom" data-color="#F4F5F7">\n\n</div>\n'), }
        for name, (content, expected) in cases.items():
            with self.subTest(case=name):
                markdown = self._markdown(content)

                self.assertEqual(markdown, expected)
                self.assertEqual(self._adf(markdown), content)

    def test_round_trips_panels_in_columns_cells_and_list_items(self) -> None:
        custom = _panel("custom", _paragraph(_text("c")), **CUSTOM_PANEL_ATTRS)
        cell = {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1}}
        cases = {
            "layout column": [_layout(_column(50.0, custom), _column(50.0, _panel("tip", _paragraph(_text("t")))))],
            "table cell": [
                {
                    "type":
                    "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content":
                            [{
                                **cell, "content": [custom]}, {
                                    **cell, "content": [_panel("note", _paragraph(_text("n")))]}]}]}],
            "list item": [{
                "type": "bulletList",
                "content": [_list_item(_paragraph(_text("a")), custom)]}], }
        for name, content in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self._adf(self._markdown(content)), content)

    def test_reads_twg_panels_with_local_ids_and_tags_without_blank_lines(self) -> None:
        markdown = '<div data-local-id="p" data-type="panel-custom" data-icon="&#x1F3AF;">\n\nx\n\n</div>\n'

        self.assertEqual(self._adf(markdown), [_panel("custom", _paragraph(_text("x")), panelIcon="🎯")])

    def test_reads_legacy_and_joined_nested_panel_tags(self) -> None:
        expected = [_panel("custom", _panel("tip", _paragraph(_text("x"))))]
        fixtures = (
            '<div data-type="panel-custom">\n\n<div data-type="panel-tip">\n\nx\n\n</div>\n\n</div>\n',
            '<div data-type="panel-custom">\n<div data-type="panel-tip">\n\nx\n\n</div>\n</div>\n')
        for markdown in fixtures:
            with self.subTest(markdown=markdown):
                self.assertEqual(self._adf(markdown), expected)

    def test_keeps_a_panel_with_unsupported_attributes_opaque(self) -> None:
        panel = _panel("custom", _paragraph(_text("x")), unknown="y")

        markdown = self._markdown([panel])

        self.assertIn("``` atlas_doc_format", markdown)
        self.assertEqual(self._adf(markdown), [panel])

    def test_rejects_malformed_panels(self) -> None:
        cases = {
            "not closed": ('<div data-type="panel-info">\n\nx\n', "panel is not closed"),
            "invalid type": ('<div data-type="panel-x">\n\nx\n\n</div>\n', "invalid data-type 'panel-x'"),
            "unsupported attribute": ('<div data-type="panel-info" style="x">\n\nx\n\n</div>\n', "unsupported attribute 'style'"),
            "layout inside": (
                '<div data-type="panel-info">\n\n<section data-type="layout-section">\n\n</section>\n\n</div>\n',
                "only at the top level"),
            "in a cell": (
                '<table><tr><td><div data-type="panel-info" style="x"><p>x</p></div></td></tr></table>\n',
                "unsupported attribute 'style'"), }
        for name, (markdown, message) in cases.items():
            with self.subTest(case=name):
                with self.assertRaisesRegex(ConversionError, message):
                    self._adf(markdown)


def _status(text, color, style=None, **extra):
    attrs = {"text": text, "color": color, **extra}
    if style is not None:
        attrs["style"] = style

    return {"type": "status", "attrs": attrs}


class TestStatus(unittest.TestCase):
    """A status is written in twg's form, a <span data-type="status" data-color data-status-style> around its text."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _markdown(self, content):
        return ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})

    def _adf(self, markdown):
        return MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_writes_twg_status_spans(self) -> None:
        cases = {
            "with style": (
                _status("In *review*", "blue",
                        "bold"), '<span data-type="status" data-color="blue" data-status-style="bold">In \\*review\\*</span>'),
            "without style": (_status("Done", "green"), '<span data-type="status" data-color="green">Done</span>'),
            "escaped style":
            (_status("x", "red", 'a"b'), '<span data-type="status" data-color="red" data-status-style="a&quot;b">x</span>'), }
        for name, (status, expected) in cases.items():
            with self.subTest(case=name):
                content = [_paragraph(_text("State: "), status)]

                markdown = self._markdown(content)

                self.assertEqual(markdown, f"State: {expected}\n")
                self.assertEqual(self._adf(markdown), content)

    def test_round_trips_every_colour_in_paragraphs_and_html_table_cells(self) -> None:
        statuses = [_status(color.upper(), color, style) for color in sorted(STATUS_COLORS) for style in ("bold", "mixedCase")]
        cell = {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1}}
        cases = {
            "paragraph": [_paragraph(*statuses)],
            "html table cell": [
                {
                    "type":
                    "table",
                    "content":
                    [{
                        "type": "tableRow",
                        "content": [{
                            **cell, "content": [_paragraph(*statuses), _paragraph(_text("second"))]}]}]}], }
        for name, content in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self._adf(self._markdown(content)), content)

    def test_reads_twg_defaults_and_local_ids(self) -> None:
        markdown = (
            '<span data-type="status">a</span> <span data-local-id="x" data-color="green" '
            'data-type="status" data-status-style="bold">b</span>\n')

        self.assertEqual(self._adf(markdown), [_paragraph(_status("a", "neutral"), _text(" "), _status("b", "green", "bold"))])

    def test_keeps_a_status_with_unsupported_attributes_opaque(self) -> None:
        for name, status in {"attribute": _status("x", "green", unknown="y"), "colour": _status("x", "orange")}.items():
            with self.subTest(case=name):
                content = [_paragraph(status)]

                markdown = self._markdown(content)

                self.assertIn("``` atlas_doc_format", markdown)
                self.assertEqual(self._adf(markdown), content)

    def test_rejects_malformed_statuses(self) -> None:
        cases = {
            "cfl-type form": ('<span cfl-type="status" style="background-color: green">Done</span>\n', "no longer supported"),
            "invalid colour": ('<span data-type="status" data-color="orange">x</span>\n', "invalid data-color 'orange'"),
            "unsupported attribute": ('<span data-type="status" style="x">x</span>\n', "unsupported attribute 'style'"),
            "no text": ('<span data-type="status" data-color="green"></span>\n', "status needs text"),
            "in a cell":
            ('<table><tr><td><span data-type="status" data-color="orange">x</span></td></tr></table>\n', "invalid data-color"), }
        for name, (markdown, message) in cases.items():
            with self.subTest(case=name):
                with self.assertRaisesRegex(ConversionError, message):
                    self._adf(markdown)


def _card(url):
    return {"type": "inlineCard", "attrs": {"url": url}}


class TestInlineCards(unittest.TestCase):
    """Inline cards are written in twg's form, an <a> with data-card-appearance="inline" around the URL."""

    URL = "https://example.atlassian.net/browse/X_1?a=1&b=*2*|c"

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _markdown(self, content):
        return ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})

    def _adf(self, markdown):
        return MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_round_trips_a_card_in_a_paragraph(self) -> None:
        content = [_paragraph(_text("see "), _card(self.URL), _text(" now"))]

        markdown = self._markdown(content)

        self.assertEqual(
            markdown, 'see <a href="https://example.atlassian.net/browse/X_1?a=1&amp;b=*2*&#124;c" '
            'data-card-appearance="inline">https://example.atlassian.net/browse/X_1?a=1&b=\\*2\\*\\|c</a> now\n')
        self.assertEqual(self._adf(markdown), content)

    def test_round_trips_a_card_in_pipe_and_html_table_cells(self) -> None:
        header = {"type": "tableRow", "content": [_cell("tableHeader", [_paragraph(_text("h"))])]}
        # Pandoc's HTML reader percent-encodes "|" in an href, as for links, so the HTML table uses a URL without it.
        cases = {
            "pipe table": [_paragraph(_card(self.URL))],
            "html table": [_paragraph(_card(self.URL.replace("|", ""))),
                           _paragraph(_text("second"))], }
        for name, blocks in cases.items():
            with self.subTest(table=name):
                table = {"type": "table", "content": [header, {"type": "tableRow", "content": [_cell("tableCell", blocks)]}]}

                document = self._adf(self._markdown([table]))

                self.assertEqual(document[0]["content"][1]["content"][0]["content"], blocks)

    def test_reads_twg_local_ids_and_ignores_the_card_text(self) -> None:
        markdown = '<a data-local-id="l" href="https://a.test/x" data-card-appearance="inline">edited text</a>\n'

        self.assertEqual(self._adf(markdown), [_paragraph(_card("https://a.test/x"))])

    def test_keeps_cards_with_data_or_marks_opaque(self) -> None:
        for name, card in {"data": {"type": "inlineCard", "attrs": {"data": {"name": "x"}}}, "marks":
                           {**_card("https://a.test/x"), "marks": [{"type": "annotation", "attrs": {"id": "1"}}]}, }.items():
            with self.subTest(card=name):
                self.assertIn("``` atlas_doc_format", self._markdown([_paragraph(card)]))

    def test_rejects_malformed_cards(self) -> None:
        card = '<a href="https://a.test/x" data-card-appearance="inline">x</a>'
        cases = {
            "other raw link": ('<a href="https://a.test/x">x</a>\n', "raw HTML links are not supported"),
            "formatted": (f"**{card}**\n", "cannot be formatted"),
            "missing href": ('<a data-card-appearance="inline">x</a>\n', "needs an href"),
            "not closed": ('<a href="https://a.test/x" data-card-appearance="inline">x\n', "not closed"),
            "unsupported attribute": (card.replace("<a ", '<a title="t" ') + "\n", "unsupported attribute 'title'"), }
        for name, (markdown, message) in cases.items():
            with self.subTest(case=name):
                with self.assertRaisesRegex(ConversionError, message):
                    self._adf(markdown)


def _expand(title, *content, nested=False, breakout=None):
    node = {"type": "nestedExpand" if nested else "expand", "attrs": {"title": title}, "content": list(content)}
    if breakout is not None:
        node["marks"] = [{"type": "breakout", "attrs": breakout}]
    return node


class TestExpands(unittest.TestCase):
    """Expands use twg's details and summary tags around editable Markdown bodies."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _markdown(self, content):
        return ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})

    def _adf(self, markdown):
        return MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_round_trips_title_breakout_and_markdown_body(self) -> None:
        expand = _expand(
            ' A & "<b>" **literal** ',
            _paragraph(_text("bold", {"type": "strong"})),
            _bullet_list("a", "b"),
            breakout={
                "mode": "wide",
                "width": 1800})
        content = [_paragraph(_text("before")), expand, _paragraph(_text("after"))]

        markdown = self._markdown(content)

        self.assertEqual(
            markdown, 'before\n\n<details data-breakout="wide" data-breakout-width="1800">\n'
            '<summary> A &amp; &quot;&lt;b&gt;&quot; **literal** </summary>\n\n'
            '**bold**\n\n- a\n- b\n\n</details>\n\nafter\n')
        self.assertEqual(self._adf(markdown), content)

    def test_round_trips_nested_expands_in_tables_and_columns(self) -> None:
        nested = _expand(" a\t b\n<&> ", _paragraph(_text("x")), nested=True)
        table = {
            "type":
            "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [_cell("tableHeader", [_paragraph(_text("h"))])]}, {
                        "type": "tableRow",
                        "content": [_cell("tableCell", [nested, _paragraph(_text("z"))])]}]}
        expand = _expand("outer", table, _expand("inner", _bullet_list("i"), nested=True))
        cases = [[expand], [_layout(_column(100.0, expand))], [table]]
        for content in cases:
            with self.subTest(content=content):
                markdown = self._markdown(content)
                self.assertIn('<details data-type="nested-expand">', markdown)
                self.assertEqual(self._adf(markdown), content)

    def test_keeps_panel_and_expand_container_boundaries_separate(self) -> None:
        expand = _expand("t", _paragraph(_text("x")), _panel("custom", _paragraph(_text("y")), panelColor="#F4F5F7"))
        cases = [
            [_panel("custom", expand, _paragraph(_text("after")), panelColor="#F4F5F7")],
            [{
                "type": "blockquote",
                "content": [expand, _paragraph(_text("after"))]}],
            [{
                "type": "bulletList",
                "content": [_list_item(_paragraph(_text("before")), expand)]}]]
        for content in cases:
            with self.subTest(content=content):
                self.assertEqual(self._adf(self._markdown(content)), content)

    def test_keeps_code_and_opaque_content_inside_expands(self) -> None:
        expand = _expand(
            "t", {
                "type": "codeBlock",
                "attrs": {
                    "language": "html"},
                "content": [_text("</details>\n<summary>code</summary>")]}, {
                    "type": "extension",
                    "attrs": {
                        "extensionKey": "toc",
                        "extensionType": "macro"}}, _paragraph(_text("after")))
        self.assertEqual(self._adf(self._markdown([expand])), [expand])

    def test_reads_twg_local_ids_empty_titles_and_adjacent_tag_lines(self) -> None:
        markdown = '<details data-local-id="e">\n<summary></summary>\n\nx\n\n</details>\n'
        self.assertEqual(self._adf(markdown), [_expand("", _paragraph(_text("x")))])
        for breakout in ({"mode": "full-width"}, {"mode": "wide", "width": 960.5}):
            content = [_expand("t", EMPTY_PARAGRAPH, breakout=breakout)]
            with self.subTest(breakout=breakout):
                self.assertEqual(self._adf(self._markdown(content)), content)

    def test_reads_compact_html_and_preserves_title_whitespace(self) -> None:
        self.assertEqual(
            self._adf('<details><summary> a  &amp; b </summary><p>x</p></details>\n'),
            [_expand(" a  & b ", _paragraph(_text("x")))])

    def test_reads_legacy_and_joined_expand_tags_in_nested_contexts(self) -> None:
        expand = _expand("A & B", _paragraph(_text("x")))
        fixtures = (
            (
                [expand], '<details>\n\n<summary>A &amp; B</summary>\n\nx\n\n</details>\n',
                '<details>\n<summary>A &amp; B</summary>\n\nx\n\n</details>\n'), (
                    [_expand("outer", _expand("I\nT", _paragraph(_text("x")), nested=True))
                     ], '<details>\n\n<summary>outer</summary>\n\n<details data-type="nested-expand">\n\n'
                    '<summary>I&#10;T</summary>\n\nx\n\n</details>\n\n</details>\n',
                    '<details>\n<summary>outer</summary>\n<details data-type="nested-expand">\n'
                    '<summary>I&#10;T</summary>\n\nx\n\n</details>\n</details>\n'), (
                        [{
                            "type": "bulletList",
                            "content": [_list_item(_paragraph(_text("item")), expand)]}
                         ], '- item\n\n  <details>\n\n  <summary>A &amp; B</summary>\n\n  x\n\n  </details>\n',
                        '- item\n\n  <details>\n  <summary>A &amp; B</summary>\n\n  x\n\n  </details>\n'), (
                            [{
                                "type": "blockquote",
                                "content": [expand]}], '> <details>\n>\n> <summary>A &amp; B</summary>\n>\n> x\n>\n> </details>\n',
                            '> <details>\n> <summary>A &amp; B</summary>\n>\n> x\n>\n> </details>\n'))
        for expected, legacy, compact in fixtures:
            for markdown in (legacy, compact):
                with self.subTest(markdown=markdown):
                    self.assertEqual(self._adf(markdown), expected)

    def test_retitle_preserves_legacy_and_joined_expand_tags(self) -> None:
        fixtures = (
            '<details>\n\n<summary>T</summary>\n\nx\n\n</details>\n', '<details>\n<summary>T</summary>\n\nx\n\n</details>\n')
        reverse = MarkdownToADFConverter(self.pandoc)
        for body in fixtures:
            with self.subTest(body=body):
                renamed = reverse.retitle("# Old\n\n" + body, "Old", "New")
                self.assertEqual(renamed, "# New\n\n" + body)
                self.assertEqual(reverse.convert(renamed, title="New")["content"], [_expand("T", _paragraph(_text("x")))])

    def test_reads_ordinary_details_in_a_cell_as_nested_expand(self) -> None:
        markdown = '<table><tr><td><details><summary>T</summary><p>x</p></details></td></tr></table>\n'
        self.assertEqual(
            self._adf(markdown)[0]["content"][0]["content"][0]["content"], [_expand("T", _paragraph(_text("x")), nested=True)])

    def test_repairs_an_empty_body_with_a_paragraph(self) -> None:
        self.assertEqual(self._adf('<details>\n\n<summary>T</summary>\n\n</details>\n'), [_expand("T", EMPTY_PARAGRAPH)])

    def test_keeps_unsupported_expands_opaque_and_reads_old_fences(self) -> None:
        valid = _expand("t", _paragraph(_text("x")))
        cases = [
            {
                **valid, "attrs": {
                    "title": "t",
                    "unknown": True}}, {
                        **valid, "attrs": {
                            "title": 1}}, {
                                **valid, "marks": [{
                                    "type": "other"}]},
            _expand("t", EMPTY_PARAGRAPH, nested=True, breakout={"mode": "wide"}),
            _expand("t", EMPTY_PARAGRAPH, breakout={
                "mode": "wide",
                "width": float("inf")}),
            _expand("t", EMPTY_PARAGRAPH, breakout={
                "mode": "wide",
                "width": True}),
            _expand("t", EMPTY_PARAGRAPH, breakout={"mode": "other"}),
            _expand("t", EMPTY_PARAGRAPH, breakout={"mode": ["wide"]}),
            _expand("t")]
        for content in cases:
            with self.subTest(content=content):
                markdown = self._markdown([content])
                self.assertIn("``` atlas_doc_format", markdown)
                self.assertEqual(self._adf(markdown), [content])
        self.assertEqual(self._adf("```atlas_doc_format\n" + json.dumps(valid) + "\n```\n"), [valid])

    def test_rejects_malformed_expands(self) -> None:
        start = '<details>\n\n<summary>T</summary>\n\n'
        cases = {
            "unclosed": (start + "x\n", "not closed with </details>"),
            "no summary": ('<details>\n\nx\n\n</details>\n', "needs a plain-text <summary>"),
            "unknown type": (start.replace('<details>', '<details data-type="other">') + '</details>\n', "invalid data-type"),
            "unknown attribute": (start.replace('<details>', '<details open="true">') + '</details>\n', "unsupported attribute"),
            "bad mode": (start.replace('<details>', '<details data-breakout="other">') + '</details>\n', "invalid data-breakout"),
            "width alone":
            (start.replace('<details>', '<details data-breakout-width="1">') + '</details>\n', "without data-breakout"),
            "nested breakout": (
                start.replace('<details>', '<details data-type="nested-expand" data-breakout="wide">') + '</details>\n',
                "invalid data-breakout"),
            "summary attributes":
            (start.replace('<summary>', '<summary class="x">') + '</details>\n', "needs a plain-text <summary>"),
            "formatted summary": ('<details><summary><b>T</b></summary><p>x</p></details>\n', "only plain text"),
            "unclosed summary": ('<details>\n\n<summary>\n\nx\n', "summary is not closed"),
            "layout inside":
            (start + '<section data-type="layout-section">\n\n</section>\n\n</details>\n', "only at the top level"),
            "second summary": (start + '<summary>other</summary>\n\n</details>\n', "raw content"),
            "orphan summary": ('<summary>T</summary>\n', "raw content"),
            "orphan end": ('</details>\n', "raw content")}
        cases["unknown details tag"] = ('<detailsx>\n', "raw content")
        cases["unsupported opening syntax"] = ("<details data-type='nested-expand'>\n", "raw content")
        for width in ("0", "-1", "nan", "inf", "x"):
            cases[f"bad width {width}"] = (
                start.replace('<details>', f'<details data-breakout="wide" data-breakout-width="{width}">') + '</details>\n',
                "invalid data-breakout-width")
        for name, (markdown, message) in cases.items():
            with self.subTest(case=name):
                with self.assertRaisesRegex(ConversionError, message):
                    self._adf(markdown)


class TestCompactContainerOutput(unittest.TestCase):
    """Writer compaction applies recursively, without changing body spacing or literal code."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    def _markdown(self, content, title=None):
        return ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content}, title=title)

    def _adf(self, markdown):
        return MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]

    def test_writes_joined_tags_with_list_and_quote_prefixes(self) -> None:
        expand = _expand("T", _paragraph(_text("x")))
        item = _list_item(_paragraph(_text("item")), expand)
        cases = (
            ([expand], '<details>\n<summary>T</summary>\n\nx\n\n</details>\n'),
            ([{
                "type": "bulletList",
                "content": [item]}], '- item\n  <details>\n  <summary>T</summary>\n\n  x\n\n  </details>\n'), (
                    [{
                        "type": "orderedList",
                        "attrs": {
                            "order": 1},
                        "content": [item]}], '1.  item\n    <details>\n    <summary>T</summary>\n\n    x\n\n    </details>\n'), (
                            [
                                {
                                    "type": "bulletList",
                                    "content": [_list_item(_paragraph(_text("outer")), {
                                        "type": "bulletList",
                                        "content": [item]})]}],
                            '- outer\n  - item\n    <details>\n    <summary>T</summary>\n\n    x\n\n    </details>\n'),
            ([{
                "type": "blockquote",
                "content": [expand]}], '> <details>\n> <summary>T</summary>\n>\n> x\n>\n> </details>\n'),
            ([_panel("warning", expand)], '> [!WARNING]\n> <details>\n> <summary>T</summary>\n>\n> x\n>\n> </details>\n'))
        for content, expected in cases:
            with self.subTest(content=content):
                markdown = self._markdown(content)
                self.assertEqual(markdown, expected)
                self.assertEqual(self._adf(markdown), content)

    def test_merges_across_nested_and_sibling_container_boundaries(self) -> None:
        nested = _panel("custom", _panel("tip", _paragraph(_text("x"))))
        sibling = _panel("tip", _paragraph(_text("y")))
        content = [nested, sibling]
        markdown = self._markdown(content)
        self.assertEqual(
            markdown, '<div data-type="panel-custom">\n<div data-type="panel-tip">\n\nx\n\n'
            '</div>\n</div>\n<div data-type="panel-tip">\n\ny\n\n</div>\n')
        self.assertEqual(self._adf(markdown), content)

    def test_merges_layout_tags_with_an_expand_body(self) -> None:
        content = [_layout(_column(100.0, _expand("T", _paragraph(_text("x")))))]
        markdown = self._markdown(content)
        self.assertEqual(
            markdown, '<section data-type="layout-section">\n<div data-type="column" data-width="100">\n'
            '<details>\n<summary>T</summary>\n\nx\n\n</details>\n</div>\n</section>\n')
        self.assertEqual(self._adf(markdown), content)

    def test_preserves_nested_expand_summary_and_body_in_html_table_cells(self) -> None:
        nested = _expand(" A\tB\n<&> ", _paragraph(_text("x")), nested=True)
        content = [
            {
                "type": "table",
                "content": [{
                    "type": "tableRow",
                    "content": [_cell("tableCell", [nested, _paragraph(_text("after"))])]}]}]
        markdown = self._markdown(content)
        self.assertEqual(
            markdown, '<table>\n<tbody>\n<tr>\n<td><details data-type="nested-expand">\n'
            '<summary> A&#9;B&#10;&lt;&amp;&gt; </summary>\n<p>x</p>\n</details>\n'
            '<p>after</p></td>\n</tr>\n</tbody>\n</table>\n')
        self.assertEqual(self._adf(markdown), content)

    def test_distinguishes_no_blocks_from_an_empty_paragraph_barrier(self) -> None:
        for content, expected in (([_panel("tip")], '<div data-type="panel-tip">\n</div>\n'),
                                  ([_panel("tip", EMPTY_PARAGRAPH)], '<div data-type="panel-tip">\n\n</div>\n')):
            with self.subTest(content=content):
                markdown = self._markdown(content)
                self.assertEqual(markdown, expected)
                self.assertEqual(self._adf(markdown), [_panel("tip", EMPTY_PARAGRAPH)])

    def test_keeps_non_tag_block_spacing_and_literal_code(self) -> None:
        pipe = LIST_ITEM_SECOND_BLOCKS["pipe table"]
        opaque = {"type": "extension", "attrs": {"extensionType": "macro", "extensionKey": "toc"}}
        code = "</details>\n\n<summary>code</summary>"
        cases = (
            ([_paragraph(_text("a")), _paragraph(_text("b"))], 'a\n\nb'), (
                [
                    _paragraph(_text("a")), {
                        "type": "heading",
                        "attrs": {
                            "level": 2},
                        "content": [_text("H")]},
                    _paragraph(_text("b"))], 'a\n\n## H\n\nb'),
            ([_paragraph(_text("a")), {
                "type": "rule"}, _paragraph(_text("b"))],
             'a\n\n' + '-' * 72 + '\n\nb'), ([_bullet_list("a", "b"), _paragraph(_text("after"))], '- a\n- b\n\nafter'),
            ([_code_block(code, "html")], '``` html\n</details>\n\n<summary>code</summary>\n```'),
            ([{
                "type": "codeBlock",
                "content": [_text(code)]}], '    </details>\n\n    <summary>code</summary>'), ([pipe], '| h   |\n|-----|\n| c   |'),
            ([opaque], '``` atlas_doc_format\n{"attrs":{"extensionKey":"toc","extensionType":"macro"},"type":"extension"}\n```'))
        for body, expected in cases:
            content = [_expand("T", *body)]
            with self.subTest(body=body):
                markdown = self._markdown(content)
                self.assertEqual(markdown, '<details>\n<summary>T</summary>\n\n' + expected + '\n\n</details>\n')
                self.assertEqual(self._adf(markdown), content)

    def test_retitle_preserves_generated_nested_tag_runs(self) -> None:
        content = [_layout(_column(100.0, _expand("T", _paragraph(_text("x"))), _panel("tip", _paragraph(_text("y")))))]
        markdown = self._markdown(content, title="Old")
        self.assertIn('</details>\n<div data-type="panel-tip">', markdown)
        reverse = MarkdownToADFConverter(self.pandoc)
        renamed = reverse.retitle(markdown, "Old", "New")
        self.assertEqual(renamed, '# New\n\n' + markdown[len('# Old\n\n'):])
        self.assertEqual(reverse.convert(renamed, title="New")["content"], content)


class TestImageDescriptions(unittest.TestCase):
    """An unwrapped block image's description is its caption, not independent media alt text."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()
        self.media = MediaResolver([("f.png", "file-1"), ("no-suffix", "file-2")])

    def _adf(self, markdown):
        return MarkdownToADFConverter(self.pandoc, self.media, "contentId-1").convert(markdown)["content"]

    def _markdown(self, content):
        return ADFToMarkdownConverter(self.pandoc, self.media).convert({"type": "doc", "version": 1, "content": content})

    @staticmethod
    def _image(caption, external=False) -> dict:
        attrs = {
            "type": "external",
            "url": "https://example.test/f.png"} if external else {
                "type": "file",
                "id": "file-1",
                "collection": "contentId-1"}
        return {
            "type": "mediaSingle",
            "attrs": {
                "layout": "center"},
            "content": [{
                "type": "media",
                "attrs": attrs}, {
                    "type": "caption",
                    "content": caption}]}

    def test_reads_plain_formatted_and_empty_descriptions_as_captions(self) -> None:
        cases = (("plain caption", [_text("plain caption")]), ("**bold**", [_text("bold", {"type": "strong"})]), ("", []))
        for external in (False, True):
            target = "https://example.test/f.png" if external else "_attachments/f.png"
            for description, caption in cases:
                with self.subTest(description=description, external=external):
                    self.assertEqual(self._adf(f"![{description}]({target})\n"), [self._image(caption, external)])

    def test_legacy_figure_keeps_alt_separate_from_explicit_caption(self) -> None:
        for body, caption in (("", None), ("<figcaption>Caption</figcaption>", [_text("Caption")])):
            with self.subTest(caption=caption):
                markdown = '<figure data-type="media-single">\n\n![Alt](_attachments/f.png)\n\n' + body + '\n</figure>\n'
                image = self._image([])
                image["content"][0]["attrs"]["alt"] = "Alt"
                image["content"] = image["content"][:1] if caption is None else [
                    image["content"][0], {
                        "type": "caption",
                        "content": caption}]
                self.assertEqual(self._adf(markdown), [image])

    def test_caption_precedence_and_captionless_fallbacks_are_stable(self) -> None:
        for external in (False, True):
            for caption in (None, [], [_text("Caption")]):
                for alt in (None, "Independent alt"):
                    with self.subTest(caption=caption, alt=alt, external=external):
                        source = self._image([] if caption is None else caption, external)
                        if caption is None:
                            source["content"].pop()
                        if alt is not None:
                            source["content"][0]["attrs"]["alt"] = alt
                        description = caption if caption is not None else [_text(alt or "f.png")]
                        expected = self._image(description, external)
                        markdown = self._markdown([source])
                        self.assertNotIn("<figure", markdown)
                        self.assertEqual(self._adf(markdown), [expected])
                        self.assertEqual(self._markdown([expected]), markdown)
                        self.assertEqual(self._adf(self._markdown([expected])), [expected])

    def test_round_trips_caption_formatting_and_supported_inline_nodes(self) -> None:
        captions: list[list[dict]] = [[_text("marked", {"type": mark})] for mark in ("strong", "em", "strike", "code")]
        captions.extend(
            [
                [_text("linked", {
                    "type": "link",
                    "attrs": {
                        "href": "https://example.test",
                        "title": ""}})], [_text("first"), {
                            "type": "hardBreak"}, _text("second")]])
        for name in ("underline", "subscript", "superscript", "text colour", "highlight", "formatted colours", "status", "date",
                     "mention"):
            paragraph: dict = HTML_CELL_CONSTRUCTS[name]
            captions.append(paragraph["content"])
        captions.append([_card("https://example.test/card")])
        for caption in captions:
            with self.subTest(caption=caption):
                image = self._image(caption)
                markdown = self._markdown([image])
                self.assertTrue(markdown.startswith("!["))
                self.assertEqual(TestColourMarks._normalized(self._adf(markdown)), TestColourMarks._normalized([image]))

    def test_unicode_emoji_in_caption_follows_existing_text_normalization(self) -> None:
        image = self._image([{"type": "emoji", "attrs": {"shortName": ":smile:", "id": "1f604", "text": "😄"}}])
        self.assertEqual(self._markdown([image]), "![😄](_attachments/f.png)\n")
        self.assertEqual(self._adf(self._markdown([image])), [self._image([_text("😄")])])

    def test_caption_escaping_and_extensionless_targets(self) -> None:
        caption = [_text('literal [brackets] \\ *stars* & "quotes" café')]
        self.media = MediaResolver([("Pasted & café (1).png", "file-1"), ("no-suffix", "file-2")])
        for external in (False, True):
            for extensionless in (False, True):
                with self.subTest(external=external, extensionless=extensionless):
                    image = self._image(caption, external)
                    attrs = image["content"][0]["attrs"]
                    if external:
                        attrs["url"] = "https://example.test/" + ("no-suffix" if extensionless else "f.png?a=1&b=2")
                    elif extensionless:
                        attrs["id"] = "file-2"
                    markdown = self._markdown([image])
                    self.assertEqual(self._adf(markdown), [image])
                    self.assertEqual(self._markdown(self._adf(markdown)), markdown)
                    if not external and not extensionless:
                        self.assertIn("_attachments/Pasted%20%26%20caf%C3%A9%20%281%29.png", markdown)

    def test_inline_images_and_image_groups_keep_alt_text(self) -> None:
        media = self._image([])["content"][0]
        media["attrs"]["alt"] = "Alt"
        inline = {"type": "mediaInline", "attrs": media["attrs"]}
        self.assertEqual(
            self._adf("before ![Alt](_attachments/f.png) after\n"), [_paragraph(_text("before "), inline, _text(" after"))])
        self.assertEqual(
            self._adf("![Alt](_attachments/f.png) ![Alt](_attachments/f.png)\n"),
            [{
                "type": "mediaGroup",
                "content": [media, media]}])

    def test_retitle_preserves_a_formatted_image_description(self) -> None:
        body = self._markdown([self._image([_text("bold", {"type": "strong"})])])
        reverse = MarkdownToADFConverter(self.pandoc, self.media, "contentId-1")
        renamed = reverse.retitle("# Old\n\n" + body, "Old", "New")
        self.assertEqual(renamed, "# New\n\n" + body)
        self.assertEqual(reverse.convert(renamed, title="New")["content"], self._adf(body))

    def test_captioned_images_round_trip_in_block_containers(self) -> None:
        for caption in ([], [_text("Caption")], [_text("bold", {"type": "strong"})]):
            image = self._image(caption)
            cases = (
                [image], [_expand("T", image)], [_panel("warning", image)], [_panel("tip", image)],
                [_layout(_column(100.0, image))], [{
                    "type": "blockquote",
                    "content": [image]}], [{
                        "type": "bulletList",
                        "content": [_list_item(_paragraph(_text("item")), image)]
                    }], [{
                        "type": "orderedList",
                        "attrs": {
                            "order": 1},
                        "content": [_list_item(_paragraph(_text("item")), image)]}])
            for content in cases:
                with self.subTest(caption=caption, container=content[0]["type"]):
                    markdown = self._markdown(content)
                    self.assertNotIn("<figure", markdown)
                    self.assertEqual(self._adf(markdown), content)

    @staticmethod
    def _table(blocks, html=False):
        return {
            "type":
            "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [_cell("tableHeader", [_paragraph(_text("h"))])]}, {
                        "type": "tableRow",
                        "content": [_cell("tableCell", blocks + ([_paragraph(_text("after"))] if html else []))]}]}

    def test_plain_and_empty_captions_round_trip_in_pipe_and_html_tables(self) -> None:
        for caption in ([], [_text("Caption")]):
            for html in (False, True):
                with self.subTest(caption=caption, html=html):
                    table = self._table([self._image(caption)], html)
                    markdown = self._markdown([table])
                    self.assertEqual("<table>" in markdown, html)
                    self.assertNotIn("<figure", markdown)
                    self.assertNotIn("atlas_doc_format", markdown)
                    self.assertEqual(self._adf(markdown), [table])

    def test_rich_table_captions_preserve_only_the_image_opaquely(self) -> None:
        captions = ([_text("bold", {"type": "strong"})], [STATUS], [_text("a"), {"type": "hardBreak"}, _text("b")])
        for caption in captions:
            for html in (False, True):
                image = self._image(caption)
                image["content"][0]["attrs"].update({"alt": "Independent alt", "width": 400, "height": 300})
                image["attrs"].update({"width": 400, "widthType": "pixel"})
                wrappers = (
                    [image], [_expand("T", image, nested=True)], [_panel("tip", image)],
                    [{
                        "type": "bulletList",
                        "content": [_list_item(_paragraph(_text("item")), image)]}], [self._table([image])])
                for blocks in wrappers:
                    with self.subTest(caption=caption, html=html, nested=blocks[0]["type"]):
                        table = self._table(blocks, html)
                        markdown = self._markdown([table])
                        self.assertIn("atlas_doc_format", markdown)
                        self.assertNotIn("<figure", markdown)
                        self.assertEqual(self._adf(markdown), [table])

    def test_rich_caption_is_protected_when_another_cell_requires_html(self) -> None:
        image = self._image([_text("bold", {"type": "strong"})])
        table = {
            "type":
            "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [_cell("tableHeader", [_paragraph(_text("a"))]),
                                _cell("tableHeader", [_paragraph(_text("b"))])]},
                {
                    "type":
                    "tableRow",
                    "content":
                    [_cell("tableCell", [image]),
                     _cell("tableCell", [_paragraph(_text("first")), _paragraph(_text("second"))])]}]}
        markdown = self._markdown([table])
        self.assertIn("<table>", markdown)
        self.assertIn("atlas_doc_format", markdown)
        self.assertEqual(self._adf(markdown), [table])

    def test_table_context_is_restored_after_success_and_failure(self) -> None:
        converter = ADFToMarkdownConverter(self.pandoc, self.media)
        image = self._image([_text("bold", {"type": "strong"})])
        for fail in (False, True):
            with self.subTest(fail=fail):
                table = self._table([None] if fail else [image])
                document = {"type": "doc", "version": 1, "content": [table]}
                if fail:
                    with self.assertRaisesRegex(ConversionError, "ADF block must be an object"):
                        converter.convert(document)
                else:
                    self.assertIn("atlas_doc_format", converter.convert(document))
                self.assertEqual(
                    converter.convert({
                        "type": "doc",
                        "version": 1,
                        "content": [image]}), "![**bold**](_attachments/f.png)\n")

    def test_rejects_images_inside_caption_descriptions(self) -> None:
        with self.assertRaisesRegex(ConversionError, "unsupported caption content"):
            self._adf("![![nested](_attachments/f.png)](_attachments/f.png)\n")


class TestImageFigures(unittest.TestCase):
    """Only images requiring figures preserve geometry; plain Markdown images intentionally omit it."""

    def setUp(self) -> None:
        self.pandoc = PandocRunner()
        self.media = MediaResolver([("f.png", "file-1"), ("no-suffix", "file-2")])

    def _markdown(self, content):
        return ADFToMarkdownConverter(self.pandoc, self.media).convert({"type": "doc", "version": 1, "content": content})

    def _adf(self, markdown):
        return MarkdownToADFConverter(self.pandoc, self.media, "contentId-1").convert(markdown)["content"]

    def _figure(self, attrs=None, dimensions=None, caption=None, external=False) -> dict:
        media_attrs = {
            "type": "external",
            "url": "https://example.test/f.png"} if external else {
                "type": "file",
                "id": "file-1",
                "collection": "contentId-1"}
        media_attrs.update({"alt": 'a & "b"', **(dimensions or {})})
        content = [{"type": "media", "attrs": media_attrs}]
        if caption is not None:
            content.append({"type": "caption", "content": caption})
        return {"type": "mediaSingle", "attrs": {"layout": "center", **(attrs or {})}, "content": content}

    def _simplified(self, dimensions=None, caption=None, external=False) -> dict:
        image = self._figure(dimensions=dimensions, external=external)
        alt = image["content"][0]["attrs"].pop("alt")
        image["content"].append({"type": "caption", "content": [_text(alt)] if caption is None else caption})
        return image

    def test_default_image_keeps_markdown_form(self) -> None:
        figure = self._figure()
        markdown = self._markdown([figure])
        self.assertNotIn("<figure", markdown)
        self.assertIn("![", markdown)
        self.assertEqual(self._adf(markdown), [self._simplified()])

    def test_round_trips_all_layouts_and_width_units(self) -> None:
        for layout in ("center", "wrap-left", "wrap-right", "wide", "full-width", "align-start", "align-end"):
            for width_type, width in (("percentage", 80.5), ("pixel", 640.5), ("pixel", 1024), (None, 75)):
                attrs = {"layout": layout, "width": width}
                if width_type:
                    attrs["widthType"] = width_type
                figure = self._figure(attrs, {"width": 1024, "height": 768.5})
                with self.subTest(layout=layout, unit=width_type, width=width):
                    markdown = self._markdown([figure])
                    if layout == "center" and width_type == "pixel" and width == 1024:
                        self.assertEqual(markdown, '![a & "b"](_attachments/f.png)\n')
                        self.assertEqual(self._adf(markdown), [self._simplified()])
                    else:
                        self.assertIn('<figure data-type="media-single"', markdown)
                        self.assertIn('width="1024" height="768.5"', markdown)
                        self.assertEqual(self._adf(markdown), [figure])

    def test_selects_image_form_by_display_width_not_intrinsic_dimensions(self) -> None:
        cases = (
            ("no dimensions", {}, {}, False), ("native dimensions only", {}, {
                "width": 400,
                "height": 300}, False), ("native height only", {}, {
                    "height": 300}, False), ("pixel type without width", {
                        "widthType": "pixel"}, {
                            "width":
                            400}, False), ("percentage type without width", {
                                "widthType": "percentage"}, {
                                    "width": 400}, False), ("width type without dimensions", {
                                        "widthType": "pixel"}, {}, False),
            ("equal integer widths", {
                "width": 400,
                "widthType": "pixel"}, {
                    "width": 400,
                    "height":
                    300}, False), ("equal float native width", {
                        "width": 400,
                        "widthType": "pixel"}, {
                            "width": 400.0}, False),
            ("equal float display width", {
                "width": 400.0,
                "widthType": "pixel"}, {
                    "width":
                    400}, False), ("equal fractional widths", {
                        "width": 400.5,
                        "widthType": "pixel"}, {
                            "width": 400.5}, False),
            ("unequal fractional widths", {
                "width": 400.5000001,
                "widthType": "pixel"}, {
                    "width": 400.5}, True), ("smaller width", {
                        "width": 200,
                        "widthType": "pixel"}, {
                            "width": 400}, True), ("larger width", {
                                "width": 800,
                                "widthType": "pixel"}, {
                                    "width": 400}, True), ("unknown native width", {
                                        "width": 400,
                                        "widthType": "pixel"}, {}, True),
            ("height is not native width", {
                "width": 400,
                "widthType": "pixel"}, {
                    "height":
                    300}, True), ("percentage is not pixels", {
                        "width": 80.5,
                        "widthType": "percentage"}, {
                            "width": 80.5}, True), ("implicit percentage", {
                                "width": 80}, {
                                    "width": 80}, True))
        for external in (False, True):
            target = 'https://example.test/f.png' if external else '_attachments/f.png'
            for name, attrs, dimensions, html in cases:
                with self.subTest(case=name, external=external):
                    figure = self._figure(attrs, dimensions, external=external)
                    markdown = self._markdown([figure])
                    if html:
                        self.assertIn('<figure data-type="media-single"', markdown)
                        self.assertIn('<img src="' + target + '"', markdown)
                        self.assertNotIn('![', markdown)
                        self.assertEqual(self._adf(markdown), [figure])
                    else:
                        self.assertEqual(markdown, '![a & "b"](' + target + ')\n')
                        self.assertEqual(self._adf(markdown), [self._simplified(external=external)])

    def test_non_center_layouts_require_raw_images_even_without_dimensions(self) -> None:
        cases: list[tuple[str, list[dict[str, object]] | None]] = [
            (layout, None) for layout in ("wrap-left", "wrap-right", "wide", "full-width", "align-start", "align-end")]
        cases.extend((("wrap-right", []), ("wrap-right", [_text("Cap")])))
        for external in (False, True):
            target = 'https://example.test/f.png' if external else '_attachments/f.png'
            for layout, caption in cases:
                with self.subTest(layout=layout, caption=caption, external=external):
                    figure = self._figure({"layout": layout}, caption=caption, external=external)
                    opening = '<figure data-type="media-single"' + (
                        f' data-layout="{layout}"' if layout != "center" else '') + '>\n\n'
                    expected = opening + f'<img src="{target}" alt="a &amp; &quot;b&quot;" />\n\n'
                    if caption is None:
                        expected += '</figure>\n'
                    else:
                        body = 'Cap\n\n' if caption else ''
                        expected += '<figcaption>\n\n' + body + '</figcaption>\n</figure>\n'

                    markdown = self._markdown([figure])
                    self.assertEqual(markdown, expected)
                    self.assertEqual(self._adf(markdown), [figure])

    def test_retains_escaped_urls_and_fractional_native_geometry_in_figures(self) -> None:
        figure = self._figure({"width": 400.5, "widthType": "pixel"}, {"width": 800.25, "height": 600.75}, external=True)
        figure["content"][0]["attrs"]["url"] = 'https://example.test/f.png?a=1&b=2'
        markdown = self._markdown([figure])
        self.assertEqual(
            markdown, '<figure data-type="media-single" data-width="400.5" data-width-type="pixel">\n\n'
            '<img src="https://example.test/f.png?a=1&amp;b=2" width="800.25" height="600.75" '
            'alt="a &amp; &quot;b&quot;" />\n\n</figure>\n')
        self.assertEqual(self._adf(markdown), [figure])

    def test_simplifies_extensionless_block_images(self) -> None:
        for external in (False, True):
            figure = self._figure({"width": 400, "widthType": "pixel"}, {"width": 400}, external=external)
            expected = self._simplified(external=external)
            key = "url" if external else "id"
            value = "https://example.test/no-suffix" if external else "file-2"
            figure["content"][0]["attrs"][key] = value
            expected["content"][0]["attrs"][key] = value
            target = value if external else "_attachments/no-suffix"
            with self.subTest(external=external):
                markdown = self._markdown([figure])
                self.assertEqual(markdown, '![a & "b"](' + target + ')\n')
                self.assertEqual(self._adf(markdown), [expected])

    def test_caption_is_editable_markdown_with_inline_formatting(self) -> None:
        caption = [
            _text("bold", {"type": "strong"}),
            _text(" and "),
            _text("link", {
                "type": "link",
                "attrs": {
                    "href": "https://example.test",
                    "title": ""}}), {
                        "type": "hardBreak"}, {
                            "type": "date",
                            "attrs": {
                                "timestamp": "1767225600000"}},
            _text(" "), STATUS]
        figure = self._figure(caption=caption)
        markdown = self._markdown([figure])
        self.assertIn("![**bold**", markdown)
        self.assertNotIn("<figure", markdown)
        self.assertEqual(self._adf(markdown), [self._simplified(caption=caption)])
        edited = markdown.replace("**bold**", "**edited**")
        self.assertEqual(self._adf(edited)[0]["content"][1]["content"][0], _text("edited", {"type": "strong"}))

    def test_round_trips_external_and_extensionless_images(self) -> None:
        external = self._figure({"widthType": "pixel", "width": 400}, {"height": 200}, [_text("caption")], external=True)
        local = self._figure({"layout": "wrap-right"})
        local["content"][0]["attrs"]["id"] = "file-2"
        self.assertEqual(self._adf(self._markdown([external, local])), [external, local])

    def test_figures_in_containers_and_html_table_cells(self) -> None:
        for caption in (None, [], [_text("a "), _text("bold", {"type": "strong"}), _text(" caption")]):
            figure = self._figure({"layout": "wrap-left", "width": 50}, {"width": 640, "height": 480}, caption)
            table = {
                "type":
                "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [_cell("tableHeader", [_paragraph(_text("h"))])]}, {
                            "type": "tableRow",
                            "content": [_cell("tableCell", [figure, _paragraph(_text("after"))])]}]}
            cases = [
                [figure], [table], [_expand("t", figure)], [_layout(_column(100, figure))],
                [{
                    "type": "bulletList",
                    "content": [_list_item(_paragraph(_text("item")), figure)]}], [{
                        "type": "blockquote",
                        "content": [figure]}]]
            for content in cases:
                with self.subTest(caption=caption, container=content[0]["type"]):
                    self.assertEqual(self._adf(self._markdown(content)), content)

    def test_plain_and_retained_images_round_trip_in_all_block_contexts(self) -> None:
        simplified = self._figure({"width": 400, "widthType": "pixel"}, {"width": 400, "height": 300})
        retained = self._figure({"layout": "wrap-right"}, caption=[_text("Cap")])
        for source, pushed in ((simplified, self._simplified()), (retained, retained)):
            source_item = _list_item(_paragraph(_text("item")), source)
            pushed_item = _list_item(_paragraph(_text("item")), pushed)
            cases = (
                ([source], [pushed]), ([_expand("T", source)], [_expand("T", pushed)]), (
                    [_expand("outer", _expand("inner", source,
                                              nested=True))], [_expand("outer", _expand("inner", pushed, nested=True))]),
                ([_layout(_column(100.0, source))], [_layout(_column(100.0, pushed))]),
                ([_panel("tip", source)], [_panel("tip", pushed)]), ([_panel("warning", source)], [_panel("warning", pushed)]),
                ([{
                    "type": "bulletList",
                    "content": [source_item]}], [{
                        "type": "bulletList",
                        "content": [pushed_item]}]), (
                            [{
                                "type": "orderedList",
                                "attrs": {
                                    "order": 1},
                                "content":
                                [source_item]}], [{
                                    "type": "orderedList",
                                    "attrs": {
                                        "order": 1},
                                    "content": [pushed_item]}]),
                (
                    [
                        {
                            "type": "bulletList",
                            "content": [_list_item(_paragraph(_text("outer")), {
                                "type": "bulletList",
                                "content": [source_item]})]}], [
                                    {
                                        "type":
                                        "bulletList",
                                        "content":
                                        [_list_item(_paragraph(_text("outer")), {
                                            "type": "bulletList",
                                            "content": [pushed_item]})]}]),
                ([{
                    "type": "blockquote",
                    "content": [source]}], [{
                        "type": "blockquote",
                        "content": [pushed]}]), (
                            [
                                {
                                    "type":
                                    "table",
                                    "content":
                                    [{
                                        "type": "tableRow",
                                        "content": [_cell("tableCell", [source, _paragraph(_text("after"))])]}]}],
                            [
                                {
                                    "type":
                                    "table",
                                    "content":
                                    [{
                                        "type": "tableRow",
                                        "content": [_cell("tableCell", [pushed, _paragraph(_text("after"))])]}]}]))
            for content, expected in cases:
                with self.subTest(image=source, container=content[0]["type"]):
                    markdown = self._markdown(content)
                    if content[0]["type"] == "table":
                        self.assertIn('<table>', markdown)
                        self.assertIn('<img ', markdown)

                    self.assertEqual(self._adf(markdown), expected)

    def test_reads_compact_html_and_raw_img(self) -> None:
        markdown = '<figure data-type="media-single" data-width="70" data-layout="wide">' \
            '<img src="_attachments/f.png" alt="a &amp; &quot;b&quot;" width="640" />' \
            '<figcaption><strong>caption</strong></figcaption></figure>\n'
        self.assertEqual(
            self._adf(markdown),
            [self._figure({
                "width": 70,
                "layout": "wide"}, {"width": 640}, [_text("caption", {"type": "strong"})])])
        self.assertEqual(
            self._adf('<img src="_attachments/f.png" alt="a &amp; &quot;b&quot;" height="480" />\n'),
            [self._simplified(dimensions={"height": 480})])

    def test_reads_single_line_figcaption_as_html(self) -> None:
        start = '<figure data-type="media-single">\n\n![a](_attachments/f.png)\n\n'
        for caption, end, content in (('<figcaption>caption</figcaption>', '\n\n</figure>\n', [_text("caption")]),
                                      ('<figcaption data-local-id="c"><strong>caption</strong></figcaption>', '\n</figure>\n',
                                       [_text("caption", {"type": "strong"})]), ('<figcaption>**caption**</figcaption>',
                                                                                 '\n\n</figure>\n', [_text("**caption**")])):
            with self.subTest(caption=caption):
                self.assertEqual(self._adf(start + caption + end)[0]["content"][1]["content"], content)
        for caption in ('<figcaption class="x">x</figcaption>', '<figcaption>a</figcaption><figcaption>b</figcaption>',
                        '<figcaption><p>a</p><p>b</p></figcaption>'):
            with self.subTest(caption=caption):
                with self.assertRaises(ConversionError):
                    self._adf(start + caption + '\n\n</figure>\n')

    def test_accepts_local_ids_and_edits_to_geometry_and_attachment_paths(self) -> None:
        figure = self._figure({"widthType": "pixel", "width": 400}, {"width": 800}, [_text("caption")])
        markdown = self._markdown([figure]).replace('<figure ', '<figure data-local-id="figure-id" ')
        markdown = markdown.replace('<img ', '<img data-local-id="media-id" ')
        markdown = markdown.replace('<figcaption>', '<figcaption data-local-id="caption-id">')
        self.assertEqual(self._adf(markdown), [figure])
        edited = markdown.replace('data-width="400"', 'data-width="600"').replace('_attachments/f.png', '_attachments/no-suffix')
        changed = self._figure({"widthType": "pixel", "width": 600}, {"width": 800}, [_text("caption")])
        changed["content"][0]["attrs"]["id"] = "file-2"
        self.assertEqual(self._adf(edited), [changed])
        self.assertEqual(
            self._adf('<table><tr><td>' + edited.replace('\n\n', '\n') +
                      '</td></tr></table>')[0]["content"][0]["content"][0]["content"], [changed])

    def test_writes_joined_caption_closings_and_keeps_raw_image_boundaries(self) -> None:
        figure = self._figure(
            {"layout": "wrap-right"}, dimensions={
                "width": 400,
                "height": 3}, caption=[_text("Cap")], external=True)
        markdown = self._markdown([figure])
        self.assertEqual(
            markdown, '<figure data-type="media-single" data-layout="wrap-right">\n\n'
            '<img src="https://example.test/f.png" width="400" height="3" alt="a &amp; &quot;b&quot;" />\n\n'
            '<figcaption>\n\nCap\n\n</figcaption>\n</figure>\n')
        self.assertEqual(len(markdown.splitlines()), 10)
        self.assertEqual(self._adf(markdown), [figure])

    def test_reads_and_retitles_legacy_and_joined_caption_closings(self) -> None:
        opening = '<figure data-type="media-single">\n\n' \
            '<img src="https://example.test/f.png" width="400" height="3" alt="a &amp; &quot;b&quot;" />\n\n' \
            '<figcaption>\n\nCap\n\n'
        expected = [self._figure(dimensions={"width": 400, "height": 3}, caption=[_text("Cap")], external=True)]
        reverse = MarkdownToADFConverter(self.pandoc, self.media, "contentId-1")
        for closing in ('</figcaption>\n\n</figure>\n', '</figcaption>\n</figure>\n'):
            body = opening + closing
            with self.subTest(closing=closing):
                self.assertEqual(self._adf(body), expected)
                renamed = reverse.retitle("# Old\n\n" + body, "Old", "New")
                self.assertEqual(renamed, "# New\n\n" + body)
                self.assertEqual(reverse.convert(renamed, title="New")["content"], expected)

    def test_keeps_blank_lines_around_a_captionless_raw_image(self) -> None:
        figure = self._figure({"width": 400, "widthType": "pixel"}, {"width": 800})
        expected = '<figure data-type="media-single" data-width="400" data-width-type="pixel">\n\n' \
            '<img src="_attachments/f.png" width="800" alt="a &amp; &quot;b&quot;" />\n\n</figure>\n'
        self.assertEqual(self._markdown([figure]), expected)
        self.assertEqual(self._adf(expected), [figure])
        with self.assertRaisesRegex(ConversionError, "figure is not closed"):
            self._adf('<figure data-type="media-single">\n\n<img src="_attachments/f.png" width="800" />\n</figure>\n')

    def test_reads_legacy_figures_with_equal_display_and_native_widths(self) -> None:
        markdown = '<figure data-type="media-single" data-width="400" data-width-type="pixel">\n\n' \
            '<img src="_attachments/f.png" width="400" alt="a &amp; &quot;b&quot;" />\n\n</figure>\n'
        self.assertEqual(self._adf(markdown), [self._figure({"width": 400, "widthType": "pixel"}, {"width": 400})])

    def test_retitle_keeps_legacy_equal_width_figure_geometry(self) -> None:
        body = '<figure data-type="media-single" data-width="400" data-width-type="pixel">\n\n' \
            '<img src="_attachments/f.png" width="400" height="300" alt="a &amp; &quot;b&quot;" />\n\n</figure>\n'
        reverse = MarkdownToADFConverter(self.pandoc, self.media, "contentId-1")
        renamed = reverse.retitle('# Old\n\n' + body, "Old", "New")
        self.assertEqual(renamed, '# New\n\n' + body)
        self.assertEqual(
            reverse.convert(renamed, title="New")["content"],
            [self._figure({
                "width": 400,
                "widthType": "pixel"}, {
                    "width": 400,
                    "height": 300})])

    def test_unsupported_figures_stay_opaque_and_old_fences_still_read(self) -> None:
        cases = [
            self._figure({"unknown": "x"}),
            self._figure({"layout": "unknown"}),
            self._figure({"widthType": "other"}),
            self._figure({"widthType": None}),
            self._figure({"width": None}),
            self._figure({"width": 101}),
            self._figure({"width": True}),
            self._figure(dimensions={"height": 0}),
            self._figure(dimensions={"height": None}),
            self._figure(dimensions={"width": "640"}),
            self._figure(caption=[_paragraph(_text("block"))]),
            self._figure(caption=[{
                "type": "inlineExtension",
                "attrs": {
                    "extensionKey": "anchor"}}])]
        marked = self._figure()
        marked["marks"] = [{"type": "other"}]
        cases.append(marked)
        for figure in cases:
            with self.subTest(figure=figure):
                markdown = self._markdown([figure])
                self.assertIn("``` atlas_doc_format", markdown)
                self.assertEqual(self._adf(markdown), [figure])
        valid = self._figure(caption=[_text("caption")])
        self.assertEqual(self._adf("```atlas_doc_format\n" + json.dumps(valid) + "\n```\n"), [valid])

    def test_rejects_malformed_figures_and_discarded_html_attributes(self) -> None:
        start = '<figure data-type="media-single">\n\n'
        image = '![a](_attachments/f.png)\n\n'
        end = '</figure>\n'
        cases = [
            start + image, start + end, start + image + image + end, start + 'text\n\n' + image + end,
            start + image + '<figcaption>\n\nx\n\n' + end, start + image + '<figcaption>\n\nx\n\ny\n\n</figcaption>\n\n' + end,
            start + image + '<figcaption>\n\nx\n\n</figcaption>\n\nx\n\n' + end, start + start + image + end + end]
        for attr in ('data-layout="other"', 'data-width="0"', 'data-width="nan"', 'data-width="101"', 'data-width-type="em"',
                     'class="x"'):
            cases.append(start.replace('data-type="media-single"', 'data-type="media-single" ' + attr) + image + end)
        for attr in ('style="width: 5px"', 'width="10%"', 'height="-1"', 'width="inf"'):
            cases.append(start + '<img src="_attachments/f.png" ' + attr + ' />\n\n' + end)
        compact = '<figure data-type="media-single"><img src="_attachments/f.png" />'
        for caption in ('<figcaption class="x">x</figcaption>', '<figcaption></figcaption><figcaption></figcaption>',
                        '<figcaption><img src="_attachments/f.png" /></figcaption>', '<figcaption>x',
                        '<figcaption>x</figcaption><img src="_attachments/f.png" />'):
            cases.append(compact + caption + '</figure>\n')
        for markdown in cases:
            with self.subTest(markdown=markdown):
                with self.assertRaises(ConversionError):
                    self._adf(markdown)
                with self.assertRaises(ConversionError):
                    self._adf('<table><tr><td>' + markdown + '</td></tr></table>\n')


# vim: set ts=4 sw=4 et tw=132:


class TestColourMarks(unittest.TestCase):

    def setUp(self) -> None:
        self.pandoc = PandocRunner()

    @staticmethod
    def _normalized(value):
        if isinstance(value, list):
            return [TestColourMarks._normalized(child) for child in value]
        if isinstance(value, dict):
            result = {key: TestColourMarks._normalized(child) for key, child in value.items()}
            if "marks" in result:
                result["marks"].sort(key=lambda mark: json.dumps(mark, sort_keys=True))
            return result
        return value

    def _round_trip(self, content):
        markdown = ADFToMarkdownConverter(self.pandoc).convert({"type": "doc", "version": 1, "content": content})
        back = MarkdownToADFConverter(self.pandoc).convert(markdown)["content"]
        self.assertEqual(self._normalized(back), self._normalized(content))
        return markdown

    def test_round_trips_colour_combinations_and_formatting(self) -> None:
        for colours in ([TEXT_COLOUR], [HIGHLIGHT], [TEXT_COLOUR, HIGHLIGHT]):
            for formatting in ([], [{"type": "strong"}], [{"type": "em"}], [{"type": "strike"}], [UNDERLINE], [SUPERSCRIPT],
                               [{"type": "link", "attrs": {"href": "https://a.test", "title": ""}}], [{"type": "strong"},
                                                                                                      {"type": "em"}, UNDERLINE]):
                with self.subTest(colours=colours, formatting=formatting):
                    markdown = self._round_trip([_paragraph(_text("a < b & [x] * y", *colours, *formatting))])
                    for mark in colours:
                        property_name = "color" if mark["type"] == "textColor" else "background-color"
                        self.assertIn(f'<span style="{property_name}: {mark["attrs"]["color"]}">', markdown)

    def test_round_trips_adjacent_runs_and_marked_spaces(self) -> None:
        self._round_trip(
            [
                _paragraph(
                    _text("a", TEXT_COLOUR, {"type": "strong"}), _text(" ", TEXT_COLOUR), _text("b", HIGHLIGHT, {"type": "strong"}),
                    _text("c", {"type": "strong"}), _text("d", TEXT_COLOUR, HIGHLIGHT))])

    def test_round_trips_colours_in_containers_and_caption(self) -> None:
        paragraph = _paragraph(_text("coloured", TEXT_COLOUR, HIGHLIGHT))
        self._round_trip(
            [
                {
                    "type": "heading",
                    "attrs": {
                        "level": 2},
                    "content": paragraph["content"]},
                _bullet_list_of(paragraph), {
                    "type": "panel",
                    "attrs": {
                        "panelType": "warning"},
                    "content": [paragraph]}, {
                        "type": "expand",
                        "attrs": {
                            "title": "Details"},
                        "content": [paragraph]}, {
                            "type":
                            "mediaSingle",
                            "attrs": {
                                "layout": "center"},
                            "content": [
                                {
                                    "type": "media",
                                    "attrs": {
                                        "type": "external",
                                        "url": "https://a.test/image.png"}}, {
                                            "type": "caption",
                                            "content": paragraph["content"]}]}])

    def test_accepts_combined_styles_and_nested_overrides_in_both_readers(self) -> None:
        for wrapper in ("{}", "<table><tr><td><p>{}</p></td></tr></table>"):
            for bold in ("**x**", "<strong>x</strong>"):
                # Markdown emphasis is used outside HTML tables; HTML emphasis inside them.
                if (wrapper == "{}") != (bold == "**x**"):
                    continue
                source = (
                    '<span style=" COLOR : #Ab1234; background-color: #F8E6A0;">'
                    f'a<span style="color: #ffffff">{bold}</span>b</span>')
                content = MarkdownToADFConverter(self.pandoc).convert(wrapper.format(source))["content"]
                if wrapper != "{}":
                    content = content[0]["content"][0]["content"][0]["content"]
                self.assertEqual(
                    self._normalized(content),
                    self._normalized(
                        [
                            _paragraph(
                                _text("a", TEXT_COLOUR, HIGHLIGHT),
                                _text("x", {
                                    "type": "textColor",
                                    "attrs": {
                                        "color": "#ffffff"}}, HIGHLIGHT, {"type": "strong"}), _text("b", TEXT_COLOUR, HIGHLIGHT))]))

    def test_reads_mark_as_yellow_and_writes_the_hex_span(self) -> None:
        yellow = {"type": "backgroundColor", "attrs": {"color": "#FFFF00"}}
        for source in ("<mark>x</mark>", "<table><tr><td><p><mark>x</mark></p></td></tr></table>"):
            document = MarkdownToADFConverter(self.pandoc).convert(source)
            paragraph = document["content"][0]
            if paragraph["type"] == "table":
                paragraph = paragraph["content"][0]["content"][0]["content"][0]
            self.assertEqual(paragraph, _paragraph(_text("x", yellow)))
            self.assertIn('<span style="background-color: #FFFF00">', ADFToMarkdownConverter(self.pandoc).convert(document))

    def test_preserves_invalid_or_unsupported_adf_colours_opaquely(self) -> None:
        marks = [
            {
                "type": "textColor"}, {
                    "type": "textColor",
                    "attrs": {
                        "color": "red"}}, {
                            "type": "backgroundColor",
                            "attrs": {
                                "color": "#123"}}, {
                                    "type": "textColor",
                                    "attrs": {
                                        "color": None}}, {
                                            "type": "textColor",
                                            "attrs": {
                                                "color": ["#123456"]}}, {
                                                    "type": "textColor",
                                                    "attrs": {
                                                        "color": '#123456\" onclick=\"x'}}, {
                                                            "type": "textColor",
                                                            "attrs": {
                                                                "color": "#123456",
                                                                "future": True}}, {
                                                                    **TEXT_COLOUR, "future": True}]
        for selected in ([mark] for mark in marks):
            with self.subTest(marks=selected):
                self.assertIn("atlas_doc_format", self._round_trip([_paragraph(_text("x", *selected))]))
        for selected in ([TEXT_COLOUR, TEXT_COLOUR], [TEXT_COLOUR, {"type": "code"}]):
            with self.subTest(marks=selected):
                self.assertIn("atlas_doc_format", self._round_trip([_paragraph(_text("x", *selected))]))

    def test_rejects_styles_that_cannot_be_preserved(self) -> None:
        for tag in ('<span style="color: red">', '<span style="color: #123">', '<span style="color: #123456; font-weight: bold">',
                    '<span style="color: #123456; color: #abcdef">', '<span style="">', '<span id="x" style="color: #123456">'):
            for wrapper in ("{}", "<table><tr><td><p>{}</p></td></tr></table>"):
                with self.subTest(tag=tag, wrapper=wrapper):
                    with self.assertRaises(ConversionError):
                        MarkdownToADFConverter(self.pandoc).convert(wrapper.format(f"{tag}x</span>"))
        for source in ('<span style="color: #123456">x', '<mark>x', '<span style="color: #123456">`code`</span>'):
            with self.subTest(source=source):
                with self.assertRaises(ConversionError):
                    MarkdownToADFConverter(self.pandoc).convert(source)
