"""Order-independent multiset diff engine (docs/PRD.md, section 6)."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from lxml import etree

from .signature import (
    CompareOptions,
    ElemInfo,
    analyze,
    attr_key,
    display_name,
    element_children,
    localname,
    normalize_text,
    tag_key,
)


ACTIONS = ("take_a", "take_b", "take_both", "skip")
MAX_TREE_NODES = 20000


@dataclass
class DiffEntry:
    entry_id: str
    side: Optional[str]
    kind: str
    path: str
    tag: str
    value: Optional[str] = None
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    snippet: Optional[str] = None
    attrs: Optional[dict] = None
    subtree_count: int = 0
    signature: str = ""
    el: Optional[etree._Element] = None
    parent_el: Optional[etree._Element] = None


@dataclass
class DiffResult:
    identical: bool
    root_diff: Optional[dict]
    root_entries: List[DiffEntry]
    entries: List[DiffEntry]
    tree: Optional[dict]
    truncated: bool
    summary: dict
    options: dict
    elapsed_ms: float


def compare_trees(tree_a, tree_b, opts: CompareOptions) -> DiffResult:
    started = time.perf_counter()
    matcher = opts.ignore_matcher
    info_a = analyze(tree_a, opts, matcher, [localname(tree_a.tag)])
    info_b = analyze(tree_b, opts, matcher, [localname(tree_b.tag)])

    entries: List[DiffEntry] = []
    root_entries: List[DiffEntry] = []
    counters = {"a": 0, "b": 0, "r": 0}
    budget = [MAX_TREE_NODES]
    truncated = [False]

    def next_id(prefix):
        counters[prefix] += 1
        return f"{prefix}{counters[prefix]}"

    root_path_a = "/" + localname(tree_a.tag)
    root_path_b = "/" + localname(tree_b.tag)

    root_diff = None
    tree_json = None
    common = 0

    if info_a.tag_key != info_b.tag_key:
        root_diff = {
            "tag_a": display_name(tree_a),
            "tag_b": display_name(tree_b),
            "path_a": root_path_a,
            "path_b": root_path_b,
        }
    else:
        root_entries = _root_content_diff(tree_a, tree_b, opts, root_path_a, root_path_b, next_id)
        children, common_children = _diff_children(
            tree_a, tree_b, info_a, info_b, opts,
            root_path_a, root_path_b, next_id, entries, budget, truncated,
        )
        common = 1 + common_children
        tree_json = {
            "status": "common",
            "tag": display_name(tree_a),
            "path_a": root_path_a,
            "path_b": root_path_b,
            "attrs": dict(tree_a.attrib),
            "snippet": info_a.snippet or None,
            "children": children,
        }

    identical = root_diff is None and not root_entries and not entries

    return DiffResult(
        identical=identical,
        root_diff=root_diff,
        root_entries=root_entries,
        entries=entries,
        tree=tree_json,
        truncated=truncated[0],
        summary={
            "total_a": info_a.subtree_count,
            "total_b": info_b.subtree_count,
            "common": common,
            "only_a": sum(1 for e in entries if e.side == "a"),
            "only_b": sum(1 for e in entries if e.side == "b"),
            "ignored_a": info_a.ignored_count,
            "ignored_b": info_b.ignored_count,
            "root_entries": len(root_entries),
        },
        options={
            "ns_mode": opts.ns_mode,
            "normalize_ws": opts.normalize_ws,
            "ignore_attrs": sorted(opts.ignore_attrs),
            "ignore_xpaths": list(opts.ignore_xpaths),
        },
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
    )


def _root_content_diff(el_a, el_b, opts, path_a, path_b, next_id):
    entries = []

    attrs_a = {}
    for name, value in el_a.attrib.items():
        if localname(name) in opts.ignore_attrs:
            continue
        attrs_a[attr_key(el_a, name, opts.ns_mode)] = (name, value)
    attrs_b = {}
    for name, value in el_b.attrib.items():
        if localname(name) in opts.ignore_attrs:
            continue
        attrs_b[attr_key(el_b, name, opts.ns_mode)] = (name, value)

    for key in sorted(set(attrs_a) | set(attrs_b)):
        in_a = key in attrs_a
        in_b = key in attrs_b
        name_a, value_a = attrs_a[key] if in_a else (None, None)
        name_b, value_b = attrs_b[key] if in_b else (None, None)
        if in_a and in_b and normalize_text(value_a, opts.normalize_ws) == normalize_text(value_b, opts.normalize_ws):
            continue
        entry_id = next_id("r")
        if in_a and in_b:
            entries.append(DiffEntry(
                entry_id=entry_id, side=None, kind="attr_pair",
                path=f"{path_a}/@{name_a}", tag=name_a,
                value_a=value_a, value_b=value_b,
            ))
        elif in_a:
            entries.append(DiffEntry(
                entry_id=entry_id, side="a", kind="attr",
                path=f"{path_a}/@{name_a}", tag=name_a, value=value_a,
            ))
        else:
            entries.append(DiffEntry(
                entry_id=entry_id, side="b", kind="attr",
                path=f"{path_b}/@{name_b}", tag=name_b, value=value_b,
            ))

    text_a = normalize_text(el_a.text, opts.normalize_ws)
    text_b = normalize_text(el_b.text, opts.normalize_ws)
    if text_a != text_b:
        entries.append(DiffEntry(
            entry_id=next_id("r"), side=None, kind="text_pair",
            path=f"{path_a}/text()", tag="text()",
            value_a=text_a or None, value_b=text_b or None,
        ))
    return entries


def _child_infos(el, info, parent_path):
    elements = element_children(el)
    pairs = list(zip(elements, info.children))
    seen = Counter()
    totals = Counter()
    for _, ci in pairs:
        totals[ci.tag_key] += 1
    result = []
    for ce, ci in pairs:
        position = seen[ci.tag_key]
        seen[ci.tag_key] += 1
        if totals[ci.tag_key] > 1:
            path = f"{parent_path}/{ci.localname}[{position + 1}]"
        else:
            path = f"{parent_path}/{ci.localname}"
        result.append((ce, ci, path))
    return result


def _diff_children(el_a, el_b, info_a, info_b, opts, path_a, path_b, next_id, entries, budget, truncated):
    a_items = _child_infos(el_a, info_a, path_a)
    b_items = _child_infos(el_b, info_b, path_b)

    b_by_sig = defaultdict(list)
    for ce, ci, path in b_items:
        if not ci.ignored:
            b_by_sig[ci.sig].append((ce, ci, path))

    matched = Counter()
    children_json = []
    common = 0

    def room():
        return budget[0] > 0

    for ce, ci, path in a_items:
        if ci.ignored:
            continue
        candidates = b_by_sig.get(ci.sig)
        if candidates is not None and matched[ci.sig] < len(candidates):
            be, bi, b_path = candidates[matched[ci.sig]]
            matched[ci.sig] += 1
            sub, sub_common = _diff_children(
                ce, be, ci, bi, opts, path, b_path, next_id, entries, budget, truncated,
            )
            common += 1 + sub_common
            if room():
                budget[0] -= 1
                children_json.append({
                    "status": "common",
                    "tag": ci.display,
                    "path_a": path,
                    "path_b": b_path,
                    "snippet": ci.snippet or None,
                    "children": sub,
                })
            else:
                truncated[0] = True
        else:
            entry_id = next_id("a")
            entries.append(DiffEntry(
                entry_id=entry_id, side="a", kind="element", path=path,
                tag=ci.display, snippet=ci.snippet or None,
                attrs=dict(ce.attrib) if ce.attrib else None,
                subtree_count=ci.subtree_count, signature=ci.sig,
                el=ce, parent_el=el_a,
            ))
            if room():
                budget[0] -= 1
                children_json.append({
                    "status": "only_a", "id": entry_id, "tag": ci.display,
                    "path": path, "attrs": dict(ce.attrib) if ce.attrib else None,
                    "snippet": ci.snippet or None,
                    "subtree_count": ci.subtree_count,
                })
            else:
                truncated[0] = True

    used = Counter()
    for ce, ci, path in b_items:
        if ci.ignored:
            continue
        if used[ci.sig] < matched[ci.sig]:
            used[ci.sig] += 1
            continue
        entry_id = next_id("b")
        entries.append(DiffEntry(
            entry_id=entry_id, side="b", kind="element", path=path,
            tag=ci.display, snippet=ci.snippet or None,
            attrs=dict(ce.attrib) if ce.attrib else None,
            subtree_count=ci.subtree_count, signature=ci.sig,
            el=ce, parent_el=el_a,
        ))
        if room():
            budget[0] -= 1
            children_json.append({
                "status": "only_b", "id": entry_id, "tag": ci.display,
                "path": path, "attrs": dict(ce.attrib) if ce.attrib else None,
                "snippet": ci.snippet or None,
                "subtree_count": ci.subtree_count,
            })
        else:
            truncated[0] = True

    return children_json, common


def _entry_json(entry):
    out = {
        "id": entry.entry_id,
        "side": entry.side,
        "kind": entry.kind,
        "path": entry.path,
        "tag": entry.tag,
    }
    if entry.value is not None:
        out["value"] = entry.value
    if entry.value_a is not None:
        out["value_a"] = entry.value_a
    if entry.value_b is not None:
        out["value_b"] = entry.value_b
    if entry.kind == "element":
        out["attrs"] = entry.attrs
        out["snippet"] = entry.snippet
        out["subtree_count"] = entry.subtree_count
    return out


def diff_payload(result: DiffResult, session_id: str) -> dict:
    return {
        "session_id": session_id,
        "identical": result.identical,
        "summary": result.summary,
        "options": result.options,
        "root_diff": result.root_diff,
        "root_entries": [_entry_json(e) for e in result.root_entries],
        "entries": [_entry_json(e) for e in result.root_entries]
        + [_entry_json(e) for e in result.entries],
        "tree": result.tree,
        "truncated": result.truncated,
        "elapsed_ms": result.elapsed_ms,
    }
