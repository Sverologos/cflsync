# Roadmap

Each section describes one feature idea. Implementation steps are included when
they are known.

## Scoped API tokens

### Summary

Allow profiles to use scoped Atlassian API tokens, including read-only tokens
for `pull` and `status`. Classic tokens must continue to work. Commands that
need permissions missing from a scoped token should report the required
permission clearly. This changes credential configuration, not the workarea
format.

### Implementation steps

1. Handle HTTP 401 responses with `OAuth` or `Basic` challenges as `APIError`
   instead of an uncaught exception. For an `OAuth` challenge, suggest checking
   whether the token needs a scoped-token profile.
2. Verify the scoped-token gateway against Atlassian documentation and a real
   site. Confirm the cloud ID lookup, v1 and v2 API URLs, attachment downloads,
   pagination and download-link resolution, and the scopes required by each
   command. Record the results in [SPEC.md](SPEC.md).
3. Add an optional `cloud_id` to profiles. Route profiles with a cloud ID
   through the gateway while keeping existing site-URL profiles compatible.
   Update `auth` to configure scoped tokens and `auth --list` to identify
   gateway profiles. Report missing-scope errors with the affected operation.
4. Document scoped-token setup and read-only and full-use scopes in the README
   and [SPEC.md](SPEC.md). Test both token types, gateway URL construction,
   authentication failures, and permission errors.

The feature is complete when all commands work with classic tokens and scoped
tokens carrying the documented scopes, while read-only scoped tokens support
`pull` and `status` and produce clear permission errors for other commands.

## Page-link resolution

### Summary

On pull, rewrite links to managed Confluence pages as relative links to their
local `content.md` files when those pages have local copies. On push, resolve
those local links back to Confluence page links using the target page IDs.
Leave links to pages without local copies and unrelated URLs unchanged.
Renaming or moving a page must not leave links to its local copy broken.

### Implementation steps

1. Identify Confluence page links by page ID and resolve them against the
   workarea's cached page tree and existing local files. Preserve link text,
   fragments, and other URL components where applicable.
2. Generate relative Markdown links on pull, including when the target page is
   installed later in the same repository pull. Update affected links when a
   page's local path changes.
3. Resolve local page links through the cached page tree on push and emit
   Confluence links to the corresponding page IDs. Keep unresolved or unrelated
   links as ordinary links.
4. Test pull and push round trips, missing local targets, links within and
   outside the managed tree, and page renames or moves. Ensure link rewriting
   does not create spurious local-change or conflict reports.

## Folder support

### Summary

Support Confluence folders anywhere in the managed tree, including as its root.
A workarea may be anchored to a page or a folder, and folders may contain pages
and nested folders. Mirror each managed folder as a local directory. Repository
and page commands must traverse folders without treating pages below them as
absent. Distinguish managed folders from unrelated local directories; other
Confluence content types remain unsupported.

### Implementation steps

1. Verify the Confluence folder APIs and define the supported folder operations,
   including creation, rename, move, and removal.
2. Allow `init` to anchor a workarea at a page or folder. Extend root state,
   remote discovery, scope checks, and cached tree state to record page and
   folder types. Define a compatible migration for existing workareas.
3. Install and relocate folder directories with their descendants. Include
   folders in `pull`, `push`, and `status`, and allow page commands to resolve
   parents and descendants through folders. Require explicit managed state
   before changing or deleting a local directory.
4. Test page and folder roots, mixed page-and-folder trees, nested folders,
   name clashes, moves, partial failures, and deletion. An incomplete folder
   listing must fail before it can be mistaken for remote deletion.
