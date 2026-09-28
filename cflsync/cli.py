# Copyright (c) 2026 Sven Rosiers
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Command-line interface for cflsync."""

from __future__ import annotations

import sys
import hashlib
import json
import shutil
from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Sequence
from getpass import getpass
from pathlib import Path

from .api import APIClient, APIError
from .config import Config, Profile
from .convert import ADFToMarkdownConverter, MarkdownToADFConverter, PandocRunner
from .errors import SyncError
from .sync import (
    InstallationPlan, PageChangeDetector, PageChangeStatus, PagePushOperation, PageStatus, PageStatusState, PlannedPage,
    RepositoryPushOperation, TreeStatus)
from .workarea import (
    CONTENT_FILENAME, AttachmentMetadata, MediaResolver, PageMetadata, PageRef, PageState, Workarea, filesystem_error_message)


class InitCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        init_parser = subparsers.add_parser(
            "init", help="initialise a cflsync workarea in the current directory, anchored at a root page")
        init_parser.add_argument("-p", "--profile", default="default", help="use PROFILE instead of 'default'")
        init_parser.add_argument("root_page_ref", help="root page ID or title")
        init_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(args.root_page_ref, args.profile)

    def run(self, root_page_ref: str, profile: str = "default") -> int:
        api = _api_client(profile)
        reference = PageRef.resolve_remote(root_page_ref, api)
        page = api.get_page(reference.page_id)
        Workarea.init(Path.cwd(), page.id, profile)
        print(f"Initialised a workarea anchored at page '{page.id}' ({page.title}), using profile '{profile}'.")
        print(f"Pull the root page with 'cflsync page pull {page.id}'.")
        return 0


class RepositoryPushCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        push_parser = subparsers.add_parser("push", help="push all cached pages in the workarea")
        push_parser.add_argument("-f", "--force", action="store_true", help="prefer local content, overwriting remote changes")
        push_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(force=args.force)

    def run(self, force: bool = False) -> int:
        try:
            workarea, api = _open_workarea()
            status = TreeStatus.for_workarea(workarea, api, PageChangeDetector(PandocRunner()))
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot push workarea: {filesystem_error_message(error)}") from error

        results = RepositoryPushOperation().push(workarea, api, status, force)
        results.report()
        return 1 if results.failed else 0


class RepositoryStatusCommand:

    # How each synchronization state is reported.
    LABELS = {
        PageStatusState.ABSENT_LOCAL: "not in local",
        PageStatusState.ABSENT_REMOTE: "remote removed",
        PageStatusState.REMOTE_CHANGED: "remote changed",
        PageStatusState.LOCAL_CHANGED: "local changed",
        PageStatusState.CONFLICT: "conflict",
        PageStatusState.UNCHANGED: "unchanged"}

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        status_parser = subparsers.add_parser("status", help="show the synchronization status of every page in the workarea")
        status_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run()

    def run(self) -> int:
        try:
            workarea, api = _open_workarea()
            status = TreeStatus.for_workarea(workarea, api, PageChangeDetector(PandocRunner()))
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot report workarea status: {filesystem_error_message(error)}") from error

        for page_status in status.pages:
            print(f"Page '{page_status.id}' ({page_status.title}): {self.LABELS[page_status.status]}")

        counts = {label: 0 for label in self.LABELS.values()}
        for page_status in status.pages:
            counts[self.LABELS[page_status.status]] += 1

        print(f"Summary: {', '.join(f'{count} {label}' for label, count in counts.items() if count)}.")
        return 0


class AuthCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        auth_parser = subparsers.add_parser("auth", help="store Confluence Cloud credentials")
        auth_parser.add_argument("-p", "--profile", default="default", help="store credentials under PROFILE instead of 'default'")
        auth_action = auth_parser.add_mutually_exclusive_group()
        auth_action.add_argument("-l", "--list", action="store_true", help="list available profiles")
        auth_action.add_argument("-d", "--delete", action="store_true", help="delete stored credentials")
        auth_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        config = Config.find()
        if args.list:
            for name in config.profiles:
                print(name)
            return 0

        if args.delete:
            if args.profile not in config.profiles:
                return 0
            if input(f"Delete profile '{args.profile}'? [y/N] ").lower() in ["y", "yes"]:
                del config.profiles[args.profile]
                config.save()
            return 0

        hostname = input("Confluence Cloud hostname: ")
        username = input("Confluence Cloud username: ")
        apitoken = getpass("Confluence Cloud API token: ")
        config.profiles[args.profile] = Profile(hostname, username, apitoken)
        config.save()
        return 0


class PageCreateCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        page_create_parser = subparsers.add_parser("create", help="create an empty Confluence Cloud child page")
        page_create_parser.add_argument("parent_page_ref", help="parent page ID, title, content.md file, or page directory")
        page_create_parser.add_argument("title", help="title for the new page")
        page_create_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(args.parent_page_ref, args.title)

    def run(self, parent_page_ref: str, title: str) -> int:
        _validate_page_title(title)

        try:
            workarea, api = _open_workarea()
            reference = PageRef.resolve(parent_page_ref, workarea, api)
            parent = api.get_page(reference.page_id)
            if parent.space_id is None:
                raise SyncError(f"parent page '{reference.page_id}' reports no space")

            # The new page is pulled below its parent, so both must be possible before it is created remotely.
            PagePullCommand()._install_ancestors(workarea, api, parent.id, PandocRunner(), include_page=True)
            workarea.page_directory_target(None, parent.id, workarea.page_directory_name(title))
            page = api.create_page(parent.space_id, parent.id, title)
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot create page: {filesystem_error_message(error)}") from error

        try:
            return PagePullCommand().run(page.id)
        except SyncError as error:
            raise SyncError(f"created page '{page.id}' remotely but could not pull it: {error}") from error


class PagePullCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        page_pull_parser = subparsers.add_parser("pull", help="pull a page from Confluence Cloud")
        page_pull_parser.add_argument(
            "-f", "--force", action="store_true", help="prefer remote content, overwriting local changes to managed files")
        page_pull_parser.add_argument("page_ref", help="page ID, title, content.md file, or page directory")
        page_pull_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(args.page_ref, force=args.force)

    def run(self, page_ref: str, force: bool = False) -> int:
        try:
            workarea, api = _open_workarea()
            reference = PageRef.resolve(page_ref, workarea, api)
            page = api.get_page(reference.page_id)
            pandoc = PandocRunner()
            self._install_ancestors(workarea, api, page.id, pandoc)
            self._pull(workarea, page, pandoc, api, force)
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot pull page: {filesystem_error_message(error)}") from error

        return 0

    def _install_ancestors(self, workarea, api, page_id, pandoc, include_page=False) -> None:
        """Plan and install missing ancestors of *page_id*, optionally including that page."""
        plan = InstallationPlan.for_ancestors(workarea, api, page_id, include_page=include_page)
        plan.install(lambda planned: self._pull_planned(workarea, planned, pandoc, api))

    def _pull_planned(self, workarea, planned: PlannedPage, pandoc, api) -> None:
        """Install one missing ancestor at its planned cached or remote location."""
        self._pull(
            workarea,
            planned.page,
            pandoc,
            api,
            force=planned.restore,
            parent_id=planned.parent_id,
            directory_name=planned.directory_name,
            directory=planned.directory)

    def _pull(self, workarea, page, pandoc, api, force=False, parent_id=None, directory_name=None, directory=None):
        inspector = PageChangeDetector(pandoc)
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
            directory_name = workarea.page_directory_name(page.title)
            directory = workarea.relative_directory(parent_id, directory_name)

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
                if inspector.local_status(source, previous) != PageChangeStatus.UNCHANGED:
                    raise SyncError(f"page '{page.id}' has local changes; pull conflicts")

                # A page moved or renamed remotely is relocated even when its content is unchanged.
                if inspector.remote_status(
                        page, attachments,
                        previous) == PageChangeStatus.UNCHANGED and source == workarea.page_directory_path(directory):
                    print(f"Page '{page.id}' is already in sync; nothing pulled. Use --force to regenerate local content.")
                    return

        # Cached siblings count even when their directories are missing.
        workarea.page_directory_target(page.id, parent_id, directory_name)

        try:
            document = json.loads(page.body)
        except (TypeError, json.JSONDecodeError) as error:
            raise SyncError(f"page '{page.id}' has invalid ADF JSON") from error

        if not isinstance(document, dict):
            raise SyncError(f"page '{page.id}' ADF must be an object")

        markdown = ADFToMarkdownConverter(pandoc, media, api.get_user).convert(document, title=page.title)
        bodies = {}
        metadata = {}
        for attachment in attachments:
            body = attachment.download()
            bodies[attachment.filename] = body
            metadata[attachment.filename] = AttachmentMetadata(attachment.id, attachment.version, hashlib.sha256(body).hexdigest())

        state = PageState(
            PageMetadata(page.id, page.title, parent_id, directory_name, page.version, inspector.content_hash(markdown)), metadata)
        managed = ()
        if previous is not None:
            managed = previous.attachments

        staging = workarea.stage_page(directory, markdown, bodies, source=source, managed_attachments=managed)
        try:
            with workarea.replace_page(staging, directory, source, set(managed) | set(bodies)):
                state.save(cache_path)
        finally:
            if staging.exists():
                shutil.rmtree(staging)


class PagePushCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        page_push_parser = subparsers.add_parser("push", help="push a page to Confluence Cloud")
        page_push_parser.add_argument("-f", "--force", action="store_true", help="prefer local content, overwriting remote changes")
        page_push_parser.add_argument("page_ref", help="page ID, title, content.md file, or page directory")
        page_push_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(args.page_ref, force=args.force)

    def run(self, page_ref: str, force: bool = False) -> int:
        try:
            workarea, api = _open_workarea()
            reference = PageRef.resolve(page_ref, workarea, api)
            cache_path = workarea.cache_path(reference.page_id)
            if not cache_path.exists():
                raise SyncError(f"page '{reference.page_id}' is not managed in this workarea")

            state = PageState.load(cache_path)
            status = PageStatus(PageStatusState.LOCAL_CHANGED, None, state)
            pushed = PagePushOperation().push(workarea, api, status, force)
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot push page: {filesystem_error_message(error)}") from error

        if not pushed:
            print(f"Page '{reference.page_id}' is already in sync; nothing pushed. Use --force to upload local content.")

        return 0


class PageRenameCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        page_rename_parser = subparsers.add_parser("rename", help="rename a synchronized Confluence Cloud page")
        page_rename_parser.add_argument("page_ref", help="page ID, title, content.md file, or page directory")
        page_rename_parser.add_argument("title", help="new page title")
        page_rename_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(args.page_ref, args.title)

    def run(self, page_ref: str, title: str) -> int:
        _validate_page_title(title)
        try:
            workarea, api = _open_workarea()
            reference = PageRef.resolve(page_ref, workarea, api)
            cache_path = workarea.cache_path(reference.page_id)
            if not cache_path.exists():
                raise SyncError(f"page '{reference.page_id}' is not managed in this workarea")

            state = PageState.load(cache_path)
            page = api.get_page(reference.page_id)
            self._rename(workarea, page, state, cache_path, PandocRunner(), title)
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot rename page: {filesystem_error_message(error)}") from error

        return 0

    def _rename(self, workarea, page, state, cache_path, pandoc, title):
        inspector = PageChangeDetector(pandoc)
        directory = workarea.page_directory(state)
        attachments = page.attachments()
        if inspector.local_status(directory, state) != PageChangeStatus.UNCHANGED or inspector.remote_status(
                page, attachments, state) != PageChangeStatus.UNCHANGED:
            raise SyncError(f"page '{page.id}' has local or remote changes; rename conflicts")

        if title == page.title:
            print(f"Page '{page.id}' is already named '{title}'; nothing renamed.")
            return

        if page.body is None:
            raise SyncError(f"page '{page.id}' has no ADF body")

        directory_name = workarea.page_directory_name(title)
        target = workarea.relative_directory(state.page.parent_id, directory_name)
        markdown = (directory / CONTENT_FILENAME).read_text(encoding="utf-8")
        renamed_markdown = MarkdownToADFConverter(pandoc).retitle(markdown, state.page.title, title)
        content_hash = inspector.content_hash(renamed_markdown)
        workarea.page_directory_target(page.id, state.page.parent_id, directory_name)
        staging = workarea.stage_page(target, renamed_markdown, {}, source=directory)
        try:
            updated = page.update(page.body, title)
            if updated.title != title:
                raise SyncError(f"page '{page.id}' was renamed remotely to unexpected title '{updated.title}'")

            renamed_state = PageState(
                PageMetadata(updated.id, updated.title, state.page.parent_id, directory_name, updated.version, content_hash),
                state.attachments)
            try:
                with workarea.replace_page(staging, target, directory):
                    renamed_state.save(cache_path)
            except (OSError, SyncError) as error:
                raise SyncError(
                    f"renamed page '{page.id}' remotely but could not update local state: {filesystem_error_message(error)}; "
                    f"run: cflsync page pull {page.id}") from error
        finally:
            if staging.exists():
                shutil.rmtree(staging)


class PageMoveCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        page_move_parser = subparsers.add_parser("move", help="move a synchronized Confluence Cloud page")
        page_move_parser.add_argument("page_ref", help="page ID, title, content.md file, or page directory")
        page_move_parser.add_argument("new_parent_ref", help="page ID, title, content.md file, or page directory")
        page_move_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(args.page_ref, args.new_parent_ref)

    def run(self, page_ref: str, new_parent_ref: str) -> int:
        try:
            workarea, api = _open_workarea()
            reference = PageRef.resolve(page_ref, workarea, api)
            cache_path = workarea.cache_path(reference.page_id)
            if not cache_path.exists():
                raise SyncError(f"page '{reference.page_id}' is not managed in this workarea")

            state = PageState.load(cache_path)
            page = api.get_page(reference.page_id)
            parent_reference = PageRef.resolve(new_parent_ref, workarea, api)
            parent = api.get_page(parent_reference.page_id)
            self._move(workarea, page, parent, state, cache_path, PandocRunner(), api)
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot move page: {filesystem_error_message(error)}") from error

        return 0

    def _move(self, workarea, page, parent, state, cache_path, pandoc, api):
        if page.id == workarea.root_page_id:
            raise SyncError(f"page '{page.id}' is the root page of this workarea and cannot be moved")

        inspector = PageChangeDetector(pandoc)
        directory = workarea.page_directory(state)
        attachments = page.attachments()
        if inspector.local_status(directory, state) != PageChangeStatus.UNCHANGED or inspector.remote_status(
                page, attachments, state) != PageChangeStatus.UNCHANGED:
            raise SyncError(f"page '{page.id}' has local or remote changes; move conflicts")

        if page.id == parent.id:
            raise SyncError("a page cannot be its own parent")
        if page.space_id is None:
            raise SyncError(f"page '{page.id}' reports no space")
        if parent.space_id is None:
            raise SyncError(f"new parent page '{parent.id}' reports no space")
        if page.space_id != parent.space_id:
            raise SyncError(f"new parent page '{parent.id}' is in a different space")
        if page.parent_id == parent.id:
            print(f"Page '{page.id}' is already a child of '{parent.id}'; nothing moved.")
            return

        if page.body is None:
            raise SyncError(f"page '{page.id}' has no ADF body")

        # The page directory moves into its new parent's directory, so both must be possible before the remote update.
        PagePullCommand()._install_ancestors(workarea, api, parent.id, pandoc, include_page=True)
        workarea.page_directory_target(page.id, parent.id, state.page.directory)
        try:
            updated = page.update(page.body, parent_id=parent.id)
        except SyncError as error:
            raise SyncError(f"cannot move page '{page.id}' to parent '{parent.id}': {error}") from error
        if updated.parent_id != parent.id:
            raise SyncError(f"page '{page.id}' was moved remotely to unexpected parent '{updated.parent_id}'")
        if updated.title != state.page.title:
            raise SyncError(f"page '{page.id}' was moved remotely with unexpected title '{updated.title}'")

        moved_state = PageState(
            PageMetadata(updated.id, state.page.title, parent.id, state.page.directory, updated.version, state.page.content_hash),
            state.attachments)
        try:
            with workarea.relocation(directory, workarea.relative_directory(parent.id, state.page.directory)):
                moved_state.save(cache_path)
        except (OSError, SyncError) as error:
            raise SyncError(
                f"moved page '{page.id}' remotely but could not update local state: {filesystem_error_message(error)}; "
                f"run: cflsync page pull {page.id}") from error


class PageRemoveCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        page_remove_parser = subparsers.add_parser("remove", help="remove a managed Confluence Cloud page")
        page_remove_parser.add_argument("-f", "--force", action="store_true", help="remove without confirmation")
        page_remove_parser.add_argument("page_ref", help="managed page ID, title, content.md file, or page directory")
        page_remove_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(args.page_ref, force=args.force)

    def run(self, page_ref: str, force: bool = False) -> int:
        try:
            workarea, api = _open_workarea()
            reference = PageRef.resolve_local(page_ref, workarea)
            cache_path = workarea.cache_path(reference.page_id)
            if not cache_path.exists():
                raise SyncError(f"page '{reference.page_id}' is not managed in this workarea")

            state = PageState.load(cache_path)
            workarea.page_directory(state)
            try:
                page = api.get_page(reference.page_id)
            except APIError as error:
                if error.status != 404:
                    raise
                page = None

            self._require_no_children(workarea, state, page, api)
            if page is not None:
                detector = PageChangeDetector(PandocRunner())
                directory = workarea.page_directory(state)
                attachments = page.attachments()
                if detector.local_status(directory, state) != PageChangeStatus.UNCHANGED or detector.remote_status(
                        page, attachments, state) != PageChangeStatus.UNCHANGED:
                    raise SyncError(f"page '{page.id}' has local or remote changes; remove conflicts")

            if not force and not self._confirm(state, remote_exists=page is not None):
                return 0

            if page is not None:
                page.delete()

            try:
                workarea.remove_page(state)
                cache_path.unlink()
            except (OSError, SyncError) as error:
                scope = "removed remotely but could not remove local state" if page is not None else "could not remove local state"
                raise SyncError(f"page '{state.page.id}' {scope}: {filesystem_error_message(error)}") from error
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot remove page: {filesystem_error_message(error)}") from error

        return 0

    def _require_no_children(self, workarea, state, page, api):
        # Removing a page with children is not supported yet; its directory contains theirs.
        children = {page_id for page_id, other in workarea.page_tree().states.items() if other.page.parent_id == state.page.id}
        if page is not None:
            children.update(child.id for child in api.page_children(page.id))

        if len(children) == 1:
            raise SyncError(f"page '{state.page.id}' has 1 child page; remove it first")
        if children:
            raise SyncError(f"page '{state.page.id}' has {len(children)} child pages; remove them first")

    def _confirm(self, state: PageState, remote_exists: bool) -> bool:
        scope = "remote and local copy of" if remote_exists else "local copy of"
        response = input(f"Remove {scope} page '{state.page.title}' ({state.page.id})? [y/N] ")
        return response.lower() in {"y", "yes"}


class PageStatusCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        page_status_parser = subparsers.add_parser("status", help="show a page's synchronization status")
        page_status_parser.add_argument("page_ref", help="page ID, title, content.md file, or page directory")
        page_status_parser.set_defaults(command=self)

    def __call__(self, args: Namespace) -> int:
        return self.run(args.page_ref)

    def run(self, page_ref: str) -> int:
        try:
            workarea, api = _open_workarea()
            # Status only reports cached pages, which are in the workarea's tree.
            reference = PageRef.resolve_local(page_ref, workarea)
            state = PageState.load(workarea.cache_path(reference.page_id))
            inspector = PageChangeDetector(PandocRunner())
            # A missing page directory is a local change, not a lookup failure.
            directory = workarea.page_directory(state, must_exist=False)
            page = self._remote_page(api, state.page.id)
            location = None
            if page is None:
                page_locally, attachments_locally = inspector.local_changes(directory, state)
                remote = "not found; the page was deleted, or is not accessible"
            elif not workarea.contains(page.id, api):
                page_locally, attachments_locally = inspector.local_changes(directory, state)
                remote = "moved outside this workarea's tree"
            else:
                page_locally, attachments_locally = inspector.local_changes(directory, state)
                page_remotely, attachments_remotely = inspector.remote_changes(page, page.attachments(), state)
                remote = self._summary(page_remotely, "page", attachments_remotely)
                location = self._location(workarea, state, page)
        except (OSError, UnicodeError) as error:
            raise SyncError(f"cannot report page status: {filesystem_error_message(error)}") from error

        print(f"Page '{state.page.id}' ({state.page.title})")
        print(f"  local:  {self._summary(page_locally, CONTENT_FILENAME, attachments_locally)}")
        print(f"  remote: {remote}")
        if location is not None:
            print(f"  location: {location}")

        return 0

    def _remote_page(self, api, page_id):
        try:
            return api.get_page(page_id)
        except APIError as error:
            if error.status == 404:
                return None

            raise

    def _location(self, workarea, state, page):
        # Describe the relocation that the next pull applies after a remote rename or move.
        parent_id = None if page.id == workarea.root_page_id else page.parent_id
        name = workarea.page_directory_name(page.title)
        if parent_id == state.page.parent_id and name == state.page.directory:
            return None

        current = workarea.relative_directory(state.page.parent_id, state.page.directory)
        if parent_id is not None and not workarea.cache_path(parent_id).exists():
            return f"moves from '{current}' below page '{parent_id}' on pull, which pulls that page first"

        return f"moves from '{current}' to '{workarea.relative_directory(parent_id, name)}' on pull"

    def _summary(self, page_changed, page_label, attachment_names):
        changed = [page_label] if page_changed else []
        changed.extend(f"_attachments/{name}" for name in attachment_names)
        if not changed:
            return "unchanged"

        return "changed: " + ", ".join(changed)


class PageCommand:

    def configure(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        self.page_parser = subparsers.add_parser("page", help="page commands")
        self.page_parser.set_defaults(command=self)
        page_subparsers = self.page_parser.add_subparsers(title="page commands", metavar="command")
        PageCreateCommand().configure(page_subparsers)
        PagePullCommand().configure(page_subparsers)
        PagePushCommand().configure(page_subparsers)
        PageRenameCommand().configure(page_subparsers)
        PageMoveCommand().configure(page_subparsers)
        PageRemoveCommand().configure(page_subparsers)
        PageStatusCommand().configure(page_subparsers)

    def __call__(self, args: Namespace) -> int:
        self.page_parser.print_usage()
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run one cflsync command, defaulting to this process's arguments."""
    if argv is None:
        argv = sys.argv

    parser = ArgumentParser(prog="cflsync")
    parser.set_defaults(command=lambda args: _print_usage(parser))
    subparsers = parser.add_subparsers(title="commands", metavar="command")
    AuthCommand().configure(subparsers)
    InitCommand().configure(subparsers)
    RepositoryPushCommand().configure(subparsers)
    RepositoryStatusCommand().configure(subparsers)
    PageCommand().configure(subparsers)
    args = parser.parse_args(argv[1:])
    try:
        return args.command(args)
    except SyncError as error:
        print(f"{parser.prog}: {error}", file=sys.stderr)
        return 1


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


def _open_workarea():
    workarea = Workarea.find(Path.cwd())
    return workarea, _api_client(workarea.profile)


def _api_client(profile_name):
    profile = Config.find().profiles.get(profile_name)
    if profile is None:
        raise SyncError(f"credential profile '{profile_name}' does not exist")

    return APIClient(profile.hostname, profile.username, profile.apitoken)


def _print_usage(parser: ArgumentParser) -> int:
    parser.print_usage()
    return 0


def _validate_page_title(title: str) -> None:
    if not title.strip() or title.strip() != title or "\n" in title or "\r" in title or "\t" in title:
        raise SyncError("page title must be non-empty single-line text without surrounding whitespace")


# vim: set ts=4 sw=4 et tw=132:
