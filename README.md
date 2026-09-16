# SemXMLDiff

Semantic XML compare & merge tool — 100% local, nothing leaves your machine.

Compare two XML files by **content, not order**. Element order, attribute order and
whitespace are ignored: two elements are considered identical when their tag,
attributes and entire subtree carry the same information, regardless of how the
siblings are arranged. Differences are listed in a readable tree view; you choose
what to take from each side; the tool produces a merged XML document with source
tracking.

## Features

- **Order-independent semantic compare** based on canonical SHA-256 signatures
  (multiset matching at every tree level).
- **Tree view** of the differences with color-coded categories: common (gray),
  only in A (blue), only in B (orange).
- **Per-difference decisions**: take A / take B / take both / skip, plus bulk
  actions ("Prefer A everywhere", "Prefer B everywhere", "Include all", "Skip all").
- **Live preview** of the merged result while you decide.
- **Source marking** for every node that came from a single side:
  - `none` (default): clean XML + a separate merge report (JSON + human-readable HTML),
  - `attribute`: a `data-merge-source="A|B"` attribute on every such element
    (attribute name is configurable via the API),
  - `comment`: a `<!-- source: A|B -->` comment before such elements.
- **Comparison options**: whitespace normalization (on by default), namespace
  handling (URI / prefix / ignore), ignored attributes, ignored XPath patterns.
- **Fully local**: files are kept in memory only (no persistence, no network calls,
  entities/DTD disabled).
- Works offline on **Windows 10/11** and **Ubuntu 20.04+**.

## Quick start

Requires Python 3.11+.

```bash
# Windows
run.bat

# Ubuntu
./run.sh
```

The first run creates a virtual environment and installs the dependencies, then
starts the server on `http://127.0.0.1:8765` and opens your browser automatically.

Manual start:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # .venv\Scripts\pip on Windows
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

Environment variables:

| Variable              | Default        | Purpose                          |
| --------------------- | -------------- | -------------------------------- |
| `SEMXMLDIFF_PORT`     | `8765`         | Local port                       |
| `SEMXMLDIFF_HOST`     | `127.0.0.1`    | Bind host                        |
| `SEMXMLDIFF_NO_BROWSER` | unset        | Set to `1` to skip auto-opening the browser |

## Usage

1. **Upload** — drop (or pick) two XML files, A and B. Optionally adjust the
   comparison options, then press **Compare**. Invalid XML is reported with
   line/column information.
2. **Review** — summary chips show element totals; the tree view lists every
   difference with its XPath. Toggle **Only show differences** for a flat list
   (useful for large files). Choose **Take A / Take B / Take both / Skip** per
   difference or use the bulk actions. The right pane shows a live preview of the
   merged XML.
3. **Merge** — press **Merge** and download the merged XML and/or the merge
   report (JSON and HTML).

## Comparison semantics

- Every element gets a canonical signature: namespace-normalized tag, attributes
  sorted by name (attribute order is ignored), whitespace-normalized text, and the
  sorted signatures of its children — so ordering is ignored at every depth.
- Siblings are matched as **multisets**: duplicates are handled by count.
- Differences are reported at the **deepest level**: when a whole subtree differs,
  its root is shown as a single difference (its children are not listed
  separately).
- **No change detection (MVP by design):** if a single attribute of an element
  changes, the two versions appear as two separate "only in A" / "only in B"
  differences, not as a matched "modified" pair.
- Root element attributes and text are compared separately and can be merged per
  attribute. If the root tags themselves differ, you pick which root to use.
- Ignored elements (via XPath patterns) and ignored attributes are excluded from
  the comparison entirely; ignored elements are kept unchanged from A.
- Comments and processing instructions are not compared; the merged document
  keeps those of A. Elements taken from B are appended after A's children within
  their parent (order is insignificant to this tool).
- Selection defaults: "only in A" differences default to *Take A*, "only in B"
  default to *Take B* — an additive merge. "Take both" keeps the single existing
  version (with two-file comparison there is no second copy to keep).
- Sessions are memory-only and expire after 1 hour (or when the server stops).

## REST API

All endpoints are local-only.

| Method | Path                          | Description                                          |
| ------ | ----------------------------- | ---------------------------------------------------- |
| POST   | `/api/upload`                 | multipart `file_a`, `file_b` → `session_id` + file info |
| POST   | `/api/compare`                | `{session_id, options}` → diff tree, entries, summary |
| POST   | `/api/merge`                  | `{session_id, selections, marking, preview}` → merged XML + report |
| GET    | `/api/download/{session_id}/{kind}` | download `merged.xml`, `merge_report.json`, `merge_report.html` |
| GET    | `/api/health`                 | health check                                         |

Compare options:

```json
{
  "ns_mode": "uri",        // "uri" | "prefix" | "local"
  "normalize_ws": true,
  "ignore_attrs": ["timestamp", "generatedId"],
  "ignore_xpaths": ["/config/generated", "//logs"]
}
```

Merge selections map a difference id (from `/api/compare`) to one of
`take_a`, `take_b`, `take_both`, `skip`. Missing ids fall back to the defaults
above. `marking`: `{"mode": "none" | "attribute" | "comment", "attribute_name": "data-merge-source"}`.

## Project structure

```
SemXMLDiff/
├── backend/
│   ├── main.py        # FastAPI app + REST endpoints
│   ├── signature.py   # canonical signatures, options, ignore matcher
│   ├── diff.py        # multiset diff engine + JSON payload
│   ├── merge.py       # merge engine, source marking, reports
│   ├── session.py     # in-memory session store
│   └── models.py      # request schemas
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── tests/             # pytest suite (engine + API)
├── requirements.txt
├── requirements-dev.txt
├── run.sh / run.bat
└── docs/PRD.md
```

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

## Known limitations (MVP)

- No key/id-based "modified element" matching (see the PRD, section 6.4).
- Two-file comparison only; no project history or saved sessions.
- Elements taken from B are appended at the end of their parent (order is
  insignificant by design).
- Very large files: the interactive tree is capped; use "Only show differences"
  for a flat list of every difference.
