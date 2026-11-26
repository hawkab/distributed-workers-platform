#!/usr/bin/env python3
"""Render the same UML component model with one repository's ownership highlighted."""
import argparse
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
    "gateway": ("Gateway", "HTTPS API | admission & leases | durable receipts"),
    "worker-portable": ("Portable worker", "Node.js / PHP | execution slots | checkpoint & outbox"),
    "worker-android": ("Android worker", "foreground service | execution slots | SQLite & updater"),
    "worker-routeros": ("RouterOS adapter", "ARM64 container | PHP SDK supervisor | persistent mounts"),
    "protocol": ("Protocol", "JSON Schemas | portable JS ABI | effect & artifact contracts"),
    "platform": ("Platform", "deployment recipes | component composition | release CI tools"),
}


def model(component):
    # Fixed positions make ownership variants comparable and keep the SVG legible
    # at README width. Coordinates and routes are part of the editable DOT source.
    lines = [
        '// Generated from platform/tools/render-architecture.py.',
        '// Render with neato -n2 -Tsvg architecture.dot -o architecture.svg.',
        'digraph Fleet {',
        'graph [layout=neato, bgcolor="white", pad="0.25", splines=true, overlap=true,',
        'fontname="DejaVu Sans", fontsize=18, label="Distributed Workers — UML components", labelloc=t];',
        'node [shape=component, style="filled", fillcolor="#f1f4f8", color="#8391a5",',
        'fontcolor="#334155", fontname="DejaVu Sans", fontsize=12, width=3.1, height=1.35, fixedsize=true];',
        'edge [color="#64748b", fontcolor="#475569", fontname="DejaVu Sans", fontsize=10, arrowsize=0.7];',
    ]
    positions = {"protocol": (170, 760), "platform": (550, 760), "gateway": (550, 540),
                 "worker-portable": (170, 260), "worker-android": (550, 260), "worker-routeros": (930, 260)}
    for name, (title, detail) in COMPONENTS.items():
        selected = name == component
        marker = "THIS REPOSITORY" if selected else "other repository"
        label = title + "\\n" + marker + "\\n" + name + "\\n" + detail.replace(" | ", "\\n")
        attrs = 'fillcolor="#e7f0ff", color="#2058ad", fontcolor="#133d78", penwidth=2.5, ' if selected else ''
        x, y = positions[name]
        lines.append('"' + name + '" [' + attrs + 'pos="' + str(x) + ',' + str(y) + '!", label="' + label + '"];')
    lines += [
        'application [shape=box, pos="170,540!", height=0.8, fillcolor="#fffaf0", label="External application\\nsubmit jobs / consume results"];',
        'infrastructure [shape=box3d, pos="930,540!", height=1.5, label="Durable infrastructure\\nPostgreSQL: canonical ledger\\nRabbitMQ: commands + references\\nFilesystem: sealed artifacts"];',
        'source [shape=box, pos="170,45!", height=0.8, fillcolor="#fffaf0", label="External HTTP source\\noperator-selected data"];',
        'releases [shape=folder, pos="930,760!", height=0.8, label="Signed release mirrors\\nGitea → GitFlic → GitHub"];',
        'legend [shape=plain, pos="690,20!", label="Blue + THIS REPOSITORY = owned here\\nGrey = another repository / external infrastructure\\nSolid: runtime   Dashed: contract or reuse   Dotted: deployment/update"];',
    ]
    def edge(a, b, route, label, lp, style="solid", both=False):
        lines.append('"' + a + '" -> "' + b + '" [style=' + style + ', pos="' + route + '", label="' + label + '", lp="' + lp + '"' + (', dir=both' if both else '') + '];')
    edge("application", "gateway", "e,435,540 284,540 330,540 380,540 428,540", "HTTPS", "360,557")
    edge("gateway", "infrastructure", "e,815,540 665,540 710,540 765,540 808,540", "transactions / streams", "740,557")
    edge("worker-portable", "gateway", "e,500,489 170,310 170,410 500,395 500,482", "outbound HTTPS: claim / heartbeat / result", "320,408", both=True)
    edge("worker-android", "gateway", "e,550,489 550,310 550,365 550,425 550,482", "outbound HTTPS", "625,390", both=True)
    edge("worker-routeros", "worker-portable", "e,284,260 930,209 930,135 300,135 291,260", "reuses PHP SDK", "550,155", "dashed")
    edge("worker-portable", "source", "e,170,77 170,209 170,165 170,120 170,84", "HTTP stream", "106,140")
    edge("worker-android", "source", "e,286,45 500,209 500,95 340,45 293,45", "HTTP stream", "390,90")
    edge("protocol", "gateway", "e,490,591 170,709 170,665 490,660 490,598", "wire contract", "330,665", "dashed")
    edge("platform", "gateway", "e,550,591 550,709 550,675 550,630 550,598", "deployment recipes", "640,651", "dotted")
    edge("platform", "releases", "e,815,760 665,760 715,760 760,760 808,760", "release composition", "740,778", "dotted")
    edge("releases", "worker-routeros", "e,1045,260 1045,760 1110,760 1110,260 1052,260", "signed image", "1060,620", "dotted")
    edge("releases", "worker-portable", "e,80,310 815,729 730,670 20,670 20,670 20,580 20,310 73,310", "signed SDK updates", "65,655", "dotted")
    edge("releases", "worker-android", "e,665,280 815,729 760,680 760,380 672,284", "signed APK updates", "780,420", "dotted")
    lines.append('}')
    return "\n".join(lines) + "\n"


def render(component, directory):
    directory.mkdir(parents=True, exist_ok=True)
    text = model(component)
    dot = directory / "architecture.dot"
    dot.write_text(text)
    # The fixed-layout SVG needs only Python. DOT is also supplied for Graphviz
    # users; neither a renderer server nor a network request is required.
    namespace = "http://www.w3.org/2000/svg"
    ET.register_namespace("", namespace)
    def element(parent, name, **attrs):
        return ET.SubElement(parent, "{" + namespace + "}" + name, {k.replace("_", "-"): str(v) for k, v in attrs.items()})
    svg = ET.Element("{" + namespace + "}svg", {"viewBox": "0 0 1180 890", "width": "1180", "height": "890", "role": "img", "aria-labelledby": "title desc"})
    element(svg, "title", id="title").text = "Distributed Workers UML — " + component
    element(svg, "desc", id="desc").text = "Six shared components; this repository is blue and explicitly labelled. Solid runtime links, dashed contracts or reuse, dotted deployment or updates."
    element(svg, "rect", x=0, y=0, width=1180, height=890, fill="white")
    defs = element(svg, "defs")
    for name, path, ref in [("arrow", "M0,-4 L8,0 L0,4 Z", 8), ("back", "M8,-4 L0,0 L8,4 Z", 0)]:
        marker = element(defs, "marker", id=name, viewBox="0 -5 10 10", refX=ref, refY=0, markerWidth=7, markerHeight=7, orient="auto")
        element(marker, "path", d=path, fill="#64748b")
    def point(x, y):
        return float(x) + 25, 840 - float(y)
    def attribute(line, key, default=None):
        match = re.search(r'\b' + key + r'="([^"]*)"', line)
        return match.group(1) if match else default
    def label(parent, value, x, y, size=12, color="#334155", weight="normal"):
        parts = value.split("\\n")
        text = element(parent, "text", x=x, y=y - (len(parts)-1)*8, fill=color, font_family="DejaVu Sans, sans-serif", font_size=size, text_anchor="middle", font_weight=weight)
        for index, part in enumerate(parts):
            element(text, "tspan", x=x, dy=0 if index==0 else 16).text = part
    label(svg, "Distributed Workers — UML component architecture", 590, 24, size=18, weight="bold")
    edges = [line for line in text.splitlines() if ' -> ' in line]
    nodes = [line for line in text.splitlines() if 'pos="' in line and ' -> ' not in line]
    for line in edges:
        raw = attribute(line, "pos").split()
        ending = point(*raw[0].split(",")[1:])
        coordinates = [point(*item.split(",")) for item in raw[1:]]
        path = "M %g,%g" % coordinates[0]
        for offset in range(1, len(coordinates), 3):
            path += " C %g,%g %g,%g %g,%g" % (*coordinates[offset], *coordinates[offset+1], *coordinates[offset+2])
        path += " L %g,%g" % ending
        style = re.search(r'style=(\w+)', line).group(1)
        attrs = {"d": path, "fill": "none", "stroke": "#64748b", "stroke_width": 1.4, "marker_end": "url(#arrow)"}
        if style != "solid":
            attrs["stroke_dasharray"] = "7 5" if style == "dashed" else "2 5"
        if "dir=both" in line:
            attrs["marker_start"] = "url(#back)"
        element(svg, "path", **attrs)
    for line in nodes:
        name = line.split(" [", 1)[0].strip('"')
        x, y = point(*attribute(line, "pos").rstrip("!").split(","))
        value = attribute(line, "label")
        if 'shape=plain' in line:
            label(svg, value, x, y, size=11)
            continue
        selected = name == component
        height = float(re.search(r'height=([.\d]+)', line).group(1))*72 if 'height=' in line else 97.2
        width = 223.2
        element(svg, "rect", x=x-width/2, y=y-height/2, width=width, height=height, rx=2,
                fill="#e7f0ff" if selected else attribute(line,"fillcolor","#f1f4f8"),
                stroke="#2058ad" if selected else "#8391a5", stroke_width=2.5 if selected else 1)
        if name in COMPONENTS:
            for dy in (-10, 5):
                element(svg,"rect",x=x-width/2-5,y=y-height/2+12+dy,width=10,height=7,
                        fill="#e7f0ff" if selected else "#f1f4f8",stroke="#2058ad" if selected else "#8391a5")
        label(svg, value, x, y+4, color="#133d78" if selected else "#334155")
    for line in edges:
        x, y = point(*attribute(line,"lp").split(","))
        value = attribute(line,"label")
        element(svg,"rect",x=x-len(value)*2.65-3,y=y-11,width=len(value)*5.3+6,height=15,fill="white",opacity="0.94")
        label(svg,value,x,y,size=10,color="#475569")
    (directory / "architecture.svg").write_bytes(ET.tostring(svg,encoding="utf-8",xml_declaration=True)+b"\n")
    return hashlib.sha256(text.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=COMPONENTS, default="platform")
    parser.add_argument("--output", type=Path, default=ROOT / "docs")
    parser.add_argument("--workspace", type=Path, help="explicit workspace containing repos/<component>; render all six")
    args = parser.parse_args()
    if args.workspace:
        for name in COMPONENTS:
            destination = args.workspace / "repos" / name
            if not (destination / "README.md").is_file():
                parser.error("workspace does not contain " + name)
        for name in COMPONENTS:
            print(name, render(name, args.workspace / "repos" / name / "docs"))
    else:
        print(args.component, render(args.component, args.output))


if __name__ == "__main__":
    main()
