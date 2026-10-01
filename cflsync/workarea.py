# Copyright (c) 2026 Sverologos BV
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Delay annotation evaluation so nested type references work on Python 3.11+.
from __future__ import annotations

import errno
import json
import os
import posixpath
import re
import shutil
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Self
import unicodedata
from urllib.parse import quote, unquote, urlsplit

from .api import APIError, RemoteContentRef
from .errors import SyncError

# The Markdown file in each page directory. The name is not page-specific, to allow other content types later.
CONTENT_FILENAME = "content.md"
# The maximum length of a page directory name in characters, including a disambiguation suffix.
DIRECTORY_NAME_LIMIT = 64
# The version of the workarea layout, stored in .cflsync/version.
WORKAREA_VERSION = 3
# The format of the per-page cache entries.
STATE_FORMAT = 3
# How to move the content of a workarea that this version of cflsync does not support.
_TRANSITION_INSTRUCTIONS = (
    "push its local changes with the cflsync version that created it, then create a new workarea in an empty "
    "directory with 'cflsync init ROOT_PAGE_REF', pull, and copy any unmanaged files across")


class MediaResolutionError(SyncError):
    """Raised when a managed attachment cannot be resolved safely."""


class MediaResolver:
    """Map a page attachment manifest between IDs and local paths."""

    def __init__(self, manifest: Iterable[tuple[str, str]]) -> None:
        paths_by_id = {}
        ids_by_filename = {}
        for filename, attachment_id in manifest:
            self._validate_filename(filename)
            self._validate_attachment_id(attachment_id)
            if filename in ids_by_filename:
                raise MediaResolutionError(f"attachment filename '{filename}' is ambiguous")

            if attachment_id in paths_by_id:
                raise MediaResolutionError(f"attachment ID '{attachment_id}' is ambiguous")

            paths_by_id[attachment_id] = f"_attachments/{filename}"
            ids_by_filename[filename] = attachment_id

        self._paths_by_id = paths_by_id
        self._ids_by_filename = ids_by_filename

    def path_for(self, attachment_id: str) -> str:
        """Return the managed Markdown path for one attachment ID."""
        self._validate_attachment_id(attachment_id)
        try:
            return self._paths_by_id[attachment_id]
        except KeyError as error:
            raise MediaResolutionError(f"attachment ID '{attachment_id}' is not managed") from error

    def id_for(self, path: str) -> str:
        """Return the attachment ID for one managed Markdown path."""
        filename = self._filename_from_path(path)
        try:
            return self._ids_by_filename[filename]
        except KeyError as error:
            raise MediaResolutionError(f"attachment path '{path}' is not managed") from error

    def _validate_filename(self, filename):
        if not isinstance(filename, str) or not filename or filename in {".", ".."}:
            raise MediaResolutionError("attachment filename must be a non-empty basename")

        if "/" in filename or "\\" in filename or "\x00" in filename:
            raise MediaResolutionError(f"attachment filename '{filename}' is unsafe")

    def _validate_attachment_id(self, attachment_id):
        if not isinstance(attachment_id, str) or not attachment_id:
            raise MediaResolutionError("attachment ID must be a non-empty string")

    def _filename_from_path(self, path):
        if not isinstance(path, str):
            raise MediaResolutionError("attachment path must be a string")

        parts = path.split("/")
        if len(parts) != 2 or parts[0] != "_attachments":
            raise MediaResolutionError(f"attachment path '{path}' is outside _attachments")

        filename = parts[1]
        self._validate_filename(filename)

        return filename


class LinkResolver:
    """Map page links in one page between Confluence page URLs and local ``content.md`` links.

    *page_id* and *directory* identify the page being converted; *directory* is relative to the workarea root, with
    "/" separators. *index* supplies remote page information through ``lookup(page_id)``, which returns a
    :class:`RemoteContentRef` for a page in the workarea's tree and ``None`` otherwise, ``find_by_title(space_key,
    title)``, and ``space_key``. Only links to pages in the tree are converted; fragments are copied unchanged. Local
    links that look like page links but name no page in the tree are recorded in :attr:`broken`.
    """

    # Page view routes: /wiki/spaces/<space>/pages/<id>, optionally followed by a title slug, which does not identify
    # the page; and /wiki/pages/viewpage.action?pageId=<id>.
    _PAGE_ROUTE = re.compile(r"/wiki/spaces/[^/]+/pages/([0-9]+)(?:/[^/]*)?")
    _VIEW_PAGE_ROUTE = "/wiki/pages/viewpage.action"
    # Title routes: /wiki/display/<space key>/<title>.
    _TITLE_ROUTE = re.compile(r"/wiki/display/([^/]+)/([^/]+)")

    def __init__(self, workarea: "Workarea", hostname: str, page_id: str, directory: str, index) -> None:
        self._workarea = workarea
        self._hostname = hostname
        self._page_id = page_id
        self._directory = directory
        self._index = index
        self._tree: PageTree | None = None
        self.broken: list[tuple[str, str]] = []

    def to_markdown(self, href: str) -> str | None:
        """Return the local link for a Confluence link to a page in the tree, or ``None`` to keep *href*."""
        path, query, fragment = self._split(href)
        if path is None or not self._is_site_path(href, path):
            return None

        target = self._remote_page_id(path, query)
        if target is None or self._index.lookup(target) is None:
            return None

        if target == self._page_id:
            return "content.md" if fragment is None else f"#{fragment}"

        if self._tree is None:
            self._tree = self._workarea.page_tree()

        location = self._workarea.page_location(target, self._index, self._tree)
        # Pages below a page that is being moved, such as its descendants, move with it.
        if self._page_id in self._tree.states:
            previous = self._tree.directory(self._page_id)
            if previous != self._directory and (location == previous or location.startswith(f"{previous}/")):
                location = self._directory + location[len(previous):]

        relative = posixpath.relpath(f"{location}/{CONTENT_FILENAME}", self._directory)
        link = "/".join(quote(segment, safe="") for segment in relative.split("/"))
        return link if fragment is None else f"{link}#{fragment}"

    def to_adf(self, href: str, text: str) -> str | None:
        """Return the Confluence URL for a local link to a page in the tree, or ``None`` to keep *href*.

        A local ``content.md`` link in a directory named after a page that is not in the tree is recorded in
        :attr:`broken` as ``(text, href)``.
        """
        if not isinstance(href, str) or not href or href.startswith(("/", "#")):
            return None

        reference = urlsplit(href.split("#", 1)[0])
        path, query, fragment = self._split(href)
        if reference.scheme or reference.netloc or not path or query is not None:
            return None

        segments = []
        for segment in path.split("/"):
            decoded = unquote(segment)
            if "/" in decoded or "\\" in decoded:
                return None

            segments.append(decoded)

        resolved = posixpath.normpath(posixpath.join(self._directory, *segments))
        if resolved == ".." or resolved.startswith("../") or resolved.startswith("/"):
            return None

        parts = resolved.split("/")
        if len(parts) < 2 or parts[-1] != CONTENT_FILENAME:
            return None

        target = self._workarea.page_id_from_directory_name(parts[-2])
        if target is None:
            return None

        if self._index.lookup(target) is None:
            self.broken.append((text, href))
            return None

        url = f"https://{self._hostname}/wiki/spaces/{quote(self._index.space_key, safe='')}/pages/{target}"
        return url if fragment is None else f"{url}#{fragment}"

    @staticmethod
    def _split(href):
        # Return the path, the query (None without "?"), and the fragment (None without "#") of href, unchanged; the
        # path is None for a URL with a scheme or authority other than an absolute https URL, which _is_site_path
        # checks.
        if not isinstance(href, str):
            return None, None, None

        fragment = None
        if "#" in href:
            href, fragment = href.split("#", 1)

        query = None
        if "?" in href:
            href, query = href.split("?", 1)

        parts = urlsplit(href)
        if parts.scheme or parts.netloc:
            if parts.scheme != "https" or not parts.netloc:
                return None, None, None

            return parts.path, query, fragment

        return href, query, fragment

    def _is_site_path(self, href, path):
        # An absolute URL must name this site on the default port; otherwise the path must be site-root-relative.
        parts = urlsplit(href.split("#", 1)[0])
        if parts.scheme:
            try:
                port = parts.port
            except ValueError:
                return False

            if parts.username is not None or parts.password is not None or port not in {None, 443}:
                return False

            if (parts.hostname or "").lower() != self._hostname.lower():
                return False

        return path.startswith("/wiki/")

    def _remote_page_id(self, path, query):
        # Return the ID of the page that a page view or title route denotes, or None for any other route.
        match = self._PAGE_ROUTE.fullmatch(path)
        if match is not None:
            return match.group(1) if query is None else None

        if path == self._VIEW_PAGE_ROUTE:
            match = re.fullmatch(r"pageId=([0-9]+)", query or "")
            return None if match is None else match.group(1)

        match = self._TITLE_ROUTE.fullmatch(path)
        if match is None or query is not None:
            return None

        # Confluence resolves a title with "+" kept literal first, then with every "+" read as a space.
        space_key = unquote(match.group(1).replace("+", " "))
        title = unquote(match.group(2))
        for candidate in dict.fromkeys([title, title.replace("+", " ")]):
            page_id = self._index.find_by_title(space_key, candidate)
            if page_id is not None:
                return page_id

        return None


class StateError(SyncError):
    """Raised when a page synchronization state file is invalid."""


class PageMetadata:
    """The last synchronized state of one Confluence page.

    *parent_id* is the cached parent page, whose directory contains this page's directory, or ``None`` for the root
    page. *directory* is this page's own directory name, relative to its parent's directory.
    """

    def __init__(self, id: str, title: str, parent_id: str | None, directory: str, version: int, content_hash: str) -> None:
        if not id or not id.isdigit():
            raise StateError("page.id must be a numeric identifier")
        if not title:
            raise StateError("page.title must be a non-empty string")
        if parent_id is not None and (not parent_id or not parent_id.isdigit()):
            raise StateError("page.parent_id must be a numeric identifier or null")
        if not directory:
            raise StateError("page.directory must be a non-empty string")
        if directory in {".", ".."} or "/" in directory or "\\" in directory or "\x00" in directory:
            raise StateError("page.directory must be a single directory name")
        if version < 1:
            raise StateError("page.version must be a positive integer")
        if re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
            raise StateError("page.content_hash must be a SHA-256 hexadecimal digest")

        self.id = id
        self.title = title
        self.parent_id = parent_id
        self.directory = directory
        self.version = version
        self.content_hash = content_hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PageMetadata):
            return NotImplemented

        return (self.id, self.title, self.parent_id, self.directory, self.version,
                self.content_hash) == (other.id, other.title, other.parent_id, other.directory, other.version, other.content_hash)

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "parent_id": self.parent_id,
            "directory": self.directory,
            "version": self.version,
            "content_hash": self.content_hash}

    @classmethod
    def from_json(cls, value: object) -> "PageMetadata":
        """Validate and decode page metadata from a state JSON value."""
        if not isinstance(value, Mapping):
            raise StateError("page must be an object")

        try:
            id = value["id"]
            title = value["title"]
            parent_id = value["parent_id"]
            directory = value["directory"]
            version = value["version"]
            content_hash = value["content_hash"]
        except KeyError as error:
            raise StateError(f"page.{error.args[0]} is required") from error
        if not isinstance(id, str):
            raise StateError("page.id must be a string")
        if not isinstance(title, str):
            raise StateError("page.title must be a string")
        if parent_id is not None and not isinstance(parent_id, str):
            raise StateError("page.parent_id must be a string or null")
        if not isinstance(directory, str):
            raise StateError("page.directory must be a string")
        if type(version) is not int:
            raise StateError("page.version must be an integer")
        if not isinstance(content_hash, str):
            raise StateError("page.content_hash must be a string")

        return cls(id, title, parent_id, directory, version, content_hash)


class AttachmentMetadata:
    """The last synchronized state of one managed attachment."""

    def __init__(self, id: str, version: int, content_hash: str) -> None:
        if not id or re.search(r"[\s/\\\x00]", id):
            raise StateError("attachment.id must be a non-empty opaque identifier")
        if version < 1:
            raise StateError("attachment.version must be a positive integer")
        if re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
            raise StateError("attachment.content_hash must be a SHA-256 hexadecimal digest")

        self.id = id
        self.version = version
        self.content_hash = content_hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AttachmentMetadata):
            return NotImplemented

        return (self.id, self.version, self.content_hash) == (other.id, other.version, other.content_hash)

    def to_json(self) -> dict[str, object]:
        return {"id": self.id, "version": self.version, "content_hash": self.content_hash}

    @classmethod
    def from_json(cls, value: object, name: str) -> "AttachmentMetadata":
        """Validate and decode attachment metadata from a state JSON value."""
        if not isinstance(value, Mapping):
            raise StateError(f"attachment '{name}' must be an object")
        try:
            id = value["id"]
            version = value["version"]
            content_hash = value["content_hash"]
        except KeyError as error:
            raise StateError(f"attachment '{name}'.{error.args[0]} is required") from error
        if not isinstance(id, str):
            raise StateError(f"attachment '{name}'.id must be a string")
        if type(version) is not int:
            raise StateError(f"attachment '{name}'.version must be an integer")
        if not isinstance(content_hash, str):
            raise StateError(f"attachment '{name}'.content_hash must be a string")

        return cls(id, version, content_hash)


class PageState:
    """Format-3 synchronization state for one managed page."""

    def __init__(self, page: PageMetadata, attachments: Mapping[str, AttachmentMetadata], format: int = STATE_FORMAT) -> None:
        if format != STATE_FORMAT:
            raise StateError(f"unsupported state format {format}")

        copied_attachments: dict[str, AttachmentMetadata] = {}
        for name, attachment in attachments.items():
            if not name:
                raise StateError("attachment name must be a non-empty string")
            copied_attachments[name] = attachment

        self.page = page
        self.attachments = copied_attachments
        self.format = format

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PageState):
            return NotImplemented

        return (self.page, self.attachments, self.format) == (other.page, other.attachments, other.format)

    def to_json(self) -> dict[str, object]:
        return {
            "format": self.format,
            "page": self.page.to_json(),
            "attachments": {
                name: attachment.to_json()
                for name, attachment in self.attachments.items()}}

    @classmethod
    def from_json(cls, value: object) -> "PageState":
        """Validate and decode a format-3 state JSON value."""
        if not isinstance(value, Mapping):
            raise StateError("state must be an object")
        try:
            state_format = value["format"]
            page_value = value["page"]
            attachment_values = value["attachments"]
        except KeyError as error:
            raise StateError(f"state.{error.args[0]} is required") from error
        if type(state_format) is not int:
            raise StateError("state.format must be an integer")
        if state_format < STATE_FORMAT:
            raise StateError(
                f"state format {state_format} was written by cflsync 0.4 or earlier, which this version of cflsync "
                f"does not support; {_TRANSITION_INSTRUCTIONS}")
        if not isinstance(attachment_values, Mapping):
            raise StateError("attachments must be an object")

        attachments: dict[str, AttachmentMetadata] = {}
        for name, attachment_value in attachment_values.items():
            if not isinstance(name, str) or not name:
                raise StateError("attachment name must be a non-empty string")
            attachments[name] = AttachmentMetadata.from_json(attachment_value, name)

        return cls(page=PageMetadata.from_json(page_value), attachments=attachments, format=state_format)

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load the validated state file at *path*."""
        if path.suffix != ".json" or not path.stem.isdigit():
            raise StateError(f"state path '{path}' must have a numeric cache filename")

        try:
            with path.open(encoding="utf-8") as state_file:
                value = json.load(state_file)
        except FileNotFoundError as error:
            raise StateError(f"state file does not exist for page '{path.stem}'") from error
        except json.JSONDecodeError as error:
            raise StateError(f"invalid JSON in state file for page '{path.stem}'") from error
        except OSError as error:
            raise StateError(f"cannot read state file for page '{path.stem}': {error}") from error

        state = cls.from_json(value)
        if state.page.id != path.stem:
            raise StateError(f"state file '{path.name}' does not match page.id '{state.page.id}'")

        return cls(state.page, state.attachments, state.format)

    def save(self, path: Path) -> None:
        """Atomically persist this state under its page-ID cache key."""
        if path.suffix != ".json" or path.stem != self.page.id:
            raise StateError(f"state path '{path}' does not match page.id '{self.page.id}'")

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{self.page.id}.", suffix=".tmp",
                                    delete=False) as temporary_file:
                temporary_path = Path(temporary_file.name)
                if not _is_windows():
                    temporary_path.chmod(0o600)
                json.dump(self.to_json(), temporary_file, indent=2)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, path)
        except OSError as error:
            raise StateError(f"cannot write state file for page '{self.page.id}': {error}") from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass


class PageTree:
    """The cached pages of a workarea, with each page's directory derived from its chain of cached parents.

    Every cached page except the root page has a cached parent. A missing parent, a page other than the root without
    a parent, a root with a parent, or a cycle makes the cache invalid.
    """

    def __init__(self, states: Mapping[str, PageState], root_page_id: str) -> None:
        self.states = dict(states)
        self.root_page_id = root_page_id
        self._directories = {page_id: self._derive_directory(page_id) for page_id in self.states}

    def directory(self, page_id: str) -> str:
        """Return a cached page's directory relative to the workarea root, with "/" separators."""
        if page_id not in self._directories:
            raise StateError(f"page '{page_id}' is not cached")

        return self._directories[page_id]

    def _derive_directory(self, page_id):
        names = []
        seen = set()
        current = page_id
        while True:
            if current in seen:
                raise StateError(f"the cached parents of page '{page_id}' form a cycle")

            seen.add(current)
            state = self.states.get(current)
            if state is None:
                raise StateError(f"cached parent page '{current}' of page '{page_id}' is missing")

            names.insert(0, state.page.directory)
            parent_id = state.page.parent_id
            if current == self.root_page_id:
                if parent_id is not None:
                    raise StateError(f"root page '{current}' must not have a cached parent")

                return "/".join(names)

            if parent_id is None:
                raise StateError(f"cached page '{current}' has no parent but is not the root page '{self.root_page_id}'")

            current = parent_id


class Workarea:

    class Error(SyncError):

        def __init__(self, message):
            super().__init__(message)

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()

    @classmethod
    def init(cls, p: Path, root_page_id: str, profile: str = "default"):
        """Initialise a workarea at path p, anchored at a root page and using the named auth profile.

        An existing workarea at p, of any version, is re-anchored if its cache holds no page state: its profile and
        root are replaced, and it becomes a current-version workarea. Any other existing workarea at or above p is
        refused.
        """
        if not p.is_dir():
            raise Workarea.Error(f"'{p}' is not a directory")
        if re.fullmatch(r"[0-9]+", root_page_id) is None:
            raise Workarea.Error("root page ID must be numeric")
        if not profile or "\n" in profile or "\r" in profile:
            raise Workarea.Error("profile must be a non-empty single-line name")

        # Any existing workarea counts, including a version-1 workarea that find() refuses.
        existing = cls._locate(p)
        if existing is not None and existing != p.resolve():
            raise Workarea.Error(f"'{p}' is already part of a cflsync workarea ({existing})")

        if existing is not None:
            workarea = cls(existing)
            workarea._reanchor(root_page_id, profile)
            return workarea

        cflsync_dir = p / ".cflsync"
        if cflsync_dir.exists():
            raise Workarea.Error(f"'{p}' already contains '{cflsync_dir.name}'")

        staging: Path | None = None
        try:
            staging = Path(mkdtemp(prefix=".cflsync-init-", dir=p))
            cache_dir = staging / "cache"
            cache_dir.mkdir(mode=0o700)
            if not _is_windows():
                cache_dir.chmod(0o700)

            for name, value in [("profile", profile), ("version", WORKAREA_VERSION), ("root", root_page_id)]:
                path = staging / name
                with path.open("w", encoding="utf-8") as file:
                    file.write(f"{value}\n")
                    file.flush()
                    os.fsync(file.fileno())
                if not _is_windows():
                    path.chmod(0o600)

            os.replace(staging, cflsync_dir)
        except OSError as error:
            raise Workarea.Error(f"cannot initialise workarea: {error}") from error
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

        return cls(p)

    def is_empty(self) -> bool:
        """Report whether the cache holds no page state, which allows re-anchoring the workarea."""
        return not self.cache_dir.is_dir() or not self.page_state_paths()

    def _reanchor(self, root_page_id, profile):
        # The cache, not the directory contents, decides whether the workarea is empty: without cache state, local
        # entries are unmanaged, and the next pull reports clashes with them.
        if not self.is_empty():
            raise Workarea.Error(
                f"'{self.root_dir}' is a workarea with cached pages and cannot be re-anchored; remove its pages first "
                "with 'cflsync page remove'")

        try:
            self.cache_dir.mkdir(mode=0o700, exist_ok=True)
            # Each file is replaced atomically. The root goes last, so that a version-1 workarea only becomes an
            # anchored workarea once its profile and version are set.
            _write_private_file(self.cflsync_dir / "profile", f"{profile}\n")
            _write_private_file(self.cflsync_dir / "version", f"{WORKAREA_VERSION}\n")
            _write_private_file(self.cflsync_dir / "root", f"{root_page_id}\n")
        except OSError as error:
            raise Workarea.Error(f"cannot re-anchor workarea: {filesystem_error_message(error)}") from error

    @property
    def cflsync_dir(self) -> Path:
        return self.root_dir / ".cflsync"

    @property
    def cache_dir(self) -> Path:
        return self.cflsync_dir / "cache"

    @property
    def profile(self) -> str:
        with open(self.cflsync_dir / "profile", "r") as f:
            return f.read().rstrip("\r\n")

    @property
    def root_page_id(self) -> str:
        """Return the ID of the root page that anchors this workarea."""
        path = self.cflsync_dir / "root"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise Workarea.Error(
                f"'{self.root_dir}' is a version-1 cflsync workarea, which this version of cflsync does not support; "
                "create a new workarea anchored at a root page with 'cflsync init ROOT_PAGE_REF', or re-anchor this one "
                "the same way if it has no cached pages") from error
        except (OSError, UnicodeError) as error:
            raise Workarea.Error(f"cannot read '{path}': {filesystem_error_message(error)}") from error

        root_page_id = text.removesuffix("\n")
        if re.fullmatch(r"[0-9]+", root_page_id) is None:
            raise Workarea.Error(f"'{path}' must contain one numeric page ID")

        return root_page_id

    @property
    def version(self) -> int:
        """Return the workarea version, refusing a workarea that this version of cflsync does not support.

        Workareas created by cflsync 0.4 or earlier have no version file.
        """
        path = self.cflsync_dir / "version"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise Workarea.Error(
                f"'{self.root_dir}' was created by cflsync 0.4 or earlier, which this version of cflsync does not support; "
                f"{_TRANSITION_INSTRUCTIONS}") from error
        except (OSError, UnicodeError) as error:
            raise Workarea.Error(f"cannot read '{path}': {filesystem_error_message(error)}") from error

        value = text.removesuffix("\n")
        if re.fullmatch(r"[0-9]+", value) is None:
            raise Workarea.Error(f"'{path}' must contain one workarea version number")

        version = int(value)
        if version > WORKAREA_VERSION:
            raise Workarea.Error(
                f"'{self.root_dir}' has workarea version {version} and was created by a newer version of cflsync; "
                "use that version")
        if version < WORKAREA_VERSION:
            raise Workarea.Error(
                f"'{self.root_dir}' has workarea version {version}, which this version of cflsync does not support; "
                f"{_TRANSITION_INSTRUCTIONS}")

        return version

    def cache_path(self, page_id: str) -> Path:
        if not page_id.isdigit():
            raise ValueError(f"expected page-id, got '{page_id}'")

        return self.cache_dir / f"{page_id}.json"

    def page_state_paths(self) -> dict[str, Path]:
        """Return every numeric page-ID cache path, ordered by page ID."""
        try:
            cache_paths = sorted(self.cache_dir.glob("*.json"), key=lambda path: int(path.stem))
        except ValueError as error:
            raise StateError("cache contains a non-numeric page-state filename") from error

        paths: dict[str, Path] = {}
        for cache_path in cache_paths:
            if not cache_path.is_file():
                raise StateError(f"cache entry '{cache_path.name}' is not a file")
            paths[cache_path.stem] = cache_path

        return paths

    def contains(self, page_id: str, api) -> bool:
        """Report whether a remote page is this workarea's root page or one of its descendants.

        Ancestors above the root page may be folders; below the root page, only pages are supported.
        """
        if page_id == self.root_page_id:
            return True

        ancestors = api.page_ancestors(page_id)
        ancestor_ids = [ancestor.id for ancestor in ancestors]
        if self.root_page_id not in ancestor_ids:
            return False

        for ancestor in ancestors[ancestor_ids.index(self.root_page_id) + 1:]:
            if ancestor.type != "page":
                raise SyncError(
                    f"page '{page_id}' is below {ancestor.type} '{ancestor.id}' in this workarea's tree; only pages are supported")

        return True

    def page_tree(self) -> PageTree:
        """Load every cached page state as a tree anchored at this workarea's root page."""
        states = {page_id: PageState.load(path) for page_id, path in self.page_state_paths().items()}
        for page_id, state in states.items():
            if self.page_id_from_directory_name(state.page.directory) != page_id:
                raise StateError(
                    f"cached page '{page_id}' has directory '{state.page.directory}', which does not end in its page ID "
                    f"'_{page_id}'")

        return PageTree(states, self.root_page_id)

    def _page_directories(self):
        # The resolved directory of every cached page, derived from one page tree.
        tree = self.page_tree()
        return {page_id: self.page_directory_path(tree.directory(page_id)) for page_id in tree.states}

    def relative_directory(self, parent_id: str | None, name: str) -> str:
        """Return the directory of a page named *name* below cached parent *parent_id*, relative to the workarea root.

        The root page, which has no cached parent, is placed directly below the workarea root.
        """
        if parent_id is None:
            return name

        return f"{self.page_tree().directory(parent_id)}/{name}"

    def page_location(self, page_id: str, index, tree: PageTree | None = None) -> str:
        """Return the directory of page *page_id* relative to the workarea root, whether or not it is installed.

        A cached page keeps its cached directory. A page that is not cached is placed below its parent's location,
        under the name its installation would use; *index* supplies its title and parent through ``lookup(page_id)``,
        which returns a :class:`RemoteContentRef` for a page in the workarea's tree. *tree* is the loaded page tree,
        if the caller already has one. A page that *index* does not know is refused.
        """
        if tree is None:
            tree = self.page_tree()

        names = []
        seen = set()
        current: str | None = page_id
        while current is not None and current not in tree.states:
            if current in seen:
                raise SyncError(f"the remote parents of page '{page_id}' form a cycle")

            seen.add(current)
            page: RemoteContentRef | None = index.lookup(current)
            if page is None:
                raise SyncError(f"page '{current}' is not in this workarea's tree")
            if not page.title:
                raise SyncError(f"page '{current}' reports no title")

            names.insert(0, self.page_directory_name(page.title, current))
            current = page.parent_id

        if current is not None:
            names.insert(0, tree.directory(current))

        return "/".join(names)

    def page_directory(self, state: PageState, must_exist: bool = True) -> Path:
        """Return the safe managed path below the page's cached parent, normally requiring a directory and content.md."""
        directory = self.page_directory_path(self.relative_directory(state.page.parent_id, state.page.directory))
        if not must_exist:
            return directory

        if not directory.is_dir():
            raise Workarea.Error("managed page directory does not exist")
        if not (directory / CONTENT_FILENAME).is_file():
            raise Workarea.Error("managed page directory does not contain content.md")

        return directory

    def missing_root_error(self) -> SyncError:
        """Return the error that reports this workarea's root page as no longer existing."""
        return PageRefError(
            f"root page '{self.root_page_id}' of this workarea no longer exists; once its local pages are removed with "
            "'cflsync page remove', re-anchor the workarea with 'cflsync init ROOT_PAGE_REF'")

    def check_removable(self, directory: Path) -> None:
        """Refuse to remove *directory* while it contains the current directory, which Windows does not allow."""
        if _is_windows() and _current_directory_is_inside(directory):
            raise Workarea.Error("cannot remove a page directory while it is the current directory; run cflsync from outside it")

    def remove_page(self, state: PageState, must_exist: bool = True) -> None:
        """Remove one complete managed page directory; with *must_exist* false, a missing directory is not an error."""
        directory = self.page_directory(state, must_exist=must_exist)
        if not directory.exists():
            return

        self.check_removable(directory)

        try:
            shutil.rmtree(directory)
        except OSError as error:
            raise Workarea.Error(f"cannot remove managed page directory: {filesystem_error_message(error)}") from error

    def unmanaged_entries(self, state: PageState) -> list[str]:
        """Return the entries of a cached page's directory that cflsync does not manage, relative to that directory.

        Managed entries are the content file, managed attachments, and the directories of cached child pages.
        """
        directory = self.page_directory(state, must_exist=False)
        if not directory.is_dir():
            return []

        children = {other.page.directory for other in self.page_tree().states.values() if other.page.parent_id == state.page.id}
        entries = []
        for entry in sorted(directory.iterdir()):
            if entry.name == CONTENT_FILENAME and entry.is_file():
                continue

            if entry.name == "_attachments" and entry.is_dir():
                for attachment in sorted(entry.iterdir()):
                    if attachment.name not in state.attachments:
                        entries.append(f"_attachments/{attachment.name}")
                continue

            if entry.name in children and entry.is_dir():
                continue

            entries.append(entry.name)

        return entries

    def page_directory_target(self, page_id: str | None, parent_id: str | None, name: str) -> Path:
        """Return the safe, unoccupied path for page *page_id* named *name* below cached parent *parent_id*.

        The path is refused if a cached sibling uses the same name, or if the parent directory already contains another
        entry with that name, compared case-insensitively. A page whose directory is already at the path may keep it.
        *page_id* is ``None`` for a page that does not exist yet.
        """
        tree = self.page_tree()
        directory = self.relative_directory(parent_id, name)
        target = self.page_directory_path(directory)
        for other_id, other in tree.states.items():
            if other_id != page_id and other.page.parent_id == parent_id and same_directory_name(other.page.directory, name):
                raise Workarea.Error(f"a sibling page ('{other_id}') already uses directory '{directory}'")

        source = None
        if page_id in tree.states:
            source = self.page_directory_path(tree.directory(page_id))

        if target.parent.is_dir():
            for existing in target.parent.iterdir():
                if same_directory_name(existing.name, name) and existing != source:
                    raise Workarea.Error(f"page directory '{directory}' already exists")

        if source is not None and source != target and _is_windows() and _current_directory_is_inside(source):
            raise Workarea.Error("cannot rename a page directory while it is the current directory; run cflsync from outside it")

        return target

    def relocate(self, source: Path, directory: str) -> Path:
        """Move a page directory, with everything below it, to *directory* relative to the workarea root.

        The move is one directory rename. It is refused if another cached page is assigned the target directory, or
        if the target's parent already contains an entry with the same name, compared case-insensitively.
        """
        target = self.page_directory_path(directory)
        if target == source:
            return target

        for other_id, path in self._page_directories().items():
            if same_directory_name(str(path), str(target)) and path != source:
                raise Workarea.Error(f"page directory '{directory}' is assigned to page '{other_id}'")

        if target.parent.is_dir():
            for existing in target.parent.iterdir():
                if same_directory_name(existing.name, target.name) and existing != source:
                    raise Workarea.Error(f"page directory '{directory}' already exists")

        if _is_windows() and _current_directory_is_inside(source):
            raise Workarea.Error("cannot rename a page directory while it is the current directory; run cflsync from outside it")

        try:
            os.rename(source, target)
        except OSError as error:
            raise Workarea.Error(f"cannot move page directory: {filesystem_error_message(error)}") from error

        return target

    @contextmanager
    def relocation(self, source: Path, directory: str) -> Iterator[Path]:
        """Move a page directory as :meth:`relocate` does, and move it back if the enclosed block fails."""
        target = self.relocate(source, directory)
        try:
            yield target
        except BaseException:
            if target != source:
                os.rename(target, source)

            raise

    def page_directory_name(self, title: str, page_id: str) -> str:
        """Return the deterministic safe directory name of page *page_id* titled *title*, at most 64 characters long.

        The name is the encoded title followed by ``_<page_id>``, so that no two pages share a name and the page ID
        can be recovered from it. A long title is cut between characters, never inside an escape, to keep the suffix
        within the limit.
        """
        if not isinstance(title, str) or not title:
            raise Workarea.Error("page title must be a non-empty string")

        # One piece per title character: the character itself, or its escape.
        pieces = [_directory_name_piece(character) for character in unicodedata.normalize("NFC", title)]
        # Names starting with "_" are reserved for cflsync entries in a page directory, such as _attachments.
        if pieces[0] == "_":
            pieces[0] = "%5F"

        trailing_spaces = 0
        while pieces and pieces[-1] == " ":
            pieces.pop()
            trailing_spaces += 1

        if "".join(pieces).upper() in _WINDOWS_RESERVED_NAMES:
            pieces[0] = f"%{ord(pieces[0]):02X}"

        pieces.extend(["%20"] * trailing_spaces)
        suffix = f"_{page_id}"

        kept = []
        length = len(suffix)
        size = len(suffix.encode("utf-8"))
        for piece in pieces:
            # Characters count towards the limit; the UTF-8 size must also stay within the common 255-byte name limit.
            if length + len(piece) > DIRECTORY_NAME_LIMIT or size + len(piece.encode("utf-8")) > 255:
                break

            kept.append(piece)
            length += len(piece)
            size += len(piece.encode("utf-8"))

        # A cut can end the name on an interior space, which Windows would strip.
        while kept and kept[-1] == " ":
            kept.pop()

        return "".join(kept) + suffix

    def page_id_from_directory_name(self, name: str) -> str | None:
        """Return the page ID that a page directory name ends in, or ``None`` if it does not end in ``_<digits>``."""
        match = re.fullmatch(r".*_([0-9]+)", name, re.DOTALL)
        return None if match is None else match.group(1)

    def stage_page(
        self,
        directory: str,
        markdown: str,
        attachments: Mapping[str, bytes],
        source: Path | None = None,
        managed_attachments: Iterable[str] = ()) -> Path:
        """Write one complete page representation to a hidden staging directory.

        *directory* is the page directory relative to the workarea root, with "/" separators.
        """
        self.page_directory_path(directory)
        if not isinstance(markdown, str):
            raise Workarea.Error("page Markdown must be a string")

        staging = Path(mkdtemp(prefix=".cflsync-stage-", dir=self.root_dir))
        try:
            if source is not None:
                shutil.copytree(source, staging, dirs_exist_ok=True, symlinks=True)

            page_path = staging / CONTENT_FILENAME
            page_path.unlink(missing_ok=True)
            attachment_directory = staging / "_attachments"
            if attachment_directory.is_symlink():
                raise Workarea.Error("attachment directory must not be a symbolic link")

            attachment_directory.mkdir(exist_ok=True)
            for filename in managed_attachments:
                self._attachment_path(attachment_directory, filename).unlink(missing_ok=True)

            for filename in attachments:
                path = self._attachment_path(attachment_directory, filename)
                if path.exists() or path.is_symlink():
                    raise Workarea.Error(f"attachment '{filename}' would overwrite an unmanaged file")

            (staging / CONTENT_FILENAME).write_text(markdown, encoding="utf-8", newline="\n")
            for filename, body in attachments.items():
                self._attachment_path(attachment_directory, filename).write_bytes(body)

            return staging
        except SyncError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except (OSError, TypeError) as error:
            shutil.rmtree(staging, ignore_errors=True)
            raise Workarea.Error(f"cannot stage page directory: {filesystem_error_message(error)}") from error
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @contextmanager
    def replace_page(self,
                     staging: Path,
                     directory: str,
                     source: Path | None = None,
                     managed_attachments: Iterable[str] = ()) -> Iterator[Path]:
        """Replace managed files, retaining backups until the caller commits state.

        *directory* is the target page directory relative to the workarea root, with "/" separators.
        """
        target = self.page_directory_path(directory)
        if source is not None:
            try:
                source_directory = source.relative_to(self.root_dir).as_posix()
            except ValueError as error:
                raise Workarea.Error("previous page directory must be inside the workarea") from error

            if source.is_symlink() or source != self.page_directory_path(source_directory):
                raise Workarea.Error("previous page directory must be a page directory inside the workarea")

        if target.exists() and target != source:
            raise Workarea.Error(f"page directory '{directory}' already exists")

        if source is None:
            self.install_page(staging, directory)
            try:
                yield target
            except BaseException:
                os.replace(target, staging)
                raise

            return

        paths = [Path(CONTENT_FILENAME)]
        for filename in sorted(set(managed_attachments)):
            self._attachment_path(source / "_attachments", filename)
            paths.append(Path("_attachments") / filename)

        backup = Path(mkdtemp(prefix=".cflsync-backup-", dir=self.root_dir))
        (backup / "_attachments").mkdir()
        changed = []
        renamed = False
        created_attachments = False
        cleanup = False
        try:
            if source != target:
                self.relocate(source, directory)
                renamed = True

            attachment_directory = target / "_attachments"
            if attachment_directory.is_symlink():
                raise Workarea.Error("attachment directory must not be a symbolic link")

            if not attachment_directory.exists():
                attachment_directory.mkdir()
                created_attachments = True

            for relative in paths:
                destination = target / relative
                replacement = staging / relative
                existed = destination.exists() or destination.is_symlink()
                if existed:
                    shutil.copy2(destination, backup / relative, follow_symlinks=False)

                if replacement.exists() or replacement.is_symlink():
                    os.replace(replacement, destination)
                elif existed:
                    destination.unlink()

                changed.append((relative, existed))

            yield target
            cleanup = True
        except BaseException:
            for relative, existed in reversed(changed):
                if existed:
                    os.replace(backup / relative, target / relative)
                else:
                    (target / relative).unlink(missing_ok=True)

            if created_attachments:
                (target / "_attachments").rmdir()

            if renamed:
                os.rename(target, source)

            cleanup = True

            raise
        finally:
            if cleanup:
                shutil.rmtree(backup, ignore_errors=True)

    def install_page(self, staging: Path, directory: str, replace: bool = False) -> Path:
        """Install a new page directory or atomically replace its files.

        *directory* is the page directory relative to the workarea root, with "/" separators.
        """
        target = self.page_directory_path(directory)
        if target.exists() and not replace:
            raise Workarea.Error(f"page directory '{directory}' already exists")

        try:
            staging = staging.resolve()
            staging.relative_to(self.root_dir)
        except ValueError as error:
            raise Workarea.Error("staging directory is outside the workarea") from error

        if not staging.is_dir() or not (staging / CONTENT_FILENAME).is_file() or not (staging / "_attachments").is_dir():
            raise Workarea.Error("staging directory is incomplete")

        if not target.exists():
            try:
                os.replace(staging, target)
            except OSError as error:
                raise Workarea.Error(f"cannot install page directory: {filesystem_error_message(error)}") from error

            return target

        filenames = {path.name for path in (target / "_attachments").iterdir()}
        filenames.update(path.name for path in (staging / "_attachments").iterdir())
        try:
            with self.replace_page(staging, directory, target, filenames):
                pass
        except OSError as error:
            raise Workarea.Error(f"cannot replace page directory: {filesystem_error_message(error)}") from error

        shutil.rmtree(staging, ignore_errors=True)

        return target

    def page_directory_path(self, directory: str) -> Path:
        """Return the resolved path of a page directory given relative to the workarea root.

        *directory* separates directory names with "/" on every platform, as :meth:`PageTree.directory` returns them.
        The resolved path must stay inside the workarea.
        """
        components = directory.split("/")
        for component in components:
            if not component or component in {".", ".."} or Path(component).name != component:
                raise Workarea.Error(f"page directory '{directory}' must be a relative path of directory names")

        path = self.root_dir.joinpath(*components)
        path = path.resolve()
        try:
            path.relative_to(self.root_dir)
        except ValueError as error:
            raise Workarea.Error("page directory is outside the workarea") from error
        if path == self.root_dir:
            raise Workarea.Error("page directory must be below the workarea root")

        return path

    def _attachment_path(self, attachment_directory: Path, filename: str) -> Path:
        if not isinstance(filename, str) or not filename or filename in {".", ".."}:
            raise Workarea.Error("attachment filename must be a non-empty basename")

        if "/" in filename or "\\" in filename or "\x00" in filename:
            raise Workarea.Error(f"attachment filename '{filename}' is unsafe")

        path = attachment_directory / filename

        return path

    @classmethod
    def find(cls, p: Path):
        """Locate the workarea that contains path p, refusing a workarea that is not anchored at a root page."""
        dir = cls._locate(p)
        if dir is None:
            raise Workarea.Error(f"'{p}' is not part of a cflsync workarea")

        workarea = cls(dir)
        # Reading the root page ID and the version validates the workarea format; a missing root is reported first.
        workarea.root_page_id
        workarea.version
        return workarea

    @classmethod
    def _locate(cls, p):
        dir = (p if p.is_dir() else p.parent).resolve()
        while True:
            cflsync_dir = dir / ".cflsync"
            if cflsync_dir.is_dir() and (cflsync_dir / "profile").is_file():
                return dir

            if dir == dir.parent:
                return None

            dir = dir.parent


class PageRefError(SyncError):
    """Raised when a page reference cannot identify exactly one page."""


class PageRef:
    """A resolved Confluence page identifier."""

    def __init__(self, page_id: str) -> None:
        self.page_id = page_id

    @classmethod
    def resolve(cls, value: str | Path, workarea: Workarea, api, cwd: Path | None = None) -> "PageRef":
        """Resolve a local path, page ID, or title to one Confluence page ID in the workarea's tree.

        Cached pages are in the tree. Any other page must be the root page or have it among its ancestors.
        """
        text = str(value)
        path = _page_ref_path(value, cwd)
        if path.exists():
            return cls._from_path(path, workarea)

        states = _cached_states(workarea)
        if text.isdigit():
            try:
                page_id = api.get_page(text).id
            except APIError as error:
                if error.status == 404 and text == workarea.root_page_id:
                    raise workarea.missing_root_error() from error

                raise

            if page_id not in states and not workarea.contains(page_id, api):
                _require_root_page(workarea, api)
                raise PageRefError(
                    f"page '{page_id}' is not found in this workarea, which is anchored at page '{workarea.root_page_id}'")

            return cls(page_id)

        cached_ids = [state.page.id for state in states.values() if state.page.title == text]
        if cached_ids:
            return cls(_one_cached_page_id(cached_ids, text, states, workarea))

        pages = [page for page in api.find_pages_by_title(text) if page.title == text]
        page_ids = [page.id for page in pages if workarea.contains(page.id, api)]
        if not page_ids:
            _require_root_page(workarea, api)

        return cls(_one_page_ref_id(page_ids, f"title '{text}' in this workarea"))

    @classmethod
    def resolve_copy_source(cls, value: str | Path, workarea: Workarea, api, cwd: Path | None = None) -> "PageRef":
        """Resolve a copy source, preferring managed matches over same-site external pages.

        Selection preserves cached identity; copy must independently check its current
        ancestry and synchronization before installation or mutation.
        """
        text = str(value)
        states = workarea.page_tree().states
        path = _page_ref_path(value, cwd)
        if path.exists():
            return cls._from_path(path, workarea)

        if text.isdigit():
            if text in states:
                return cls(text)

            try:
                page_id = api.get_page(text).id
            except APIError as error:
                if error.status == 404 and text == workarea.root_page_id:
                    raise workarea.missing_root_error() from error

                raise

            if not workarea.contains(page_id, api):
                _require_root_page(workarea, api)

            return cls(page_id)

        cached_ids = [state.page.id for state in states.values() if state.page.title == text]
        if cached_ids:
            return cls(_one_cached_page_id(cached_ids, text, states, workarea))

        pages = [page for page in api.find_pages_by_title(text) if page.title == text]
        managed_ids = [page.id for page in pages if workarea.contains(page.id, api)]
        if managed_ids:
            return cls(_one_page_ref_id(managed_ids, f"title '{text}' in this workarea"))

        _require_root_page(workarea, api)
        return cls(_one_page_ref_id([page.id for page in pages], f"title '{text}' on the configured site"))

    @classmethod
    def resolve_remote(cls, value: str, api) -> "PageRef":
        """Resolve a page ID or title to one Confluence page ID through the API, without a workarea."""
        if value.isdigit():
            return cls(api.get_page(value).id)

        pages = [page for page in api.find_pages_by_title(value) if page.title == value]
        return cls(_one_page_ref_id([page.id for page in pages], f"title '{value}'"))

    @classmethod
    def resolve_local(cls, value: str | Path, workarea: Workarea, cwd: Path | None = None) -> "PageRef":
        """Resolve a local managed page path, ID, or title without remote access."""
        text = str(value)
        path = _page_ref_path(value, cwd)
        if path.exists():
            return cls._from_path(path, workarea)

        states = _cached_states(workarea)
        if text.isdigit() and text in states:
            return cls(text)

        cached_ids = [state.page.id for state in states.values() if state.page.title == text]
        if cached_ids:
            return cls(_one_cached_page_id(cached_ids, text, states, workarea))

        raise PageRefError(f"no managed local page matches '{text}'")

    @classmethod
    def _from_path(cls, path: Path, workarea: Workarea) -> "PageRef":
        try:
            path.relative_to(workarea.root_dir)
        except ValueError as error:
            raise PageRefError(f"page path '{path}' is outside the workarea") from error

        if path.is_file():
            if path.name != CONTENT_FILENAME:
                raise PageRefError(f"page file '{path}' is not named {CONTENT_FILENAME}")
            directory = path.parent
        elif path.is_dir():
            directory = path
            if not (directory / CONTENT_FILENAME).is_file():
                raise PageRefError(f"page directory '{path}' does not contain {CONTENT_FILENAME}")
        else:
            raise PageRefError(f"page path '{path}' is neither a file nor a directory")

        # A page is found by the location where the cache places it, which also covers nested directories.
        for page_id, page_directory in workarea._page_directories().items():
            if page_directory == directory:
                return cls(page_id)

        raise PageRefError(f"page path '{path}' is not managed by cflsync")


def _page_ref_path(value: str | Path, cwd: Path | None) -> Path:
    base = cwd or Path.cwd()
    return (base / Path(value)).resolve()


def _cached_states(workarea):
    return {page_id: PageState.load(path) for page_id, path in workarea.page_state_paths().items()}


def _require_root_page(workarea, api):
    # A reference outside the tree may be explained by a root page that no longer exists, for example after removing it.
    try:
        api.get_page(workarea.root_page_id)
    except APIError as error:
        if error.status == 404:
            raise workarea.missing_root_error() from error

        raise


def _one_cached_page_id(page_ids, title, states, workarea):
    if len(page_ids) > 1:
        matches = []
        for page_id in page_ids:
            directory = workarea.page_directory(states[page_id], must_exist=False).relative_to(workarea.root_dir)
            matches.append(f"{page_id} ({directory.as_posix()})")

        raise PageRefError(f"multiple pages match cached title '{title}': {', '.join(matches)}")

    return page_ids[0]


def _one_page_ref_id(page_ids: list[str], description: str) -> str:
    if not page_ids:
        raise PageRefError(f"no page matches {description}")
    if len(page_ids) > 1:
        raise PageRefError(f"multiple pages match {description}: {', '.join(page_ids)}")

    return page_ids[0]


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3",
    "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9", }


def _write_private_file(path, text):
    # Write *text* to a temporary file next to *path*, then rename it over *path*.
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
                                delete=False) as file:
            temporary_path = Path(file.name)
            if not _is_windows():
                temporary_path.chmod(0o600)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _is_windows() -> bool:
    return os.name == "nt"


def _current_directory_is_inside(directory: Path) -> bool:
    try:
        Path.cwd().resolve().relative_to(directory.resolve())
    except (OSError, ValueError):
        return False

    return True


def _directory_name_piece(character):
    # ASCII characters other than letters, digits, space, "-", "_", and "~" are escaped, "." included, so that names
    # such as ".", "..", and "content.md" cannot occur. Other characters are kept, unless they do not print.
    if character == ".":
        return "%2E"

    if character.isascii() or not character.isprintable():
        return quote(character, safe=" -_")

    return character


def directory_name_key(name: str) -> str:
    """Return the form in which a case-insensitive, normalizing filesystem compares directory names."""
    return unicodedata.normalize("NFC", name).casefold()


def same_directory_name(first: str, second: str) -> bool:
    """Report whether two directory names are equal on a case-insensitive, normalizing filesystem."""
    return directory_name_key(first) == directory_name_key(second)


def filesystem_error_message(error: Exception) -> str:
    """Describe a filesystem error, explaining a path that the operating system rejected as too long."""
    if not isinstance(error, OSError) or not _is_path_length_error(error):
        return str(error)

    paths = [str(path) for path in (error.filename, error.filename2) if path is not None]
    if not paths:
        return f"a path is too long for this system: {error}"

    path = max(paths, key=len)
    return f"path is too long for this system ({len(path)} characters): '{path}'; on Windows, enable long path support"


def _is_path_length_error(error):
    # Windows reports ERROR_FILENAME_EXCED_RANGE (206); other systems report ENAMETOOLONG.
    return error.errno == errno.ENAMETOOLONG or getattr(error, "winerror", None) == 206


# vim: set ts=4 sw=4 et tw=132:
