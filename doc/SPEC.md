# cflsync specification

## Command interface

```text
cflsync auth [-p PROFILE] [--list | --delete]
cflsync init [-p PROFILE] ROOT_PAGE_REF
cflsync pull [-f | --force] [-d | --delete]
cflsync push [-f | --force]
cflsync status
cflsync page create PARENT_PAGE_REF TITLE
cflsync page copy [--parent PARENT_PAGE_REF] SOURCE_PAGE_REF NEW_TITLE
cflsync page pull [-f | --force] PAGE_REF
cflsync page push [-f | --force] PAGE_REF
cflsync page rename PAGE_REF TITLE
cflsync page move PAGE_REF NEW_PARENT_REF
cflsync page remove [-f | --force] PAGE_REF
cflsync page status PAGE_REF
```

A workarea manages one Confluence page tree: a root page and its descendants.
Commands do not write, create below, or move to a page outside that tree.
Only `page copy` may read an external source page on the configured site.
Commands locate a workarea by walking upward to a directory containing
`.cflsync/profile`. A workarea without a valid `.cflsync/root` was created by
an earlier cflsync version; every command except `auth` refuses it and explains
how to create a new, anchored workarea, or to re-anchor an empty one. A
workarea without `.cflsync/version` was created by cflsync 0.4 or earlier, and
a workarea with a version other than 3 by another cflsync version; every
command except `auth` and `init` refuses them before contacting Confluence.
For a 0.4 workarea, the refusal explains the transition: push local changes
with the version that created it, initialise a new workarea in an empty
directory, pull, and copy unmanaged files across.

Confirmation prompts require a terminal. Without one, a command that would
prompt fails before changing anything and suggests `--force`.

`init [-p PROFILE] ROOT_PAGE_REF` resolves `ROOT_PAGE_REF`, a page ID or an
exact page title, through Confluence with the profile's credentials. It then
creates `.cflsync/` with an empty `cache/`, `profile`, `version`, and `root`,
which records the root page ID, as one atomic installation. A failed lookup leaves no
`.cflsync/` behind. `init` does not pull pages.

`init` also re-anchors an existing workarea, of any version, when run at its
root and when its cache holds no page state: after the root page was removed, a
workarea anchored at the wrong root and never pulled, or an empty workarea of
an earlier version, which is converted in place. The new root is resolved
first; then `profile`, `version`, and `root` are each replaced atomically, the
root last. `-p` has its
usual meaning, so omitting it sets the profile to `default`. The new root may
be the old one. Local entries without cache state are unmanaged; the next pull
reports clashes with them. `init` refuses a workarea with cached pages, and any
directory below an existing workarea.

`page pull PAGE_REF` resolves `PAGE_REF` and creates or updates its page
directory and cache entry. The root page's directory is directly below the
workarea root; every other page's directory is inside its parent's page
directory. Before pulling the requested page, cflsync installs each missing
ancestor up to the root, parents before children. An uncached ancestor is
pulled, while a cached ancestor is retained as-is; a cached ancestor whose
directory is missing is restored at its cached location. Each installation
prints `Pulled parent 'TITLE' (ID) to PATH`. If a later ancestor installation
fails, earlier installations remain and the error lists them. Directory names
and clashes with unmanaged entries are checked for the whole ancestor chain
before the first installation. Each installed ancestor's remote parent must
match the chain; otherwise the command stops with a retry hint, and pages
already installed remain valid. `--force` applies only to `PAGE_REF`, not to
its ancestors. When a page's remote title or parent
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
reports one line per page, parents before children, with the label of its state
(see [Page states](#page-states)), followed by counts per state. It changes
nothing. If discovery fails, for example because a listing is denied or the
tree contains a folder, the command fails before reporting anything, so an
incomplete listing is never reported as remote removals.

`page status PAGE_REF` reports local and remote changes of a cached page, and
where the next pull would move its directory (see
[Change detection and synchronization](#change-detection-and-synchronization)).

`page create PARENT_PAGE_REF TITLE` resolves `PARENT_PAGE_REF`, creates an
empty child page remotely, then runs the equivalent of `page pull` for its
returned ID. Before creating the remote child, it installs the parent and any
missing ancestors. The new page's directory name carries its page ID, which is
only known once the page exists, so the pull after creation checks it for
clashes with unmanaged entries (see
[Workarea and local representation](#workarea-and-local-representation)). It
has no offline mode, so each local page begins with
Confluence-authoritative metadata.

`page rename PAGE_REF TITLE` requires the referenced managed page to be in
sync. It updates the remote title with optimistic concurrency, rewrites the
generated title heading, renames the title-derived local directory, and writes
the updated cache state. The directory keeps its parent; child page directories
and unmanaged files move with it, and only the renamed page's cache entry
changes. The new name is derived from the new title and keeps the page-ID
suffix. Another entry of that name in the parent directory is refused before
the remote update. `TITLE` must be non-empty, single-line text
without surrounding whitespace. It is the explicit local-title operation;
`page push` continues to reject an edited title heading. The root page may be
renamed.

`page move PAGE_REF NEW_PARENT_REF` requires the referenced managed page to be
in sync, and not to be the workarea's root page. `NEW_PARENT_REF` resolves to a
page in the workarea's tree. Before the remote update, it installs the new
parent and any missing ancestors. The page keeps its directory name, which
carries its page ID and so cannot clash with a sibling page; another entry of
that name is refused. It then changes the remote parent, moves
the page directory, with its child pages and unmanaged files, into the new
parent's directory, and records the new parent in the cache. The Markdown is
unchanged. If Confluence rejects the update, installed ancestors remain.

`page remove [-f | --force] PAGE_REF` removes a page and all pages below it,
remotely and locally. It requires a managed local page directory and cache
entry. It compares the page's subtree, remote and cached, and runs every check
before any change:

- Every page of the subtree must be in sync. A page removed remotely whose
  local copy changed is refused unless `--force` is given; `--force` does not
  override other changes.
- A page moved remotely into or out of the subtree is refused, with a hint to
  run `cflsync pull` first, so that no page still in the tree is removed with a
  directory it is no longer below.
- On Windows, removing a directory that contains the current directory is
  refused.
- Unless `--force` is given, the command asks for confirmation; without a
  terminal, it fails instead of prompting. For a page with descendants, it
  lists them, marking pages without a local copy and directories with
  unmanaged files. Declining changes nothing.

Pages are then removed children first: remotely (a 404 counts as already
removed), then their local directory, including unmanaged files, then their
cache entry. Remote-only descendants are removed remotely, and pages already
removed remotely only locally. A failure stops the removal and names the pages
removed before it; running the command again completes it. Removing the root
page removes the whole tree and leaves an empty workarea: only `.cflsync`, with
its profile, root page ID, and an empty cache, remains. Commands that then refer
to pages, and `pull`, `push`, and `status`, report that the root page no longer
exists; `init ROOT_PAGE_REF` re-anchors the workarea.

### Page copy

`page copy [--parent PARENT_PAGE_REF] SOURCE_PAGE_REF NEW_TITLE` copies one
remote page and immediately installs it locally. Source lookup preserves the
usual path/ID/exact-title classification and gives cached matches precedence.
Without a cached title match, exact remote candidates inside the workarea take
precedence over external candidates. Ambiguity at either stage is an error,
not a reason to fall back. Local paths must still identify managed pages.
Sources may be in another space on the configured site; cross-site references
and folder references are unsupported.

For a cached or current in-tree source, content and managed attachments must
be unchanged locally and remotely, including title and current parent. Missing
local state or an unpulled in-tree source requires synchronization first.
A cached source moved outside the tree is refused rather than treated as an
external source. These checks finish before installing any destination ancestor
or creating a remote page. External sources without cached state are copied
directly; local content is never uploaded by copy.

The destination parent must currently be inside the managed tree, including
when resolved from cache. Without `--parent`, use the source's current parent.
An external source or the root requires an explicit parent. The source itself
or an in-tree descendant is an eligible explicit parent. Missing destination
ancestors are preflighted and installed under the same rules as `page create`.
Dirty cached ancestors are retained, and earlier installations survive failure.

Use the native v1 single-page copy endpoint with `copyAttachments` and
`copyLabels` true, and `copyPermissions`, `copyProperties`, and
`copyCustomContents` false. Copy the body, current attachment bytes, and labels,
excluding descendants, comments, history, source restrictions/properties/custom
content, and unmanaged local files. Labels remain remote metadata; there is no
local label baseline or label-only change detection.

Confluence determines title disambiguation and restricted-parent permissions.
Accept the actual title, fetch the returned ID through v2, and use normal pull
to install content, attachments, and a new format-3 baseline. Success reports
the actual title, ID, and local path. Final local naming/clash checks use that
actual title and can fail after remote creation. No force mode, title uniqueness
preflight, manual fallback, permission workaround, or mutation retry is added.

Structured source-owned media is remapped natively to copied attachment file
IDs. Ordinary download URLs, Smart Links, version parameters, and foreign-page
media remain unchanged and can still depend on the source. This is page copying,
not template instantiation or a guarantee of a self-contained page.

If a known created ID cannot be pulled, report failure and
`cflsync page pull NEW_ID`, retaining the remote page and installed ancestors.
Do not copy again or automatically delete it. A lost or unusable creation
response reports an uncertain outcome; repeating copy may create a duplicate.
Concurrent edits/moves after preflight remain subject to the existing
check-then-mutate race, without a pinned snapshot or cross-system transaction.

Native evidence dated 2026-09-30: disposable probes using the existing Basic
email/API-token profile verified version-1 copies, current attachments with
fresh IDs, labels, excluded source restrictions/properties/comments/children,
owned-media remapping, unchanged URL strings, same-site cross-space copying,
native ` (2)` disambiguation, and restricted-parent HTTP 403. The original
cross-space fixture contained no attachments or labels. A sanitized media
fixture is stored in `tests/fixtures/page_copy/source-adf.json`; image and
inline-file mappings are checked individually after correcting the original
aggregate comparison. Browser rendering, app-specific macros, and real push
round trips require separate verification and are not inferred from these probes.

The [single-page endpoint documentation](https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content---children-and-descendants/#api-wiki-rest-api-content-id-copy-post),
checked 2026-09-30, requires destination-space Add permission. It lists classic
OAuth scope `write:confluence-content`, or granular scopes
`read:content-details:confluence` and `write:page:confluence`. These are endpoint
scopes, not a complete scope set for cflsync's lookup/download/pull operations.
Current profiles use site-bound Basic authentication; scoped-token gateway
support remains separate work. Source reads and final pull also require access
to their pages and attachments, and native restricted-parent rejection remains
authoritative even when ordinary page creation there succeeds.

Implementation validation on 2026-09-30 additionally verified live command
copy/pull, no-op push and real edited push of copied images and inline files,
preserved source download URLs and labels, same-site cross-space copies with
attachments/labels, source preservation, title disambiguation, and native
restricted-parent rejection. Copied properties, read restrictions, comments,
and children were absent. The native core TOC extension survived opaque ADF
and real push, and appeared in server-rendered view metadata. Disposable pages
were trashed and the repository workarea cache was unchanged. Sanitized results
are in `tests/fixtures/page_copy/implementation-results.json`.

An isolated Firefox rendering of `body.view` is not a signed-in Confluence
browser test: interactive attachment cards and macro components require the
Confluence frontend. Signed-in rendering and third-party app macros remain
unverified. Preservation of ADF is not a guarantee that an app depending on
excluded properties/custom content will render correctly.

## Current limitations

The following situations are refused with an error that explains what to do:

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

For the commands listed above, references only resolve to pages in the
workarea's tree: the root page and its
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
    version
    root
    cache/
      123456.json
      123457.json
  <root-page-title>_<root-page-id>/
    content.md
    _attachments/
      <attachment filename>
    <child-page-title>_<child-page-id>/
      content.md
      _attachments/
```

`content.md` contains GitHub Flavored Markdown (GFM); `_attachments` contains
downloaded attachment files. Each setting in `.cflsync` is one file, named
after the setting and containing its value as one line.
`.cflsync/profile` selects the credential profile. `.cflsync/version` holds the
workarea version, `3`, as one numeric line. `.cflsync/root` holds the root page
ID as one numeric line.
`.cflsync/cache/<page-id>.json` is private synchronization state, not page
content.

A page directory's managed entries are `content.md`, `_attachments/`, and the
directories of its cached child pages. A subdirectory is a child page only if
the cache records it as one; all other entries are unmanaged. Unmanaged entries
move with their page directory and are deleted with it, but cflsync never
deletes a directory that has no cache state on its own.

The page directory name is a deterministic filesystem-safe encoding of the
remote title, normalized to Unicode NFC. Non-ASCII characters are kept as they
are, unless they do not print, such as zero-width or non-breaking spaces. ASCII
characters other than letters, digits, space, `-`, `_`, and `~` are
percent-encoded, `.` always as `%2E`, so that no title can produce `.`, `..`,
or the name `content.md`. A leading `_` is also encoded, as `%5F`, so that
names starting with `_`, such as `_attachments`, stay reserved for cflsync.
Trailing spaces are encoded as `%20`, and Windows device names such as `CON`
are escaped.

Every page directory name, including the root page's, ends in `_` and the
page ID, as in `Release notes_123456`; the encoded title comes first. A name
has at most 64 characters, and at most 255 UTF-8 bytes, including the suffix.
A longer title is cut between characters, never inside an escape, to make room
for the full suffix, and a space left at the end of the cut is dropped. A title
that itself ends in `_` and digits, such as `Beta_300` for page 400, gets the
suffix as well: `Beta_300_400`.

Because page IDs are unique, sibling names never clash, also when compared
case-insensitively and after NFC normalization, and a name depends only on the
page's title and ID, not on its siblings or on history. The page ID can be read
back from a directory name: it is the digits after the last `_`. A cache entry
whose directory name does not end in its own page ID is invalid.

The cache's page ID and directory name are authoritative; after a remote rename
not yet pulled, the cached name still reflects the old title. A pull moves a
page directory only if its target is unused; otherwise it stops without
overwriting data. An unmanaged entry with the same name as a page's directory
makes the page fail, and the entry is left untouched.

On Windows, a page directory cannot be renamed, moved, or removed when cflsync
is running from inside it. The command stops before mutation and asks the user
to run it from the workarea or another directory before retrying.

cflsync does not limit path lengths itself. When the operating system rejects a
path as too long (`ENAMETOOLONG`, or Windows error 206), the command reports the
path and its length, and the failed page installation leaves local state
unchanged. On Windows, paths are limited to 260 characters unless long path
support is enabled; see the README.

Attachments use relative Markdown URLs:

```markdown
![Diagram](_attachments/diagram.png)
[Download spreadsheet](_attachments/report.xlsx)
```

ADF-to-GFM conversion rewrites resolved media and links to these paths. The
filename is percent-encoded as page-link path segments are, so a name with
spaces or parentheses stays a valid Markdown link:
`![Pasted](_attachments/Pasted%20image%201.png)`. Reverse conversion decodes
the path; a path that does not decode to a managed filename is looked up as
written, which accepts the unencoded paths of releases before 0.5.3. The
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

## Page links

Page links are ADF `link` marks whose target is a page of the managed tree,
and the local Markdown links that represent them. They are converted inside
the existing converter link handlers, through a `workarea.LinkResolver` that
the synchronization supplies (see [MAPPING.md](MAPPING.md#page-links)).

**Membership.** A page is in the tree if it is the root page, or if the root
page is in its ancestor chain and every ancestor below the root is a page. A
page that is deleted, trashed, moved outside the root, or not visible with the
profile's credentials (HTTP 403 or 404) is not in the tree, whether or not a
local copy or cache entry remains. A trashed page is reported by
`GET /pages/{id}` with status `trashed`, no parent, and no ancestors.

**Pull.** For every page that pull installs or updates, each link to a page in
the tree becomes a relative link from that page's `content.md` to the target's
`content.md`. A link qualifies when it is an absolute `https` URL on the
configured host and default port, or a site-root-relative URL starting with
`/wiki/`, with one of these routes:

- `/wiki/spaces/<any>/pages/<id>`, optionally followed by a title slug, without
  a query. The page ID identifies the page; the space segment and the slug are
  ignored. Confluence adds the slug to stored links that carry a fragment.
- `/wiki/pages/viewpage.action?pageId=<id>`, with no other query parameter.
- `/wiki/display/<space key>/<title>`, without a query, for a title in the
  tree's space. Space key and title match ignoring case. The title is
  percent-decoded and looked up first with `+` kept, then with every `+` read
  as a space, which reproduces the observed Confluence resolution.

Every other link is kept: other hosts, `http`, other ports, other query
parameters (comment, version, and diff links), edit and history routes, short
links (`/wiki/x/<code>`), REST URLs, and links to pages outside the tree. The
target path is the target's cached directory, or for a page that is not
installed, the cached directory of its nearest installed ancestor followed by
the directory name of each uninstalled page below it. A target inside the
directory of a page that the pull is moving resolves inside its new directory.
Path segments are percent-encoded. A link to the page itself becomes
`#<fragment>`, or `content.md` without a fragment.

**Push.** A local link is a page link when it is a relative reference without
scheme, authority, or query, not starting with `/` or `#`, that resolves
against the referring `content.md` to `content.md` in a directory whose name
ends in `_<digits>` inside the workarea. The digits are the page ID; the rest
of the path need not match the target's current location, so links left
behind by renames and moves still name the right page. A page link to a page
in the tree becomes `https://<host>/wiki/spaces/<space key>/pages/<id>`, with
the fragment appended. All other local links, including `../notes.md`,
directory links, and fragment-only links, are pushed unchanged. Before any
remote change, including attachment uploads, push converts the page once
without side effects; if it has page links to pages that are not in the tree,
it refuses the page:

```text
page '<id>' has broken page links; nothing was pushed:
  <workarea-relative path of content.md>: [<link text>](<href>)
```

with one line per such link, in document order. The link text is empty when
it carries formatting. Repository push reports a refused page as failed and
continues with the other pages.

**Fragments.** The text after `#` is copied byte for byte in both directions.
Confluence's heading anchors and the GitHub-style anchors of Markdown previews
differ, so a fragment navigates only where its exact text matches that
environment's anchor; no translation is attempted.

**Smart Links.** `inlineCard`, `blockCard`, and `embedCard` nodes are not page
links. They remain retained ADF, as does an ordinary link in the same block,
and push never creates them.

**Written pages only.** Links are generated only in the pages that a command
writes from their remote version. `page rename`, `page move`, and pull do not
rewrite links in any other file, so a link can become stale for local
navigation after a rename or move; push still resolves it by page ID, and the
next pull that writes the referring page makes it current. Converting links
never changes the content hash or the synchronization state of other pages.
Caveat: within one repository pull, a page converted before another page is
relocated by a remote rename or move in the same pull links to that page's
previous directory.

**Lookups.** Repository commands list the full subtree once, as for their
status comparison, and resolve every link from that listing. Page commands
look up only what their links need: each target with `GET /pages/{id}` and
`GET /pages/{id}/ancestors`, each uninstalled ancestor's title with
`GET /pages/{id}`, title links with `GET /pages?title=...&space-id=...`, and
the space key once with `GET /spaces/{id}`. Every page is looked up at most
once per command.

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
or directories. Format 3 is:

```json
{
  "format": 3,
  "page": {
    "id": "123457",
    "title": "Example page",
    "parent_id": "123456",
    "directory": "Example page_123457",
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
a second page without a parent makes the cache invalid. Format-1 and format-2
entries, written by cflsync 0.4 or earlier, are refused with the transition
instructions; their JSON structure equals format 3, but format 3 belongs to
workarea version 3.

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

`page remove` resolves only local managed state. It lists the page's remote
descendants, which fails on a folder below the page, and looks up each cached
descendant missing from that list to tell a removed page from a moved one. The
confirmation comes after all checks and before any deletion. Each page's remote
deletion precedes its local removal, so a remote failure leaves that page's
local directory and cache intact.

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

### Page states

`pull`, `push`, `status`, and `page remove` compare remote pages with the cache
and classify each page by combining its local and remote change:

| State | Meaning | `status` label |
| --- | --- | --- |
| `absent-local` | Remote page present, but no cache state or no local directory | not in local |
| `absent-remote` | Cached page absent from the tree (deleted, inaccessible, or moved outside the root); its local copy is unchanged or missing | remote removed |
| `conflict-absent-remote` | Cached page absent from the tree; its local copy changed | remote removed, local changed |
| `remote-changed` | Changed remotely only, including a remote rename or move | remote changed |
| `local-changed` | Changed locally only | local changed |
| `conflict` | Changed on both sides | conflict |
| `unchanged` | Unchanged on both sides | unchanged |

`conflict-absent-remote` is a conflict too, but a separate state, because every
command resolves `conflict` by assuming that the remote page exists. Push skips
it; pull without `--delete` keeps it; `pull --delete` and `page remove` delete
it only with `--force`.

### Failure model

- **Structural failures** make the tree's boundary unknown: an inaccessible
  root, an incomplete listing, non-page content inside the tree, or an invalid
  cache. They stop the command before any change, and an incomplete listing is
  never interpreted as a remote deletion.
- **Checks before execution.** A repository command and `page remove` perform
  every check before they change anything: conflicts (which abort unless
  `--force` is given), terminal availability, and confirmation. A failed check
  or a declined prompt leaves the workarea and Confluence untouched.
- **Per-page failures** during execution are reported; repository commands
  continue with the other pages and block the pages below a failed one, and
  exit non-zero if any page failed. `page remove` stops at its first failure.
- **Atomicity.** Remote and local work cannot form one transaction. Each page
  is installed atomically and its state persisted immediately; deletions remove
  children before parents, and a page's directory before its cache entry. An
  interrupted command leaves a valid cache, and running it again completes it.
- **Deletion.** Local deletions never propagate to Confluence. `page remove` is
  the only command that deletes remote pages; remote deletions reach the
  workarea only through `pull --delete`.

## Content hierarchy requests

The API client lists a page's ancestors, which page references and ancestor
installation use to check that a page is in the workarea's tree, and its
direct children, from which it lists all page descendants for the repository
commands and `page remove`. Their behaviour was verified against
Confluence Cloud:

- `GET /pages/{id}/ancestors` returns `id` and `type`, without titles, for
  every ancestor, highest first. Non-page ancestors such as folders are included. A response
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
- `GET /pages?title=...&space-id=...` matches titles ignoring case.
  `APIClient.find_pages_by_title` keeps only exact matches unless asked to keep
  all of them, as page-link title lookups do.
- `GET /spaces/{id}` returns the space's `key`, which browser page URLs use;
  page responses report only the numeric `spaceId`. This endpoint is taken
  from the API reference and was not exercised against a live site.
