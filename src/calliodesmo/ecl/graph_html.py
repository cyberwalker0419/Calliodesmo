"""关系图 HTML 可视化：把 cognify 消解后的图渲染为单文件 vis.js 网络图。"""

from __future__ import annotations

import json

_TYPE_COLORS = {
    "organization": "#3b82f6",
    "person": "#ef4444",
    "location": "#10b981",
    "model": "#8b5cf6",
    "unit": "#f59e0b",
    "event": "#ec4899",
    "document": "#6366f1",
    "technology": "#14b8a6",
}
_DEFAULT_COLOR = "#64748b"


def _type_color(t: str | None) -> str:
    return _TYPE_COLORS.get((t or "").lower(), _DEFAULT_COLOR)


def _node_obj(n) -> str:
    title = (n.type or "其他") + "\n" + (n.description or "")[:120]
    parts = [
        ("id", json.dumps(n.name, ensure_ascii=False)),
        ("label", json.dumps(n.name[:24], ensure_ascii=False)),
        ("group", json.dumps(n.type or "other", ensure_ascii=False)),
        ("title", json.dumps(title, ensure_ascii=False)),
        ("color", json.dumps(_type_color(n.type), ensure_ascii=False)),
        ("shape", json.dumps("dot")),
        ("size", "16"),
    ]
    return "{" + ", ".join(f"{k}: {v}" for k, v in parts) + "}"


def _edge_obj(e) -> str:
    parts = [
        ("from", json.dumps(e.source, ensure_ascii=False)),
        ("to", json.dumps(e.target, ensure_ascii=False)),
        ("label", json.dumps((e.type or "")[:20], ensure_ascii=False)),
        ("arrows", json.dumps("to")),
    ]
    return "{" + ", ".join(f"{k}: {v}" for k, v in parts) + "}"


def render_graph_html(nodes: dict, edges: list, path: str) -> None:
    """生成单文件 vis.js 网络图 HTML（CDN 引入，浏览器直接打开）。"""
    nodes_js = ",\n".join(_node_obj(n) for n in nodes.values())
    edges_js = ",\n".join(_edge_obj(e) for e in edges)
    colors_js = json.dumps(_TYPE_COLORS, ensure_ascii=False)
    dot = "\u25cf"
    html = (
        "<!DOCTYPE html>\n"
        '<html lang="zh"><head><meta charset="utf-8">'
        "<title>Calliodesmo \u5173\u7cfb\u56fe</title>\n"
        '<script src="https://unpkg.com/vis-network/standalone/umd/'
        'vis-network.min.js"></script>\n'
        "<style>html,body,#net{height:100%;margin:0}#net{background:#0f172a}"
        "#legend{position:fixed;top:8px;left:8px;background:rgba(15,23,42,.8);"
        "color:#e2e8f0;padding:8px 12px;border-radius:6px;font:13px/1.6 system-ui}"
        "</style></head>\n"
        '<body><div id="legend"></div><div id="net"></div><script>\n'
        "var nodes=new vis.DataSet([\n" + nodes_js + "\n]);\n"
        "var edges=new vis.DataSet([\n" + edges_js + "\n]);\n"
        'new vis.Network(document.getElementById("net"),{nodes:nodes,edges:edges},\n'
        '  {nodes:{shape:"dot",font:{color:"#e2e8f0"}},\n'
        '   edges:{font:{color:"#94a3b8",size:11},'
        'color:{color:"#475569",highlight:"#38bdf8"}},\n'
        "   physics:{stabilization:{iterations:200}}});\n"
        "var colors=" + colors_js + ";\n"
        "var legend=Object.entries(colors).map(([k,v])=>"
        "'<span style=\"color:'+v+'\">" + dot + "</span> '+k)"
        ".join('&nbsp;&nbsp;');\n"
        "document.getElementById('legend').innerHTML='\u5b9e\u4f53\u7c7b\u578b\uff1a'"
        '+legend+\' <span style="color:#64748b">' + dot + "</span> \u5176\u4ed6';\n"
        "</script></body></html>\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
