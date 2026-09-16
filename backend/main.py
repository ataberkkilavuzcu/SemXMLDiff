"""SemXMLDiff local web application (FastAPI + lxml)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from lxml import etree

from .diff import ACTIONS, compare_trees, diff_payload
from .merge import MarkingOptions, apply_merge, render_html_report
from .models import CompareRequest, MergeRequest
from .session import SessionStore
from .signature import CompareOptions, display_name

sys.setrecursionlimit(20000)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
HOST = os.environ.get("SEMXMLDIFF_HOST", "127.0.0.1")
PORT = int(os.environ.get("SEMXMLDIFF_PORT", "8765"))

store = SessionStore()


def parse_xml(data: bytes, label: str):
    parser = etree.XMLParser(recover=False, resolve_entities=False, no_network=True, huge_tree=True)
    try:
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        line = column = None
        if exc.error_log:
            line = exc.error_log[0].line
            column = (exc.error_log[0].column or 0) + 1
        raise HTTPException(status_code=400, detail={
            "error": f"Invalid XML in {label}: {exc.msg or str(exc)}",
            "file": label,
            "line": line,
            "column": column,
        })
    except (ValueError, etree.LxmlError) as exc:
        raise HTTPException(status_code=400, detail={"error": f"Invalid XML in {label}: {exc}"})


@asynccontextmanager
async def lifespan(_app):
    if os.environ.get("SEMXMLDIFF_NO_BROWSER") != "1":
        def _open_browser():
            time.sleep(1.0)
            webbrowser.open(f"http://{HOST}:{PORT}/")
        threading.Thread(target=_open_browser, daemon=True).start()
    yield
    store.clear()


app = FastAPI(title="SemXMLDiff", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def api_health():
    return {"status": "ok", "tool": "SemXMLDiff", "version": "0.1.0"}


@app.post("/api/upload")
async def api_upload(file_a: UploadFile = File(...), file_b: UploadFile = File(...)):
    data_a = await file_a.read()
    data_b = await file_b.read()
    if not data_a or not data_a.strip():
        raise HTTPException(status_code=400, detail={"error": "File A is empty"})
    if not data_b or not data_b.strip():
        raise HTTPException(status_code=400, detail={"error": "File B is empty"})
    name_a = file_a.filename or "file_a.xml"
    name_b = file_b.filename or "file_b.xml"
    tree_a = parse_xml(data_a, f"A ({name_a})")
    tree_b = parse_xml(data_b, f"B ({name_b})")
    session = store.create(name_a, name_b, data_a, data_b)
    session.tree_a = tree_a
    session.tree_b = tree_b
    session.root_a = display_name(tree_a)
    session.root_b = display_name(tree_b)
    session.element_count_a = sum(1 for _ in tree_a.iter())
    session.element_count_b = sum(1 for _ in tree_b.iter())
    return {
        "session_id": session.id,
        "files": {
            "a": {
                "name": name_a,
                "size": len(data_a),
                "root_tag": session.root_a,
                "element_count": session.element_count_a,
            },
            "b": {
                "name": name_b,
                "size": len(data_b),
                "root_tag": session.root_b,
                "element_count": session.element_count_b,
            },
        },
    }


@app.post("/api/compare")
def api_compare(req: CompareRequest):
    session = _get_session(req.session_id)
    opts = CompareOptions(
        ns_mode=req.options.ns_mode,
        normalize_ws=req.options.normalize_ws,
        ignore_attrs={a.strip() for a in req.options.ignore_attrs if a.strip()},
        ignore_xpaths=[p.strip() for p in req.options.ignore_xpaths if p.strip()],
    )
    try:
        opts.validate()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)})
    session.tree_a = parse_xml(session.data_a, f"A ({session.name_a})")
    session.tree_b = parse_xml(session.data_b, f"B ({session.name_b})")
    result = compare_trees(session.tree_a, session.tree_b, opts)
    session.compare_result = result
    return diff_payload(result, session.id)


@app.post("/api/merge")
def api_merge(req: MergeRequest):
    session = _get_session(req.session_id)
    if session.compare_result is None:
        raise HTTPException(status_code=400, detail={"error": "Run /api/compare before merging"})
    bad = sorted({v for k, v in req.selections.items() if k != "root" and v not in ACTIONS})
    if bad:
        raise HTTPException(status_code=400, detail={"error": f"Invalid selection action(s): {bad}"})
    marking = MarkingOptions(mode=req.marking.mode, attribute_name=req.marking.attribute_name)
    merged_xml, report = apply_merge(
        session.tree_a,
        session.tree_b,
        (session.name_a, session.name_b),
        session.compare_result,
        req.selections,
        marking,
    )
    if req.preview:
        return {"preview": True, "merged_xml": merged_xml, "report": report}
    session.merged_xml = merged_xml
    session.merged_bytes = merged_xml.encode("utf-8")
    session.report_json = json.dumps(report, indent=2).encode("utf-8")
    session.report_html = render_html_report(report).encode("utf-8")
    base = f"/api/download/{session.id}"
    return {
        "preview": False,
        "merged_xml": merged_xml,
        "report": report,
        "downloads": {
            "xml": f"{base}/merged.xml",
            "json": f"{base}/merge_report.json",
            "html": f"{base}/merge_report.html",
        },
    }


@app.get("/api/download/{session_id}/{kind}")
def api_download(session_id: str, kind: str):
    session = _get_session(session_id)
    files = {
        "merged.xml": (session.merged_bytes, "merged.xml", "application/xml"),
        "merge_report.json": (session.report_json, "merge_report.json", "application/json"),
        "merge_report.html": (session.report_html, "merge_report.html", "text/html"),
    }
    if kind not in files:
        raise HTTPException(status_code=404, detail={"error": f"Unknown download kind: {kind}"})
    content, filename, media_type = files[kind]
    if content is None:
        raise HTTPException(status_code=404, detail={"error": "Merge result not available"})
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _get_session(session_id: str):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"error": "Unknown or expired session"})
    return session


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
