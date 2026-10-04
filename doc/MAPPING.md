# Atlassian Document Format to Pandoc AST mapping

This document specifies the `cflsync` conversion boundary:

```text
atlas_doc_format ⇄ Pandoc AST ⇄ GFM
```

Pandoc supplies the second conversion through its `gfm` reader and writer.
The reader runs without the `autolink_bare_uris` extension: URLs, `www.`
hosts, and email addresses in text stay text, as in CommonMark, and only
`<URL>` and `[text](URL)` are links. The writer emits links in these forms.
`cflsync` exposes `ADFToMarkdownConverter` and `MarkdownToADFConverter`;
Pandoc's JSON AST is an internal representation. The ADF API payload is a
JSON-encoded ADF document; it is decoded before conversion and encoded again
when sent to Confluence.

ADF is the remote source of truth. Conversion is intentionally lossy: supported
content becomes readable GFM, while unrelated metadata and unsupported
formatting are omitted. Unsupported structures are retained as complete ADF
JSON in a Pandoc code block, which Pandoc writes as a fenced GFM block.

## Conversion invariants

- Every emitted ADF document has `type: "doc"` and `version: 1`.
- Supported node handlers consume only the fields needed for conversion.
  Extra fields and attributes do not alone cause opaque fallback.
- Required values and content shapes remain validated. Unsupported node types
  and structures retain their original JSON, including metadata.
- Ignored attributes and formatting are not recovered by reverse conversion;
  a subsequent push may discard them remotely.
- Ordinary Pandoc GFM is not interpreted as a Confluence-specific construct
  unless it matches a mapping below or a cflsync opaque marker.
- An opaque marker is decoded only as JSON and validated in its destination
  parent context; malformed, altered, or contextually invalid data fails
  before an API request.
- The resulting GFM is canonicalized by Pandoc. Preservation concerns document
  structure and opaque JSON payloads, not original Markdown spelling.
- Text follows Markdown's reading rules, which are accepted rather than
  compensated: runs of spaces collapse to one, spaces at the edges of
  paragraphs and table cells are trimmed, a paragraph holding only `---`
  reads back as a rule, a list item whose text starts with `☐` or `☒`
  reads back as a task item, a code block loses its final line break and,
  when written indented (without language), its leading and trailing blank
  lines, an inline image alone in a paragraph reads back as a block image,
  `strong`, `em`, or `strike` runs that cross read back with literal
  delimiters, and so does `strong` or `em` text that starts with punctuation
  after a letter or ends with punctuation before one. A push of unchanged pulled Markdown can therefore
  differ from the original ADF in these respects.

## Root document

| ADF | Pandoc AST |
| --- | --- |
| `{ "type": "doc", "version": 1, "content": [...] }` | `Pandoc Meta [Block]` |
| Empty ADF document | `Pandoc Meta []` |

ADF page metadata remains in the cflsync page cache rather than Pandoc
metadata. For page conversion, the caller supplies the title from page
metadata; it becomes the first and only level-one Markdown heading. Body
level-one headings become level two; levels two through six remain unchanged.
The converter itself has no cache access. Pull supplies the fetched title
that will be recorded in the cache, including on first pull and title changes.
Body-only conversion may omit the title.

The generated title heading is presentation metadata, not an ADF body node.
Reverse conversion removes it when the caller supplies the title, and rejects a
heading that no longer matches, because push does not rename pages. `page
rename` rewrites the generated heading separately from body conversion.

## Direct block mappings

| ADF node | Pandoc AST | Reverse ADF node |
| --- | --- | --- |
| `paragraph` | `Para` | `paragraph` |
| `heading` with `attrs.level` 1–6 | `Header max(2, level)` | `heading` with `attrs.level` |
| `blockquote` | `BlockQuote` | `blockquote` |
| `panel` | GFM alert `Div`, or raw HTML `<div data-type="panel-TYPE">` tag blocks around its blocks | `panel` with the same type and attributes |
| `bulletList` and `listItem` | `BulletList` | `bulletList` and `listItem` |
| `orderedList` and `listItem` | `OrderedList` | `orderedList` and `listItem` |
| `taskList` and `taskItem` | `BulletList` beginning each item with `☐` or `☒` | `taskList` and `taskItem` |
| `codeBlock` | `CodeBlock`; `attrs.language` becomes its language class | `codeBlock` with `attrs.language` |
| `rule` | `HorizontalRule` | `rule` |
| `layoutSection` and `layoutColumn`, at the top level | raw HTML `<section>` and `<div>` tag blocks around the columns' blocks | `layoutSection` and `layoutColumn` |

Handlers validate and convert meaningful fields such as heading level,
ordered-list start number, and code language. Other attributes, including
`localId` and presentation attributes, are ignored for these supported nodes.
Reading GFM gives every heading an implicit Pandoc identifier, which the reverse
mapping ignores since ADF has no counterpart.
A paragraph with omitted or empty `content` converts to an empty paragraph,
which Pandoc omits from canonical GFM. In a list item, this leaves a bare
marker (`- `, `2.  `, or `<li></li>` in an HTML table), which reads back as an
item without blocks; the reverse mapping gives such an item, and an item that
starts with a nested list, a leading empty paragraph again. Malformed required
values cause opaque fallback; malformed document structure may instead raise a
conversion error.

A list item's first paragraph is written tight only when the next block in the
item interrupts a paragraph: a fenced code block, a heading, a blockquote or
alert, a rule, raw HTML, or a list whose first item has content and, if
ordered, starts at 1. Otherwise, as before a second paragraph, an image, a code
block without language, or a pipe table, it stays a paragraph and Pandoc writes
the list loose, so that the next block does not read back as a continuation of
the paragraph.

Some adjacent blocks would read back as one: a list followed by a list of the
same kind, and a list or code block without language followed by a code block
without language. An empty paragraph between them does not separate them,
since Pandoc writes it as nothing. In any block container, including list
items and table cells, such a pair is written with an empty HTML comment
`<!-- -->` between the blocks. Reverse conversion ignores every block that
holds only an HTML comment, whatever its text, so Pandoc's own separators and
hand-written comments are accepted; the comments are not pushed. A comment
inside a paragraph is rejected like other raw inline HTML.

A layout section at the top level of the page is written in twg's HTML form,
each tag on a line of its own and separated by blank lines from the column
content, which stays Markdown:

```markdown
<section data-type="layout-section" data-breakout="wide" data-breakout-width="1800">

<div data-type="column" data-width="50">

Column text

</div>

<div data-type="column" data-width="50">

- item

</div>

</section>
```

The section type is always the generic `layout-section`, where twg names it
after the column widths (`layout-two-equal` and others). The columns alone
define the layout: their number and order, and each `data-width`, the column's
`attrs.width`, written without a trailing `.0`. The section's `breakout` mark
becomes `data-breakout` (`wide` or `full-width`) and, when present,
`data-breakout-width`. `localId` is dropped, as on other nodes. A section with
other attributes or marks, or a column with other attributes, stays opaque, as
does a layout anywhere but at the top level, where ADF does not allow one.
Reverse conversion groups the tag blocks at the top level: it accepts any
section `data-type` that starts with `layout-`, twg's `data-local-id`, and tag
lines written without blank lines between them. Content in a section outside a
column, an unclosed section or column, nested sections or columns, a layout
inside another block, and unknown or invalid attributes are rejected. A column
without blocks becomes a column holding an empty paragraph, the form in which
an empty column was written.

Blockquotes map to Markdown `>` blocks and back to ADF `blockquote` nodes,
with their contained blocks and inline formatting converted recursively.

Panels of the five types that GitHub has an alert for, without icon or colour,
map one to one to GFM alerts:

| ADF `panelType` | GFM alert |
| --- | --- |
| `info` | `NOTE` |
| `note` | `IMPORTANT` |
| `success` | `TIP` |
| `warning` | `WARNING` |
| `error` | `CAUTION` |

Every other panel, `custom` and `tip` panels and panels with `panelIcon`,
`panelIconId`, `panelIconText`, or `panelColor`, is written in twg's HTML form,
tag lines around Markdown blocks as for layouts:

```markdown
<div data-type="panel-custom" data-icon=":dart:" data-color="#F4F5F7" data-icon-id="1f3af" data-icon-text="🎯">

Panel content.

</div>
```

`data-type` is `panel-` followed by the panel type; `data-icon`, `data-color`,
`data-icon-id`, and `data-icon-text` hold `panelIcon`, `panelColor`,
`panelIconId`, and `panelIconText`, HTML-escaped, in that order. twg reads
`panel-tip` as `info` (twg's reference); cflsync keeps `tip`. A panel with other
attributes, or non-string attribute values, stays opaque. `localId` is not
written; twg's `data-local-id` is accepted and ignored on reverse conversion.
Panels in this form are recognized wherever blocks are, including layout
columns, list items, and HTML-table cells, where the HTML reader returns the
`<div>` as a Pandoc `Div` with its attributes. An unclosed panel, a layout
inside a panel, an unknown panel type, and unknown attributes are rejected. A
panel without blocks becomes a panel holding an empty paragraph.

Only the Pandoc alert `Div` shape emitted by GFM alert syntax is recognized as
an alert panel on reverse conversion; ordinary blockquotes remain blockquotes.

Task lists map directly to GFM task lists: `TODO` becomes `- [ ]` and `DONE`
becomes `- [x]`. Pandoc represents these markers as leading `☐` and `☒` inline
nodes in a `BulletList`. A nested task list remains nested under its preceding
task item. Reverse conversion emits no task-list or task-item `localId`.

## Direct inline mappings

| ADF node or mark | Pandoc AST | Reverse ADF form |
| --- | --- | --- |
| `text` | `Str` and `Space`; a `SoftBreak` read from Markdown becomes a space | `text` |
| `hardBreak` | `LineBreak`; dropped at the end of a paragraph, heading, or task item | `hardBreak` |
| `strong` mark | `Strong` | `strong` mark |
| `em` mark | `Emph` | `em` mark |
| `strike` mark | `Strikeout` | `strike` mark |
| `code` mark | `Code` | `code` mark |
| `underline` mark | Raw HTML `<u>` inline pair | `underline` mark |
| `subsup` mark | Raw HTML `<sub>` or `<sup>` inline pair | `subsup` mark |
| `link` mark | `Link`; page links become local links (see below) | `link` mark |
| `emoji` with `attrs.text` | `Str` holding that text | `text` |
| `mention` with `attrs.id` and a resolvable email address | `Link` with a `mailto:` target | `mention` |
| `mention` with `attrs.id` but no email address | raw HTML `span` | `mention` |
| `date` with a millisecond timestamp | raw HTML `<time datetime>` inline pair | `date` at UTC midnight |
| `status` | raw HTML `<span data-type="status">` inline pair | `status` |
| `inlineCard` with `attrs.url` | raw HTML `<a href="URL" data-card-appearance="inline">` inline pair around the URL | `inlineCard` |

Underline, subscript, and superscript are represented by strict `<u>`,
`<sub>`, and `<sup>` raw HTML inline pairs, so they remain editable in the
local Markdown file. ADF `subsup.attrs.type` must be `sub` or `sup`; it cannot
be combined with an ADF `code` mark. Markdown has no hard break at the end of a block: Pandoc writes a hard break
as a backslash before the line end, which reads back as a literal backslash
when nothing follows. Trailing hard breaks, and spaces after them, are
therefore dropped, as Markdown drops trailing whitespace; a paragraph that
holds only hard breaks becomes empty. Hard breaks inside a block are kept.
ADF splits text into a node wherever its marks change, also for marks that
are not converted, such as `textColor`. Neighbouring text nodes that share
`strong`, `em`, or `strike` are therefore written inside one pair of
delimiters, `**a (*b*)**` rather than `**a (****b****)**`, which Markdown
reads differently; where marks overlap, the mark covering the longest run
becomes the outer one, and a single node keeps `strong` outside `em` outside
`strike`. Text with a link, underline, or subscript/superscript mark keeps its
delimiters inside that mark's syntax, which already separates them from its
neighbours. Two marks that cross, such as `strong` over `a b` and `em` over
`b c`, have no Markdown form without touching delimiters and do not convert
back intact.
Whitespace at the start or end of such a run, such as a non-breaking space, is
written outside the delimiters and converts back without that mark, since a
delimiter next to whitespace cannot open or close.
ADF combines `code` with `link` only, which
maps to code inside a link (`` [`x`](URL) ``); `Code` inside any other
formatting is rejected on reverse conversion. Supported text marks are emitted in a
deterministic nesting order. Other marks
are ignored while retaining their text and supported marks. Extra fields on
supported marks are ignored, but required values such as a link's non-empty
string destination remain validated. Malformed or duplicate supported marks
cause retention of the enclosing block.

### Page links

Both converters accept an optional link resolver, which pull and push supply
as a `workarea.LinkResolver`; the converters use it only through two methods
and import nothing from the workarea module.

- ADF to Pandoc: a `link` mark's `href` is passed to `to_markdown(href)`; a
  returned string replaces the `Link` target, and `None` keeps it.
- Pandoc to ADF: a `Link` target is passed to `to_adf(href, text)` after the
  attachment and mailto-mention cases; a returned string replaces the `link`
  mark's `href`, and `None` keeps it. `text` is the link's plain text, or empty
  when the link content carries formatting.

Only link targets change: link text, title, and the fragment after `#` are
kept exactly, so fragments are not translated between Confluence and Markdown
anchors. Images, `_attachments/` links, and links inside retained ADF never
reach the resolver. Links in pipe tables and HTML tables pass through the same
handler. Which targets are page links is specified in
[SPEC.md](SPEC.md#page-links).

## Tables and media

`table`, `tableRow`, `tableHeader`, and `tableCell` map to a Pandoc `Table`.
Pandoc then picks the GFM representation: a pipe table when every cell holds a
single paragraph and all spans are 1, and an HTML `<table>` otherwise. The
reverse direction reads a pipe table directly; an HTML table arrives as a raw
block and is parsed back into a Pandoc `Table` by a second Pandoc invocation,
after which both representations share one mapping. Only raw blocks that are
HTML tables, layout tags, or panel tags are accepted; other raw content has no ADF
equivalent. Pandoc's
HTML writer adds the text-presentation selector U+FE0E after `↔` and `↩` that
lack one, so these characters in an HTML-table cell are pushed with it; the
change happens once, and is accepted.

Pandoc's HTML reader, used for that second invocation, represents some cell
content differently from the GFM reader. The reverse mapping accepts both
forms:

| Content | GFM reader | HTML reader |
| --- | --- | --- |
| `<u>`, `<sub>`, `<sup>` | raw HTML inline pair | `Underline`, `Subscript`, `Superscript` |
| status and mention spans | raw HTML inline pair | `Span` with the same attributes, except that `data-status-style` and `data-local-id` lose the `data-` prefix |
| `<time datetime>` | raw HTML inline pair | raw HTML inline pair |
| inline card `<a … data-card-appearance="inline">` | raw HTML inline pair | `Link` with the attribute `card-appearance` (the `data-` prefix dropped), its `href` percent-encoded as for any link |
| ordered list | `Decimal`, `Period` | `Decimal`, `DefaultDelim` |
| task item | `☐`/`☒` marker | the same marker inside a raw `<label>` pair, which is ignored |

The HTML reader runs with Pandoc's `raw_html` extension, so HTML that Pandoc
does not model stays raw, as in the GFM reader, instead of being dropped with
only its text kept; such HTML is rejected like anywhere else. Writing GFM
disables syntax highlighting, so a code block in an HTML table is written as
`<pre class="LANGUAGE"><code>`. Earlier releases wrote highlighted HTML
(`<div class="sourceCode">`); that form is still read as a code block with its
language.

Cell content uses the ordinary block mapping, so opaque markers inside a cell
are retained like anywhere else. An ADF table converts unless its structure is
invalid; a leading row of `tableHeader` cells becomes the table head, and a
table without one is written with an empty header row, which becomes a real
empty header row when pushed back.

These table features do not survive conversion: header cells outside the first
row, hard breaks inside a cell, table `layout`, `width`, and `localId`, cell
`colwidth` and `background`, `isNumberColumnEnabled`, and column alignment,
which has no ADF counterpart in either direction.

`mediaSingle` and `mediaGroup` map to a Pandoc paragraph of `Image` or `Link`
inlines when the page attachment manifest resolves the ADF media identifier to
a managed local `_attachments/<filename>` path. A `mediaSingle` always becomes
an `Image`, whatever its file name, such as `GetClipboardImage.ashx?Id=…`; in
a `mediaGroup` and for `mediaInline`, `Image` is used for filenames with an
image suffix and `Link` otherwise, since the ADF media node carries no media
type. The `alt` text is the inline text; media without `alt` is labelled
with its filename, decoded from the percent-encoded path, or with the last
path segment of an external URL. External media uses its own URL and needs no
manifest. The reverse
mapping uses the manifest to reconstruct images as ADF media; file links become
`mediaInline` references, so their original block container is not retained.
Media that the manifest cannot resolve stays opaque. Layout, width, and height
attributes are dropped.

`mediaInline` maps to a Pandoc `Image` or `Link` inside its paragraph, and an
image that shares a paragraph with other content maps back to `mediaInline`. An
image alone in a paragraph is `mediaSingle` in both directions, so a lone
`mediaInline` becomes `mediaSingle` after a round trip. An inline image outside
`_attachments/` is rejected, since ADF inline media has no external form.

## Opaque ADF retention

### Marker representation

An opaque ADF node is represented in the Pandoc AST as:

```text
CodeBlock ("", ["atlas_doc_format"], []) JSON
```

`JSON` is a canonical JSON serialization of one complete ADF node. Pandoc's
GFM writer renders this as a fenced code block with `atlas_doc_format` as its info
string:

````markdown
```atlas_doc_format
{"type":"expand","attrs":{"title":"Details"},"content":[...]}
```
````

The ADF conversion recognizes only this exact marker class. It parses the JSON
and inserts the node into the current ADF container. It must not turn the fence
into an ADF `codeBlock`.

### Retention granularity

An emoji becomes its Unicode text, so it reads as an ordinary character and
pushes back as a `text` node rather than an `emoji` node; `shortName` and `id`
are dropped. A custom emoji carries no `attrs.text` and is retained opaquely,
keeping its identity. Reading GFM turns a typed `:shortcode:` into a Pandoc
emoji span, which the reverse mapping accepts and reduces to the same Unicode
text; other spans have no ADF form.

A date is a calendar day, which Confluence stores as the timestamp of its UTC
midnight. It becomes twg's form, `<time datetime="YYYY-MM-DD">Month D,
YYYY</time>`: `datetime` is the UTC calendar date of `TIMESTAMP`, and the text
spells out the same date in English. Reverse conversion, as twg's, reads only
`datetime` and pushes the UTC midnight of that date; the text is ignored. A
`datetime` other than `YYYY-MM-DD`, an invalid calendar date, a date with
marks, or an unclosed element causes conversion to fail before an API request.
The date spans of cflsync 0.5.3 and earlier (`<span cfl-type="date">`, with
or without a zone or `cfl-timestamp`) are rejected with a message naming the
`<time>` form.

A status becomes twg's form,
`<span data-type="status" data-color="COLOR" data-status-style="STYLE">TEXT</span>`.
`COLOR` is the ADF colour (`neutral`, `purple`, `blue`, `red`, `yellow`, or
`green`); `data-status-style` holds `style`, HTML-escaped, and is left out when
the status has none. `localId` is not written. A status with another colour or
other attributes stays opaque within its paragraph. Reverse conversion parses
the opening tag through Pandoc and reads the plain text up to `</span>` as
`text`; as in twg, a missing `data-color` is `neutral`. twg's `data-local-id`
is accepted and ignored. An unknown colour, other attributes, and an empty text
are rejected. The status spans of cflsync 0.5.6 and earlier
(`<span cfl-type="status" style="background-color: COLOR">`) are rejected
with a message naming the new form.

A mention whose account ID resolves to a user with an email address becomes
`[Display name](mailto:address)`; the leading `@` in the ADF text is omitted
from the display name. On push, this form queries Confluence for that display
name and emits a mention when exactly one result has the given email address.
It otherwise remains an email link. This applies to every mention of a
deactivated user: pull resolves the account ID and writes the email link, but
Confluence and Jira user search leave deactivated accounts out, so push sends
an email link instead of a mention. When the resolved user has no email
address, a mention becomes `<span cfl-type="mention" cfl-id="ACCOUNT-ID">TEXT</span>`.
For this fallback, `accessLevel` and `userType` become `cfl-access-level` and
`cfl-user-type` attributes. `localId` is ignored. Reverse conversion parses
the span through Pandoc and requires a non-empty account ID; it performs no
name or email lookup.

An `inlineCard` is written in twg's form,
`<a href="URL" data-card-appearance="inline">URL</a>`, its URL HTML-escaped in
the attribute (with `|` as `&#124;`, which would otherwise end a pipe-table
cell) and repeated as text. The URL is kept verbatim, also for pages in the
workarea's tree; page links are not localized for cards. A card with other
attributes, such as embedded `data` instead of a URL, or with marks, keeps its
paragraph opaque; `localId` is dropped. Reverse conversion reads the `href`
and ignores the text; it accepts twg's `data-local-id`, and rejects a card
inside formatting, a card without `href`, an unclosed card, other attributes,
and any other raw `<a>`. In HTML-table cells, Pandoc's HTML reader
percent-encodes `|`, `{`, `}`, `^`, `` ` ``, `[`, `]`, and spaces in the `href`
of a card or link, which yields an equivalent URL.

ADF has inline nodes without a readable form, such as `inlineExtension`. A GFM
fence is a block construct and cannot occupy a position inside a Pandoc `Para`
or `Header`.

Therefore, when an unsupported inline node occurs, the ADF reader
retains the smallest enclosing ADF block node as one `atlas_doc_format` marker.
For example, a paragraph containing a `status` node becomes a fence containing
the complete original `paragraph` JSON. This is lossless, but the rest of that
paragraph is not independently editable as GFM.

For unsupported content inside a list item, table cell, panel, or other
container, the reader retains the smallest enclosing node that is valid in the
same parent position. The writer validates the recovered node against that
parent's allowed ADF child types. If no such block boundary exists, the reader
retains the nearest valid ancestor rather than changing the document shape.

### Initially opaque ADF features

- Custom emoji and unsupported media. Inline cards were promoted to a readable
  mapping (see Direct inline mappings).
- `expand`, `nestedExpand`, decision lists, and `extensionFrame`. Layouts
  were promoted to a readable mapping (see Direct block mappings).
- `extension`, `bodiedExtension`, `multiBodiedExtension`, sync blocks, and
  third-party Confluence macro nodes.
- Tables, including multi-paragraph cells and unsupported geometry.

Each feature can later be promoted to a readable GFM mapping only when the
structural mapping and reverse conversion are defined. Formatting marks such
as `textColor`, and decorative attributes such as
alignment, do not by themselves trigger opaque retention on supported nodes.

## Attachment interaction

The ADF/Pandoc converter does not download or upload attachment bytes. It
uses a `MediaResolver` supplied by the synchronization layer:

```text
ADF media identifier ⇄ attachment file ID ⇄ _attachments/filename
```

ADF media nodes reference an attachment by its file ID, which the Confluence
attachment manifest reports as `fileId`. That value differs from the attachment
ID used by the attachment API operations, so the media manifest is keyed on the
file ID. The synchronization layer performs the attachment API operations and
supplies the manifest; it never emits a guessed local path. `MediaResolver`
receives ordered `(filename, file ID)` manifest entries and exposes the two pure
lookups `path_for()` and `id_for()`. `path_for()` percent-encodes the filename
as page-link path segments are encoded, since Pandoc's GFM writer does not
escape link destinations and a name with spaces or unbalanced parentheses
would otherwise not read back as a link. `id_for()` looks up the decoded
filename first and the path segment as written second, for unencoded paths
written by earlier releases. The manifest holds one entry per filename: of
remote attachments sharing a filename, the synchronization layer supplies only
the managed one (`unique_attachments`), so media referencing another stays
opaque.

Managed `_attachments/<filename>` links become `mediaInline` file references
on push, using the manifest's file ID and the destination page's collection.
This restores downloaded inline-file references rather than publishing a local
filesystem URL. Plain link labels become media alt text, so media pulled
without `alt` is pushed with its filename as `alt`; ordinary Confluence
download URLs remain unchanged links and are not redirected to copied files.

## Required tests

- ADF → Pandoc AST → ADF semantic round trips for every direct mapping.
- Pandoc GFM → AST → ADF → AST → GFM round trips for the supported GFM subset.
- Exact JSON preservation for opaque markers, including an inline `status`
  node retained through its enclosing paragraph.
- Parent-context rejection for malformed or misplaced opaque JSON.
- Attachment resolver tests for image and file references, ambiguity, and path
  traversal rejection.
- Tolerance of extra metadata and formatting on supported nodes without
  mutating the source document.
- Validation of required values and exact retention of unsupported structures.
