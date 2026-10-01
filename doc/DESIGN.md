# cflsync: page tree synchronization design

## Scope

A workarea manages one Confluence Cloud page tree: a single anchored root page
and all of its descendant pages. Local page directories mirror the page
hierarchy. The `.cflsync` directory is at the workarea root, separate from
managed page content. The command, storage, and synchronization contracts are
specified in [SPEC.md](SPEC.md); this document records the design and its
rationale.

Out of scope:

- Multiple roots per workarea (a managed forest). The single-root design keeps
  an upgrade path open.
- Folders and other non-page content. Every item in the managed tree must be a
  page.
- A combined `sync` command.
- Automatic upgrade of version-1 (loose-page) workareas with cached pages.

## Ownership and the root boundary

A workarea owns exactly one immutable Confluence root page ID, recorded in
`.cflsync/root`, and every page below it. A page is in scope if it is the root,
or the root is among its remote ancestors. The workarea does not own the root's
ancestors, pages outside the tree, or local directories that happen to exist in
the workarea. The anchor is an ownership boundary, not only a traversal
starting point: it is what makes repository-wide and destructive operations
safe, because every page an operation touches is provably below the root.

Only `page copy` may read an external source on the configured site; its new
page and destination parent remain inside the root boundary. Other commands
do not cross that boundary. Copy checks current ancestry even for cached
references and requires a synchronized in-tree source before installation.
Normal pull writes the copy's own baseline, without a cache schema change or
separate remote inventory. Recovery pulls a known new ID rather than repeating
copy, which would create another page.

Local references (a `content.md` file, a
page directory, a cached page ID) are checked against the cache, which records
only in-scope pages. Remote-only references are checked with one page-ancestors
request. A narrow check-then-update race remains, in which a target moves out of
the tree between the check and the update; it is accepted.

The root page ID is the identifier because titles and paths change. The valid
presence of `.cflsync/root` is also the repository-format discriminator: a
workarea without it is a version-1 workarea, which is refused rather than
interpreted with mixed semantics.

## Local representation

The cache, not a directory scan or a path reconstructed from titles, is the
authoritative local location of a page. Each cache entry stores the page's
cached parent and its own directory name, relative to that parent; a page's
path is the chain of names up to the root. Consequences:

- A subdirectory is a child page only if the cache records it as one; any other
  entry is unmanaged. Unmanaged entries move with their page directory and are
  deleted with it, but a directory without cache state is never deleted on its
  own.
- Renaming or moving a page, with its whole subtree, is one directory rename
  plus one cache write for the page itself. Descendants' entries are unaffected,
  so there is no window in which their cached paths are stale.
- The chain must be complete: every cached page except the root has a cached
  parent. Nesting requires it (a page is only installed below a local parent,
  which is why page commands pull missing ancestors), and every deletion
  removes children before parents. A broken chain is a structural error.

The content file is `content.md`, not `page.md`, in preparation for other
content types. The `_` prefix of directory names is reserved for cflsync
entries such as `_attachments`.

### Directory names

A directory name is derived from the title, and kept readable: printable
non-ASCII characters are kept as they are, and only characters that are unsafe
or reserved on some supported platform are escaped. Names are compared
case-insensitively and after NFC normalization, since some filesystems store
names decomposed.

Names are capped at 64 characters, including the page-ID suffix. The cap
bounds every name well below the per-name filesystem limit, which a single long
non-Latin title could otherwise exceed at any depth, and 97% of the titles of a
measured 2,685-page production tree fit within it unchanged. It does not bound
path length, which is dominated by depth.

Every name ends in `_` and the page ID. A page's local path is then a function
of its own title and ID and those of its ancestors: it does not depend on
siblings, installation order, how much of the tree a command discovered, or
naming history. This lets page links point to pages that are not installed yet,
at the path where a later pull installs them, and lets push recover the page ID
from a link's path even after the target was renamed or moved. Sibling clashes,
and the bookkeeping they need, disappear. The cost is readability: every
directory name carries an ID. Suffixing only on a clash was rejected because
the resulting paths depend on history and cannot be computed for pages not yet
pulled; suffixing only on a clash with a remote sibling was rejected because a
new remote sibling would then rename an existing directory.

### Path length

Nesting adds one path component per level, so deep trees reach the Windows
260-character path limit. cflsync does not compute or limit path lengths
itself: the effective limit depends on the operating system, its configuration,
and the filesystem, and only the operating system knows it. It relies on the
failing operation instead, and reports the path and its length. The user
documentation describes Windows long path support and Git's `core.longpaths`.

## Synchronization model

Change detection classifies each side of a page independently against its
cached state. `PageChangeDetector.local_status` compares canonical GFM and
managed attachment hashes; `remote_status` compares the page version, title,
and attachment manifest. Each returns a `PageChangeStatus`: absent, changed, or
unchanged.

Repository commands (`pull`, `push`, `status`) build one comparison of the
complete remote tree with the cache, a `TreeStatus`: one `PageStatus` per page
in the union of both, combining the two sides into a `PageStatusState`, sorted
parents before children. `status` renders it; `pull` and `push` map a page
operation over it (`RepositoryPullOperation`, `RepositoryPushOperation`), so the
state alone determines what happens to a page. `page remove` builds the same
comparison for one subtree (`PageRemoveOperation`).

A page removed remotely and changed locally is a conflict, but it has its own
state, `conflict-absent-remote`, rather than `conflict`: every operation
resolves `conflict` by assuming that the remote page exists, so a pull would
fetch a missing page and a push would recreate one.

Discovery is complete or fails. A failed or truncated listing, a permission
failure, or non-page content in the tree stops the command, and is never read
as a remote deletion; skipping a folder would silently drop the pages below it.

Every repository operation first compares, then checks, and only then
executes. The conflict check, terminal availability, and any confirmation all
run before the first change, so a refusal or a declined prompt leaves the
workarea and Confluence untouched. During execution, a per-page failure is
reported and the command continues, blocking only the pages below the failed
one.

Remote and local work cannot form one transaction. Each page is installed
atomically and its state persisted immediately; deletions run children first
and remove the directory before the cache entry. An interrupted command
therefore always leaves a valid cache. Synchronization can be resumed; a
partially installed copy is recovered by pulling its created ID.
Local deletions never propagate to Confluence: `page remove` is the only
command that deletes remote pages, and remote deletions reach the workarea only
through `pull --delete`.

The core of each page operation (`PagePullOperation`, `PagePushOperation`) lives
in `sync.py`, which links the remote API (`api.py`) with the local workarea
(`workarea.py`). The CLI only resolves arguments, confirms, and reports.

## Implementation constraints

Minimize external dependencies. Prefer the Python standard library whenever it
provides the required capability: use `urllib` for HTTP, `json` for JSON,
`pathlib` and `tempfile` for filesystem operations, `hashlib` for content
hashes, and `unittest` for tests unless an external dependency provides a
clear, necessary capability that the standard library lacks.

Use `uv` for all Python dependency management. Add or change dependencies via
`uv`, record declared runtime dependencies in `pyproject.toml`, and commit the
corresponding `uv.lock` update. Do not install unmanaged project dependencies
with `pip` or rely on globally installed Python packages. Pandoc is an
external executable prerequisite, not a Python package dependency.

`tzlocal` resolves the machine's IANA time-zone name across supported
platforms. `tzdata` supplies the IANA database for the embedded Windows
runtime, where the operating system does not provide it to `zoneinfo`.

Prefer small, module-level classes with shallow inheritance. Use duck typing
for internal collaborations when a formal abstraction adds no behavioral
guarantee. Add type annotations for public contracts and non-obvious data
shapes; avoid elaborate generic, protocol, or class hierarchies without a
concrete interoperability need.

Separate every conditional or loop block from a following statement at the
same indentation with a blank line. Avoid conditional expressions for returns.

## Conversion strategy

Page bodies use `atlas_doc_format` as the Confluence transport format. The
conversion boundary is:

```text
atlas_doc_format ⇄ Pandoc AST ⇄ GFM
```

Pandoc provides the GFM reader and writer. The Python implementation exposes
`ADFToMarkdownConverter` and `MarkdownToADFConverter`, using Pandoc's JSON
AST internally. The current Markdown dialect is GFM. The converters have no
cache, remote-page, or workspace state.

On pull, the ADF body becomes canonical GFM for `content.md`. On push, `content.md`
becomes ADF for the versioned API update. The synchronization operations own
cache state, staging, attachment resolution, and concurrent-edit handling.
Change detection is a separate concern: `PageChangeDetector` compares local
files, cached state, and remote metadata, and pull, status, and push interpret
its results through the decision tables in `SPEC.md`.

`PandocRunner` invokes a pinned compatible Pandoc binary through argument
lists rather than a shell and verifies the expected Pandoc JSON API version.
`MediaResolver` is supplied by the synchronization operations. It maps ADF
media identifiers to the managed attachment IDs and local `_attachments/`
paths recorded in the page cache. It has no API, filesystem, or cache access;
the caller supplies an attachment manifest as `(filename, ID)` pairs.

Conversion is intentionally lossy. Supported nodes become readable GFM using
the fields needed by their mapping; unrelated metadata, extra attributes, and
unsupported formatting marks are ignored. Underline uses raw HTML `<u>` inline
pairs because GFM has no underline syntax. Required values and content shapes
are still checked at the ADF input boundary.

Unsupported structures, such as macros, are retained as `atlas_doc_format`
fenced blocks containing complete original ADF-node JSON. Tables convert
instead: Pandoc writes a pipe table where GFM allows one and an HTML table
otherwise, keeping spans and multi-block cells at the cost of one extra Pandoc
invocation when reading such a table back. For
unsupported inline nodes, the smallest enclosing ADF block is retained so the
fence remains valid GFM. Retained JSON is not normalized or stripped of metadata.
Malformed or contextually invalid retained JSON stops reverse conversion.

The full mapping, opaque-marker format, and required conversion tests are in
[MAPPING.md](MAPPING.md).

## Alternatives considered

- **Recursive loose pages:** the smallest change from the loose-page model, but
  without repository-wide ownership, a move can drop pages out of a traversal.
- **Managed forest (several roots):** more flexible, but adds root lifecycle
  commands and collision rules that one root does not need. It remains a
  possible extension.
- **Roots inferred from local directories:** no root record needed, but stale
  cache entries and local deletions make the boundary ambiguous, which rules
  out destructive operations.
- **`<Title>/_children/<Child>/` layout:** separates pages from user files by
  structure, but produces deeper paths and an extra navigation level.
- **Flat `<Root>_<Child>/` layout:** every internal move or rename cascades into
  renames of all descendant directories, the separator is ambiguous, and the
  per-name limit is reached quickly.
- **Full paths in the cache:** a subtree relocation would have to rewrite every
  descendant's entry after one rename, leaving stale paths after an
  interruption, or require a journal.
- **Suffixes only on a sibling clash:** readable names in the common case, but
  either history-dependent (stable suffixes) or renamed by unrelated remote
  events (recomputed suffixes); neither yields paths computable from a page
  reference.
- **ID-only directory names:** renames would never move a directory, but names
  are unreadable.
- **Precomputed path-length limits:** a fixed limit cannot match every system
  configuration; the operating system is the only reliable judge.

## Deferred functionality

- Page-link resolution.
- Automatic three-way merge or conflict markers.
- Arbitrary Confluence macros and unsupported ADF constructs.
- Attachment rename tracking beyond delete-and-upload semantics.
- Bidirectional synchronization of page metadata other than title, parent, and
  body.
