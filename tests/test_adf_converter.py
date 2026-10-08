# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for ADF to Markdown conversion."""

from copy import deepcopy
import json
from typing import Any
import unittest
from types import SimpleNamespace

from cflsync import ADFToMarkdownConverter, PandocRunner


class RecordingPandoc:

    def pandoc_to_gfm(self, pandoc):
        self.pandoc = pandoc
        return "converted\n"


class TestADFToMarkdownConverter(unittest.TestCase):

    def test_unsupported_formatting_keeps_text_and_supported_marks(self) -> None:
        pandoc = RecordingPandoc()
        text = {
            "type":
            "text",
            "text":
            "Synthetic",
            "marks": [
                {
                    "type": "futureMark",
                    "attrs": {
                        "color": "#123456"}}, {
                            "type": "code",
                            "extra": True}, {
                                "type": "strong",
                                "attrs": {
                                    "future": 1}}, {
                                        "type": "link",
                                        "attrs": {
                                            "href": "https://example.test",
                                            "future": 2}}, ]}
        document = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [text, {
                        "type": "hardBreak",
                        "attrs": {
                            "future": 3}}, {
                                "type": "text",
                                "text": "after"}]}]}
        ADFToMarkdownConverter(pandoc).convert(document)

        inlines = pandoc.pandoc["blocks"][0]["c"]
        self.assertEqual(inlines[0]["t"], "Link")
        self.assertEqual(inlines[0]["c"][2], ["https://example.test", ""])
        strong = inlines[0]["c"][1][0]
        self.assertEqual(strong["t"], "Strong")
        self.assertEqual(strong["c"], [{"t": "Code", "c": [["", [], []], "Synthetic"]}])
        self.assertEqual(inlines[1], {"t": "LineBreak"})

    def test_invalid_subsup_marks_retain_the_enclosing_block(self) -> None:
        cases: list[list[dict[str, Any]]] = [
            [{
                "type": "subsup"}], [{
                    "type": "subsup",
                    "attrs": {
                        "type": "invalid"}}], [{
                            "type": "subsup",
                            "attrs": {
                                "type": "sub"}}],
            [{
                "type": "subsup",
                "attrs": {
                    "type": "sub"}}, {
                        "type": "subsup",
                        "attrs": {
                            "type": "sup"}}], ]
        for marks in cases:
            with self.subTest(marks=marks):
                if marks[0].get("attrs", {}).get("type") == "sub":
                    marks = [*marks, {"type": "code"}]

                pandoc = RecordingPandoc()
                document = {
                    "type": "doc",
                    "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": "Synthetic",
                            "marks": marks}]}]}
                ADFToMarkdownConverter(pandoc).convert(document)

                self.assertEqual(pandoc.pandoc["blocks"][0]["t"], "CodeBlock")

    def test_structures_and_invalid_required_values_retain_original_json(self) -> None:
        paragraph = {"type": "paragraph", "content": [{"type": "text", "text": "Cell"}]}
        nodes = [
            {
                "type": "extension",
                "attrs": {
                    "extensionKey": "synthetic",
                    "metadata": {
                        "value": 42}}}, {
                            "type": "panel",
                            "attrs": {
                                "panelType": "invalid"},
                            "content": [paragraph]}, {
                                "type": "heading",
                                "attrs": {
                                    "level": "invalid"},
                                "content": []}, {
                                    "type": "orderedList",
                                    "attrs": {
                                        "order": 0},
                                    "content": []},
            {
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": "Invalid link",
                    "marks": [{
                        "type": "link",
                        "attrs": {
                            "href": 42}}]}]}, ]
        for node in nodes:
            with self.subTest(node_type=node["type"]):
                pandoc = RecordingPandoc()
                ADFToMarkdownConverter(pandoc).convert({"type": "doc", "version": 1, "content": [node]})
                block = pandoc.pandoc["blocks"][0]

                self.assertEqual(block["t"], "CodeBlock")
                self.assertEqual(block["c"][0], ["", ["atlas_doc_format"], []])
                self.assertEqual(json.loads(block["c"][1]), node)

    def test_maps_direct_blocks_and_inlines(self) -> None:
        pandoc = RecordingPandoc()
        converter = ADFToMarkdownConverter(pandoc)
        document = {
            "type":
            "doc",
            "version":
            1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{
                        "type": "text",
                        "text": "plain text"}]}, {
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
                    "type": "bulletList",
                    "content":
                    [{
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [{
                                "type": "text",
                                "text": "Item"}]}]}]}, {
                                    "type": "codeBlock",
                                    "attrs": {
                                        "language": "python"},
                                    "content": [{
                                        "type": "text",
                                        "text": "print(1)"}]}, {
                                            "type": "rule"}, ], }

        self.assertEqual(converter.convert(document), "converted\n")
        self.assertEqual(
            pandoc.pandoc, {
                "pandoc-api-version":
                list(PandocRunner.API_VERSION),
                "meta": {},
                "blocks": [
                    {
                        "t": "Para",
                        "c": [{
                            "t": "Str",
                            "c": "plain"}, {
                                "t": "Space"}, {
                                    "t": "Str",
                                    "c": "text"}]}, {
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
                                                                    "c": "Item"}]}]]}, {
                                                                        "t": "CodeBlock",
                                                                        "c": [["", ["python"], []], "print(1)"]}, {
                                                                            "t": "HorizontalRule"}, ], })

    def test_maps_a_task_list_to_pandoc_checkboxes(self) -> None:
        pandoc = RecordingPandoc()
        task_list = {
            "type":
            "taskList",
            "attrs": {
                "localId": "list-1"},
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {
                        "localId": "item-1",
                        "state": "TODO"},
                    "content": [{
                        "type": "text",
                        "text": "Open"}]}, {
                            "type": "taskItem",
                            "attrs": {
                                "localId": "item-2",
                                "state": "DONE"},
                            "content": [{
                                "type": "text",
                                "text": "Done"}]}]}

        ADFToMarkdownConverter(pandoc).convert({"type": "doc", "version": 1, "content": [task_list]})

        self.assertEqual(
            pandoc.pandoc["blocks"][0], {
                "t":
                "BulletList",
                "c": [
                    [{
                        "t": "Plain",
                        "c": [{
                            "t": "Str",
                            "c": "☐"}, {
                                "t": "Space"}, {
                                    "t": "Str",
                                    "c": "Open"}]}],
                    [{
                        "t": "Plain",
                        "c": [{
                            "t": "Str",
                            "c": "☒"}, {
                                "t": "Space"}, {
                                    "t": "Str",
                                    "c": "Done"}]}]]})

    def test_maps_panel_types_to_pandoc_alerts(self) -> None:
        alerts = {"info": "note", "note": "important", "success": "tip", "warning": "warning", "error": "caution"}
        paragraph = {"type": "paragraph", "content": [{"type": "text", "text": "Content"}]}

        for panel_type, alert in alerts.items():
            with self.subTest(panel_type=panel_type):
                pandoc = RecordingPandoc()
                panel = {"type": "panel", "attrs": {"panelType": panel_type, "localId": "ignored"}, "content": [paragraph]}

                ADFToMarkdownConverter(pandoc).convert({"type": "doc", "version": 1, "content": [panel]})

                attributes, blocks = pandoc.pandoc["blocks"][0]["c"]
                self.assertEqual(attributes, ["", [alert], []])
                self.assertEqual(
                    blocks[0], {
                        "t": "Div",
                        "c": [["", ["title"], []], [{
                            "t": "Para",
                            "c": [{
                                "t": "Str",
                                "c": alert.title()}]}]]})
                self.assertEqual(blocks[1], {"t": "Para", "c": [{"t": "Str", "c": "Content"}]})

    def test_writes_a_nested_task_list_as_gfm_checkboxes(self) -> None:
        document = {
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
                                "text": "Parent"}]},
                        {
                            "type":
                            "taskList",
                            "content":
                            [{
                                "type": "taskItem",
                                "attrs": {
                                    "state": "DONE"},
                                "content": [{
                                    "type": "text",
                                    "text": "Child"}]}]}]}]}

        markdown = ADFToMarkdownConverter(PandocRunner()).convert(document)

        self.assertEqual(markdown, "- [ ] Parent\n  - [x] Child\n")

    def test_retains_a_structurally_invalid_table(self) -> None:
        pandoc = RecordingPandoc()
        table = {"type": "table", "content": [{"type": "tableRow", "content": [{"type": "paragraph", "content": []}]}]}

        ADFToMarkdownConverter(pandoc).convert({"type": "doc", "version": 1, "content": [table]})

        self.assertEqual(pandoc.pandoc["blocks"][0]["c"][0], ["", ["atlas_doc_format"], []])

    def test_maps_an_emoji_to_its_unicode_text(self) -> None:
        pandoc = RecordingPandoc()
        emoji = {"type": "emoji", "attrs": {"shortName": ":smile:", "id": "1f604", "text": "\U0001F604"}}
        paragraph = {"type": "paragraph", "content": [{"type": "text", "text": "Nice"}, emoji]}

        ADFToMarkdownConverter(pandoc).convert({"type": "doc", "version": 1, "content": [paragraph]})

        self.assertEqual(
            pandoc.pandoc["blocks"][0], {
                "t": "Para",
                "c": [{
                    "t": "Str",
                    "c": "Nice"}, {
                        "t": "Str",
                        "c": "\U0001F604"}]})

    def test_maps_a_mention_to_a_mailto_link_when_the_user_has_an_email(self) -> None:
        pandoc = RecordingPandoc()
        mention = {"type": "mention", "attrs": {"id": "account-123", "text": "@Example User"}}

        ADFToMarkdownConverter(
            pandoc, mention_lookup=lambda account_id: SimpleNamespace(email="example.user@example.test")).convert(
                {
                    "type": "doc",
                    "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [mention]}]})

        self.assertEqual(
            pandoc.pandoc["blocks"][0]["c"], [
                {
                    "t":
                    "Link",
                    "c": [
                        ["", [], []], [{
                            "t": "Str",
                            "c": "Example"}, {
                                "t": "Space"}, {
                                    "t": "Str",
                                    "c": "User"}], ["mailto:example.user@example.test", ""]]}])

    def test_retains_a_custom_emoji_without_unicode_text(self) -> None:
        pandoc = RecordingPandoc()
        emoji = {"type": "emoji", "attrs": {"shortName": ":atlassian:", "id": "atlassian-check"}}
        paragraph = {"type": "paragraph", "content": [emoji]}

        ADFToMarkdownConverter(pandoc).convert({"type": "doc", "version": 1, "content": [paragraph]})

        block = pandoc.pandoc["blocks"][0]
        self.assertEqual(block["c"][0], ["", ["atlas_doc_format"], []])
        self.assertEqual(json.loads(block["c"][1]), paragraph)


class TestImageSelection(unittest.TestCase):
    """Geometry is omitted only after validating the entire mediaSingle and choosing the Markdown form."""

    def setUp(self) -> None:
        self.pandoc = RecordingPandoc()
        self.converter = ADFToMarkdownConverter(self.pandoc)

    @staticmethod
    def _node(attrs=None, dimensions=None, caption=None):
        media = {
            "type": "media",
            "attrs": {
                "type": "external",
                "url": "https://example.test/a.png",
                "alt": "a.png",
                **(dimensions or {})}}
        content = [media]
        if caption is not None:
            content.append({"type": "caption", "content": caption})

        return {"type": "mediaSingle", "attrs": attrs or {}, "content": content}

    def test_simplified_image_ast_has_no_figure_or_dimension_attributes(self) -> None:
        cases = (
            ({}, {
                "width": 400,
                "height": 300}), ({}, {
                    "height": 300}), ({
                        "width": 400,
                        "widthType": "pixel"}, {
                            "width": 400.0,
                            "height": 300.5}), ({
                                "widthType": "pixel"}, {
                                    "width": 400}), ({
                                        "widthType": "percentage"}, {}))
        expected = {
            "t": "Para",
            "c": [{
                "t": "Image",
                "c": [["", [], []], [{
                    "t": "Str",
                    "c": "a.png"}], ["https://example.test/a.png", ""]]}]}
        for attrs, dimensions in cases:
            with self.subTest(attrs=attrs, dimensions=dimensions):
                self.converter.convert({"type": "doc", "version": 1, "content": [self._node(attrs, dimensions)]})
                self.assertEqual(self.pandoc.pandoc["blocks"], [expected])

    def test_required_figures_have_independent_raw_images_without_native_dimensions(self) -> None:
        cases = (
            ({
                "layout": "wrap-right"}, None), ({
                    "width": 400,
                    "widthType": "pixel"}, None), ({
                        "layout": "wrap-right"}, []), ({
                            "layout": "wrap-right"}, [{
                                "type": "text",
                                "text": "Cap"}]))
        for attrs, caption in cases:
            with self.subTest(attrs=attrs, caption=caption):
                self.converter.convert({"type": "doc", "version": 1, "content": [self._node(attrs, caption=caption)]})
                blocks = self.pandoc.pandoc["blocks"]
                self.assertEqual(blocks[0]["t"], "RawBlock")
                self.assertTrue(blocks[0]["c"][1].startswith('<figure data-type="media-single"'))
                self.assertEqual(
                    blocks[1], {
                        "t": "RawBlock",
                        "c": ["html", '<img src="https://example.test/a.png" alt="a.png" />']})
                if caption is None:
                    self.assertEqual(len(blocks), 3)
                    self.assertEqual(blocks[-1], {"t": "RawBlock", "c": ["html", '</figure>']})
                else:
                    self.assertEqual(len(blocks), 5)
                    self.assertEqual(blocks[2], {"t": "RawBlock", "c": ["html", '<figcaption>']})
                    self.assertEqual(blocks[-1], {"t": "RawBlock", "c": ["html", '</figcaption>\n</figure>']})

    def test_caption_replaces_description_without_requiring_a_figure(self) -> None:
        for caption, description in (([], []), ([{"type": "text", "text": "Cap"}], [{"t": "Str", "c": "Cap"}])):
            with self.subTest(caption=caption):
                node = self._node({"width": 400, "widthType": "pixel"}, {"width": 400, "height": 300}, caption)
                self.converter.convert({"type": "doc", "version": 1, "content": [node]})
                self.assertEqual(
                    self.pandoc.pandoc["blocks"],
                    [{
                        "t": "Para",
                        "c": [{
                            "t": "Image",
                            "c": [["", [], []], description, ["https://example.test/a.png", ""]]}]}])

    def test_invalid_native_geometry_cannot_be_discarded_by_simplification(self) -> None:
        for name in ("width", "height"):
            for value in (0, -1, None, True, "400", float("nan"), float("inf")):
                with self.subTest(name=name, value=value):
                    node = self._node(dimensions={name: value})
                    self.converter.convert({"type": "doc", "version": 1, "content": [node]})
                    block = self.pandoc.pandoc["blocks"][0]
                    self.assertEqual(block["t"], "CodeBlock")
                    self.assertEqual(block["c"][0], ["", ["atlas_doc_format"], []])

    def test_invalid_caption_keeps_equal_width_image_opaque(self) -> None:
        node = self._node({"width": 400, "widthType": "pixel"}, {"width": 400}, [{"type": "paragraph", "content": []}])
        self.converter.convert({"type": "doc", "version": 1, "content": [node]})
        block = self.pandoc.pandoc["blocks"][0]
        self.assertEqual(block["t"], "CodeBlock")
        self.assertEqual(json.loads(block["c"][1]), node)


class TestTagBlockCompaction(unittest.TestCase):
    """Only adjacent supported raw tag blocks merge, including already joined nested runs."""

    def setUp(self) -> None:
        self.pandoc = RecordingPandoc()
        self.converter = ADFToMarkdownConverter(self.pandoc)

    @staticmethod
    def _raw(text, format="html"):
        return {"t": "RawBlock", "c": [format, text]}

    def test_merges_empty_singleton_and_long_runs_without_mutation(self) -> None:
        tags = ['<details>', '<summary>A &amp; B&#10;C&#9;D</summary>', '</details>']
        for count in (0, 1, 3):
            blocks = [self._raw(tag) for tag in tags[:count]]
            original = deepcopy(blocks)
            expected = [self._raw("\n".join(tags[:count]))] if count else []
            with self.subTest(count=count):
                self.assertEqual(self.converter._merge_tag_blocks(blocks), expected)
                self.assertEqual(blocks, original)

    def test_merges_multiline_runs_idempotently_and_preserves_entities(self) -> None:
        blocks = [
            self._raw('<section data-type="layout-section">\n<div data-type="column" data-width="50">'),
            self._raw('<details>\n<summary>A &amp; B&#10;C&#9;D</summary>'),
            self._raw('</details>\n</div>\n</section>')]
        expected = [
            self._raw(
                '<section data-type="layout-section">\n<div data-type="column" data-width="50">\n'
                '<details>\n<summary>A &amp; B&#10;C&#9;D</summary>\n</details>\n</div>\n</section>')]
        original = deepcopy(blocks)
        merged = self.converter._merge_tag_blocks(blocks)
        self.assertEqual(merged, expected)
        self.assertEqual(self.converter._merge_tag_blocks(merged), expected)
        self.assertEqual(blocks, original)

    def test_ineligible_blocks_break_runs_and_stay_unchanged(self) -> None:
        boundaries = [
            {
                "t": "Para",
                "c": [{
                    "t": "Str",
                    "c": "x"}]}, {
                        "t": "Para",
                        "c": []}, {
                            "t": "Plain",
                            "c": []}, {
                                "t": "Header",
                                "c": [2, ["", [], []], []]}, {
                                    "t": "CodeBlock",
                                    "c": [["", ["html"], []], '</details>\n\n<summary>code</summary>']},
            self._raw('<img src="a.png" />'),
            self._raw('<!-- -->'),
            self._raw('<div>text</div>'),
            self._raw('<details>', "latex"),
            self._raw('<details>\n\n</details>'),
            self._raw('<details>\n'),
            self._raw(' <details>'),
            self._raw(''), {
                "t": "RawBlock",
                "c": []}, {
                    "t": "RawBlock",
                    "c": ["html", 42]}]
        for boundary in boundaries:
            blocks = [
                self._raw('<details>'),
                self._raw('<summary>T</summary>'), boundary,
                self._raw('</details>'),
                self._raw('</div>')]
            original = deepcopy(blocks)
            with self.subTest(boundary=boundary):
                self.assertEqual(
                    self.converter._merge_tag_blocks(blocks),
                    [self._raw('<details>\n<summary>T</summary>'), boundary,
                     self._raw('</details>\n</div>')])
                self.assertEqual(blocks, original)

    def test_converts_flattened_container_runs_before_writing(self) -> None:
        paragraph = {"type": "paragraph", "content": [{"type": "text", "text": "x"}]}
        para = {"t": "Para", "c": [{"t": "Str", "c": "x"}]}
        cases = [
            (
                {
                    "type": "layoutSection",
                    "content": [{
                        "type": "layoutColumn",
                        "attrs": {
                            "width": 100},
                        "content": [paragraph]}]}, [
                            self._raw('<section data-type="layout-section">\n<div data-type="column" data-width="100">'), para,
                            self._raw('</div>\n</section>')]),
            (
                {
                    "type": "expand",
                    "attrs": {
                        "title": "T"},
                    "content": [paragraph]}, [self._raw('<details>\n<summary>T</summary>'), para,
                                              self._raw('</details>')]),
            (
                {
                    "type": "panel",
                    "attrs": {
                        "panelType": "custom"},
                    "content": [{
                        "type": "panel",
                        "attrs": {
                            "panelType": "tip"},
                        "content": [paragraph]}]},
                [self._raw('<div data-type="panel-custom">\n<div data-type="panel-tip">'), para,
                 self._raw('</div>\n</div>')]),
            (
                {
                    "type":
                    "mediaSingle",
                    "attrs": {
                        "layout": "wrap-right"},
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                "type": "external",
                                "url": "https://example.test/a.png",
                                "width": 400,
                                "height": 3}}, {
                                    "type": "caption",
                                    "content": [{
                                        "type": "text",
                                        "text": "x"}]}]},
                [
                    self._raw('<figure data-type="media-single" data-layout="wrap-right">'),
                    self._raw('<img src="https://example.test/a.png" width="400" height="3" alt="a.png" />'),
                    self._raw('<figcaption>'), para,
                    self._raw('</figcaption>\n</figure>')])]
        for node, expected in cases:
            with self.subTest(type=node["type"]):
                self.converter.convert({"type": "doc", "version": 1, "content": [node]})
                self.assertEqual(self.pandoc.pandoc["blocks"], expected)

    def test_retains_empty_paragraph_and_separator_comment_barriers(self) -> None:
        empty = {"type": "paragraph", "content": []}
        panel = {"type": "panel", "attrs": {"panelType": "tip"}, "content": [empty]}
        self.converter.convert({"type": "doc", "version": 1, "content": [panel]})
        self.assertEqual(
            self.pandoc.pandoc["blocks"], [self._raw('<div data-type="panel-tip">'), {
                "t": "Para",
                "c": []}, self._raw('</div>')])
        item = {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]}
        bullet = {"type": "bulletList", "content": [item]}
        expand = {"type": "expand", "attrs": {"title": "T"}, "content": [bullet, empty, bullet]}
        self.converter.convert({"type": "doc", "version": 1, "content": [expand]})
        self.assertEqual(self.pandoc.pandoc["blocks"][3], self._raw('<!-- -->'))
        self.assertEqual(self.pandoc.pandoc["blocks"][0], self._raw('<details>\n<summary>T</summary>'))

    def test_reusing_converter_does_not_merge_across_documents(self) -> None:
        paragraph = {"type": "paragraph", "content": [{"type": "text", "text": "x"}]}
        first = {"type": "doc", "version": 1, "content": [{"type": "expand", "attrs": {"title": "T"}, "content": [paragraph]}]}
        original = deepcopy(first)
        self.converter.convert(first)
        captured = deepcopy(self.pandoc.pandoc)
        self.converter.convert({"type": "doc", "version": 1, "content": [paragraph]})
        self.assertEqual(self.pandoc.pandoc["blocks"], [{"t": "Para", "c": [{"t": "Str", "c": "x"}]}])
        self.assertEqual(first, original)
        self.assertEqual(captured["blocks"][-1], self._raw('</details>'))


class RecordingLinks:
    """A link resolver that maps chosen targets and records every call."""

    def __init__(self, replacements=None):
        self.replacements = replacements or {}
        self.calls = []

    def to_markdown(self, href):
        self.calls.append(href)
        return self.replacements.get(href)


# vim: set ts=4 sw=4 et tw=132:
