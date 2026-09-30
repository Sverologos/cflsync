# Page copy fixtures

`source-adf.json` is a sanitized source document from the 2026-09-30
attachment probe recorded in PLAN.md. Page 400 owns `file-att1`
(`owned-image.png`) and `file-att2` (`owned-document.txt`); page 900 owns
`file-foreign`. IDs and the site hostname have been replaced.

The native result remaps owned media IDs/collections, copies current attachment
bytes under new IDs/version 1, and preserves foreign media and every URL string.
The inline-media aggregation correction was confirmed for each media node.
No browser rendering or app-owned macro guarantee is inferred from this fixture.

`implementation-results.json` records sanitized results of the completed
2026-09-30 live API checks, including cross-space attachments and labels,
actual copied-media push, native naming/rejection, and disposable-page cleanup.
Signed-in browser rendering and third-party app behavior remain unverified.

## Prepared live verification cases

Use a disposable source and destination below the configured workarea anchor,
with an isolated local workarea. Attach `owned-image.png` and
`owned-document.txt` (current versions), plus an unreferenced file and a file
updated twice. Populate the source with this fixture after substituting the
real file/page IDs. Add a label, source content property, read restriction,
comment, and child page. The copy should include current attachments/labels,
exclude source metadata/restrictions/comments/children, resolve owned media to
the new manifest, and retain foreign media and URL strings. Compare source
version/body and attachment bytes before and after.

For the cross-space case, create the disposable source below an accessible
parent in another space on the same site, with an attachment, label, and owned
media. Use the managed anchor as destination. Verify destination space,
attachment downloads, labels, and source preservation.

For each case, run copy, unchanged push, then a supported local text edit and
normal push. Inspect resulting media IDs/collections, opaque nodes, URLs,
remote labels, and browser rendering. Test an app-owned macro separately and
record dependencies on excluded properties/custom content without changing copy
flags. Request an existing title to observe native disambiguation; copy below
a restricted parent to observe the native result without a workaround.

Record the authentication mode, required page/space access, returned ID, v2
visibility, and comparisons. Trash only the disposable pages after testing.
These prepared cases are executed in implementation step 10; they are not
passed live checks merely because the offline fixture exists.
