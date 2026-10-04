# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Status reporting against a recorded HTTP transport."""

from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cflsync import APIClient, Profile, SyncError
from cflsync.cli import PagePullCommand, PageStatusCommand
from tests.support import FakeConfluence, MockResponse, MockTransport, run_with_site, temporary_workarea
from tests.test_api_operations import attachment_fixture, page_fixture


def page_body(text="Example"):
    document = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}

    return {"atlas_doc_format": {"value": json.dumps(document)}}


class TestPageStatus(unittest.TestCase):

    def _page(self, version=17, title="Example page"):
        page = page_fixture(title=title)
        page["version"] = {"number": version}
        page["body"] = page_body()

        return page

    def _run(self, workarea, command, responses):
        transport = MockTransport(responses)
        client = APIClient("example.atlassian.net", "user", "token", transport=transport)
        config = SimpleNamespace(profiles={workarea.profile: Profile("example.atlassian.net", "user", "token")})
        output = StringIO()
        with patch("cflsync.cli.Path.cwd", return_value=workarea.root_dir):
            with patch("cflsync.cli.Config.find", return_value=config):
                with patch("cflsync.cli.APIClient", return_value=client):
                    with redirect_stdout(output):
                        status = command()

        return output.getvalue(), status, transport

    def _pull(self, workarea, page=None, attachments=None):
        if page is None:
            page = self._page()

        if attachments is None:
            attachments = [attachment_fixture()]

        responses = [
            MockResponse.from_json(page),
            MockResponse.from_json(page),
            MockResponse.from_json({"results": attachments}), *[MockResponse(200, {}, b"PNG") for attachment in attachments], ]
        self._run(workarea, lambda: PagePullCommand().run("123456"), responses)

    def _status(self, workarea, page=None, attachments=None):
        if page is None:
            page = self._page()

        if attachments is None:
            attachments = [attachment_fixture()]

        responses = [MockResponse.from_json(page), MockResponse.from_json({"results": attachments})]

        return self._run(workarea, lambda: PageStatusCommand().run("123456"), responses)

    def _snapshot(self, workarea):
        return {
            str(path.relative_to(workarea.root_dir)): path.read_bytes() if path.is_file() else None
            for path in workarea.root_dir.rglob("*")}

    def test_rejects_a_page_without_a_cache_entry(self) -> None:
        with temporary_workarea() as workarea:
            with self.assertRaisesRegex(SyncError, "no managed local page matches '123456'"):
                self._status(workarea)


class TestPageStatusInTree(unittest.TestCase):
    """Status in a tree of Root (100), with Child (200) and Other (400) below it."""

    def setUp(self):
        self.site = self._site()

    def _site(self):
        site = FakeConfluence()
        site.add_page("100", "Root")
        site.add_page("200", "Child", parent_id="100")
        site.add_page("400", "Other", parent_id="100")
        return site

    def _pull(self, workarea, *page_ids):
        for page_id in page_ids:
            run_with_site(self.site, workarea, lambda: PagePullCommand().run(page_id))

    def _status(self, workarea, page_ref="200"):
        return run_with_site(self.site, workarea, lambda: PageStatusCommand().run(page_ref))

    def _remote_change(self, page_id, **fields):
        self.site.content[page_id].update(fields)
        self.site.content[page_id]["version"] += 1

    def test_reports_a_move_below_a_parent_that_pull_installs_first(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            self._remote_change("200", parent_id="400")

            output = self._status(workarea)

            self.assertIn("location: moves from 'Root_100/Child_200' below page '400' on pull, which pulls that page first", output)

    def test_reports_a_page_deleted_remotely_with_its_local_changes(self) -> None:
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            (workarea.root_dir / "Root_100" / "Child_200" / "content.md").write_text("# Child\n\nEdited\n", encoding="utf-8")
            del self.site.content["200"]

            output = self._status(workarea)

            self.assertIn("local:  changed: content.md", output)
            self.assertIn("remote: not found; the page was deleted, or is not accessible", output)
            self.assertNotIn("location:", output)

    def test_reports_a_page_moved_outside_the_tree(self) -> None:
        self.site.add_page("900", "Outside")
        with temporary_workarea(root_page_id="100") as workarea:
            self._pull(workarea, "100", "200")
            self._remote_change("200", parent_id="900")

            output = self._status(workarea)

            self.assertIn("local:  unchanged", output)
            self.assertIn("remote: moved outside this workarea's tree", output)
            self.assertNotIn("location:", output)


# vim: set ts=4 sw=4 et tw=132:
