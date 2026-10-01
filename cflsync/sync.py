# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Repository synchronization:
#
# Build a TreeStatus (TreeStatus.for_workarea):
#
# 1. List the root reference and every remote descendant (APIClient.page_descendants). Discovery either returns the
#    complete page hierarchy or raises, for example on a failed listing or non-page content, so no absence is ever
#    inferred from a partial listing.
# 2. List all local pages by loading the local cache.
# 3. For each remote page, match its cached page. No cached state or local directory is ``absent-local``. Otherwise,
#    classify the remote representation against the cached version.
# 4. Every cached page absent from the remote list is ``absent-remote``, or ``conflict-absent-remote`` if its local copy
#    changed. For matched pages, combine local and remote change states (PageChangeDetector): both changed is
#    ``conflict``; otherwise one changed is ``local-changed`` or ``remote-changed``; neither changed is ``unchanged``.
#    ``conflict-absent-remote`` is a conflict too, but a separate state, because every operation resolves ``conflict``
#    by assuming that the remote page exists.
# 5. Sort the statuses topologically, parents before children.
#
# Report (``cflsync status``, in the CLI) maps each PageStatusState to a label, parents first:
#
# - ``absent-local``: not in local.
# - ``remote-changed``: remote changed.
# - ``local-changed``: local changed.
# - ``conflict``: conflict.
# - ``absent-remote``: remote removed.
# - ``conflict-absent-remote``: remote removed, local changed.
# - ``unchanged``: unchanged.
#
# Execute: every check runs before any page operation, so a failed check or a declined confirmation changes nothing.
#
# - Without ``--force``, any ``conflict`` entry aborts; for ``pull --delete``, so does any ``conflict-absent-remote``.
# - For pull (RepositoryPullOperation), walk the statuses parents before children, since a page directory lives inside
#   its parent's. Execute ``remote-changed`` and ``absent-local`` entries (an ``absent-local`` entry with cached state
#   restores the missing directory); with ``--force``, also execute ``conflict`` and ``unchanged`` entries as pulls.
#   Each pull places the page below its current remote parent and relocates its directory, with its subtree, after a
#   remote rename or move. Its directory name is the encoded title followed by ``_`` and the page ID, so sibling names
#   never clash. A page below a page that failed is blocked. Skip ``local-changed`` entries. Handle absent pages last,
#   after every relocation out of their directories:
#   - Without ``--delete``, keep ``absent-remote`` and ``conflict-absent-remote`` entries unchanged and report them.
#   - With ``--delete``, the CLI first confirms the deletions (PageDeletion) unless ``--force`` is given; declining
#     aborts. Then delete each absent page's local directory, with unmanaged files, and its cache entry, children
#     before parents, so that every remaining cached page keeps its cached parent after an interruption. The cache is
#     reloaded first, because the pull phase may have relocated pages. A directory is deleted only if every cached page
#     below it is deleted too; otherwise the page is blocked. A missing directory only loses its cache entry.
# - For push (RepositoryPushOperation), walk the statuses parents before children; a page push changes no hierarchy, so
#   order is only deterministic. Execute ``local-changed`` entries; with ``--force``, also execute ``conflict`` and
#   ``unchanged`` entries as pushes. Never push ``absent-remote`` or ``conflict-absent-remote`` entries; recreate those
#   pages with ``page create`` instead.
#
# Remove a page and its subtree (PageRemoveOperation, ``page remove``):
#
# 1. Compare the subtree: the page and its remote descendants against the cached subtree, as a TreeStatus. A cached
#    page missing from the remote subtree is looked up: a 404 means removed, an existing page means moved elsewhere.
# 2. Check before any change: every page is ``unchanged``, ``absent-local`` (remote only, or no local directory), or
#    ``absent-remote``; ``conflict-absent-remote`` only with ``--force``. A page moved into or out of the subtree
#    aborts, as does a current directory inside the page's directory on Windows. Then confirm unless ``--force``.
# 3. Remove children first: remotely (a 404 counts as removed), then the local directory, then the cache entry. A
#    failure stops the removal; the page given is removed last and stays resolvable, so a rerun completes it.
#
# TreeStatus only compares and orders; each repository operation is a separate class mapping a page operation over it.

"""Change detection, tree comparison, and synchronization operations linking the workarea with Confluence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from collections.abc import Callable, Iterator, Mapping
from enum import StrEnum
from graphlib import CycleError, TopologicalSorter

from .api import APIError, RemoteContentRef
from .convert import ADFToMarkdownConverter, MarkdownToADFConverter, PandocRunner
from .errors import SyncError
from .workarea import (
    AttachmentMetadata, CONTENT_FILENAME, MediaResolver, PageMetadata, PageState, Workarea, filesystem_error_message)

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
            for outcome in ["pulled", "pushed", "deleted", "unchanged", "skipped", "kept", "blocked", "failed"]}
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
    # A conflict on a page removed remotely and changed locally. It is separate from CONFLICT, which every operation
    # resolves by assuming that the remote page exists.
    CONFLICT_ABSENT_REMOTE = "conflict-absent-remote"
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

    @property
    def title(self) -> str:
        """Return the cached title, or the remote title for a page that is not cached."""
        if self.local is not None:
            return self.local.page.title
        if self.remote is not None and self.remote.title is not None:
            return self.remote.title
        return self.id


class TreeStatus:
    """The synchronization status of a remote page list and local cache."""

    def __init__(self, pages: list[PageStatus]) -> None:
        self.pages = self._parents_first(pages)
        # The complete page index that listed the remote pages, when built by for_workarea.
        self.index: PageIndex | None = None

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
    def for_workarea(cls, workarea: Workarea, api, detector: PageChangeDetector) -> "TreeStatus":
        """Compare the workarea's complete remote page tree with its local cache.

        Discovery either returns the complete page hierarchy below the root page or raises, so a cached page is only
        classified as ``absent-remote`` after a complete listing. The complete index is kept as :attr:`index`.
        """
        index = PageIndex(workarea, api, prefill=True)
        status = cls.from_pages(workarea, api, index.pages, list(workarea.page_tree().states.values()), detector)
        status.index = index
        return status

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
                pages.append(PageStatus(cls._absent_remote_status(local_status), None, local))
                continue

            remote_status = detector.remote_status(page, page.attachments(), local)
            pages.append(PageStatus(cls._status(local_status, remote_status), remote, local))

        for local in locals_.values():
            local_status = detector.local_status(workarea.page_directory(local, must_exist=False), local)
            pages.append(PageStatus(cls._absent_remote_status(local_status), None, local))

        return cls(pages)

    @staticmethod
    def _absent_remote_status(local: PageChangeStatus) -> PageStatusState:
        """Map the local change state of a page absent remotely to one synchronization state."""
        if local is PageChangeStatus.CHANGED:
            return PageStatusState.CONFLICT_ABSENT_REMOTE
        return PageStatusState.ABSENT_REMOTE

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
                    results.add(page_status.id, page_status.title, "failed", filesystem_error_message(error))
                except SyncError as error:
                    results.add(page_status.id, page_status.title, "failed", str(error))
                else:
                    results.add(page_status.id, page_status.title, "pushed" if pushed else "unchanged")
                continue

            if page_status.status is PageStatusState.UNCHANGED:
                results.add(page_status.id, page_status.title, "unchanged")
            else:
                results.add(page_status.id, page_status.title, "skipped", page_status.status)

        return results


class PagePullOperation:
    """The reusable remote-to-local synchronization operation for one page."""

    def __init__(self, pandoc: PandocRunner | None = None) -> None:
        self._pandoc = pandoc or PandocRunner()
        self._detector = PageChangeDetector(self._pandoc)

    def install_ancestors(self, workarea: Workarea, api, page_id: str, include_page: bool = False) -> None:
        """Plan and install the locally missing ancestors of *page_id*, optionally including that page."""
        plan = InstallationPlan.for_ancestors(workarea, api, page_id, include_page=include_page)
        plan.install(lambda planned: self._pull_planned(workarea, api, planned))

    def _pull_planned(self, workarea, api, planned: PlannedPage) -> None:
        # A planned ancestor is installed at its planned location; a cached one is restored there.
        self.pull(
            workarea,
            api,
            planned.page,
            force=planned.restore,
            parent_id=planned.parent_id,
            directory_name=planned.directory_name,
            directory=planned.directory)

    def pull(
            self,
            workarea: Workarea,
            api,
            page,
            force: bool = False,
            parent_id: str | None = None,
            directory_name: str | None = None,
            directory: str | None = None) -> bool:
        """Install or update the local copy of remote *page*, returning whether anything was pulled.

        The page is placed below its remote parent, which must be present locally, unless *directory* gives a
        planned location. Its directory name is the encoded title followed by ``_`` and the page ID. Without
        *force*, local changes conflict, and a page that is in sync and in place is left alone. With *force*, remote
        content is preferred and a missing local directory is restored.
        """
        attachments = page.attachments()
        MediaResolver((attachment.filename, attachment.id) for attachment in attachments)
        # ADF media nodes reference attachments by file ID, not by attachment ID.
        media = MediaResolver(
            (attachment.filename, attachment.file_id) for attachment in attachments if attachment.file_id is not None)
        cache_path = workarea.cache_path(page.id)
        # The root page's parent is outside the workarea; every other page is placed below its parent. A planner may
        # restore a cached ancestor at its cached location, despite remote hierarchy or title changes.
        if directory is None:
            parent_id = None if page.id == workarea.root_page_id else page.parent_id
            directory_name = workarea.page_directory_name(page.title, page.id)
            directory = workarea.relative_directory(parent_id, directory_name)

        assert directory_name is not None
        if parent_id is not None:
            _require_local_parent(workarea, parent_id, api)

        previous = None
        source = None
        if cache_path.exists():
            previous = PageState.load(cache_path)
            source = workarea.page_directory(previous, must_exist=not force)
            if force and not source.exists():
                source = None

            if not force:
                if self._detector.local_status(source, previous) != PageChangeStatus.UNCHANGED:
                    raise SyncError(f"page '{page.id}' has local changes; pull conflicts")

                # A page moved or renamed remotely is relocated even when its content is unchanged.
                if self._detector.remote_status(
                        page, attachments,
                        previous) == PageChangeStatus.UNCHANGED and source == workarea.page_directory_path(directory):
                    return False

        # Cached siblings count even when their directories are missing.
        workarea.page_directory_target(page.id, parent_id, directory_name)

        try:
            document = json.loads(page.body)
        except (TypeError, json.JSONDecodeError) as error:
            raise SyncError(f"page '{page.id}' has invalid ADF JSON") from error

        if not isinstance(document, dict):
            raise SyncError(f"page '{page.id}' ADF must be an object")

        markdown = ADFToMarkdownConverter(self._pandoc, media, api.get_user).convert(document, title=page.title)
        bodies = {}
        metadata = {}
        for attachment in attachments:
            body = attachment.download()
            bodies[attachment.filename] = body
            metadata[attachment.filename] = AttachmentMetadata(attachment.id, attachment.version, hashlib.sha256(body).hexdigest())

        state = PageState(
            PageMetadata(page.id, page.title, parent_id, directory_name, page.version, self._detector.content_hash(markdown)),
            metadata)
        managed: Mapping[str, AttachmentMetadata] = {}
        if previous is not None:
            managed = previous.attachments

        staging = workarea.stage_page(directory, markdown, bodies, source=source, managed_attachments=managed)
        try:
            with workarea.replace_page(staging, directory, source, set(managed) | set(bodies)):
                state.save(cache_path)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

        return True


class PageDeletion:
    """One page that ``pull --delete`` or ``page remove`` deletes.

    *directory* is its local directory relative to the workarea root, with "/" separators, or ``None`` for a page that
    is not cached. *unmanaged* lists the entries of that directory that Confluence cannot restore.
    """

    def __init__(self, status: PageStatus, directory: str | None, unmanaged: list[str]) -> None:
        self.status = status
        self.directory = directory
        self.unmanaged = unmanaged


class RepositoryPullOperation:
    """Apply page pull operations to a complete tree-status comparison."""

    ABSENT = {PageStatusState.ABSENT_REMOTE, PageStatusState.CONFLICT_ABSENT_REMOTE}

    def __init__(self, page_pull: PagePullOperation | None = None) -> None:
        self._page_pull = page_pull or PagePullOperation()

    def pull(
            self,
            workarea: Workarea,
            api,
            status: TreeStatus,
            force: bool = False,
            delete: bool = False,
            confirm: Callable[[list[PageDeletion]], bool] | None = None) -> PageOperationResults:
        """Pull remotely changed and missing pages parents first; with *delete*, delete pages absent from the tree.

        Every check runs before any change. Without *force*, a conflict aborts the command; with *delete*, so does a
        page removed remotely and changed locally. With *delete* and without *force*, *confirm* receives the planned
        deletions, and declining aborts the command. A page below a page that failed is blocked. Without *delete*,
        cached pages absent from the tree are kept and reported.
        """
        conflicts = {PageStatusState.CONFLICT}
        if delete:
            conflicts.add(PageStatusState.CONFLICT_ABSENT_REMOTE)

        if not force and any(page.status in conflicts for page in status.pages):
            raise SyncError("repository pull conflicts; resolve conflicts or use --force")

        deletions = []
        if delete:
            deletions = self._deletions(workarea, status)
            if deletions and not force and (confirm is None or not confirm(deletions)):
                raise SyncError("repository pull cancelled; nothing was changed")

        results = PageOperationResults()
        unsuccessful: set[str] = set()
        pulled = {PageStatusState.ABSENT_LOCAL, PageStatusState.REMOTE_CHANGED}
        if force:
            pulled |= {PageStatusState.CONFLICT, PageStatusState.UNCHANGED}

        for page_status in status.pages:
            if page_status.status in self.ABSENT:
                continue

            if page_status.parent_id in unsuccessful:
                unsuccessful.add(page_status.id)
                results.add(page_status.id, page_status.title, "blocked", f"parent page '{page_status.parent_id}' was not pulled")
                continue

            if page_status.status not in pulled:
                if page_status.status is PageStatusState.UNCHANGED:
                    results.add(page_status.id, page_status.title, "unchanged")
                else:
                    results.add(page_status.id, page_status.title, "skipped", page_status.status)
                continue

            # A cached page whose directory is missing has no local content to protect, so it is restored.
            restore = page_status.status is PageStatusState.ABSENT_LOCAL and page_status.local is not None
            try:
                changed = self._page_pull.pull(workarea, api, api.get_page(page_status.id), force=force or restore)
            except (OSError, UnicodeError) as error:
                unsuccessful.add(page_status.id)
                results.add(page_status.id, page_status.title, "failed", filesystem_error_message(error))
            except SyncError as error:
                unsuccessful.add(page_status.id)
                results.add(page_status.id, page_status.title, "failed", str(error))
            else:
                results.add(page_status.id, page_status.title, "pulled" if changed else "unchanged")

        # Absent pages are handled last, after every relocation out of their directories has been applied.
        if delete:
            self._delete(workarea, deletions, results)
        else:
            for page_status in status.pages:
                if page_status.status in self.ABSENT:
                    results.add(
                        page_status.id, page_status.title, "kept",
                        "no longer in the tree (deleted or moved outside the root); the local copy is unchanged")

        return results

    def _deletions(self, workarea, status):
        # The deletions follow the statuses' parents-first order.
        tree = workarea.page_tree()
        deletions = []
        for page_status in status.pages:
            if page_status.status in self.ABSENT:
                assert page_status.local is not None
                deletions.append(
                    PageDeletion(page_status, tree.directory(page_status.id), workarea.unmanaged_entries(page_status.local)))

        return deletions

    @staticmethod
    def _delete(workarea, deletions, results):
        # The cache is reloaded, since the pull phase may have relocated pages out of absent directories. Children are
        # deleted before parents, so that every remaining cached page keeps its cached parent after an interruption.
        tree = workarea.page_tree()
        children: dict[str | None, list[str]] = {}
        for page_id, state in tree.states.items():
            children.setdefault(state.page.parent_id, []).append(page_id)

        deleted: set[str] = set()
        for deletion in reversed(deletions):
            page_status = deletion.status
            # A directory is deleted only if every cached page below it is deleted too.
            remaining = [page_id for page_id in _descendants(children, page_status.id) if page_id not in deleted]
            if remaining:
                results.add(
                    page_status.id, page_status.title, "blocked", f"its directory contains page '{remaining[0]}', which is kept")
                continue

            try:
                _delete_local_copy(workarea, tree.states[page_status.id])
            except (OSError, UnicodeError) as error:
                results.add(page_status.id, page_status.title, "failed", filesystem_error_message(error))
            except SyncError as error:
                results.add(page_status.id, page_status.title, "failed", str(error))
            else:
                deleted.add(page_status.id)
                results.add(
                    page_status.id, page_status.title, "deleted", "no longer in the tree (deleted or moved outside the root)")


class PageRemoveOperation:
    """Remove a cached page and all its descendants, remotely and locally."""

    ALLOWED = {PageStatusState.UNCHANGED, PageStatusState.ABSENT_LOCAL, PageStatusState.ABSENT_REMOTE}

    def __init__(self, pandoc: PandocRunner | None = None) -> None:
        self._detector = PageChangeDetector(pandoc or PandocRunner())

    def remove(
            self,
            workarea: Workarea,
            api,
            page_id: str,
            force: bool = False,
            confirm: Callable[[list[PageDeletion]], bool] | None = None) -> list[PageDeletion] | None:
        """Remove cached page *page_id* and its subtree, returning the removed pages, or ``None`` if not confirmed.

        Every check runs before any change: the page's directory must exist, every page of the subtree must be in sync
        (a page removed remotely with local changes only with *force*), and no page may have moved into or out of the
        subtree remotely. Without *force*, *confirm* receives the planned deletions, children first. Pages are then
        deleted children first: remotely (a 404 counts as deleted), then their directory, then their cache entry. A
        failure stops the removal; the error names the pages removed before it.
        """
        tree = workarea.page_tree()
        state = tree.states.get(page_id)
        if state is None:
            raise SyncError(f"page '{page_id}' is not managed in this workarea")

        directory = workarea.page_directory(state)
        status = self._subtree_status(workarea, api, tree, page_id)
        self._check(status, page_id, force)
        workarea.check_removable(directory)
        deletions = []
        for page_status in reversed(status.pages):
            local = page_status.local
            if local is None:
                deletions.append(PageDeletion(page_status, None, []))
            else:
                deletions.append(PageDeletion(page_status, tree.directory(local.page.id), workarea.unmanaged_entries(local)))

        if not force and (confirm is None or not confirm(deletions)):
            return None

        removed: list[PageDeletion] = []
        for deletion in deletions:
            try:
                self._delete(workarea, api, deletion.status)
            except (OSError, UnicodeError, SyncError) as error:
                message = filesystem_error_message(error) if isinstance(error, OSError) else str(error)
                pages = ", ".join(f"'{item.status.title}' ({item.status.id})" for item in removed) or "none"
                raise SyncError(
                    f"cannot remove page '{deletion.status.id}': {message}; pages removed before the failure: {pages}") from error

            removed.append(deletion)

        return removed

    def _subtree_status(self, workarea, api, tree, page_id):
        # The cached subtree follows cached parents; the remote subtree follows remote parents. A stale cache can make
        # them differ.
        children: dict[str | None, list[str]] = {}
        for other_id, other in tree.states.items():
            children.setdefault(other.page.parent_id, []).append(other_id)

        cached_ids = [page_id, *_descendants(children, page_id)]
        try:
            page = api.get_page(page_id)
        except APIError as error:
            if error.status != 404:
                raise
            remote_pages = []
        else:
            # The page's parent is outside the subtree.
            remote_pages = [RemoteContentRef(page.id, "page", page.title, None), *api.page_descendants(page_id)]

        for remote in remote_pages:
            if remote.id in tree.states and remote.id not in cached_ids:
                raise SyncError(
                    f"page '{remote.id}' was moved remotely into the subtree of page '{page_id}'; run 'cflsync pull' first")

        states = [tree.states[cached_id] for cached_id in cached_ids]
        status = TreeStatus.from_pages(workarea, api, remote_pages, states, self._detector)
        for page_status in status.pages:
            # A cached page missing from the remote subtree was either deleted, or moved elsewhere in the tree.
            if page_status.remote is None and page_status.id != page_id and _remote_page_exists(api, page_status.id):
                raise SyncError(
                    f"page '{page_status.id}' was moved remotely out of the subtree of page '{page_id}'; "
                    "run 'cflsync pull' first")

        return status

    def _check(self, status, page_id, force):
        for page_status in status.pages:
            if page_status.status is PageStatusState.CONFLICT_ABSENT_REMOTE:
                if not force:
                    raise SyncError(
                        f"page '{page_status.id}' was removed remotely but has local changes; remove conflicts; "
                        "use --force to remove its local copy")
            elif page_status.status not in self.ALLOWED:
                raise SyncError(f"page '{page_status.id}' has local or remote changes; remove conflicts")

    @staticmethod
    def _delete(workarea, api, page_status):
        if page_status.remote is not None:
            try:
                api.delete_page(page_status.id)
            except APIError as error:
                if error.status != 404:
                    raise

        if page_status.local is not None:
            _delete_local_copy(workarea, page_status.local)


def _remote_page_exists(api, page_id):
    try:
        api.get_page(page_id)
    except APIError as error:
        if error.status == 404:
            return False

        raise

    return True


def _delete_local_copy(workarea, state):
    # The directory goes first: after an interruption, the remaining cache entry still describes the page, and
    # deleting it again completes the deletion.
    workarea.remove_page(state, must_exist=False)
    workarea.cache_path(state.page.id).unlink()


def _descendants(children, page_id):
    # Every cached page below *page_id*, from a mapping of cached parent IDs to cached child IDs.
    result = []
    pending = list(children.get(page_id, []))
    while pending:
        child_id = pending.pop()
        result.append(child_id)
        pending.extend(children.get(child_id, []))

    return result


def _require_local_parent(workarea, parent_id, api):
    # A page directory can only be placed inside its parent's page directory.
    cache_path = workarea.cache_path(parent_id)
    if not cache_path.exists():
        parent = api.get_page(parent_id)
        raise SyncError(f"parent page '{parent.title}' ({parent_id}) is not present locally; run: cflsync page pull {parent_id}")

    parent_state = PageState.load(cache_path)
    if not workarea.page_directory(parent_state, must_exist=False).is_dir():
        raise SyncError(
            f"the directory of parent page '{parent_state.page.title}' ({parent_id}) is missing; "
            f"run: cflsync page pull --force {parent_id}")


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
        while planning, or if a planned directory clashes with an unmanaged entry.
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
                name = workarea.page_directory_name(page.title, chain_id)
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


class PageIndex:
    """The pages of a workarea's tree, as page links need them: membership, titles, parents, and the space key.

    The index maps a page ID to a :class:`RemoteContentRef` for a page in the tree, with ``parent_id`` ``None`` for
    the root page, or to ``None`` for a page that is not in it: deleted, moved outside the root, or not visible with
    the profile's credentials. It is *complete* once it holds the full subtree listing, and *partial* before.

    With *prefill*, the constructor lists the full subtree, as repository commands do. Without it, pages are looked
    up one by one when first needed, as page commands do; :attr:`pages` then lists the full subtree on first use, so
    page commands must not use it.
    """

    def __init__(self, workarea: Workarea, api, prefill: bool) -> None:
        self._api = api
        try:
            root = api.get_page(workarea.root_page_id)
        except APIError as error:
            if error.status == 404:
                raise workarea.missing_root_error() from error

            raise

        self.root = root
        # The root page's parent is outside the workarea's tree.
        self._root = RemoteContentRef(root.id, "page", root.title, None)
        self._pages: dict[str, RemoteContentRef | None] = {root.id: self._root}
        self._listing: list[RemoteContentRef] | None = None
        self._space_key: str | None = None
        if prefill:
            self._discover()

    @property
    def complete(self) -> bool:
        """Report whether the index holds the full subtree listing."""
        return self._listing is not None

    @property
    def pages(self) -> list[RemoteContentRef]:
        """Return the root page followed by every page below it, in listing order.

        A partial index lists the full subtree first.
        """
        self._discover()
        assert self._listing is not None
        return [self._root, *self._listing]

    @property
    def space_key(self) -> str:
        """Return the key of the tree's space, which every page in the tree shares."""
        if self._space_key is None:
            if self.root.space_id is None:
                raise SyncError(f"root page '{self.root.id}' reports no space")

            self._space_key = self._api.get_space_key(self.root.space_id)

        return self._space_key

    def lookup(self, page_id: str) -> RemoteContentRef | None:
        """Return the reference of page *page_id* if it is in the tree, else ``None``.

        A complete index answers without requests. A partial index fetches an unknown page and its ancestors once;
        it records the ancestors too, and fetches an ancestor's title only when that ancestor is looked up.
        """
        if page_id not in self._pages:
            if self.complete:
                return None

            self._fetch(page_id)

        page = self._pages[page_id]
        if page is not None and page.title is None:
            page = self._fetch_title(page)

        return page

    def find_by_title(self, space_key: str, title: str) -> str | None:
        """Return the ID of the page in the tree with *title* in space *space_key*, else ``None``.

        Space keys and titles match ignoring case, as in Confluence.
        """
        if space_key.casefold() != self.space_key.casefold():
            return None

        if self.complete:
            matches = [
                page_id for page_id, page in self._pages.items()
                if page is not None and page.title is not None and page.title.casefold() == title.casefold()]
        else:
            pages = self._api.find_pages_by_title(title, self.root.space_id, match_case=False)
            matches = [page.id for page in pages if page.title.casefold() == title.casefold()]

        if len(matches) != 1:
            return None

        return matches[0] if self.lookup(matches[0]) is not None else None

    def _discover(self):
        if self._listing is not None:
            return

        listing = self._api.page_descendants(self.root.id)
        pages: dict[str, RemoteContentRef | None] = {self.root.id: self._root}
        for page in listing:
            pages[page.id] = page

        # A page looked up earlier but not listed is no longer in the tree.
        for page_id in self._pages:
            pages.setdefault(page_id, None)

        self._pages = pages
        self._listing = listing

    def _fetch(self, page_id):
        try:
            page = self._api.get_page(page_id)
            ancestors = self._api.page_ancestors(page_id)
        except APIError as error:
            # An unreachable page is treated as deleted.
            if error.status in {403, 404}:
                self._pages[page_id] = None
                return

            raise

        ancestor_ids = [ancestor.id for ancestor in ancestors]
        if self.root.id not in ancestor_ids:
            self._pages[page_id] = None
            return

        below_root = ancestors[ancestor_ids.index(self.root.id) + 1:]
        if any(ancestor.type != "page" for ancestor in below_root):
            self._pages[page_id] = None
            return

        # The chain runs from the root down; ancestor listings carry no titles.
        parent_id = self.root.id
        for ancestor in below_root:
            self._pages.setdefault(ancestor.id, RemoteContentRef(ancestor.id, "page", None, parent_id))
            parent_id = ancestor.id

        self._pages[page_id] = RemoteContentRef(page.id, "page", page.title, parent_id)

    def _fetch_title(self, page):
        try:
            remote = self._api.get_page(page.id)
        except APIError as error:
            if error.status in {403, 404}:
                self._pages[page.id] = None
                return None

            raise

        page = RemoteContentRef(page.id, "page", remote.title, page.parent_id)
        self._pages[page.id] = page
        return page


# vim: set ts=4 sw=4 et tw=132:
