"""Merge engine: applies user selections and builds the merged document."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from html import escape
from typing import Dict, List, Tuple

from lxml import etree

from .diff import ACTIONS, DiffResult


class MarkingOptions:
    def __init__(self, mode: str = "none", attribute_name: str = "data-merge-source"):
        self.mode = mode
        self.attribute_name = attribute_name


def apply_merge(tree_a, tree_b, names, res: DiffResult, selections: Dict[str, str], marking: MarkingOptions) -> Tuple[str, dict]:
    sel = {k: v for k, v in (selections or {}).items() if isinstance(v, str) and v in ACTIONS}

    records: List[dict] = []
    nodes_a = 0
    nodes_b = 0
    nodes_skipped = 0
    root_choice = None

    if res.root_diff:
        choice = sel.get("root")
        if choice not in ("take_a", "take_b"):
            choice = "take_a"
        merged = copy.deepcopy(tree_a if choice == "take_a" else tree_b)
        root_choice = "A" if choice == "take_a" else "B"
        if choice == "take_a":
            nodes_a = res.summary["total_a"]
        else:
            nodes_b = res.summary["total_b"]
        records.append({
            "id": "root",
            "side": None,
            "kind": "root",
            "path": res.root_diff["path_a"],
            "tag": res.root_diff["tag_a"],
            "value": None,
            "value_a": res.root_diff["tag_a"],
            "value_b": res.root_diff["tag_b"],
            "action": choice,
            "outcome": "included_from_a" if choice == "take_a" else "included_from_b",
            "source": "A" if choice == "take_a" else "B",
        })
    else:
        merged, mapping = _clone_subtree(tree_a)
        for entry in res.root_entries:
            action = sel.get(entry.entry_id, "take_a" if entry.side != "b" else "take_b")
            outcome, source = _apply_root_entry(merged, entry, action)
            records.append(_record(entry, action, outcome, source))
        for entry in res.entries:
            action = sel.get(entry.entry_id, "take_a" if entry.side == "a" else "take_b")
            if entry.side == "a":
                el = mapping.get(id(entry.el))
                if action in ("take_a", "take_both"):
                    outcome, source = "included_from_a", "A"
                    nodes_a += entry.subtree_count
                    _mark(el, "A", marking)
                else:
                    outcome, source = "skipped", None
                    nodes_skipped += entry.subtree_count
                    if el is not None and el.getparent() is not None:
                        el.getparent().remove(el)
            else:
                if action in ("take_b", "take_both"):
                    outcome, source = "included_from_b", "B"
                    nodes_b += entry.subtree_count
                    new_el = copy.deepcopy(entry.el)
                    parent = mapping.get(id(entry.parent_el))
                    parent.append(new_el)
                    _mark(new_el, "B", marking)
                else:
                    outcome, source = "skipped", None
                    nodes_skipped += entry.subtree_count
            records.append(_record(entry, action, outcome, source))

    xml_str = etree.tostring(merged, encoding="utf-8", pretty_print=True, xml_declaration=True).decode("utf-8")

    report = {
        "tool": "SemXMLDiff",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": {"a": names[0], "b": names[1]},
        "options": res.options,
        "marking": {"mode": marking.mode, "attribute_name": marking.attribute_name},
        "root_choice": root_choice,
        "summary": {
            "total_a": res.summary["total_a"],
            "total_b": res.summary["total_b"],
            "common": res.summary["common"],
            "only_a": res.summary["only_a"],
            "only_b": res.summary["only_b"],
            "elements_included_from_a": nodes_a,
            "elements_included_from_b": nodes_b,
            "elements_skipped": nodes_skipped,
        },
        "entries": records,
    }
    return xml_str, report


def _clone_subtree(root):
    new_root = copy.deepcopy(root)
    mapping = {}
    stack_old = [root]
    stack_new = [new_root]
    while stack_old:
        old = stack_old.pop()
        new = stack_new.pop()
        mapping[id(old)] = new
        for old_child, new_child in zip(old, new):
            stack_old.append(old_child)
            stack_new.append(new_child)
    return new_root, mapping


def _apply_root_entry(root, entry, action):
    if entry.kind == "attr_pair":
        name = entry.tag
        if action == "take_b":
            root.set(name, entry.value_b)
            return "included_from_b", "B"
        if action == "skip":
            root.attrib.pop(name, None)
            return "skipped", None
        root.set(name, entry.value_a)
        return "included_from_a", "A"
    if entry.kind == "attr":
        name = entry.tag
        if entry.side == "a":
            if action in ("take_b", "skip"):
                root.attrib.pop(name, None)
                return "skipped", None
            return "included_from_a", "A"
        if action in ("take_b", "take_both"):
            root.set(name, entry.value)
            return "included_from_b", "B"
        return "skipped", None
    if entry.kind == "text_pair":
        if action == "take_b":
            root.text = entry.value_b
            return "included_from_b", "B"
        if action == "skip":
            root.text = None
            return "skipped", None
        root.text = entry.value_a
        return "included_from_a", "A"
    return "skipped", None


def _record(entry, action, outcome, source):
    return {
        "id": entry.entry_id,
        "side": entry.side,
        "kind": entry.kind,
        "path": entry.path,
        "tag": entry.tag,
        "value": entry.value,
        "value_a": entry.value_a,
        "value_b": entry.value_b,
        "action": action,
        "outcome": outcome,
        "source": source,
    }


def _mark(el, source, marking):
    if el is None:
        return
    if marking.mode == "attribute":
        for node in el.iter():
            node.set(marking.attribute_name, source)
    elif marking.mode == "comment":
        el.addprevious(etree.Comment(f" source: {source} "))


def render_html_report(report) -> str:
    summary = report["summary"]
    rows = []
    for entry in report["entries"]:
        if entry.get("value") is not None:
            detail = escape(str(entry["value"]))
        elif entry.get("value_a") is not None:
            detail = f"A: {escape(str(entry['value_a']))} &middot; B: {escape(str(entry['value_b']))}"
        else:
            detail = ""
        cells = [
            escape(str(entry["id"])),
            escape(str(entry["kind"])),
            escape(entry["path"]),
            escape(entry["tag"] or ""),
            escape(entry["action"] or ""),
            escape(entry["outcome"] or ""),
            escape(entry["source"] or ""),
            detail,
        ]
        rows.append("".join(f"<td>{cell}</td>" for cell in cells))
    body = "".join(f"<tr>{row}</tr>" for row in rows)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SemXMLDiff Merge Report</title>
<style>
body {{ font-family: -apple-system, 'Segoe UI', sans-serif; margin: 24px; color: #1f2328; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; text-align: left; vertical-align: top; }}
th {{ background: #f6f8fa; }}
code {{ font-family: Consolas, monospace; font-size: 12px; }}
h1 {{ font-size: 20px; margin-bottom: 4px; }}
.meta {{ color: #57606a; font-size: 13px; }}
.summary {{ display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }}
.summary div {{ border: 1px solid #d0d7de; border-radius: 6px; padding: 10px 16px; min-width: 120px; }}
.summary b {{ display: block; font-size: 20px; }}
</style>
</head>
<body>
<h1>SemXMLDiff &mdash; Merge Report</h1>
<p class="meta">A: <code>{escape(report["files"]["a"])}</code> &middot; B: <code>{escape(report["files"]["b"])}</code></p>
<p class="meta">Generated: {escape(report["generated_at"])} &middot; Source marking: {escape(report["marking"]["mode"])}</p>
<div class="summary">
<div><b>{summary["elements_included_from_a"]}</b>elements from A</div>
<div><b>{summary["elements_included_from_b"]}</b>elements from B</div>
<div><b>{summary["elements_skipped"]}</b>skipped</div>
<div><b>{summary["common"]}</b>common</div>
</div>
<table>
<thead><tr><th>ID</th><th>Kind</th><th>Path</th><th>Tag</th><th>Action</th><th>Outcome</th><th>Source</th><th>Detail</th></tr></thead>
<tbody>{body}</tbody>
</table>
</body>
</html>"""
