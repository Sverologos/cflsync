# Copyright (c) 2026 Sven Rosiers
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Change inspection and installation planning shared by the synchronization commands."""

from __future__ import annotations

import hashlib
from pathlib import Path

from collections.abc import Callable, Iterator, Mapping

from .errors import SyncError
from .workarea import CONTENT_FILENAME, MediaResolver, PageState, Workarea

ATTACHMENTS_PREFIX = "_attachments/"


class PageChanges:
    """What differs between local files, cached state, and remote metadata."""

    def __init__(
            self, page_locally: bool, attachments_locally: list[str], page_remotely: bool, attachments_remotely: list[str]) -> None:
        self.page_locally = page_locally
        self.attachments_locally = attachments_locally
        self.page_remotely = page_remotely
        self.attachments_remotely = attachments_remotely

    @property
    def locally(self) -> bool:
        """Report whether the page or any managed attachment changed locally."""
        return self.page_locally or bool(self.attachments_locally)

    @property
    def remotely(self) -> bool:
        """Report whether the page or its attachment manifest changed remotely."""
        return self.page_remotely or bool(self.attachments_remotely)


class PageInspector:
    """Compare a page's local files and remote metadata with its cached state."""

    def __init__(self, pandoc) -> None:
        self._pandoc_runner = pandoc

    def content_hash(self, markdown: str) -> str:
        """Return the page state content hash of *markdown*, canonicalized through Pandoc."""
        canonical = self._pandoc_runner.pandoc_to_gfm(self._pandoc_runner.gfm_to_pandoc(markdown))

        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def referenced_attachments(self, markdown: str) -> list[str]:
        """Return the managed attachment filenames that *markdown* links to."""
        names = []
        for target in _link_targets(self._pandoc_runner.gfm_to_pandoc(markdown)):
            if not target.startswith(ATTACHMENTS_PREFIX):
                continue

            name = target[len(ATTACHMENTS_PREFIX):]
            if name and name not in {".", ".."} and "/" not in name and "\\" not in name:
                names.append(name)

        return names

    def inspect(self, directory: Path, state: PageState, page, attachments) -> PageChanges:
        """Report local and remote changes for one cached page."""
        page_locally, attachments_locally = self.inspect_local(directory, state)

        return PageChanges(
            page_locally, attachments_locally, self._page_changed_remotely(page, state),
            self._attachments_changed_remotely(attachments, state))

    def inspect_local(self, directory: Path, state: PageState) -> tuple[bool, list[str]]:
        """Report whether a cached page's Markdown changed locally, and which managed attachments did."""
        path = directory / CONTENT_FILENAME
        markdown = path.read_text(encoding="utf-8") if path.is_file() else None

        return (
            markdown is None or self.content_hash(markdown) != state.page.content_hash,
            self._attachments_changed_locally(directory, state, markdown))

    def _attachments_changed_locally(self, directory, state, markdown):
        MediaResolver((name, attachment.id) for name, attachment in state.attachments.items())
        changed = set()
        for name, attachment in state.attachments.items():
            path = directory / "_attachments" / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != attachment.content_hash:
                changed.add(name)

        # A referenced local file becomes managed, so content.md can introduce attachments.
        for name in self.referenced_attachments(markdown or ""):
            if name not in state.attachments and (directory / "_attachments" / name).is_file():
                changed.add(name)

        return sorted(changed)

    def _page_changed_remotely(self, page, state):
        return page.version != state.page.version or page.title != state.page.title

    def _attachments_changed_remotely(self, attachments, state):
        remote = {attachment.filename: (attachment.id, attachment.version) for attachment in attachments}
        cached = {name: (attachment.id, attachment.version) for name, attachment in state.attachments.items()}
        changed = []
        for name in sorted(set(remote) | set(cached)):
            if remote.get(name) != cached.get(name):
                changed.append(name)

        return changed


def _link_targets(value: object) -> Iterator[str]:
    """Yield the target of every Pandoc link and image in *value*."""
    if isinstance(value, Mapping):
        if value.get("t") in {"Image", "Link"}:
            content = value.get("c")
            if isinstance(content, list) and len(content) == 3 and isinstance(content[2], list) and content[2]:
                target = content[2][0]
                if isinstance(target, str):
                    yield target

        value = list(value.values())

    if isinstance(value, list):
        for item in value:
            yield from _link_targets(item)


class PlannedPage:
    """One planned page installation.

    *directory* is relative to the workarea root, with "/" separators. *restore* is true for a cached page whose
    directory is missing, and false for a page that is not cached yet.
    """

    def __init__(self, page, directory: str, restore: bool) -> None:
        self.page = page
        self.directory = directory
        self.restore = restore


class InstallationPlan:
    """An ordered list of page installations, parents before children."""

    def __init__(self, pages: list[PlannedPage]) -> None:
        self.pages = pages

    @classmethod
    def for_ancestors(cls, workarea: Workarea, api, page_id: str, include_page: bool = False) -> "InstallationPlan":
        """Plan the installation of the locally missing ancestors of a page, up to the root page.

        With *include_page*, the page itself is planned as well if it is missing locally. Planning reads from
        Confluence but changes nothing. It fails if the page is not in the workarea's tree, if its ancestors change
        while planning, or if a planned directory clashes with a cached sibling or another entry.
        """
        chain = _ancestor_chain(workarea, api, page_id)
        if not include_page:
            chain = chain[:-1]

        tree = workarea.page_tree()
        planned: dict[str, PlannedPage] = {}
        pages: list[PlannedPage] = []
        for index, chain_id in enumerate(chain):
            cached = tree.states.get(chain_id)
            if cached is not None and workarea.page_directory(cached, must_exist=False).is_dir():
                continue

            expected_parent_id = None if index == 0 else chain[index - 1]
            page = api.get_page(chain_id)
            if index > 0 and page.parent_id != expected_parent_id:
                raise SyncError(
                    f"the ancestors of page '{page_id}' changed while planning: page '{chain_id}' is now below "
                    f"'{page.parent_id}' instead of '{expected_parent_id}'; retry the command")

            if cached is not None:
                # Cached ancestors retain their cached place in the tree, even when their remote title or parent
                # changed.  A missing directory has no local content to preserve, so it can be restored there.
                parent_id = cached.page.parent_id
                name = cached.page.directory
                directory = tree.directory(chain_id)
            else:
                parent_id = expected_parent_id
                name = workarea.page_directory_name(page.title)
                if parent_id in planned:
                    directory = f"{planned[parent_id].directory}/{name}"
                else:
                    directory = workarea.relative_directory(parent_id, name)

            # Below a planned parent there cannot be an existing entry: validation of that parent's own target would
            # have rejected it.  All other targets must be checked before the first installation.
            if parent_id not in planned:
                workarea.page_directory_target(chain_id, parent_id, name)

            planned[chain_id] = PlannedPage(page, directory, cached is not None)
            pages.append(planned[chain_id])

        return cls(pages)

    def install(self, install_page: Callable[[PlannedPage], None]) -> list[PlannedPage]:
        """Install the planned pages top-down and return them.

        *install_page* installs one planned page and persists its state.  It receives the complete plan item so the
        installer can use its planned directory and restoration status. Pages installed before a failure remain; the
        error lists them.
        """
        installed: list[PlannedPage] = []
        for planned in self.pages:
            try:
                install_page(planned)
            except SyncError as error:
                if not installed:
                    raise

                pulled = ", ".join(f"'{item.page.title}' ({item.page.id})" for item in installed)
                raise SyncError(f"{error}; pages pulled before the failure: {pulled}") from error

            print(f"Pulled parent '{planned.page.title}' ({planned.page.id}) to {planned.directory}")
            installed.append(planned)

        return installed


def _ancestor_chain(workarea, api, page_id):
    # The chain runs from the root page down to the page itself.
    root_page_id = workarea.root_page_id
    if page_id == root_page_id:
        return [page_id]

    ancestors = api.page_ancestors(page_id)
    ancestor_ids = [ancestor.id for ancestor in ancestors]
    if root_page_id not in ancestor_ids:
        raise SyncError(f"page '{page_id}' is not in this workarea's tree, which is anchored at page '{root_page_id}'")

    below_root = ancestors[ancestor_ids.index(root_page_id):]
    for ancestor in below_root[1:]:
        if ancestor.type != "page":
            raise SyncError(
                f"page '{page_id}' is below {ancestor.type} '{ancestor.id}' in this workarea's tree; only pages are supported")

    return [ancestor.id for ancestor in below_root] + [page_id]


# vim: set ts=4 sw=4 et tw=132:
