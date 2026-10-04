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
| Layouts | An HTML `<section>` with one `<div data-type="column">` per column around Markdown; see [Layouts](#layouts) |

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
and a blank line before and after each, as for [layouts](#layouts).
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
its own with a blank line before and after it; otherwise the next lines are
read as HTML rather than Markdown. A column is a `<div data-type="column">`
with its width in percent as `data-width`; add, remove, or reorder columns, or
change their widths, to change the layout. `data-breakout` (`wide` or
`full-width`) and `data-breakout-width` set the width of the whole layout and
may be left out. Layouts can only be placed at the top level of a page, not
inside a list, quote, panel, or table, and cannot be nested. Content between
the columns of a section, outside any column, is rejected on push.

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

Some content is converted but loses presentation detail: image size and
layout, and advanced table formatting. Check the remote
page after pushing changes to pages that use these features.
