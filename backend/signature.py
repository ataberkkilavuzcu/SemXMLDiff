"""Canonical signature computation for order-independent XML comparison."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List, Set

from lxml import etree


NS_MODES = ("uri", "prefix", "local")


def normalize_text(value, normalize):
    if value is None:
        return ""
    if not normalize:
        return value
    stripped = value.strip()
    if stripped == value and not any(w in value for w in ("  ", "\n", "\t", "\r")):
        return value
    return " ".join(value.split())


def localname(name):
    if not name.startswith("{") and ":" not in name:
        return name
    return name.rsplit("}", 1)[-1].split(":", 1)[-1]


def tag_key(el, ns_mode):
    q = etree.QName(el)
    return tag_key_from_qname(q, el, ns_mode)


def tag_key_from_qname(q, el, ns_mode):
    if ns_mode == "local":
        return q.localname
    if ns_mode == "prefix":
        return f"{el.prefix}:{q.localname}" if el.prefix else q.localname
    return f"{{{q.namespace}}}{q.localname}" if q.namespace else q.localname


def attr_key(el, name, ns_mode):
    if ":" not in name and not name.startswith("{"):
        return name
    q = etree.QName(el, name)
    if ns_mode == "local":
        return q.localname
    if ns_mode == "prefix":
        return f"{q.prefix}:{q.localname}" if q.prefix else q.localname
    return f"{{{q.namespace}}}{q.localname}" if q.namespace else q.localname


def display_name(el):
    q = etree.QName(el)
    return f"{el.prefix}:{q.localname}" if el.prefix else q.localname


class IgnoreMatcher:
    """Matches element plain paths against simple XPath-like patterns."""

    def __init__(self, patterns):
        self.anchored = []
        self.anywhere = []
        for raw in patterns or []:
            pattern = (raw or "").strip()
            if not pattern:
                continue
            anywhere = pattern.startswith("//")
            segments = [s for s in pattern.strip("/").split("/") if s]
            if not segments:
                continue
            (self.anywhere if anywhere else self.anchored).append(segments)

    def matches(self, segments):
        for pattern in self.anchored:
            if _segments_match(segments, pattern):
                return True
        for pattern in self.anywhere:
            if len(segments) < len(pattern):
                continue
            for i in range(len(segments) - len(pattern) + 1):
                if _segments_match(segments[i:i + len(pattern)], pattern):
                    return True
        return False


def _segments_match(segments, pattern):
    return len(segments) == len(pattern) and all(
        p == "*" or p == s for s, p in zip(segments, pattern)
    )


@dataclass
class CompareOptions:
    ns_mode: str = "uri"
    normalize_ws: bool = True
    ignore_attrs: Set[str] = field(default_factory=set)
    ignore_xpaths: List[str] = field(default_factory=list)

    def validate(self):
        if self.ns_mode not in NS_MODES:
            raise ValueError(f"ns_mode must be one of {NS_MODES}, got {self.ns_mode!r}")

    @property
    def ignore_matcher(self):
        return IgnoreMatcher(self.ignore_xpaths)


@dataclass
class ElemInfo:
    sig: str
    tag_key: str
    localname: str
    display: str
    snippet: str
    subtree_count: int
    ignored_count: int
    ignored: bool
    children: List["ElemInfo"] = field(default_factory=list)


def element_children(el):
    return [child for child in el if isinstance(child.tag, str)]


def analyze(el, opts, matcher, segments):
    q = etree.QName(el)
    local = q.localname
    display = f"{el.prefix}:{local}" if el.prefix else local
    tk = tag_key_from_qname(q, el, opts.ns_mode)
    ignored = matcher.matches(segments)
    if ignored:
        count = sum(1 for _ in el.iter())
        return ElemInfo(
            sig="ignored",
            tag_key=tk,
            localname=local,
            display=display,
            snippet=normalize_text(el.text, opts.normalize_ws),
            subtree_count=count,
            ignored_count=count,
            ignored=True,
        )

    parts = [f"tag:{tk}"]
    attr_pairs = []
    for name, value in el.attrib.items():
        if localname(name) in opts.ignore_attrs:
            continue
        attr_pairs.append((attr_key(el, name, opts.ns_mode), normalize_text(value, opts.normalize_ws)))
    attr_pairs.sort()
    for key, value in attr_pairs:
        parts.append(f"@{key}={value}")
    text_norm = normalize_text(el.text, opts.normalize_ws)
    parts.append("text:" + text_norm)
    parts.append("tail:" + normalize_text(el.tail, opts.normalize_ws))

    child_infos = []
    for child in element_children(el):
        child_infos.append(analyze(child, opts, matcher, segments + [child_localname(child.tag)]))
    for info in sorted(child_infos, key=lambda c: c.sig):
        if not info.ignored:
            parts.append("child:" + info.sig)

    subtree = 1
    ignored_sum = 0
    for info in child_infos:
        subtree += info.subtree_count
        ignored_sum += info.ignored_count

    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return ElemInfo(
        sig=digest,
        tag_key=tk,
        localname=local,
        display=display,
        snippet=text_norm[:200],
        subtree_count=subtree,
        ignored_count=ignored_sum,
        ignored=False,
        children=child_infos,
    )


def child_localname(tag):
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
