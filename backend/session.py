"""In-memory session storage (files are never persisted to disk)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

from lxml import etree

from .diff import DiffResult


@dataclass
class Session:
    id: str
    created: float
    name_a: str
    name_b: str
    size_a: int
    size_b: int
    data_a: bytes
    data_b: bytes
    tree_a: Optional[etree._Element] = None
    tree_b: Optional[etree._Element] = None
    root_a: str = ""
    root_b: str = ""
    element_count_a: int = 0
    element_count_b: int = 0
    compare_result: Optional[DiffResult] = None
    merged_xml: Optional[str] = None
    merged_bytes: Optional[bytes] = None
    report_json: Optional[bytes] = None
    report_html: Optional[bytes] = None


class SessionStore:
    def __init__(self, ttl_seconds: int = 3600, max_sessions: int = 32):
        self._sessions: Dict[str, Session] = {}
        self.ttl = ttl_seconds
        self.max = max_sessions

    def create(self, name_a, name_b, data_a: bytes, data_b: bytes) -> Session:
        self._evict()
        session = Session(
            id=uuid.uuid4().hex,
            created=time.time(),
            name_a=name_a,
            name_b=name_b,
            size_a=len(data_a),
            size_b=len(data_b),
            data_a=data_a,
            data_b=data_b,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        self._evict()
        return self._sessions.get(session_id)

    def clear(self):
        self._sessions.clear()

    def _evict(self):
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.created > self.ttl]
        for sid in expired:
            del self._sessions[sid]
        while len(self._sessions) > self.max:
            oldest = min(self._sessions, key=lambda sid: self._sessions[sid].created)
            del self._sessions[oldest]
