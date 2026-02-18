#!/usr/bin/env python3
import os, json, hashlib, re
from datetime import datetime, timezone

BASE = "/home/agent/workspace"
OUT = os.path.join(BASE, "outputs")
GRAPH = os.path.join(OUT, "graph.json")

MAX_OUTPUTS = 120

ROLE_ORDER = ["pm", "research", "coder", "qa", "ops", "misc"]
ROLE_LABEL = {
    "pm": "PM",
    "research": "Research",
    "coder": "Coder",
    "qa": "QA",
    "ops": "Ops",
    "misc": "Misc",
}

# detecta rol por prefijo del nombre de output
# ej: coder_index3__2026-02-10_15-12-17.md -> coder
ROLE_RE = re.compile(r"^(pm|research|coder|qa|ops)_[^/]+__\d{4}-\d{2}-\d{2}[_-]\d{2}[-_]\d{2}[-_]\d{2}\.md$")

def nid(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def detect_role(filename: str) -> str:
    m = ROLE_RE.match(filename)
    if m:
        return m.group(1)
    # fallback simple: prefijo antes del primer "_"
    prefix = filename.split("_", 1)[0].lower()
    if prefix in ("pm","research","coder","qa","ops"):
        return prefix
    return "misc"

def main():
    os.makedirs(OUT, exist_ok=True)

    # listar outputs .md
    items = []
    for name in os.listdir(OUT):
        if not name.endswith(".md"):
            continue
        full = os.path.join(OUT, name)
        try:
            st = os.stat(full)
            items.append((name, st.st_size, int(st.st_mtime)))
        except:
            pass

    # más nuevos primero
    items.sort(key=lambda x: x[2], reverse=True)
    items = items[:MAX_OUTPUTS]

    nodes = []
    edges = []

    # nodo agente
    agent_id = nid("agent:openclaw")
    nodes.append({"id": agent_id, "label": "openclaw", "kind": "agent", "state": "active"})

    # nodos de roles + cadena jerárquica
    role_id = {}
    prev = None
    for r in ROLE_ORDER:
        rid = nid(f"role:{r}")
        role_id[r] = rid
        nodes.append({"id": rid, "label": ROLE_LABEL.get(r, r), "kind": "role"})
        # agente -> PM (inicio)
        if r == "pm":
            edges.append({"from": agent_id, "to": rid, "type": "manages", "label": ""})
        # cadena PM -> Research -> Coder -> QA -> Ops -> Misc
        if prev is not None:
            edges.append({"from": role_id[prev], "to": rid, "type": "handoff", "label": ""})
        prev = r

    # outputs colgando del rol
    # además: “next” entre outputs del mismo rol (mtime asc) para mostrar flujo dentro del rol
    by_role = {r: [] for r in ROLE_ORDER}

    for (name, size, mtime) in items:
        r = detect_role(name)
        oid = nid(f"output:{name}")
        # label corto para UI
        short = name.replace(".md","")
        if len(short) > 34:
            short = short[:34] + "…"

        nodes.append({
            "id": oid,
            "label": short,
            "kind": "output",
            "state": "done",
            "size": size,
            "mtime": mtime,
            "role": r
        })

        edges.append({"from": role_id[r], "to": oid, "type": "produces", "label": ""})
        by_role[r].append((oid, mtime))

    # cadena interna por rol (opcional)
    for r, outs in by_role.items():
        outs_sorted = sorted(outs, key=lambda x: x[1])  # mtime asc
        for (a, _), (b, _) in zip(outs_sorted, outs_sorted[1:]):
            edges.append({"from": a, "to": b, "type": "next", "label": ""})

    payload = {"nodes": nodes, "edges": edges, "ts": datetime.now(timezone.utc).isoformat()}
    with open(GRAPH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

if __name__ == "__main__":
    main()
