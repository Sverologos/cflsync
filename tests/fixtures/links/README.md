# Page-link fixtures

Observations for page-link resolution (STEPS.md, step 3), collected on
2026-10-01 against a Confluence Cloud site with API-token basic
authentication. All requests stayed within the subtree of the configured
workarea root. The site hostname, space key and ID, page IDs, short-link
codes, and the root title are replaced consistently; personal fields are
removed. The pages used:

| ID  | Page                                       | Notes                                   |
| --- | ------------------------------------------ | --------------------------------------- |
| 100 | Root page                                  | workarea root, below folder 30          |
| 110 | existing page                              | holds an editor-created link            |
| 200 | `cflsync link fixtures`                    | created for these fixtures, below 100   |
| 300 | `cflsync fixture target A+B & 50% Ünïcode` | link target with test headings, below 200 |
| 400 | `cflsync fixture trashed`                  | created below 200, then moved to trash  |

Pages 200 and 300 were left in place for the browser checks listed under
"Unverified".

## Files

- `routes.json`: browser URLs classified by kind (`page-view`, `title-view`,
  `short`, `action`, `version`, `comment`, `other`), each with the observed
  server response. Each URL was requested without following redirects; a
  `302` location shows which page a route resolves to.
- `adf-links.json`: the links sent to page 200 through the v2 API, the ADF
  that Confluence stored for pages 200 and 300, and one editor-created link
  mark from page 110.
- `api.json`: v2 responses for a current page and its ancestors, a trashed
  page and its ancestors, and title searches.

## Verified observations

Routes:

- Links created in the Confluence editor use
  `https://<host>/wiki/spaces/<KEY>/pages/<id>`, the canonical form that push
  emits (decision 13). `_links.webui` and rendered hrefs add a title slug:
  `/spaces/<KEY>/pages/<id>/<slug>`. The slug drops `&`, `%`, and non-ASCII
  letters (`A+B & 50% Ünïcode` becomes `A+B+50+n+code`), so it does not
  identify the page; the page ID does.
- Confluence rewrites a stored link that has a fragment:
  `.../pages/300#Notes` sent through the API was stored as
  `.../pages/300/<slug>#Notes`. Links without a fragment were stored as
  sent. A page pushed in canonical form can therefore come back with a slug
  on the next pull; both forms denote the same page.
- `/wiki/pages/viewpage.action?pageId=<id>` redirects to the page.
- `/wiki/display/<KEY>/<title>` redirects to the page with that title. In the
  title, `+` and `%20` both mean a space, other characters are
  percent-encoded UTF-8, and both the space key and the title match
  case-insensitively. A title containing a literal `+` resolved when spaces
  were written as `%20` and the `+` was written as `%2B`; written with `+` for
  spaces and `%2B` for the literal `+`, the same title returned 404. Titles
  containing a literal `+` are therefore ambiguous in title routes.
- `/wiki/x/<code>` redirects through `tinyurl.action` to the page; the code
  is the page's `_links.tinyui`. Discovery listings carry no such codes.
- Edit routes (`edit-v2`, `resumedraft.action`), page history
  (`viewpreviousversions.action`, `diffpagesbyversion.action`,
  `/spaces/<KEY>/history/...`), old versions (`pageVersion=`), and
  focused-comment links (`focusedCommentId=`) are distinct routes.
- `/wiki/spaces/<any segment>/pages/<id>` returns the client-rendered
  application (200) for any space segment, including another key or the
  numeric space ID, so the server response does not show which page it
  displays.

ADF:

- Link marks store the href as written: `#Local-heading` for a same-page
  fragment link written through the API stays `#Local-heading`.
- `inlineCard` stores `attrs.url` as sent.
- Links in table cells are ordinary link marks.

API:

- A trashed page returns `200` from `GET /pages/{id}` with
  `"status": "trashed"` and `"parentId": null`; its ancestors list is empty,
  and it is absent from its former parent's `direct-children` listing. The
  ancestor-based membership check (root in the ancestor chain) therefore
  treats it as outside the subtree.
- `GET /pages/{id}/ancestors` returns `id` and `type` only, without titles.
  The chain includes ancestors above the workarea root (pages 10 and 20,
  folder 30 here). Computing the path of an uninstalled page whose
  ancestors are also uninstalled needs one `GET /pages/{id}` per such
  ancestor; one ancestors call does not supply their titles.
- `GET /pages?title=<t>&space-id=<id>` matches the title case-insensitively.
  `APIClient.find_pages_by_title` currently keeps only exact-case matches.
- Server-rendered HTML (`body-format=view`, `export_view`, `styled_view`)
  gives headings legacy IDs of the form
  `<page title without spaces>-<heading without spaces>`, with `.1` for a
  duplicate: `cflsyncfixturetargetA+B&50%Ünïcode-Notes`,
  `...-MessageReference`, `...-Notes.1`, `...-A(b)&c`, `...-Überblick–café`.
  `export_view` also turns the same-page href `#Local-heading` into a full
  page URL with that fragment. These IDs come from the server renderer, not
  from the browser editor and viewer.

## Unverified

Each item lists the default that later steps use.

- **Fragment navigation in the browser:** whether
  `https://<host>/wiki/spaces/<KEY>/pages/<id>#<fragment>` scrolls to the
  heading, which anchor the browser viewer assigns to headings "Notes",
  "Message Reference", duplicated "Notes", "A (b) & c", and "Überblick –
  café" (reportedly heading text with dashes for spaces, as in
  `#Message-Reference`), and whether `#notes` reaches "Notes" in Confluence.
  This affects documentation only, since fragments are copied verbatim
  (decision 19). Check in a browser on page 300.
- **Fragment navigation in local previews:** whether `#Notes` reaches the
  heading "Notes" in GitHub and VS Code previews. Documentation only.
- **Same-page fragment links made in the editor:** how the editor stores
  them (`#frag` or a full URL). Default: `#frag`, as observed for links
  written through the API.
- **Resolution of `/wiki/spaces/<other key>/pages/<id>`:** whether the
  browser shows page `<id>` regardless of the space segment. Later steps
  identify the page by its ID (STEPS.md, step 4); this route form is
  `page-view`.
- **Pages the credentials cannot see:** not observable with a single account.
  Default: a `403` is treated like `404` (decision 10).
- **`GET /spaces/{id}`:** not requested, to stay within the workarea
  subtree. The response's `key` field is documented by Atlassian; the key is
  also visible in `_links.webui` of every page response.
