# cflsync

`cflsync` is a command-line tool for synchronizing Confluence Cloud pages with
local GitHub Flavored Markdown (GFM) page directories and their attachments.
The goal is local authoring of wiki pages in markdown format, using Confluence
as publishing platform rather than authoring environment.

## Installation

### Windows

Install from a [scoop](https://scoop.sh) bucket:

```console
scoop bucket add sverologos https://github.com/sverologos/scoop
scoop install cflsync
```

The package bundles CPython and installs Pandoc as a Scoop dependency, so no
separate Python installation is required.

### Other operating systems (Linux, MacOS...)

Install using [uv](https://docs.astral.sh/uv/).

Install `cflsync` as a standalone command in its own environment:

```console
uv tool install git+https://github.com/sverologos/cflsync
```

From a local checkout, `uv tool install .` does the same. Either way the
`cflsync` executable lands on `PATH`; Pandoc is not bundled and must be
installed separately. Without installing, the same interface is available from
a checkout as `uv run python -m cflsync`.

## Commands:

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

`PAGE_REF` may be a numeric Confluence page ID, an exact page title, a managed
local `content.md` file, or a managed page directory.

### Getting started

A workarea manages one Confluence page tree: a root page and the pages below
it. `init ROOT_PAGE_REF` anchors a new workarea at its root page, given as a
page ID or exact title; it contacts Confluence with the profile's credentials,
but does not pull any page. After a successful init, pull the whole tree, or
any single page in it; cflsync pulls missing ancestor pages first:

```console
cflsync auth
mkdir handbook && cd handbook
cflsync init "Team handbook"
cflsync pull
```

Each page is a directory containing the page content in `content.md`, its
attachments in `_attachments/`, and any child pages in subdirectories. Each
directory name is the page title followed by the page ID, as in
`Release notes_123456`, so pages with the same title never clash.

### Upgrading from cflsync 0.3

Workareas created by cflsync 0.3 follow a 'loose collection of pages' model
rather than the 'managed subtree' approach used by cflsync 0.4 and later. The
consequence is that pre-cflsync 0.4 workspaces cannot be managed by cflsync
0.4. To migrate a workarea:

1. Push any local changes with the cflsync version that created it.
2. Create a new workarea in an empty directory with `cflsync init ROOT_PAGE_REF`.
3. Pull any pages needed from the tree; cflsync installs missing ancestors.

Unmanaged files in old page directories are not carried over; copy them into
the new page directories if needed.

### Upgrading from cflsync 0.4

cflsync 0.5 changes the encoding of page directory names. On its next pull,
each page whose title contains non-ASCII characters or whose old directory name
is over 64 characters is renamed, together with its child pages and unmanaged
files. Push local changes first, or commit the workarea to version control, so
the moves can be reviewed.

### Dates written by cflsync 0.5.3 and earlier

Dates are now written as `<time datetime="YYYY-MM-DD">April 1, 2026</time>`,
the calendar date that Confluence stores as UTC midnight. cflsync 0.5.3 and
earlier wrote `<span cfl-type="date">2026-04-01[Europe/Brussels]</span>` and
pushed the local midnight of that date, which changes the stored timestamp, and
outside UTC can show a different day in Confluence. Push now rejects those spans:

1. In pages with local changes, rewrite each date span as a `<time>` element
   with the intended date, then push.
2. Run `cflsync pull --force` to rewrite all other pages in the new form; a
   normal pull rewrites only pages that changed remotely. `--force` overwrites
   local changes, so run it only after step 1.

### Statuses and panels written by cflsync 0.5.6 and earlier

Status lozenges are now written in the Atlassian `twg` CLI's form,
`<span data-type="status" data-color="green" data-status-style="bold">Done</span>`.
Push rejects the status spans of cflsync 0.5.6 and earlier,
`<span cfl-type="status" style="background-color: green">Done</span>`. GitHub
alerts now map one to one to panel types (`[!NOTE]` is an info panel, `[!TIP]`
a success panel), and other panels are written as `<div data-type="panel-…">`;
alerts written earlier still push, with the new mapping.

1. In pages with local changes, rewrite each status span in the new form, then
   push.
2. Run `cflsync pull --force` to rewrite all other pages in the new forms;
   `--force` overwrites local changes, so run it only after step 1.

### Upgrading workareas created by cflsync 0.4

This version of cflsync uses workarea version 3, recorded in
`.cflsync/version`, and cache format 3. It refuses workareas created by cflsync
0.4 or earlier, and cflsync 0.4 refuses version-3 workareas once they contain
pulled pages. To move a workarea:

1. Push any local changes with the cflsync version that created it.
2. Create a new workarea in an empty directory with `cflsync init ROOT_PAGE_REF`.
3. Pull the tree, or the pages needed from it.

Unmanaged files in old page directories are not carried over; copy them into
the new page directories if needed. An old workarea that has no pulled pages
can instead be re-anchored in place with `cflsync init ROOT_PAGE_REF`.

cflsync 0.4 does not recognize a new workarea before its first pull. Do not use
cflsync 0.4 in a new workarea: if it pulls into one, this version refuses the
workarea afterwards, and it must be created again.

### Working with pages

Pull reports when the page is already in sync. Use `page pull --force PAGE_REF`
to prefer remote content, overwriting local edits to managed files even when
the remote version is unchanged. Unmanaged files are preserved.

Push reports when there is nothing to upload, and refuses to overwrite remote
changes. Use `page push --force PAGE_REF` to prefer local content. The first
heading of `content.md` is the page title and cannot be edited; push does not
rename pages. Use `page rename PAGE_REF TITLE` to change the remote title,
generated heading, and title-derived local directory as one explicit operation.

Use `pull` to bring the complete remote page tree into the workarea. It pulls
pages that changed remotely or are missing locally, parents first, moves
directories after remote renames and moves, and reports each result and a
summary. Without `--force`, any conflict aborts the command before a page is
pulled, and locally changed pages are skipped. `pull --force` also overwrites
local changes. Pages no longer in the tree are reported but kept locally;
`pull --delete` deletes their local copies after asking for confirmation, which
`--force` skips. With `--delete`, a page removed remotely whose local copy
changed is a conflict. Nothing is ever deleted in Confluence by `pull`.

Use `push` to compare the complete remote page tree with the local cache and
apply page pushes parents before children. It pushes locally changed pages and
reports each result and a summary. Without `--force`, any conflict aborts the
command before a page is pushed. `push --force` also uploads conflicting and
unchanged pages, preferring local content. Remote-only changes and pages absent
on either side are skipped; recreate a remotely absent page with `page create`.

Use `status` to compare the complete remote page tree with the local cache
without changing anything. It lists every page as `not in local`, `remote
removed`, `remote changed`, `local changed`, `conflict`, or `unchanged`,
followed by a summary.

Local page directories mirror the page hierarchy below the root page: each
child page's directory is inside its parent's directory. `page pull` can target
any page in the tree; it installs missing ancestors top-down and prints one
`Pulled parent 'TITLE' (ID) to PATH` line for each. When a page is renamed or
moved remotely, the next `page pull` installs a missing new-parent chain first,
then moves its directory together with its child pages.

`page create PARENT_PAGE_REF TITLE` similarly installs the parent and any
missing ancestors before creating the remote child page.

`page copy SOURCE_PAGE_REF NEW_TITLE` creates one page from the remote source,
including current attachments and labels, then pulls it immediately. Sources
inside the workarea must already be synchronized; synchronize local/remote
changes first. Source lookup prefers workarea matches, and ambiguity is an
error. External sources may be in another space on the configured site.

```console
cflsync page copy "Source page" "Copy of source"
cflsync page copy --parent "Destination page" "Source page" "New title"
cflsync page copy --parent ROOT_PAGE_ID ROOT_PAGE_ID "Root copy"
cflsync page copy --parent "Destination page" EXTERNAL_PAGE_ID "Shared template copy"
```

The destination must currently be a page inside the managed tree. An external
source or the root requires `--parent`; other copies default to the source's
current parent. Copying under the source or one of its in-tree descendants is
allowed. Managed directories and `content.md` paths still select page identity,
not content to upload. Confluence chooses title disambiguation and enforces
copy permissions; success reports the actual title, new ID, and local path.

This copies no descendants, comments, history, unmanaged local files, source
restrictions, content properties, or app-owned custom content. Labels remain
remote metadata, without a local label synchronization baseline. Structured
owned media resolves to copied attachments, but ordinary download URLs, Smart
Links, version parameters, and foreign-page media remain unchanged and may
depend on source access. App macros can depend on excluded metadata. Folder,
cross-site, recursive, force, and native-template operations are unsupported.

If creation succeeds but local pull fails, the error identifies the new ID and
the recovery command, for example `cflsync page pull 123456`. Resolve the local
clash, access problem, or other reported cause, then pull that ID. The remote
copy and installed ancestors remain. If the creation response is lost or
unusable, the outcome is uncertain; inspect Confluence before repeating copy,
because another invocation may create another page. Mutations are not retried.

Use `page move PAGE_REF NEW_PARENT_REF` to move a synchronized page, with its
child pages, below another page in the same Confluence space. The new parent
and any missing ancestors are installed before the remote move; if Confluence
rejects that move, those installed pages remain. The page directory then moves
into the new parent's directory. The root page cannot be moved.

Use `page remove PAGE_REF` to delete a managed page and all pages below it,
remotely and locally. It lists the pages and asks for confirmation unless
`--force` is supplied; every page must be in sync. Pages already removed
remotely lose only their local copy; if such a page has local changes, only
`--force` removes it. Removing the root page removes the whole tree and leaves
an empty workarea.

Run `init ROOT_PAGE_REF` at the root of an empty workarea, one without cached
pages, to re-anchor it at another root page, for example after removing the
root page, or when a workarea was anchored at the wrong page and not pulled yet.
An empty workarea created by cflsync 0.3 is converted the same way.

Use `cflsync --help` for top-level help, `cflsync page --help` for page-command
help, and `cflsync page COMMAND --help` for a command's arguments.

### Page links

Links between pages of the managed tree become ordinary relative Markdown links
between their `content.md` files, so they work in editors, previews, and Git
hosts. A link from `Root_100/A_200/content.md` to page 300 at `Root_100/B_300`
becomes `../B_300/content.md`; push turns it back into a link to page 300.

- **Pull** converts links to pages in the managed tree, whether or not those
  pages are pulled yet: a link to a page that is not installed points to where
  pulling that page will put it. Recognized are links to the page itself on the
  configured site, by page ID (`/wiki/spaces/KEY/pages/ID/...`,
  `viewpage.action?pageId=ID`) or by title (`/wiki/display/KEY/TITLE`). Links
  to pages outside the tree, links with other query parameters such as comment
  or version links, edit and history links, short links (`/wiki/x/...`), and
  all other URLs stay unchanged.
- **Push** turns local links to pages in the tree back into
  `https://SITE/wiki/spaces/KEY/pages/ID` links. Other local links, such as
  `../notes.md`, are pushed as they are. A page with a local link to a page that
  is no longer in the tree (deleted, moved outside the root, or not visible with
  the profile's credentials) is not pushed; push lists each such link with its
  file, text, and target, and pushes nothing for that page, so the links can be
  corrected first.
- **Fragments** after `#` are copied unchanged in both directions. Confluence
  and Markdown previews name heading anchors differently, so a fragment works
  where its exact text matches that environment's anchor; links to headings may
  work in only one of them.

Limitations:

- Links are only rewritten in pages that a command writes. `page rename`,
  `page move`, and remote renames and moves pulled into the workarea do not
  update links in other pages, so those links can point to an old location.
  They still name the right page: push resolves them by the page ID at the end
  of the directory name. Correct them by editing, for example with an AI agent,
  or let a later pull of the referring page rewrite them.
- During one repository pull, a page converted before another page is moved by
  a remote rename or move in the same pull links to that page's previous
  location, although the page was just written. Push still resolves the link.
- Smart Links (link cards) are not supported: they stay as retained ADF, and
  so do ordinary links in the same paragraph.
- Page commands look up each linked page in Confluence (up to two requests per
  linked page, plus one per uninstalled ancestor), so pages with many links
  take longer to pull and push. Repository commands use the tree listing they
  already make.

### Long paths

Page directory names are derived from page titles and have at most 64
characters, but deep page trees in a deeply located workarea can still produce
long paths. cflsync does not limit path lengths itself: when the operating
system rejects a path as too long, the command fails without changing local
state and reports the path and its length.

On Windows, paths are limited to 260 characters unless long path support is
enabled:

- Enable `LongPathsEnabled` in the registry (Windows 10, version 1607, or
  later), for example with
  `New-ItemProperty -Path HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force`
  in an elevated PowerShell. Applications such as Windows Explorer may still
  not support long paths.
- For Git, set `git config --global core.longpaths true`.

Alternatively, place the workarea in a directory with a short path.

## Prerequisites

- Python 3.11 or later.
- [Pandoc](https://pandoc.org/) for markup conversion.

## Documentation

- [Writing pages](doc/MARKUP.md): supported Markdown for Confluence pages.
- [cflsync-skills](https://github.com/sverologos/cflsync-skills): AI coding agent skills for cflsync.

## Development

### Implementation documentation

- [Design](doc/DESIGN.md): implementation constraints, scope, and architectural
  decisions.
- [Specification](doc/SPEC.md): command behavior, local storage, and
  synchronization rules.
- [Mapping](doc/MAPPING.md): `atlas_doc_format` to Pandoc AST mapping and
  opaque retention strategy.

### Development tooling

Required tooling:

- [uv](https://docs.astral.sh/uv/) manages the development environment and runs project commands.
- [YAPF](https://github.com/google/yapf/) formats Python code through uv's `dev` dependency group.
- [Zuban](https://docs.zubanls.com/) performs static type checking.
- [Coverage.py](https://coverage.readthedocs.io/) measures test coverage through uv's `dev` dependency group.

YAPF is configured to align closely with PEP-8 style. Apply formatting before
committing changes:

```console
uv run --group dev python -m yapf --recursive --in-place cflsync tests packaging/scripts
```

Check formatting without modifying files:

```console
uv run --group dev python -m yapf --recursive --diff cflsync tests packaging/scripts
```

Check the application and test sources with Zuban:

```console
zuban check cflsync tests
```

Build the self-contained zipapp distribution artifact:

```console
uv run python packaging/scripts/build_zipapp.py
```

### Testing

Run the complete test suite with:

```console
uv run python -m unittest discover -s tests -v
```

The automated suite uses only local filesystem fixtures and recorded HTTP
transports. Importing the `tests` package blocks address resolution and socket
connections, so an accidental live request fails instead of reaching a real
site.

Measure line and branch coverage of the `cflsync` package while running the
suite, then report it per module with the missed lines:

```console
uv run --group dev coverage run -m unittest discover -s tests
uv run --group dev coverage report
```

`uv run --group dev coverage html` writes a browsable report to `htmlcov/`.
Coverage data (`.coverage`) and `htmlcov/` are ignored by Git.

## License

Copyright (c) 2026 Sverologos BV.

This project is licensed under the [Mozilla Public License 2.0](LICENSE.md).
