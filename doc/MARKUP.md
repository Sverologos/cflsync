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
| Panels | `> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`, or `> [!CAUTION]`, followed by quoted panel content |
| Lists | `- item`, `1. item`, and task items such as `- [ ] todo` or `- [x] done` |
| Code blocks | Fenced blocks such as ```` ```python ````; the language is retained by Confluence |
| Horizontal rules | `---` |
| Tables | Pipe tables with a header row, for example `| Name | Value |` |
| Attachments | `![](_attachments/image.png)` for images and `[](_attachments/file.pdf)` for downloadable files |

Nest list items with indentation. Images or files in `_attachments/` are
uploaded and maintained with the page. Links outside `_attachments/` remain
ordinary links; external images are supported as external media.
Pull writes attachment filenames percent-encoded, as in
`![](_attachments/Pasted%20image.png)` for `Pasted image.png`; write a name with
spaces the same way, or in angle brackets: `![](<_attachments/Pasted image.png>)`.
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
- A bare URL or email address stays text; write `<https://example.com>` or
  `[label](https://example.com)` for a link.
- HTML comments, such as the `<!-- -->` that pull writes between two lists
  that would otherwise merge, are not pushed.

## Macros

### Supported macros

Pulled dates are represented by an HTML `<time>` element, and status lozenges
by a special HTML span; cflsync converts both back to their Confluence forms on
push. Mentions whose users have no visible email address also use a special
HTML span. They can be edited, but their required attributes must remain
intact:

- Change the text inside a status span and, if needed, its
  `background-color` to `gray`, `purple`, `blue`, `red`, `yellow`, or `green`.
- Change a date by changing its `datetime="YYYY-MM-DD"` attribute. The text
  inside `<time>` is for reading only and is ignored on push; update it to
  match. The same element creates a new date.
- A mention span needs its non-empty `cfl-id`; preserve its other metadata
  unless the corresponding Confluence account values are known.

These are HTML forms rather than ordinary Markdown syntax. The date form is
the one the Atlassian `twg` CLI uses; a pulled date is written as:

```html
<time datetime="2026-04-01">April 1, 2026</time>
```

Date spans written by cflsync 0.5.3 and earlier, such as
`<span cfl-type="date">2026-04-01[Europe/Brussels]</span>`, are no longer
accepted; push reports them, and they must be rewritten as `<time>` elements.

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

### Other macros

Confluence macro content without an ordinary Markdown representation is written
as a fenced `atlas_doc_format` block containing its original JSON. Leave these
blocks unchanged: cflsync restores them on the next push. They are not a
Markdown authoring format.

## Round-trip limitations

Some content is converted but loses presentation detail: panel colours and
icons, image size and layout, and advanced table formatting. Check the remote
page after pushing changes to pages that use these features.
