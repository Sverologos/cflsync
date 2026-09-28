# Copyright (c) 2026 Sven Rosiers
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Repository synchronization plan (draft):
#
# Build a TreeStatus:
#
# 1. List the root reference and every remote descendant.
# 2. List all local pages by loading the local cache.
# 3. For each remote page, match its cached page. No cached state or local directory is ``absent-local``. Otherwise,
#    classify the remote representation against the cached version.
# 4. Every cached page absent from the remote list is ``absent-remote``. For matched pages, combine local and remote
#    change states: both changed is ``conflict``; otherwise one changed is ``local-changed`` or ``remote-changed``;
#    neither changed is ``unchanged``.
#
# Commands map PageStatusState mechanically:
#
# - ``absent-local``: not in local.
# - ``remote-changed``: remote changed.
# - ``local-changed``: local changed.
# - ``conflict``: conflict.
# - ``absent-remote``: remote removed.
# - ``unchanged``: unchanged.
#
# Execute:
#
# - If any ``conflict`` entry exists, abort unless ``--force`` was specified.
# - For pull, topologically sort the statuses parents before children. Execute ``remote-changed`` and ``absent-local``;
#   with ``--force``, also execute ``conflict`` and ``unchanged`` entries as pulls; skip every other entry.
# - For push (RepositoryPushOperation), walk the statuses parents before children; a page push changes no hierarchy, so
#   order is only deterministic. Execute ``local-changed`` entries; with ``--force``, also execute ``conflict`` and
#   ``unchanged`` entries as pushes. Never push ``absent-remote`` entries; recreate those pages with ``page create``
#   instead.
#
# TreeStatus only compares and orders; each repository operation is a separate class mapping a page operation over it.

"""Change inspection and installation planning shared by the synchronization commands."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from collections.abc import Callable, Iterator, Mapping
from enum import StrEnum
from graphlib import CycleError, TopologicalSorter

from .api import APIError, RemoteContentRef
from .convert import MarkdownToADFConverter, PandocRunner
from .errors import SyncError
from .workarea import AttachmentMetadata, CONTENT_FILENAME, MediaResolver, PageMetadata, PageState, Workarea, filesystem_error_message

ATTACHMENTS_PREFIX = "_attachments/"


class PageOperationResult:
    """The outcome of one page in a repository-level operation."""

    def __init__(self, page_id: str, title: str, outcome: str, detail: str | None = None) -> None:
        self.page_id = page_id
        self.title = title
        self.outcome = outcome
        self.detail = detail


class PageOperationResults:
    """Per-page outcomes and a summary for a repository-level operation."""

    def __init__(self) -> None:
        self.pages: list[PageOperationResult] = []

    @property
    def failed(self) -> bool:
        """Report whether any page operation failed."""
        return any(result.outcome == "failed" for result in self.pages)

    def add(self, page_id: str, title: str, outcome: str, detail: str | None = None) -> None:
        """Record one page outcome."""
        self.pages.append(PageOperationResult(page_id, title, outcome, detail))

    def report(self) -> None:
        """Print every result followed by its outcome counts."""
        for result in self.pages:
            detail = f": {result.detail}" if result.detail is not None else ""
            print(f"Page '{result.page_id}' ({result.title}): {result.outcome}{detail}")

        if not self.pages:
            print("Summary: no cached pages.")
            return

        counts = {
            outcome: sum(result.outcome == outcome for result in self.pages)
            for outcome in ["pushed", "unchanged", "skipped", "failed"]}
        summary = ", ".join(f"{count} {outcome}" for outcome, count in counts.items() if count)
        print(f"Summary: {summary}.")


class PageChangeStatus(StrEnum):
    """The local or remote change state of a page representation."""

    ABSENT = "absent"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


class PageChangeDetector:
    """Classify local files and remote metadata independently against cached state."""

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

    def local_status(self, directory: Path | None, state: PageState | None) -> PageChangeStatus:
        """Return ``absent``, ``changed``, or ``unchanged`` for the local cached page representation."""
        if state is None or directory is None or not directory.is_dir():
            return PageChangeStatus.ABSENT

        page_changed, attachments_changed = self.local_changes(directory, state)
        return PageChangeStatus.CHANGED if page_changed or attachments_changed else PageChangeStatus.UNCHANGED

    def remote_status(self, page, attachments, state: PageState | None) -> PageChangeStatus:
        """Return ``absent``, ``changed``, or ``unchanged`` for remote metadata against cached state."""
        if page is None:
            return PageChangeStatus.ABSENT
        if state is None:
            return PageChangeStatus.CHANGED

        page_changed, attachments_changed = self.remote_changes(page, attachments, state)
        return PageChangeStatus.CHANGED if page_changed or attachments_changed else PageChangeStatus.UNCHANGED

    def local_changes(self, directory: Path, state: PageState) -> tuple[bool, list[str]]:
        """Return local page and managed-attachment changes for detailed status reporting."""
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

    def remote_changes(self, page, attachments, state: PageState) -> tuple[bool, list[str]]:
        """Return remote page and managed-attachment changes for detailed status reporting."""
        page_changed = page.version != state.page.version or page.title != state.page.title
        remote = {attachment.filename: (attachment.id, attachment.version) for attachment in attachments}
        cached = {name: (attachment.id, attachment.version) for name, attachment in state.attachments.items()}
        changed = []
        for name in sorted(set(remote) | set(cached)):
            if remote.get(name) != cached.get(name):
                changed.append(name)

        return page_changed, changed


class PageStatusState(StrEnum):
    """The combined local and remote synchronization state of a page."""

    ABSENT_LOCAL = "absent-local"
    ABSENT_REMOTE = "absent-remote"
    REMOTE_CHANGED = "remote-changed"
    LOCAL_CHANGED = "local-changed"
    CONFLICT = "conflict"
    UNCHANGED = "unchanged"


class PageStatus:
    """One local/remote page comparison result."""

    def __init__(self, status: PageStatusState, remote: RemoteContentRef | None, local: PageState | None) -> None:
        if remote is None and local is None:
            raise ValueError("a page status requires a remote page, a local page, or both")
        if remote is not None and local is not None and remote.id != local.page.id:
            raise ValueError("the remote and local page IDs differ")

        if remote is not None:
            self.id = remote.id
        else:
            assert local is not None
            self.id = local.page.id
        self.status = status
        self.remote = remote
        self.local = local

    @property
    def parent_id(self) -> str | None:
        """Return the current remote parent, or the cached parent if the remote page is absent."""
        if self.remote is not None:
            return self.remote.parent_id

        assert self.local is not None
        return self.local.page.parent_id


class TreeStatus:
    """The synchronization status of a remote page list and local cache."""

    def __init__(self, pages: list[PageStatus]) -> None:
        self.pages = self._parents_first(pages)

    @staticmethod
    def _parents_first(pages: list[PageStatus]) -> list[PageStatus]:
        """Return *pages* topologically sorted with every represented parent before its children."""
        by_id = _pages_by_id(pages, "tree status", lambda page: page.id)
        sorter: TopologicalSorter[str] = TopologicalSorter()
        for page in pages:
            parent_id = page.parent_id
            if parent_id is not None and parent_id in by_id:
                sorter.add(page.id, parent_id)
            else:
                sorter.add(page.id)

        try:
            page_ids = list(sorter.static_order())
        except CycleError as error:
            raise SyncError("page hierarchy contains a cycle") from error

        return [by_id[page_id] for page_id in page_ids]

    @classmethod
    def from_pages(
            cls, workarea: Workarea, api, remote_pages: list[RemoteContentRef], local_pages: list[PageState],
            detector: PageChangeDetector) -> "TreeStatus":
        """Compare *remote_pages* with *local_pages* and return one status per page ID.

        Remote page order is retained. Cached pages absent from that list are appended in their supplied order.
        """
        remotes = _pages_by_id(remote_pages, "remote page list")
        locals_ = _pages_by_id(local_pages, "local cache", lambda state: state.page.id)
        pages = []

        for remote in remotes.values():
            local = locals_.pop(remote.id, None)
            if local is None:
                pages.append(PageStatus(PageStatusState.ABSENT_LOCAL, remote, None))
                continue

            local_status = detector.local_status(workarea.page_directory(local, must_exist=False), local)
            if local_status is PageChangeStatus.ABSENT:
                pages.append(PageStatus(PageStatusState.ABSENT_LOCAL, remote, local))
                continue

            try:
                page = api.get_page(remote.id)
            except APIError as error:
                if error.status != 404:
                    raise
                pages.append(PageStatus(PageStatusState.ABSENT_REMOTE, None, local))
                continue

            remote_status = detector.remote_status(page, page.attachments(), local)
            pages.append(PageStatus(cls._status(local_status, remote_status), remote, local))

        for local in locals_.values():
            pages.append(PageStatus(PageStatusState.ABSENT_REMOTE, None, local))

        return cls(pages)

    @staticmethod
    def _status(local: PageChangeStatus, remote: PageChangeStatus) -> PageStatusState:
        """Map independent local and remote change states to one synchronization state."""
        if local is PageChangeStatus.ABSENT:
            return PageStatusState.ABSENT_LOCAL
        if remote is PageChangeStatus.ABSENT:
            return PageStatusState.ABSENT_REMOTE
        if local is PageChangeStatus.CHANGED and remote is PageChangeStatus.CHANGED:
            return PageStatusState.CONFLICT
        if local is PageChangeStatus.CHANGED:
            return PageStatusState.LOCAL_CHANGED
        if remote is PageChangeStatus.CHANGED:
            return PageStatusState.REMOTE_CHANGED
        return PageStatusState.UNCHANGED


class PagePushOperation:
    """The reusable local-to-remote synchronization operation for one existing page."""

    def __init__(self, pandoc: PandocRunner | None = None) -> None:
        self._pandoc = pandoc or PandocRunner()
        self._detector = PageChangeDetector(self._pandoc)

    def push(self, workarea: Workarea, api, status: PageStatus, force: bool = False) -> bool:
        """Push the locally cached page represented by *status*, returning whether it changed the remote page."""
        state = status.local
        if state is None:
            raise SyncError(f"page '{status.id}' is not present locally and cannot be pushed")

        page = api.get_page(status.id)
        directory = workarea.page_directory(state)
        attachments = page.attachments()
        if not force:
            if self._detector.remote_status(page, attachments, state) != PageChangeStatus.UNCHANGED:
                raise SyncError(f"page '{page.id}' has remote changes; push conflicts")

            if self._detector.local_status(directory, state) != PageChangeStatus.CHANGED:
                return False

        markdown = (directory / CONTENT_FILENAME).read_text(encoding="utf-8")
        bodies = self._managed_attachments(directory, state, markdown)
        self._upload_attachments(page, state, bodies, attachments)
        # Re-read the manifest so new uploads contribute their server-assigned file IDs.
        remote = {attachment.filename: attachment for attachment in page.attachments()}
        document = self._convert(markdown, page, bodies, remote, api)
        updated = page.update(json.dumps(document))
        self._delete_removed_attachments(state, bodies, remote)

        updated_attachments = {}
        for name, body in bodies.items():
            updated_attachments[name] = AttachmentMetadata(remote[name].id, remote[name].version, hashlib.sha256(body).hexdigest())

        PageState(
            PageMetadata(
                updated.id, updated.title, state.page.parent_id, state.page.directory, updated.version,
                self._detector.content_hash(markdown)), updated_attachments).save(workarea.cache_path(updated.id))
        return True

    def _managed_attachments(self, directory, state, markdown):
        """Return the bytes of every managed attachment still present locally."""
        names = set(state.attachments) | set(self._detector.referenced_attachments(markdown))
        bodies = {}
        for name in sorted(names):
            path = directory / "_attachments" / name
            if path.is_file():
                bodies[name] = path.read_bytes()

        return bodies

    @staticmethod
    def _upload_attachments(page, state, bodies, attachments):
        remote = {attachment.filename: attachment for attachment in attachments}
        for name, body in bodies.items():
            existing = remote.get(name)
            if existing is None:
                page.create_attachment(name, body)
                continue

            cached = state.attachments.get(name)
            local_hash = hashlib.sha256(body).hexdigest()
            if cached is None or cached.content_hash != local_hash or (existing.id, existing.version) != (cached.id,
                                                                                                          cached.version):
                existing.update(body)

    @staticmethod
    def _delete_removed_attachments(state, bodies, remote):
        for name in state.attachments:
            if name not in bodies and name in remote:
                remote[name].delete()

    def _convert(self, markdown, page, bodies, remote, api):
        # Attachments without a server-assigned file ID cannot be referenced from ADF.
        media = MediaResolver(
            (name, remote[name].file_id) for name in bodies if name in remote and remote[name].file_id is not None)
        return MarkdownToADFConverter(self._pandoc, media, f"contentId-{page.id}", api.find_user_by_name_and_email).convert(
            markdown, title=page.title)


class RepositoryPushOperation:
    """Apply page push operations to a complete tree-status comparison."""

    def __init__(self, page_push: PagePushOperation | None = None) -> None:
        self._page_push = page_push or PagePushOperation()

    def push(self, workarea: Workarea, api, status: TreeStatus, force: bool = False) -> PageOperationResults:
        """Push locally changed pages, rejecting detected conflicts unless *force* prefers local state."""
        if not force and any(page.status is PageStatusState.CONFLICT for page in status.pages):
            raise SyncError("repository push conflicts; resolve conflicts or use --force")

        results = PageOperationResults()
        for page_status in status.pages:
            if page_status.status is PageStatusState.LOCAL_CHANGED or (force and page_status.status in {PageStatusState.CONFLICT,
                                                                                                        PageStatusState.UNCHANGED}):
                try:
                    pushed = self._page_push.push(workarea, api, page_status, force=force)
                except (OSError, UnicodeError) as error:
                    results.add(page_status.id, _status_title(page_status), "failed", filesystem_error_message(error))
                except SyncError as error:
                    results.add(page_status.id, _status_title(page_status), "failed", str(error))
                else:
                    results.add(page_status.id, _status_title(page_status), "pushed" if pushed else "unchanged")
                continue

            if page_status.status is PageStatusState.UNCHANGED:
                results.add(page_status.id, _status_title(page_status), "unchanged")
            else:
                results.add(page_status.id, _status_title(page_status), "skipped", page_status.status)

        return results


def _status_title(status: PageStatus) -> str:
    """Return the best title available for a status report."""
    if status.local is not None:
        return status.local.page.title
    if status.remote is not None and status.remote.title is not None:
        return status.remote.title
    return status.id


def _pages_by_id(pages, description: str, page_id=lambda page: page.id):
    """Return *pages* indexed by ID, rejecting duplicate IDs in one input list."""
    result = {}
    for page in pages:
        identifier = page_id(page)
        if identifier in result:
            raise SyncError(f"{description} contains page '{identifier}' more than once")
        result[identifier] = page
    return result


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

    *parent_id* and *directory_name* are the location that the installer must persist. *directory* is its path
    relative to the workarea root, with "/" separators. *restore* is true for a cached page whose directory is
    missing, and false for a page that is not cached yet.
    """

    def __init__(self, page, parent_id: str | None, directory_name: str, directory: str, restore: bool) -> None:
        self.page = page
        self.parent_id = parent_id
        self.directory_name = directory_name
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

            planned[chain_id] = PlannedPage(page, parent_id, name, directory, cached is not None)
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
