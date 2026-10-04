# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for ADF to Markdown conversion."""

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
                    "type": "textColor",
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


class RecordingLinks:
    """A link resolver that maps chosen targets and records every call."""

    def __init__(self, replacements=None):
        self.replacements = replacements or {}
        self.calls = []

    def to_markdown(self, href):
        self.calls.append(href)
        return self.replacements.get(href)


# vim: set ts=4 sw=4 et tw=132:
