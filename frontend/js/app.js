"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  sessionId: null,
  fileA: null,
  fileB: null,
  compare: null,
  selections: {},
  previewTimer: null,
  markingMode: "none",
};

function defaultAction(entry) {
  if (entry.side === "b") return "take_b";
  return "take_a";
}

async function api(path, options) {
  const res = await fetch(path, options);
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    let msg = `Request failed (HTTP ${res.status})`;
    if (data && data.detail) {
      if (typeof data.detail === "string") msg = data.detail;
      else if (Array.isArray(data.detail)) msg = data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      else if (data.detail.error) msg = data.detail.error;
    }
    throw new Error(msg);
  }
  return data;
}

function toast(message, isError) {
  const box = $("#toast-container");
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

function setError(sel, message) {
  const banner = $(sel);
  banner.textContent = message || "";
  banner.hidden = !message;
}

function showStep(name) {
  ["step-upload", "step-diff", "step-result"].forEach((id) => {
    $(`#${id}`).hidden = id !== name;
  });
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(2)} MB`;
}

function splitList(value) {
  return value.split(",").map((s) => s.trim()).filter(Boolean);
}

function truncate(value, max) {
  if (value == null) return "";
  const text = String(value);
  if (text.length <= max) return text;
  return text.slice(0, max) + "\u2026";
}

function initDropzones() {
  ["a", "b"].forEach((side) => {
    const dz = $(`#dz-${side}`);
    const input = $(`#file-${side}`);
    dz.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
      if (input.files.length) setFile(side, input.files[0]);
    });
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("dragover");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
      const file = e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) setFile(side, file);
    });
  });
}

function setFile(side, file) {
  if (side === "a") state.fileA = file;
  else state.fileB = file;
  const info = $(`#file-info-${side}`);
  info.hidden = false;
  info.textContent = `${file.name} (${formatBytes(file.size)})`;
  $(`#dz-${side}`).classList.add("has-file");
  $("#btn-compare").disabled = !(state.fileA && state.fileB);
}

async function doCompare() {
  const btn = $("#btn-compare");
  btn.disabled = true;
  $("#compare-status").textContent = "Uploading and parsing\u2026";
  setError("#upload-error", "");
  try {
    const form = new FormData();
    form.append("file_a", state.fileA);
    form.append("file_b", state.fileB);
    const up = await api("/api/upload", { method: "POST", body: form });
    state.sessionId = up.session_id;
    $("#compare-status").textContent = "Comparing\u2026";
    const data = await api("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        options: {
          ns_mode: $("#opt-ns").value,
          normalize_ws: $("#opt-ws").checked,
          ignore_attrs: splitList($("#opt-ignore-attrs").value),
          ignore_xpaths: splitList($("#opt-ignore-xpaths").value),
        },
      }),
    });
    $("#compare-status").textContent = "";
    state.compare = data;
    state.selections = {};
    if (data.root_diff) state.selections.root = "take_a";
    data.entries.forEach((entry) => {
      state.selections[entry.id] = defaultAction(entry);
    });
    renderDiff(data);
  } catch (err) {
    setError("#upload-error", err.message);
    toast(err.message, true);
  } finally {
    btn.disabled = !(state.fileA && state.fileB);
  }
}

function renderChips(container, defs) {
  container.innerHTML = "";
  defs.forEach(([label, value, cls]) => {
    const chip = document.createElement("div");
    chip.className = "chip " + (cls || "");
    const v = document.createElement("span");
    v.className = "chip-value";
    v.textContent = value;
    const l = document.createElement("span");
    l.className = "chip-label";
    l.textContent = label;
    chip.appendChild(v);
    chip.appendChild(l);
    container.appendChild(chip);
  });
}

function renderDiff(data) {
  renderChips($("#summary-chips"), [
    ["Elements in A", data.summary.total_a],
    ["Elements in B", data.summary.total_b],
    ["Common", data.summary.common],
    ["Only in A", data.summary.only_a, "chip-a"],
    ["Only in B", data.summary.only_b, "chip-b"],
    ...(data.summary.ignored_a || data.summary.ignored_b
      ? [["Ignored (A/B)", `${data.summary.ignored_a}/${data.summary.ignored_b}`, "chip-muted"]]
      : []),
  ]);
  $("#identical-note").hidden = !data.identical;
  renderTreeView(data, $("#opt-only-diffs").checked);
  showStep("step-diff");
  updatePreview();
}

function renderTreeView(data, flat) {
  const container = $("#diff-tree");
  container.innerHTML = "";
  container.classList.toggle("flat", flat);

  if (data.root_diff) container.appendChild(buildRootDiffRow(data.root_diff));

  if (flat) {
    data.entries.forEach((entry) => container.appendChild(buildEntryRow(entry)));
  } else {
    data.root_entries.forEach((entry) => container.appendChild(buildEntryRow(entry)));
    if (data.tree) container.appendChild(buildTreeNode(data.tree));
    if (data.truncated) {
      const note = document.createElement("div");
      note.className = "note";
      note.textContent = "The tree is too large to render fully \u2014 enable \u201cOnly show differences\u201d for a flat list of every difference.";
      container.appendChild(note);
    }
  }
  if (!data.entries.length && !data.root_diff) {
    const note = document.createElement("div");
    note.className = "note";
    note.textContent = "No differences found \u2014 the merged result will be identical to the input.";
    container.appendChild(note);
  }
}

function buildTreeNode(node) {
  const wrap = document.createElement("div");
  wrap.className = "tree-node common-node";
  const header = document.createElement("div");
  header.className = "tree-header";

  const toggle = document.createElement("button");
  toggle.className = "tree-toggle";
  toggle.textContent = node.children && node.children.length ? "\u25be" : "\u00b7";
  header.appendChild(toggle);

  const tag = document.createElement("code");
  tag.className = "tree-tag";
  tag.textContent = `<${node.tag}>`;
  header.appendChild(tag);

  const path = document.createElement("span");
  path.className = "tree-path";
  path.textContent = node.path_a;
  header.appendChild(path);

  const count = document.createElement("span");
  count.className = "tree-count";
  count.textContent = node.children && node.children.length ? `${node.children.length} child(ren)` : "";
  header.appendChild(count);

  wrap.appendChild(header);

  const body = document.createElement("div");
  body.className = "tree-children";
  (node.children || []).forEach((child) => {
    body.appendChild(child.status === "common" ? buildTreeNode(child) : buildLeafRow(child));
  });
  wrap.appendChild(body);

  header.addEventListener("click", () => {
    wrap.classList.toggle("collapsed");
    toggle.textContent = wrap.classList.contains("collapsed") ? "\u25b8" : "\u25be";
  });
  return wrap;
}

function buildLeafRow(node) {
  return buildEntryRow({
    id: node.id,
    side: node.status === "only_a" ? "a" : "b",
    kind: "element",
    path: node.path,
    tag: node.tag,
    snippet: node.snippet,
    subtree_count: node.subtree_count,
  });
}

function buildRootDiffRow(rootDiff) {
  const row = document.createElement("div");
  row.className = "entry side-pair";

  const main = document.createElement("div");
  main.className = "entry-main";
  const badge = document.createElement("span");
  badge.className = "badge badge-pair";
  badge.textContent = "Root elements differ";
  main.appendChild(badge);
  const detail = document.createElement("span");
  detail.className = "entry-detail";
  detail.textContent = `A: <${rootDiff.tag_a}> \u00b7 B: <${rootDiff.tag_b}>`;
  main.appendChild(detail);
  row.appendChild(main);

  const choices = document.createElement("div");
  choices.className = "choices";
  [["take_a", "Use A"], ["take_b", "Use B"]].forEach(([value, label]) => {
    choices.appendChild(makeChoice(row, "root", value, label));
  });
  row.appendChild(choices);
  return row;
}

function badgeText(entry) {
  if (entry.side === "a") return "Only in A";
  if (entry.side === "b") return "Only in B";
  return "Differs";
}

function detailText(entry) {
  if (entry.kind === "attr_pair") return `A="${entry.value_a}" \u00b7 B="${entry.value_b}"`;
  if (entry.kind === "attr") return `value: ${entry.value}`;
  if (entry.kind === "text_pair") return `A="${truncate(entry.value_a, 80)}" \u00b7 B="${truncate(entry.value_b, 80)}"`;
  const parts = [];
  if (entry.snippet) parts.push(`"${truncate(entry.snippet, 60)}"`);
  if (entry.attrs) {
    const attrText = Object.entries(entry.attrs).slice(0, 3)
      .map(([k, v]) => `${k}="${truncate(v, 20)}"`).join(" ");
    if (attrText) parts.push(attrText);
  }
  if (entry.subtree_count > 1) parts.push(`${entry.subtree_count} elements`);
  return parts.join(" \u00b7 ");
}

function choiceLabel(action) {
  return { take_a: "Take A", take_b: "Take B", take_both: "Take both", skip: "Skip" }[action];
}

function makeChoice(row, id, action, label) {
  const l = document.createElement("label");
  l.className = "choice";
  const radio = document.createElement("input");
  radio.type = "radio";
  radio.name = `sel-${id}`;
  radio.value = action;
  radio.checked = state.selections[id] === action;
  radio.addEventListener("change", () => {
    state.selections[id] = action;
    row.classList.toggle("choice-skip", action === "skip");
    schedulePreview();
  });
  const span = document.createElement("span");
  span.textContent = label;
  l.appendChild(radio);
  l.appendChild(span);
  return l;
}

function buildEntryRow(entry) {
  const row = document.createElement("div");
  row.className = "entry side-" + (entry.side || "pair");
  if (state.selections[entry.id] === "skip") row.classList.add("choice-skip");

  const main = document.createElement("div");
  main.className = "entry-main";
  const badge = document.createElement("span");
  badge.className = "badge badge-" + (entry.side === "a" ? "a" : entry.side === "b" ? "b" : "pair");
  badge.textContent = badgeText(entry);
  main.appendChild(badge);

  const path = document.createElement("code");
  path.className = "entry-path";
  path.textContent = entry.path;
  main.appendChild(path);

  const tag = document.createElement("code");
  tag.className = "entry-tag";
  tag.textContent = entry.kind === "element" ? `<${entry.tag}>` : entry.kind === "text_pair" ? "text()" : `@${entry.tag}`;
  main.appendChild(tag);

  const detail = document.createElement("span");
  detail.className = "entry-detail";
  detail.textContent = detailText(entry);
  main.appendChild(detail);
  row.appendChild(main);

  const choices = document.createElement("div");
  choices.className = "choices";
  ["take_a", "take_b", "take_both", "skip"].forEach((action) => {
    choices.appendChild(makeChoice(row, entry.id, action, choiceLabel(action)));
  });
  row.appendChild(choices);
  return row;
}

function applyBulk(action) {
  if (!state.compare) return;
  state.compare.entries.forEach((entry) => {
    if (action === "defaults") state.selections[entry.id] = defaultAction(entry);
    else state.selections[entry.id] = action;
  });
  if (state.compare.root_diff) state.selections.root = action === "take_b" ? "take_b" : "take_a";
  renderTreeView(state.compare, $("#opt-only-diffs").checked);
  updatePreview();
}

function currentSelections() {
  const selections = { ...state.selections };
  if (state.compare && state.compare.root_diff) selections.root = state.selections.root || "take_a";
  return selections;
}

function schedulePreview() {
  clearTimeout(state.previewTimer);
  state.previewTimer = setTimeout(updatePreview, 400);
}

async function updatePreview() {
  if (!state.compare) return;
  try {
    const data = await api("/api/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        selections: currentSelections(),
        marking: { mode: state.markingMode },
        preview: true,
      }),
    });
    $("#preview-xml").textContent = truncate(data.merged_xml, 300000);
    const s = data.report.summary;
    $("#preview-stats").textContent =
      `From A: ${s.elements_included_from_a} \u00b7 From B: ${s.elements_included_from_b} \u00b7 Skipped: ${s.elements_skipped} \u00b7 Common: ${s.common}`;
  } catch (err) {
    $("#preview-xml").textContent = "";
    $("#preview-stats").textContent = "Preview failed: " + err.message;
  }
}

async function doMerge() {
  const btn = $("#btn-merge");
  btn.disabled = true;
  setError("#diff-error", "");
  try {
    const data = await api("/api/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        selections: currentSelections(),
        marking: { mode: state.markingMode },
        preview: false,
      }),
    });
    renderResult(data);
  } catch (err) {
    setError("#diff-error", err.message);
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

function renderResult(data) {
  const s = data.report.summary;
  renderChips($("#result-chips"), [
    ["Elements from A", s.elements_included_from_a, "chip-a"],
    ["Elements from B", s.elements_included_from_b, "chip-b"],
    ["Skipped", s.elements_skipped, "chip-muted"],
    ["Common", s.common],
  ]);
  const dl = $("#download-links");
  dl.innerHTML = "";
  [
    [data.downloads.xml, "Download merged XML", "primary"],
    [data.downloads.json, "Merge report (JSON)", ""],
    [data.downloads.html, "Merge report (HTML)", ""],
  ].forEach(([href, label, cls]) => {
    const a = document.createElement("a");
    a.className = "btn " + cls;
    a.href = href;
    a.textContent = label;
    dl.appendChild(a);
  });
  $("#result-xml").textContent = truncate(data.merged_xml, 300000);
  showStep("step-result");
  window.scrollTo(0, 0);
}

document.addEventListener("DOMContentLoaded", () => {
  initDropzones();
  $("#btn-compare").addEventListener("click", doCompare);
  $("#btn-back-upload").addEventListener("click", () => showStep("step-upload"));
  $("#btn-restart").addEventListener("click", () => {
    state.compare = null;
    state.sessionId = null;
    state.selections = {};
    showStep("step-upload");
  });
  $("#opt-only-diffs").addEventListener("change", () => {
    if (state.compare) renderTreeView(state.compare, $("#opt-only-diffs").checked);
  });
  $("#opt-marking").addEventListener("change", (e) => {
    state.markingMode = e.target.value;
    schedulePreview();
  });
  $("#bulk-a").addEventListener("click", () => applyBulk("take_a"));
  $("#bulk-b").addEventListener("click", () => applyBulk("take_b"));
  $("#bulk-both").addEventListener("click", () => applyBulk("defaults"));
  $("#bulk-skip").addEventListener("click", () => applyBulk("skip"));
  $("#btn-merge").addEventListener("click", doMerge);
});
