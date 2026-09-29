# cflsync specification

## Command interface

```text
cflsync auth [-p PROFILE] [--list | --delete]
cflsync init [-p PROFILE] ROOT_PAGE_REF
cflsync pull [-f | --force] [-d | --delete]
cflsync push [-f | --force]
cflsync status
cflsync page create PARENT_PAGE_REF TITLE
cflsync page pull [-f | --force] PAGE_REF
cflsync page push [-f | --force] PAGE_REF
cflsync page rename PAGE_REF TITLE
cflsync page move PAGE_REF NEW_PARENT_REF
cflsync page remove [-f | --force] PAGE_REF
cflsync page status PAGE_REF
```

A workarea manages one Confluence page tree: a root page and its descendants.
Commands locate a workarea by walking upward to a directory containing
`.cflsync/profile`. A workarea without a valid `.cflsync/root` was created by
an earlier cflsync version; every command except `auth` refuses it and explains
how to create a new, anchored workarea.

`init [-p PROFILE] ROOT_PAGE_REF` resolves `ROOT_PAGE_REF`, a page ID or an
exact page title, through Confluence with the profile's credentials. It then
creates `.cflsync/` with an empty `cache/`, `profile`, and `root`, which records
the root page ID, as one atomic installation. A failed lookup leaves no
`.cflsync/` behind. `init` refuses a directory inside any existing workarea,
and does not pull pages.

`page pull PAGE_REF` resolves `PAGE_REF` and creates or updates its page
directory and cache entry. The root page's directory is directly below the
workarea root; every other page's directory is inside its parent's page
directory. Before pulling the requested page, cflsync installs each missing
ancestor up to the root, parents before children. An uncached ancestor is
pulled, while a cached ancestor is retained as-is; a cached ancestor whose
directory is missing is restored at its cached location. Each installation
prints `Pulled parent 'TITLE' (ID) to PATH`. If a later ancestor installation
fails, earlier installations remain and the error lists them. `--force` applies
only to `PAGE_REF`, not to its ancestors. When a page's remote title or parent
changed, the pull installs a missing new-parent chain first, then moves its
directory, with its child pages and unmanaged files, to the new location, also
when its content is otherwise unchanged.

`page push PAGE_REF` uploads the local changes of a cached page. It never
changes the page's title or parent.

`push` discovers the root page and all of its page descendants, compares them
with the cached tree, and processes the resulting statuses parents before
children. Without `--force`, it pushes only locally changed pages and aborts
before mutation if any page conflicts. Remote-only changes and pages absent on
either side are skipped. With `--force`, conflicting and unchanged pages are
also pushed, preferring local content; a page absent remotely is still skipped
and must be recreated with `page create`. Each page is reported as pushed,
unchanged, skipped, or failed, followed by a summary. After conflict preflight,
the command continues after a per-page failure and exits non-zero if any page
failed.

`pull` discovers the tree and compares it with the cache in the same way, and
processes the resulting statuses parents before children. Without `--force`, it
aborts before any change if a page conflicts, and pulls remotely changed pages
and pages not present locally, including cached pages whose directory is
missing. Each pull places the page inside its current remote parent's
directory and moves its directory, with child pages and unmanaged files, after
a remote rename or move. Locally changed pages are skipped. With `--force`,
conflicting and unchanged pages are also pulled, overwriting local changes to
managed files. A page whose parent could not be pulled is reported as blocked.
Cached pages that are no longer in the tree, because they were deleted or moved
outside the root, are kept unchanged and reported last. Each page is reported
as pulled, deleted, unchanged, skipped, blocked, kept, or failed, followed by a
summary; the command exits non-zero if any page failed. An interrupted pull is
completed by running it again.

`pull --delete` (`-d`) also deletes the local copies of pages that are no longer
in the tree: each page's directory, including unmanaged files, and its cache
entry. Nothing is deleted remotely. Every check runs before any change:

- Without `--force`, a page removed remotely whose local copy changed is a
  conflict, and aborts the command like any other conflict.
- Without `--force`, the command lists the pages to delete, marking unmanaged
  files that Confluence cannot restore, and asks for confirmation. Declining
  aborts the command; without a terminal, the command fails and suggests
  `--force`. `--force` deletes without confirmation, including local changes.

Deletions run after all pulls and relocations, children before parents. A
page's directory is deleted only if every cached page below it is deleted too;
a child whose relocation out of the directory failed keeps its parent, which is
reported as blocked. A page whose directory is already missing only loses its
cache entry. An interrupted deletion leaves a valid cache and is completed by
running the command again. The root page is never deleted this way: if it is
gone, discovery fails first.

`status` discovers the tree and compares it with the cache in the same way, and
reports one line per page, parents before children: `not in local` (remote page
not cached, or its directory is missing), `remote removed` (cached page absent
from the tree: deleted, inaccessible, or moved outside the root), `remote
removed, local changed` (such a page whose local copy changed), `remote
changed`, `local changed`, `conflict` (changed on both sides), or `unchanged`,
followed by counts per state. It changes nothing. If discovery fails, for
example because a listing is denied or the tree contains a folder, the command
fails before reporting anything, so an incomplete listing is never reported as
remote removals.

`page status PAGE_REF` reports local and remote changes of a cached page, and
where the next pull would move its directory (see
[Change detection and synchronization](#change-detection-and-synchronization)).

`page create PARENT_PAGE_REF TITLE` resolves `PARENT_PAGE_REF`, creates an
empty child page remotely, then runs the equivalent of `page pull` for its
returned ID. Before creating the remote child, it installs the parent and any
missing ancestors. If a cached sibling uses the new page's directory name, the
created page gets the page-ID suffix (see below). Any other entry of that name
in the parent directory is refused before the page is created remotely. It has no offline mode, so each local page begins
with Confluence-authoritative metadata.

`page rename PAGE_REF TITLE` requires the referenced managed page to be in
sync. It updates the remote title with optimistic concurrency, rewrites the
generated title heading, renames the title-derived local directory, and writes
the updated cache state. The directory keeps its parent; child page directories
and unmanaged files move with it, and only the renamed page's cache entry
changes. The new name keeps an existing page-ID suffix, and gets one if a
cached sibling uses it. Another entry of that name in the parent directory is
refused before the remote update. `TITLE` must be non-empty, single-line text
without surrounding whitespace. It is the explicit local-title operation;
`page push` continues to reject an edited title heading. The root page may be
renamed.

`page move PAGE_REF NEW_PARENT_REF` requires the referenced managed page to be
in sync, and not to be the workarea's root page. `NEW_PARENT_REF` resolves to a
page in the workarea's tree. Before the remote update, it installs the new
parent and any missing ancestors. The page keeps its directory name, and gets
the page-ID suffix if a cached sibling in the new parent uses it; another entry
of that name is refused. It then changes the remote parent, moves
the page directory, with its child pages and unmanaged files, into the new
parent's directory, and records the new parent in the cache. The Markdown is
unchanged. If Confluence rejects the update, installed ancestors remain.

`page remove [-f | --force] PAGE_REF` requires a managed local page directory
and cache entry. It confirms removal unless `--force` is supplied; without a
terminal, it fails instead of prompting. When the
remote page exists, the command requires it to be synchronized, deletes it,
then removes the local directory and cache entry. A remote 404 is treated as
an already-removed remote page, so only the local copy is removed. A page with
child pages, cached locally or existing remotely, is refused before the
confirmation; its children must be removed first. Removing the root page, once
it has no children, leaves an empty workarea: only `.cflsync`, with its
profile, root page ID, and an empty cache, remains. Commands that then refer to
pages report that the root page no longer exists; the directory can be re-used
by deleting `.cflsync` and running `init` again.

## Current limitations

The following situations are refused with an error that explains what to do:

- A page with child pages cannot be removed; remove its children first.
- A workarea cannot be re-anchored at another root page; after removing the
  root page, delete `.cflsync` and run `init` again.
- Folders and other non-page content inside the tree are not supported.

## Page references

`page create`, `page pull`, `page push`, `page rename`, `page move`, and `page
status` accept a page reference: a numeric page ID, page title, local GFM file,
or local page directory. The resolver classifies the argument in this order:

1. An existing filesystem path is a local reference. A file must be managed
   `content.md`; a directory must contain that file. Its cache entry supplies the
   page ID.
2. A non-path argument containing only decimal digits is a Confluence page ID.
3. Any other argument is a page title.

Path references must be inside the discovered workarea and identify a cached
page by its directory's location; arbitrary standalone GFM files are rejected.
An ID is resolved through Confluence. A title first matches a cached title;
otherwise it is looked up remotely. Both must produce exactly one page. Zero
and multiple matches are errors; an ambiguous cached title reports the page IDs
and local paths, and an ambiguous remote title the page IDs.

References only resolve to pages in the workarea's tree: the root page and its
descendants. Cached pages are in the tree. Any other page must be the root
page, or have the root page among its Confluence ancestors, which one ancestors
request checks. Otherwise the reference fails with "not found in this
workarea", and a remote title ignores candidates outside the tree. Ancestors
above the root page may be folders; a page below non-page content inside the
tree, such as a folder, is an error, because only pages are supported.

All successful reference forms produce a page ID. Subsequent command
semantics, cache keys, concurrency checks, and conflict handling are identical.

`page remove` and `page status` accept the same forms, but each must resolve to
cached local state; they do not resolve an ID or title remotely.

## Workarea and local representation

All synchronization state is below `.cflsync`, separate from managed content,
so page directories contain no private state. The layout mirrors the page
hierarchy:

```
<workarea>/
  .cflsync/
    profile
    root
    cache/
      123456.json
      123457.json
  <root-page-title>/
    content.md
    _attachments/
      <attachment filename>
    <child-page-title>/
      content.md
      _attachments/
```

`content.md` contains GitHub Flavored Markdown (GFM); `_attachments` contains
downloaded attachment files. `.cflsync/profile` selects the credential profile.
`.cflsync/root` holds the root page ID as one numeric line.
`.cflsync/cache/<page-id>.json` is private synchronization state, not page
content.

The page directory name is a deterministic filesystem-safe encoding of the
remote title, normalized to Unicode NFC. Non-ASCII characters are kept as they
are, unless they do not print, such as zero-width or non-breaking spaces. ASCII
characters other than letters, digits, space, `-`, `_`, and `~` are
percent-encoded, `.` always as `%2E`, so that no title can produce `.`, `..`,
or the name `content.md`. A leading `_` is also encoded, as `%5F`, so that
names starting with `_`, such as `_attachments`, stay reserved for cflsync.
Trailing spaces are encoded as `%20`, and Windows device names such as `CON`
are escaped.

A name has at most 64 characters, and at most 255 UTF-8 bytes. A longer name is
cut between characters, never inside an escape, and a space left at the end of
the cut is dropped.

Sibling pages whose names are equal, compared case-insensitively and after NFC
normalization (because some filesystems store names decomposed), are
disambiguated with a suffix: `_` and the page ID, as in `Release notes_123456`.
The suffix counts towards the 64-character limit; the title part is cut to make
room. Suffixes are assigned as follows:

- A page arriving next to a cached sibling that uses its name gets the suffix;
  the existing directory is not renamed.
- When `pull` installs several new siblings with the same name, all of them get
  the suffix, so the result does not depend on their order.
- A suffix is stable: it is kept when the clash disappears, and after a rename
  or move. A rename or move into a name a cached sibling uses adds one.
- A title that literally equals a suffixed name, such as `Beta_300`, is itself
  suffixed if that name is taken.

Local paths therefore depend on history: two workareas of the same tree can use
`Title` and `Title_123456` for the same page. Only the page ID identifies a
page across workareas.

The name is presentation only: the cache's page ID and directory name are
authoritative. A pull moves a page directory only if its target is unused;
otherwise it stops without overwriting data. An unmanaged entry with the same
name as a page's directory is never suffixed around: the page fails, and the
entry is left untouched.

On Windows, a page directory cannot be renamed or moved when cflsync is
running from inside it. The command stops before mutation and asks the user to
run it from the workarea or another directory before retrying.

Attachments use relative Markdown URLs:

```markdown
![Diagram](_attachments/diagram.png)
[Download spreadsheet](_attachments/report.xlsx)
```

ADF-to-GFM conversion rewrites resolved media and links to these paths. The
reverse conversion recognizes only paths rooted at `_attachments/`; a
`MediaResolver` maps them to Confluence attachment references. Other links stay
ordinary links. Filenames are validated to prevent traversal, and duplicate
manifest names or attachment IDs are rejected as ambiguous.

On pull, the remote attachment manifest determines managed local files. A local
file under `_attachments/` that `content.md` links to also becomes managed, so new
attachments can be introduced locally; files that nothing links to stay
unmanaged. On push, managed files are uploaded or updated and previously
managed files removed locally are deleted remotely. Attachments outside the
managed set must not be deleted.

## Per-page cache entry

On Unix, each synchronized page has an atomically written `0600` cache entry
at `.cflsync/cache/<page-id>.json`; `.cflsync` and `cache` use mode `0700`.
Cache entries contain no credentials. Credential configuration is also
atomically written with mode `0600` under a mode-`0700` configuration
directory. On Windows, POSIX modes do not apply. Credentials remain below the
per-user configuration directory selected by `platformdirs`, relying on its
default user ACL; cflsync does not alter Windows ACLs. Stable page IDs are
cache keys, avoiding title-based collisions. Failed or interrupted
initialization, staging, and private-file writes remove their temporary files
or directories. Format 2 is:

```json
{
  "format": 2,
  "page": {
    "id": "123457",
    "title": "Example page",
    "parent_id": "123456",
    "directory": "Example page",
    "version": 17,
    "content_hash": "..."
  },
  "attachments": {
    "diagram.png": {
      "id": "att987654",
      "version": 3,
      "content_hash": "..."
    }
  }
}
```

`parent_id` is the cached parent page, whose directory contains this page's
directory, and is `null` for the root page. `directory` is the page's own
directory name, relative to its parent's directory: a single name without
separators. A page's path relative to the workarea root is derived by joining
the directory names along the `parent_id` chain up to the root. Every cached
page except the root must have a cached parent; a missing parent, a cycle, or
a second page without a parent makes the cache invalid. Format-1 entries are
refused.

`content_hash` is SHA-256 of canonical GFM for pages and raw bytes for
attachments, unchanged since format 1. The algorithm is part of the format
definition; an algorithm change requires a new format and cache migration or
replacement.
Cached versions and hashes describe the last state known to be identical
locally and remotely.

## Change detection and synchronization

`page status PAGE_REF` compares local content with its cache entry and fetches
remote page and attachment metadata. It reports each side as unchanged or
changed without modifying the workarea. The remote side is instead reported as
not found when Confluence returns 404 for the page, which was deleted or is not
accessible, and as moved outside the workarea's tree when the root page is no
longer among its ancestors. When the next `page pull` would move the page
directory after a remote rename or move, a `location:` line shows the current
and the new directory, or names a new parent that the pull installs first.

GET and HEAD requests retry once after a transport failure or HTTP 429, 502,
503, or 504 response. POST, PUT, and DELETE requests are never retried
implicitly, because their remote effects may be indeterminate after a failed
request.

Before either modifying operation, cflsync computes two independent changes:

| State since last successful sync | Meaning |
| --- | --- |
| Canonical GFM or a managed attachment hash differs from cache | local change |
| Confluence page or managed attachment version differs from cache | remote change |

The page and its complete managed attachment set are one atomic unit:

| Local | Remote | `page pull` | `page push` |
| --- | --- | --- | --- |
| unchanged | unchanged | no-op | no-op |
| unchanged | changed | replace local page and managed attachments | conflict |
| changed | unchanged | conflict | upload local page and attachment set |
| changed | changed | conflict | conflict |

A conflict does not alter local files, remote content, or the cache entry.
Explicit force options select which side wins; automatic merging is outside
scope. Remote updates use the current Confluence page version. A version
mismatch is a conflict even if an earlier check found no change.

An unchanged pull reports that local and remote content are already in sync
and nothing was pulled. `page pull -f` (or `--force`) bypasses this no-op and
downloads and regenerates the local representation, for example after a
converter update. It also resolves conflicts in favor of the remote version:
local changes to managed files are overwritten, and missing managed files are
restored. Unmanaged files remain protected, and failed pulls retain the previous
local files and cache. It does not force an ancestor installed for the pull.
`page push -f` (or `--force`) is the mirror image: it
bypasses the push no-op and resolves conflicts in favor of local content,
uploading it over remote changes. The update still uses the current Confluence
version, so a concurrent edit between the check and the update is a conflict.

Push never writes local files. It uploads new and changed managed attachments,
converts `content.md` to ADF, updates the page, and deletes previously managed
attachments removed locally, in that order. The title heading that pull adds is
removed before conversion and is not part of the body; editing it is rejected,
because push does not rename pages.

`page rename` is non-destructive but changes the local path. It first checks
that page and attachment state is unchanged locally and remotely, and rejects
a target directory that is occupied by an unmanaged entry. It stages the
rewritten Markdown before the remote update, preserves the current ADF body in
that update, then renames the directory and writes cache last. If the remote
update succeeds but local installation or the cache write fails, local files
are restored and the command reports incomplete synchronization, naming the
`page pull` that completes the rename; the old cache makes the remote title
change visible to `status`.

`page move` checks that the managed source page and attachments are unchanged
locally and remotely. It resolves and fetches the new parent, which must be a
different page in the same space, installs that page and its missing ancestors,
and checks the target directory. A move sends the existing title and ADF body
with the new `parentId` in one versioned update. Confluence validates the
resulting hierarchy; a rejected update identifies both the source and target
page IDs, while any installed ancestors remain. The command then moves the page
directory and writes the cache, with the new parent and the returned page
version, last. If that fails after the remote move, the directory is moved back
and the command reports incomplete synchronization, naming the `page pull` that
completes the move.

`page remove` resolves only local managed state, refuses a page with children,
checks the remote page if it still exists, and asks for confirmation
immediately before deletion. `--force`
only bypasses that prompt. A remote deletion failure leaves the local directory
and cache intact. After a successful remote deletion, it removes the complete
local directory, including unmanaged files, then its cache entry. If the remote
page is already absent, it performs that local cleanup without a remote delete.

`page pull` stages downloads, conversion, attachment-path validation, and
content validation in a temporary directory. For an existing page it preserves
the page and attachment directories, atomically replaces `content.md` and each
managed attachment, and writes the cache last. Only a remote title or parent
change moves the existing page directory. Backups allow rollback of file
changes and the move if installation or the cache write fails. These individual replacements are
not a single filesystem transaction across all files. `page push` uploads changed
attachments, updates content with optimistic concurrency, applies managed
attachment deletions, and writes cache only after complete success. A failed
remote sequence is reported as incomplete; the next `page status` detects the
resulting remote change.

## Content hierarchy requests

The API client lists a page's ancestors, which page references and ancestor
installation use to check that a page is in the workarea's tree, and its direct
children, which `page remove` checks. Their behaviour was verified against
Confluence Cloud:

- `GET /pages/{id}/ancestors` returns `id` and `type` for every ancestor,
  highest first. Non-page ancestors such as folders are included. A response
  holds at most `limit` ancestors, nearest to the requested content, and has no
  `next` link. `APIClient.page_ancestors` requests the maximum `limit` of 250.
  It continues a full response from its highest ancestor, through
  `/pages/{id}/ancestors` or `/folders/{id}/ancestors`, and rejects any other
  ancestor type as a continuation point.
- `GET /pages/{id}/direct-children` returns `id`, `status`, `title`, `type`,
  and `childPosition`, in position order, and is paginated through
  `_links.next`. According to the API reference, it includes non-page children
  (folders, whiteboards, databases, embeds). The `/pages/{id}/children`
  endpoint omits `type`, so it cannot distinguish non-page children, and is not
  used.
- `APIClient.page_descendants` repeatedly calls the direct-children endpoint,
  breadth-first, and returns every page `RemoteContentRef` below the supplied
  page. It rejects non-page children, so a successful return is complete for
  the page hierarchy.
- A `limit` above 250 is rejected with HTTP 400 by both endpoints.
