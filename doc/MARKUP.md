# Writing Confluence pages

`content.md` uses GitHub Flavored Markdown (GFM). This guide covers the Markdown
that cflsync converts to editable Confluence content. Pulling a page can also
produce preserved Confluence content that should not be edited as Markdown;
see [Macros](#macros).

## A page at a glance

```markdown
# Release checklist

## Before release

Complete the [release procedure](https://example.invalid/release).

- [ ] Review changes
- [x] Update the changelog

> [!WARNING]
> Publish only from the protected branch.

```sh
git tag v1.2.3
git push origin v1.2.3
```

| Check | Owner |
| --- | --- |
| Release notes | Documentation |

![Architecture diagram](_attachments/architecture.png)
```

The first `#` heading is the page title. It is added by `page pull`, must stay
the first and only level-one heading, and cannot rename the remote page. Use
`page rename PAGE_REF TITLE` to rename a page. Use `##` through `######` for
headings in the page body.

## Supported Markdown

| Content | Markdown |
| --- | --- |
| Paragraphs and hard line breaks | Ordinary text; lines wrapped within a paragraph are joined with a space; end a line with two spaces for a hard break. |
| Emphasis | `*italic*`, `**bold**`, `~~strikethrough~~`, `` `code` ``, `<u>underline</u>`, `<sub>subscript</sub>`, and `<sup>superscript</sup>` |
| Links | `[label](https://example.com)` |
| Headings | `## Heading` through `###### Heading` |
| Blockquotes | `> Quoted text` |
| Panels | `> [!NOTE]`, `> [!IMPORTANT]`, `> [!TIP]`, `> [!WARNING]`, or `> [!CAUTION]`, followed by quoted panel content; other panels as an HTML `<div>`; see [Panels](#panels) |
| Lists | `- item`, `1. item`, and task items such as `- [ ] todo` or `- [x] done` |
| Code blocks | Fenced blocks such as ```` ```python ````; the language is retained by Confluence |
| Horizontal rules | `---` |
| Tables | Pipe tables with a header row, for example `| Name | Value |` |
| Attachments | `![](_attachments/image.png)` for images and `[](_attachments/file.pdf)` for downloadable files |
| Image figures | `<figure data-type="media-single" …>` around an image, with optional `<figcaption>`; see [Images](#images) |
| Layouts | An HTML `<section>` with one `<div data-type="column">` per column around Markdown; see [Layouts](#layouts) |
| Expands | `<details>` with a plain-text `<summary>` title and Markdown body; see [Expands](#expands) |
| Text colour and highlight | `<span style="color: #0747a6">text</span>` and `<span style="background-color: #f8e6a0">text</span>` |

Colour spans use twg's syntax and work with emphasis, links, underline,
subscript, and superscript, including in tables and captions. Use six-digit
hex values; existing values retain their spelling. A span can contain both
`color` and `background-color`, and nested spans can override either colour.
`<mark>text</mark>` is also accepted as highlight `#FFFF00`; pull writes the
explicit colour span. Inline code cannot carry colours. GitHub strips inline
styles when rendering, so colour is preserved for Confluence but may not show
in Markdown previews.

Pull writes adjacent HTML container tags on consecutive lines, keeping blank
lines around Markdown body blocks. Both this compact form and older files
with blank lines between tags are accepted on push. Existing files keep their
spacing until a pull rewrites them, normally after a remote change or an
explicit force pull. No workarea migration is needed; `pull --force` overwrites
local edits. Adding or removing tag-spacing blank lines by hand can still
mark a page as locally changed.

Nest list items with indentation. Images or files in `_attachments/` are
uploaded and maintained with the page. Links outside `_attachments/` remain
ordinary links; external images are supported as external media.
Pull writes attachment filenames percent-encoded in the path, as in
`![Pasted image.png](_attachments/Pasted%20image.png)` for `Pasted image.png`;
write a name with spaces the same way, or in angle brackets:
`![](<_attachments/Pasted image.png>)`. The label is the alt text, or the plain
filename when Confluence has none, and is pushed as alt text. cflsync 0.5.4 and
0.5.5 wrote the encoded name as that label; edit it, or it is pushed as written.
When a page has several attachments with the same filename, which happens on
copied pages, pull downloads one of them and reports the others; cflsync
leaves those in Confluence untouched.
File links such as `[Report](_attachments/report.pdf)` become inline Confluence
file references using that page's attachment manifest. After page copy, these
references resolve to the copied files; ordinary source download URLs remain
unchanged.

## Images

Pull writes a block image as ordinary Markdown unless at least one condition
requires an HTML figure:

- Its layout differs from `center`.
- It has a caption, including an empty caption.
- Its display width is a percentage (also when the width type is omitted),
  or is a pixel width different from its native ADF width or without a known
  native width.

Equal pixel widths are compared numerically, including fractional values and
`400` versus `400.0`. Native dimensions mean the media node's dimensions in
ADF, not the attachment file's pixel size. Native width/height alone, a height
without width, or a width type without a display width do not require a figure.
The rule is the same for attachments and external URLs.

A figure retains extra settings using twg's attribute names:

```markdown
<figure data-type="media-single" data-layout="wrap-right" data-width="400" data-width-type="pixel">

<img src="_attachments/example.png" width="800" height="600" alt="Example" />

<figcaption>

An editable **caption** with [a link](https://example.test).

</figcaption>
</figure>
```

`data-width` controls the displayed width; `data-width-type` is `pixel` or
`percentage`, defaulting to percentage when omitted. Widths must be positive
finite numbers, and percentages cannot exceed 100. The `<img>` width and
height preserve the separate intrinsic pixel dimensions when present.
Every generated figure contains an HTML `<img>`, even without intrinsic
dimensions. Older figures containing `![alt](path)` remain accepted on push.

`data-layout` accepts `center` (the default), `wrap-left`, `wrap-right`,
`wide`, `full-width`, `align-start`, and `align-end`. In this tag-line form,
keep blank lines between tags and Markdown content and on both sides of a raw
`<img>` line. Adjacent container tags, such as `</figcaption>` and `</figure>`,
need no blank line between them; do not join `<img>` to those tag runs.
The caption is one paragraph of ordinary inline content, including formatting,
links, dates, mentions, statuses, and hard breaks; an empty `<figcaption>`
preserves an empty caption. Images can use managed `_attachments/` paths or
external URLs, including filenames without an image suffix. Figures also work inside lists, layouts, expands, and HTML
table cells. Compact HTML figures are accepted on push, as is a caption on a
single line, `<figcaption>Caption text.</figcaption>`; its content is then HTML
(`<strong>`), not Markdown, as in any one-line HTML block.
New local files referenced by `<img>` become managed attachments on push,
including images in HTML table cells. Pandoc may also render an otherwise plain
Markdown image as `<img>` inside an HTML table; this does not retain geometry.

Ordinary Markdown images omit native width/height and display width/type.
Push sends centered media without dimensions. Confluence restores attachment
sizes from the file, so an image whose native ADF size differs from its file
size can change displayed size on push. External images receive no restored
dimensions. This geometry loss is accepted in exchange for simpler Markdown;
retained HTML figures keep their geometry. Existing figures are not rewritten
merely by upgrading: an ordinary pull rewrites remotely changed pages, and
force pull rewrites even unchanged pages, overwriting local edits. Both image
forms remain readable and no workarea format bump or migration is required.

Figures with unsupported attributes, marks, dimensions, or caption content
remain opaque on pull; old opaque image fences still restore their original
ADF on push. Image borders and the dimensions of inline images remain
round-trip limitations.

## Tables

Use pipe tables for ordinary tables:

```markdown
| Service | State |
| --- | --- |
| API | Ready |
| Worker | Maintenance |
```

Pulled tables that require merged cells or multiple blocks in a cell may be
written as HTML tables. These are accepted on push, but table layout, widths,
cell colours, alignment, and similar presentation settings are not retained.
In HTML tables, pull writes `↔` and `↩` followed by the invisible character
U+FE0E, which selects their text form, and push keeps it; the arrows look the
same.

## Panels

Each GitHub alert is one Confluence panel type:

| Markdown | Confluence panel |
| --- | --- |
| `> [!NOTE]` | Info |
| `> [!IMPORTANT]` | Note |
| `> [!TIP]` | Success |
| `> [!WARNING]` | Warning |
| `> [!CAUTION]` | Error |

Custom panels, with an emoji and a background colour, and panels without an
alert are written as an HTML `<div>` around ordinary Markdown:

```markdown
<div data-type="panel-custom" data-icon=":dart:" data-color="#F4F5F7" data-icon-id="1f3af" data-icon-text="🎯">

Panel text, with **formatting** and lists.

</div>
```

Edit the text inside as any other Markdown, with the tags on lines of their own
and blank lines around Markdown body blocks, as for [layouts](#layouts).
Adjacent opening or closing container tags can be on consecutive lines.
`data-type` is `panel-` followed by `info`, `note`, `tip`, `success`,
`warning`, `error`, or `custom`. `data-color` sets the background colour,
`data-icon` the emoji's short name, and `data-icon-id` and `data-icon-text` its
code point and character; each may be left out. Pull uses this form for any
panel with an emoji or colour, also of the other types, and for `tip` panels.

## Layouts

A Confluence layout, columns side by side, is written as HTML tags around
ordinary Markdown:

```markdown
<section data-type="layout-section" data-breakout="wide" data-breakout-width="1800">
<div data-type="column" data-width="66.66">

Main text, with **formatting**, lists, tables, and images.

</div>
<div data-type="column" data-width="33.33">

Sidebar text.

</div>
</section>
```

Edit the text in the columns as any other Markdown. Keep each tag on a line of
its own and retain blank lines around the Markdown column content; without a
blank after an opening tag run, the body is read as HTML rather than Markdown.
No blank is needed between adjacent container tag lines.
A column is a `<div data-type="column">` with its width in percent as
`data-width`; add, remove, or reorder columns, or change their widths, to change
the layout. `data-breakout` (`wide` or
`full-width`) and `data-breakout-width` set the width of the whole layout and
may be left out. Layouts can only be placed at the top level of a page, not
inside a list, quote, panel, or table, and cannot be nested. Content between
the columns of a section, outside any column, is rejected on push.

## Expands

An expand is written as HTML tags around Markdown. The `<summary>` is its
visible title; the remaining content is the body shown when expanded:

```markdown
<details data-breakout="wide" data-breakout-width="1800">
<summary>Additional details</summary>

Text with **formatting**, lists, code, and tables.

</details>
```

Keep the tags on separate lines and blank lines around Markdown body blocks.
The opening `<details>` and complete `<summary>` can be on consecutive lines,
as can adjacent closing container tags. The title is plain text, not Markdown;
escape `&`, `<`, and `>` as `&amp;`, `&lt;`, and `&gt;`. Empty titles are allowed. An empty body becomes an empty
paragraph on push.

A nested expand uses `<details data-type="nested-expand">`, with the same
summary and body structure. Use this form inside a table cell or another
expand. Ordinary `<details>` directly inside a table cell also becomes a
nested expand on push, as in twg. The optional `data-breakout` (`wide` or
`full-width`) and positive numeric `data-breakout-width` apply to ordinary
expands; nested expands cannot carry them. Layout sections cannot be placed
inside expands. Previously pulled `atlas_doc_format` expand blocks remain
accepted on push.

## How Markdown reads text

Text pushed to Confluence is what Markdown makes of `content.md`, so ordinary
Markdown rules apply, also to text that came from Confluence:

- Runs of spaces become one space, and spaces at the start or end of a
  paragraph or table cell are dropped.
- A hard break at the end of a paragraph, heading, or task item is dropped.
- A line holding only `---` is a horizontal rule; write `\---` for the text.
- A list item that starts with `[ ]`, `[x]`, `☐`, or `☒` is a task item.
- A code block loses its final line break; a code block without a language,
  which pull writes indented, also loses blank lines at its start and end.
- An image alone in a paragraph is a block image, also when Confluence showed
  it inline.
- Bold and italic that overlap without nesting, such as bold over "a b" and
  italic over "b c", cannot be written in Markdown; such text is pushed with
  literal asterisks. Nest one inside the other, or separate them by a space,
  as in `**a *b*** *c*`.
- Bold or italic text that starts with punctuation right after a letter, or
  ends with punctuation right before one, as in `pijnpunten**:**`, is not
  formatting but text with literal asterisks. Include the neighbouring word,
  as in `**pijnpunten:**`, or leave the punctuation unformatted.
- A bare URL or email address stays text; write `<https://example.com>` or
  `[label](https://example.com)` for a link.
- HTML comments, such as the `<!-- -->` that pull writes between two lists
  that would otherwise merge, are not pushed.

## Macros

### Supported macros

Pulled dates are represented by an HTML `<time>` element, and status lozenges
by an HTML span; cflsync converts both back to their Confluence forms on push.
Mentions whose users have no visible email address also use a special HTML
span. They can be edited, but their required attributes must remain intact:

- Change the text inside a status span and, if needed, its `data-color` to
  `neutral`, `purple`, `blue`, `red`, `yellow`, or `green`. A status is
  written as
  `<span data-type="status" data-color="green" data-status-style="bold">Done</span>`;
  `data-status-style` (`bold` or `mixedCase` in Confluence) and `data-color`
  may be left out, and the same element creates a new status, `neutral` without
  `data-color`.
- Change a date by changing its `datetime="YYYY-MM-DD"` attribute. The text
  inside `<time>` is for reading only and is ignored on push; update it to
  match. The same element creates a new date.
- A mention span needs its non-empty `cfl-id`; preserve its other metadata
  unless the corresponding Confluence account values are known.

Inline cards, the link previews Confluence shows for Jira issues and pages,
are written as an HTML link with `data-card-appearance="inline"`:

```html
<a href="https://example.atlassian.net/browse/ABC-123" data-card-appearance="inline">https://example.atlassian.net/browse/ABC-123</a>
```

Change a card's target in `href`; the text between the tags is ignored on
push, and Confluence shows the card's own title. The same element creates a
new card. A card cannot be inside bold, italic, or other formatting. Other
HTML links are not supported; write them as `[text](URL)`.

These are HTML forms rather than ordinary Markdown syntax. The status, date,
and card forms are the ones the Atlassian `twg` CLI uses; a pulled date is
written as:

```html
<time datetime="2026-04-01">April 1, 2026</time>
```

Date spans written by cflsync 0.5.3 and earlier, such as
`<span cfl-type="date">2026-04-01[Europe/Brussels]</span>`, are no longer
accepted; push reports them, and they must be rewritten as `<time>` elements.
Status spans written by cflsync 0.5.6 and earlier, such as
`<span cfl-type="status" style="background-color: green">Done</span>`, are
rejected the same way and must be rewritten in the form above.

### Creating mentions

On push, a plain email link can create a Confluence user mention:

```markdown
[Example User](mailto:example.user@example.com)
```

cflsync searches for `Example User` and emits a mention only when exactly one
accessible result has the given email address. If no result or multiple results
match, the link remains an ordinary email link. Pull writes this form for a
mention whose user has a visible email address; otherwise it writes the
`cfl-type="mention"` HTML span.

Confluence search does not find deactivated users. A pulled mention of a
deactivated user, such as `[Jane Doe (Deactivated)](mailto:jane.doe@example.com)`,
is therefore pushed as an email link, not as a mention.

### Other macros

Confluence macro content without an ordinary Markdown representation is written
as a fenced `atlas_doc_format` block containing its original JSON. Leave these
blocks unchanged: cflsync restores them on the next push. They are not a
Markdown authoring format.

## Round-trip limitations

Some content is converted but loses presentation detail: image borders,
inline image dimensions, geometry of images simplified to ordinary Markdown
(see [Images](#images)), and advanced table formatting. Check the remote page
after pushing changes to pages that use these features.
