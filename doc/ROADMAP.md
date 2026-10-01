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

Implemented. Links to pages in the managed tree become relative links to their
local `content.md` files on pull, whether or not those pages are pulled, and
local links back to page links on push; see [SPEC.md](SPEC.md#page-links).
Links are only rewritten in pages that a command writes, so links in other
pages can go stale after a rename or move; push still resolves them by page ID.

Possible follow-up work:

- Within one repository pull, resolve links against the locations pages will
  have after the pull, so a page converted before another page's relocation
  does not link to its previous directory.
- An explicit command, or an option on `page move`, that rewrites stale local
  links through the converters.

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

