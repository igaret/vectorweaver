"""
VectorWeaver - offline WYSIWYG SVG vector image editor.
A Dreamweaver-style visual/source editor for SVG files with Photoshop-inspired tools.
No internet access or third-party runtime dependencies are required.
"""

from __future__ import annotations

import copy
import math
import os   
import sys
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET
from xml.dom import minidom

APP_NAME = "VectorWeaver"
APP_AUTHOR = "Garet McCallister"
APP_VERSION = "1.0.0"
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def color_to_hex(rgb: Tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def pretty_xml(element: ET.Element) -> str:
    rough = ET.tostring(element, encoding="utf-8")
    parsed = minidom.parseString(rough)
    pretty = parsed.toprettyxml(indent="  ")
    # minidom emits whitespace-only text nodes as blank lines after round-trips.
    # Remove them so Apply/Refresh does not keep adding empty vertical space.
    lines = [line.rstrip() for line in pretty.splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


def parse_float(value: Optional[str], default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        cleaned = str(value).strip().replace("px", "")
        return float(cleaned)
    except Exception:
        return default


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def extract_css_class_styles(root: ET.Element) -> Dict[str, Dict[str, str]]:
    """Extract simple .class{key:value;} CSS rules from inline SVG style tags."""
    styles: Dict[str, Dict[str, str]] = {}
    for elem in root.iter():
        if local_name(elem.tag) != "style" or not elem.text:
            continue
        css = elem.text
        for chunk in css.split("}"):
            if "{" not in chunk:
                continue
            selector, body = chunk.split("{", 1)
            selector = selector.strip()
            if not selector.startswith("."):
                continue
            class_name = selector[1:].strip()
            values: Dict[str, str] = {}
            for declaration in body.split(";"):
                if ":" in declaration:
                    key, value = declaration.split(":", 1)
                    values[key.strip()] = value.strip()
            if class_name:
                styles[class_name] = values
    return styles


def resolve_style(elem: ET.Element, css_styles: Dict[str, Dict[str, str]], inherited: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    result = dict(inherited or {})
    class_attr = elem.attrib.get("class", "")
    for cls in class_attr.split():
        result.update(css_styles.get(cls, {}))
    inline = elem.attrib.get("style", "")
    for declaration in inline.split(";"):
        if ":" in declaration:
            key, value = declaration.split(":", 1)
            result[key.strip()] = value.strip()
    for key in ("fill", "stroke", "stroke-width", "opacity"):
        if key in elem.attrib:
            result[key] = elem.attrib[key]
    return result


def tokenize_path(d: str) -> List[str]:
    tokens: List[str] = []
    token = ""
    last = ""
    for ch in d.replace(",", " "):
        if ch.isalpha():
            if token:
                tokens.append(token); token = ""
            tokens.append(ch); last = ch
        elif ch in "+-" and token and last not in "eE":
            tokens.append(token); token = ch; last = ch
        elif ch.isspace():
            if token:
                tokens.append(token); token = ""
            last = ch
        else:
            token += ch; last = ch
    if token:
        tokens.append(token)
    return tokens


def cubic_point(p0, p1, p2, p3, t: float) -> Tuple[float, float]:
    u = 1 - t
    x = u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0]
    y = u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]
    return x, y


def quad_point(p0, p1, p2, t: float) -> Tuple[float, float]:
    u = 1 - t
    x = u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0]
    y = u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1]
    return x, y


def path_to_polylines(d: str, curve_steps: int = 16) -> List[List[Tuple[float, float]]]:
    """Approximate common SVG path commands for display only. Original d is preserved on save."""
    tokens = tokenize_path(d)
    i = 0; cmd = ""; x = y = 0.0; sx = sy = 0.0
    last_c = None; last_q = None
    lines: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = []
    arity = {"M":2,"L":2,"H":1,"V":1,"C":6,"S":4,"Q":4,"T":2,"A":7}
    def is_cmd(tok): return len(tok)==1 and tok.isalpha()
    def num(tok): return parse_float(tok)
    def ensure_line():
        nonlocal current
        if not current:
            current=[]; lines.append(current)
    while i < len(tokens):
        if is_cmd(tokens[i]):
            cmd = tokens[i]; i += 1
        if not cmd:
            break
        up = cmd.upper(); rel = cmd.islower()
        if up == "Z":
            if current:
                current.append((sx, sy))
            x, y = sx, sy; last_c = last_q = None; cmd = ""; continue
        need = arity.get(up)
        if need is None:
            # Unsupported command: skip until the next explicit command token.
            while i < len(tokens) and not is_cmd(tokens[i]):
                i += 1
            last_c = last_q = None
            continue
        if i + need > len(tokens):
            break
        if any(is_cmd(t) for t in tokens[i:i+need]):
            # Avoid infinite loops on interrupted/malformed compact path data.
            i += 1
            continue
        vals = [num(t) for t in tokens[i:i+need]]; i += need
        ensure_line()
        if up == "M":
            nx, ny = vals[0], vals[1]
            if rel: nx += x; ny += y
            x, y = nx, ny; sx, sy = x, y
            current = [(x, y)]; lines.append(current)
            cmd = "l" if rel else "L"
        elif up == "L":
            nx, ny = vals[0], vals[1]
            if rel: nx += x; ny += y
            current.append((nx, ny)); x, y = nx, ny; last_c = last_q = None
        elif up == "H":
            nx = vals[0] + x if rel else vals[0]
            current.append((nx, y)); x = nx; last_c = last_q = None
        elif up == "V":
            ny = vals[0] + y if rel else vals[0]
            current.append((x, ny)); y = ny; last_c = last_q = None
        elif up == "C":
            x1,y1,x2,y2,x3,y3 = vals
            if rel: x1+=x; y1+=y; x2+=x; y2+=y; x3+=x; y3+=y
            p0=(x,y); p1=(x1,y1); p2=(x2,y2); p3=(x3,y3)
            for step in range(1, curve_steps+1): current.append(cubic_point(p0,p1,p2,p3,step/curve_steps))
            x,y=x3,y3; last_c=(x2,y2); last_q=None
        elif up == "S":
            x2,y2,x3,y3 = vals
            x1,y1 = (2*x-last_c[0], 2*y-last_c[1]) if last_c else (x,y)
            if rel: x2+=x; y2+=y; x3+=x; y3+=y
            p0=(x,y); p1=(x1,y1); p2=(x2,y2); p3=(x3,y3)
            for step in range(1, curve_steps+1): current.append(cubic_point(p0,p1,p2,p3,step/curve_steps))
            x,y=x3,y3; last_c=(x2,y2); last_q=None
        elif up == "Q":
            x1,y1,x2,y2 = vals
            if rel: x1+=x; y1+=y; x2+=x; y2+=y
            p0=(x,y); p1=(x1,y1); p2=(x2,y2)
            for step in range(1, curve_steps+1): current.append(quad_point(p0,p1,p2,step/curve_steps))
            x,y=x2,y2; last_q=(x1,y1); last_c=None
        elif up == "T":
            x2,y2 = vals
            x1,y1 = (2*x-last_q[0], 2*y-last_q[1]) if last_q else (x,y)
            if rel: x2+=x; y2+=y
            p0=(x,y); p1=(x1,y1); p2=(x2,y2)
            for step in range(1, curve_steps+1): current.append(quad_point(p0,p1,p2,step/curve_steps))
            x,y=x2,y2; last_q=(x1,y1); last_c=None
        elif up == "A":
            # Arc fallback for display: preserve exact arc in raw d, draw endpoint connection.
            rx,ry,rot,large,sweep,x2,y2 = vals
            if rel: x2+=x; y2+=y
            current.append((x2,y2)); x,y=x2,y2; last_c=last_q=None
    return [line for line in lines if len(line) >= 2]


def color_visible(value: str) -> bool:
    return bool(value) and value.lower() not in {"none", "transparent"}


def is_closed_polyline(points: List[Tuple[float, float]], tolerance: float = 0.75) -> bool:
    if len(points) < 3:
        return False
    return abs(points[0][0] - points[-1][0]) <= tolerance and abs(points[0][1] - points[-1][1]) <= tolerance


def path_is_closed(d: str) -> bool:
    return "z" in d.lower()


def all_path_points(polylines: List[List[Tuple[float, float]]]) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    for line in polylines:
        pts.extend(line)
    return pts

def preview_outline_for_fill(fill: str, stroke: str) -> str:
    """Return an outline color that keeps white/no-stroke filled objects visible on white canvas."""
    if color_visible(stroke):
        return stroke
    if fill.lower() in {"#fff", "#ffffff", "white", "rgb(255,255,255)", "rgb(255, 255, 255)"}:
        return "#d1d5db"
    return ""


def canvas_item_ids(value) -> List[int]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [int(v) for v in value if v]
    return [int(value)]



@dataclass
class Style:
    fill: str = "#4f8cff"
    stroke: str = "#1f2937"
    stroke_width: float = 2.0
    opacity: float = 1.0

    def to_svg_attribs(self) -> Dict[str, str]:
        return {
            "fill": self.fill,
            "stroke": self.stroke,
            "stroke-width": str(self.stroke_width),
            "opacity": str(self.opacity),
        }

    @classmethod
    def from_svg(cls, elem: ET.Element) -> "Style":
        return cls(
            fill=elem.attrib.get("fill", "none"),
            stroke=elem.attrib.get("stroke", "#1f2937"),
            stroke_width=parse_float(elem.attrib.get("stroke-width"), 1.0),
            opacity=parse_float(elem.attrib.get("opacity"), 1.0),
        )


@dataclass
class SvgObject:
    id: str
    kind: str
    coords: List[float]
    style: Style = field(default_factory=Style)
    text: str = "Text"
    font_size: float = 32.0
    points: List[Tuple[float, float]] = field(default_factory=list)
    visible: bool = True
    raw_attrib: Dict[str, str] = field(default_factory=dict)
    raw_d: str = ""
    source_tag: str = ""

    def clone(self) -> "SvgObject":
        return copy.deepcopy(self)

    def bbox(self) -> Tuple[float, float, float, float]:
        if self.kind == "rect":
            x, y, w, h = self.coords[:4]
            return x, y, x + w, y + h
        if self.kind == "ellipse":
            cx, cy, rx, ry = self.coords[:4]
            return cx - rx, cy - ry, cx + rx, cy + ry
        if self.kind == "line":
            x1, y1, x2, y2 = self.coords[:4]
            return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
        if self.kind == "path":
            pts = all_path_points(path_to_polylines(self.raw_d)) if self.raw_d else self.points
            if pts:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                return min(xs), min(ys), max(xs), max(ys)
        if self.kind == "polyline" and self.points:
            xs = [p[0] for p in self.points]
            ys = [p[1] for p in self.points]
            return min(xs), min(ys), max(xs), max(ys)
        if self.kind == "text":
            x, y = self.coords[:2]
            approx_w = max(30, len(self.text) * self.font_size * 0.58)
            return x, y - self.font_size, x + approx_w, y + self.font_size * 0.25
        return 0, 0, 0, 0

    def move(self, dx: float, dy: float) -> None:
        if self.kind == "rect":
            self.coords[0] += dx
            self.coords[1] += dy
        elif self.kind == "ellipse":
            self.coords[0] += dx
            self.coords[1] += dy
        elif self.kind == "line":
            self.coords[0] += dx
            self.coords[1] += dy
            self.coords[2] += dx
            self.coords[3] += dy
        elif self.kind in ("path", "polyline"):
            self.points = [(x + dx, y + dy) for x, y in self.points]
        elif self.kind == "text":
            self.coords[0] += dx
            self.coords[1] += dy

    def scale_from_bbox(self, sx: float, sy: float) -> None:
        x1, y1, x2, y2 = self.bbox()
        if abs(x2 - x1) < 0.01 or abs(y2 - y1) < 0.01:
            return
        def tx(x: float) -> float:
            return x1 + (x - x1) * sx
        def ty(y: float) -> float:
            return y1 + (y - y1) * sy
        if self.kind == "rect":
            nx1, ny1 = tx(self.coords[0]), ty(self.coords[1])
            nx2, ny2 = tx(self.coords[0] + self.coords[2]), ty(self.coords[1] + self.coords[3])
            self.coords = [min(nx1, nx2), min(ny1, ny2), abs(nx2 - nx1), abs(ny2 - ny1)]
        elif self.kind == "ellipse":
            cx, cy, rx, ry = self.coords[:4]
            self.coords = [tx(cx), ty(cy), abs(rx * sx), abs(ry * sy)]
        elif self.kind == "line":
            self.coords = [tx(self.coords[0]), ty(self.coords[1]), tx(self.coords[2]), ty(self.coords[3])]
        elif self.kind in ("path", "polyline"):
            self.points = [(tx(x), ty(y)) for x, y in self.points]
        elif self.kind == "text":
            self.coords = [tx(self.coords[0]), ty(self.coords[1])]
            self.font_size = max(4, self.font_size * ((abs(sx) + abs(sy)) / 2.0))

    def to_svg_element(self) -> ET.Element:
        attrib = dict(self.raw_attrib) if self.raw_attrib else {"id": self.id}
        attrib.setdefault("id", self.id)
        # Keep classes/raw attributes intact. Only write explicit style attrs for newly-created objects.
        if not self.raw_attrib:
            attrib.update(self.style.to_svg_attribs())
        if not self.visible:
            attrib["display"] = "none"
        elif attrib.get("display") == "none":
            attrib.pop("display", None)
        if self.kind == "rect":
            x, y, w, h = self.coords[:4]
            attrib.update({"x": str(x), "y": str(y), "width": str(abs(w)), "height": str(abs(h))})
            return ET.Element("rect", attrib)
        if self.kind == "ellipse":
            cx, cy, rx, ry = self.coords[:4]
            tag = "circle" if self.source_tag == "circle" and abs(rx - ry) < 0.01 else "ellipse"
            if tag == "circle":
                attrib.update({"cx": str(cx), "cy": str(cy), "r": str(abs(rx))})
                attrib.pop("rx", None); attrib.pop("ry", None)
            else:
                attrib.update({"cx": str(cx), "cy": str(cy), "rx": str(abs(rx)), "ry": str(abs(ry))})
            return ET.Element(tag, attrib)
        if self.kind == "line":
            x1, y1, x2, y2 = self.coords[:4]
            attrib.update({"x1": str(x1), "y1": str(y1), "x2": str(x2), "y2": str(y2)})
            if not self.raw_attrib:
                attrib["fill"] = "none"
            return ET.Element("line", attrib)
        if self.kind == "polyline":
            attrib.update({"points": " ".join(f"{x},{y}" for x, y in self.points)})
            if not self.raw_attrib:
                attrib["fill"] = "none"
            return ET.Element("polyline", attrib)
        if self.kind == "path":
            if self.raw_d:
                attrib["d"] = self.raw_d
            elif self.points:
                attrib["d"] = "M " + " L ".join(f"{x} {y}" for x, y in self.points)
            else:
                attrib["d"] = "M 0 0"
            if not self.raw_attrib:
                attrib.update({"fill": "none", "stroke-linecap": "round", "stroke-linejoin": "round"})
            return ET.Element("path", attrib)
        if self.kind == "text":
            x, y = self.coords[:2]
            attrib.update({"x": str(x), "y": str(y), "font-size": str(self.font_size)})
            attrib.setdefault("font-family", "Arial, Helvetica, sans-serif")
            elem = ET.Element("text", attrib)
            elem.text = self.text
            return elem
        return ET.Element("g", attrib)


class SvgDocument:
    def __init__(self, width: int = 1200, height: int = 800) -> None:
        self.width = width
        self.height = height
        self.objects: List[SvgObject] = []
        self.counter = 1
        self.path: Optional[str] = None
        self.viewbox: Optional[str] = None
        self.preamble_children: List[ET.Element] = []
        self.root_attrib: Dict[str, str] = {}

    def new_id(self, prefix: str) -> str:
        value = f"{prefix}_{self.counter}"
        self.counter += 1
        return value

    def add(self, obj: SvgObject) -> None:
        self.objects.append(obj)

    def remove(self, obj: SvgObject) -> None:
        if obj in self.objects:
            self.objects.remove(obj)

    def to_svg(self) -> str:
        attrib = dict(self.root_attrib) if self.root_attrib else {}
        attrib.pop("xmlns", None)
        attrib.setdefault("version", "1.1")
        if self.viewbox:
            attrib["viewBox"] = self.viewbox
        else:
            attrib["viewBox"] = f"0 0 {self.width} {self.height}"
        if "width" not in attrib and self.width:
            attrib["width"] = str(self.width)
        if "height" not in attrib and self.height:
            attrib["height"] = str(self.height)
        root = ET.Element(f"{{{SVG_NS}}}svg", attrib)
        for child in self.preamble_children:
            root.append(copy.deepcopy(child))
        if not self.preamble_children:
            meta = ET.SubElement(root, "metadata")
            meta.text = f"Created with {APP_NAME} {APP_VERSION}"
        for obj in self.objects:
            root.append(obj.to_svg_element())
        return pretty_xml(root)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_svg())
        self.path = path

    @classmethod
    def load(cls, path: str) -> "SvgDocument":
        tree = ET.parse(path)
        root = tree.getroot()
        root_attrib = dict(root.attrib)
        width = int(parse_float(root.attrib.get("width"), 1200))
        height = int(parse_float(root.attrib.get("height"), 800))
        viewbox = root.attrib.get("viewBox")
        if viewbox:
            parts = viewbox.replace(",", " ").split()
            if len(parts) == 4:
                width = int(parse_float(parts[2], width))
                height = int(parse_float(parts[3], height))
        doc = cls(width, height)
        doc.path = path
        doc.viewbox = viewbox
        doc.root_attrib = root_attrib
        css_styles = extract_css_class_styles(root)
        supported = {"rect", "ellipse", "circle", "line", "polyline", "path", "text"}
        # Preserve reusable definitions and document metadata even if they were nested in groups.
        # Editable shapes may be flattened on save, but definitions/classes/path data remain intact.
        seen_preamble = set()
        for child in root.iter():
            lname = local_name(child.tag)
            if lname in {"defs", "metadata", "title", "desc"} or (lname == "style" and local_name(getattr(root, "tag", "")) != "style"):
                if child is root:
                    continue
                raw_key = ET.tostring(child, encoding="unicode")
                if raw_key not in seen_preamble:
                    doc.preamble_children.append(copy.deepcopy(child))
                    seen_preamble.add(raw_key)
        def visit(elem: ET.Element, inherited: Dict[str, str]) -> None:
            tag = local_name(elem.tag)
            resolved = resolve_style(elem, css_styles, inherited)
            if tag in supported:
                style = Style(
                    fill=resolved.get("fill", elem.attrib.get("fill", "none")),
                    stroke=resolved.get("stroke", elem.attrib.get("stroke", "#1f2937")),
                    stroke_width=parse_float(resolved.get("stroke-width", elem.attrib.get("stroke-width")), 1.0),
                    opacity=parse_float(resolved.get("opacity", elem.attrib.get("opacity")), 1.0),
                )
                visible = elem.attrib.get("display") != "none"
                oid = elem.attrib.get("id") or doc.new_id(tag)
                raw_attrib = dict(elem.attrib)
                if tag == "rect":
                    obj = SvgObject(oid, "rect", [parse_float(elem.attrib.get("x")), parse_float(elem.attrib.get("y")), parse_float(elem.attrib.get("width")), parse_float(elem.attrib.get("height"))], style, visible=visible, raw_attrib=raw_attrib, source_tag=tag)
                elif tag in ("ellipse", "circle"):
                    if tag == "circle":
                        r = parse_float(elem.attrib.get("r"), 20); coords = [parse_float(elem.attrib.get("cx")), parse_float(elem.attrib.get("cy")), r, r]
                    else:
                        coords = [parse_float(elem.attrib.get("cx")), parse_float(elem.attrib.get("cy")), parse_float(elem.attrib.get("rx"), 20), parse_float(elem.attrib.get("ry"), 20)]
                    obj = SvgObject(oid, "ellipse", coords, style, visible=visible, raw_attrib=raw_attrib, source_tag=tag)
                elif tag == "line":
                    obj = SvgObject(oid, "line", [parse_float(elem.attrib.get("x1")), parse_float(elem.attrib.get("y1")), parse_float(elem.attrib.get("x2")), parse_float(elem.attrib.get("y2"))], style, visible=visible, raw_attrib=raw_attrib, source_tag=tag)
                elif tag == "polyline":
                    points = []
                    raw = elem.attrib.get("points", "").replace(",", " ").split()
                    for i in range(0, len(raw) - 1, 2): points.append((parse_float(raw[i]), parse_float(raw[i + 1])))
                    obj = SvgObject(oid, "polyline", [], style, points=points, visible=visible, raw_attrib=raw_attrib, source_tag=tag)
                elif tag == "path":
                    raw_d = elem.attrib.get("d", "")
                    points = []
                    polylines = path_to_polylines(raw_d)
                    if polylines: points = polylines[0]
                    obj = SvgObject(oid, "path", [], style, points=points, visible=visible, raw_attrib=raw_attrib, raw_d=raw_d, source_tag=tag)
                else:
                    obj = SvgObject(oid, "text", [parse_float(elem.attrib.get("x")), parse_float(elem.attrib.get("y"))], style, text=elem.text or "Text", font_size=parse_float(elem.attrib.get("font-size"), 32), visible=visible, raw_attrib=raw_attrib, source_tag=tag)
                doc.add(obj)
            for child in list(elem):
                visit(child, resolved)
        visit(root, {"fill": root.attrib.get("fill", "#000000"), "stroke": root.attrib.get("stroke", "none")})
        doc.counter = len(doc.objects) + 1
        return doc



class UndoStack:
    def __init__(self, limit: int = 80) -> None:
        self.limit = limit
        self.undo: List[List[SvgObject]] = []
        self.redo: List[List[SvgObject]] = []

    def snapshot(self, objects: List[SvgObject]) -> None:
        self.undo.append(copy.deepcopy(objects))
        if len(self.undo) > self.limit:
            self.undo.pop(0)
        self.redo.clear()

    def can_undo(self) -> bool:
        return bool(self.undo)

    def do_undo(self, current: List[SvgObject]) -> List[SvgObject]:
        if not self.undo:
            return current
        self.redo.append(copy.deepcopy(current))
        return self.undo.pop()

    def do_redo(self, current: List[SvgObject]) -> List[SvgObject]:
        if not self.redo:
            return current
        self.undo.append(copy.deepcopy(current))
        return self.redo.pop()

class VectorWeaverApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1450x900")
        self.minsize(1050, 700)
        self.doc = SvgDocument()
        self.undo = UndoStack()
        self.current_tool = tk.StringVar(value="select")
        self.fill_color = tk.StringVar(value="#4f8cff")
        self.stroke_color = tk.StringVar(value="#1f2937")
        self.stroke_width = tk.DoubleVar(value=2.0)
        self.opacity = tk.DoubleVar(value=1.0)
        self.zoom = tk.DoubleVar(value=1.0)
        self.grid_enabled = tk.BooleanVar(value=True)
        self.snap_enabled = tk.BooleanVar(value=True)
        self.selected: Optional[SvgObject] = None
        self.drag_start: Optional[Tuple[float, float]] = None
        self.temp_item: Optional[int] = None
        self.current_path_points: List[Tuple[float, float]] = []
        self.canvas_items: Dict[int, SvgObject] = {}
        self.object_items: Dict[str, int] = {}
        self.source_dirty = False
        self._build_ui()
        self._bind_events()
        self.new_document()

    def _build_ui(self) -> None:
        self._build_menu()
        self._build_toolbar()
        self.main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main.pack(fill=tk.BOTH, expand=True)
        self.left = ttk.Frame(self.main, width=120)
        self.center = ttk.PanedWindow(self.main, orient=tk.VERTICAL)
        self.right = ttk.Frame(self.main, width=310)
        self.main.add(self.left, weight=0)
        self.main.add(self.center, weight=1)
        self.main.add(self.right, weight=0)
        self._build_tools_panel()
        self._build_canvas_area()
        self._build_source_area()
        self._build_properties_panel()
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status, anchor=tk.W, relief=tk.SUNKEN).pack(fill=tk.X, side=tk.BOTTOM)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_document)
        file_menu.add_command(label="Open SVG...", accelerator="Ctrl+O", command=self.open_document)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_document)
        file_menu.add_command(label="Save As...", accelerator="Ctrl+Shift+S", command=self.save_as_document)
        file_menu.add_separator()
        file_menu.add_command(label="Export SVG...", command=self.export_svg)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo_action)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo_action)
        edit_menu.add_separator()
        edit_menu.add_command(label="Duplicate", accelerator="Ctrl+D", command=self.duplicate_selected)
        edit_menu.add_command(label="Delete", accelerator="Del", command=self.delete_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="Bring Forward", command=lambda: self.reorder_selected(1))
        edit_menu.add_command(label="Send Backward", command=lambda: self.reorder_selected(-1))
        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(label="Show Grid", variable=self.grid_enabled, command=self.redraw)
        view_menu.add_checkbutton(label="Snap to Grid", variable=self.snap_enabled)
        view_menu.add_separator()
        view_menu.add_command(label="Zoom In", accelerator="Ctrl++", command=lambda: self.change_zoom(1.2))
        view_menu.add_command(label="Zoom Out", accelerator="Ctrl+-", command=lambda: self.change_zoom(1 / 1.2))
        view_menu.add_command(label="Actual Size", command=lambda: self.set_zoom(1.0))
        svg_menu = tk.Menu(menu, tearoff=False)
        svg_menu.add_command(label="Refresh SVG Source", command=self.refresh_source)
        svg_menu.add_command(label="Apply SVG Source to Canvas", command=self.apply_source)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About", command=self.about)
        menu.add_cascade(label="File", menu=file_menu)
        menu.add_cascade(label="Edit", menu=edit_menu)
        menu.add_cascade(label="View", menu=view_menu)
        menu.add_cascade(label="SVG", menu=svg_menu)
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=4)
        bar.pack(fill=tk.X, side=tk.TOP)
        ttk.Button(bar, text="New", command=self.new_document).pack(side=tk.LEFT)
        ttk.Button(bar, text="Open", command=self.open_document).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bar, text="Save", command=self.save_document).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(bar, text="Fill").pack(side=tk.LEFT)
        ttk.Button(bar, textvariable=self.fill_color, command=self.choose_fill).pack(side=tk.LEFT, padx=4)
        ttk.Label(bar, text="Stroke").pack(side=tk.LEFT)
        ttk.Button(bar, textvariable=self.stroke_color, command=self.choose_stroke).pack(side=tk.LEFT, padx=4)
        ttk.Label(bar, text="Width").pack(side=tk.LEFT)
        ttk.Spinbox(bar, from_=0, to=80, increment=0.5, textvariable=self.stroke_width, width=6, command=self.apply_style_to_selected).pack(side=tk.LEFT, padx=4)
        ttk.Label(bar, text="Opacity").pack(side=tk.LEFT)
        ttk.Spinbox(bar, from_=0.05, to=1.0, increment=0.05, textvariable=self.opacity, width=6, command=self.apply_style_to_selected).pack(side=tk.LEFT, padx=4)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(bar, text="Undo", command=self.undo_action).pack(side=tk.LEFT)
        ttk.Button(bar, text="Redo", command=self.redo_action).pack(side=tk.LEFT, padx=4)
        ttk.Label(bar, text="Zoom").pack(side=tk.LEFT, padx=(16, 0))
        ttk.Button(bar, text="-", width=3, command=lambda: self.change_zoom(1 / 1.2)).pack(side=tk.LEFT)
        ttk.Label(bar, textvariable=self.zoom, width=5).pack(side=tk.LEFT)
        ttk.Button(bar, text="+", width=3, command=lambda: self.change_zoom(1.2)).pack(side=tk.LEFT)

    def _build_tools_panel(self) -> None:
        ttk.Label(self.left, text="Tools", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W, padx=8, pady=(8, 4))
        tools = [
            ("Select/Move", "select"), ("Rectangle", "rect"), ("Ellipse", "ellipse"),
            ("Line", "line"), ("Pen/Path", "path"), ("Brush", "brush"),
            ("Text", "text"), ("Eyedropper", "eyedropper"), ("Eraser", "eraser"),
        ]
        for label, value in tools:
            ttk.Radiobutton(self.left, text=label, value=value, variable=self.current_tool, command=self.tool_changed).pack(anchor=tk.W, padx=10, pady=2)
        ttk.Separator(self.left).pack(fill=tk.X, pady=8)
        ttk.Button(self.left, text="Duplicate", command=self.duplicate_selected).pack(fill=tk.X, padx=8, pady=2)
        ttk.Button(self.left, text="Delete", command=self.delete_selected).pack(fill=tk.X, padx=8, pady=2)
        ttk.Button(self.left, text="Front", command=lambda: self.reorder_selected(999)).pack(fill=tk.X, padx=8, pady=2)
        ttk.Button(self.left, text="Back", command=lambda: self.reorder_selected(-999)).pack(fill=tk.X, padx=8, pady=2)
        ttk.Separator(self.left).pack(fill=tk.X, pady=8)
        ttk.Checkbutton(self.left, text="Grid", variable=self.grid_enabled, command=self.redraw).pack(anchor=tk.W, padx=8)
        ttk.Checkbutton(self.left, text="Snap", variable=self.snap_enabled).pack(anchor=tk.W, padx=8)

    def _build_canvas_area(self) -> None:
        frame = ttk.Frame(self.center)
        self.center.add(frame, weight=4)
        self.canvas = tk.Canvas(frame, bg="#f3f4f6", highlightthickness=0, scrollregion=(0, 0, self.doc.width, self.doc.height))
        self.hbar = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.vbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

    def _build_source_area(self) -> None:
        frame = ttk.LabelFrame(self.center, text="SVG Source - edit markup then Apply")
        self.center.add(frame, weight=1)
        self.source = tk.Text(frame, height=10, wrap=tk.NONE, undo=True, font=("Consolas", 10))
        yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.source.yview)
        xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.source.xview)
        self.source.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.source.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(actions, text="Refresh from Canvas", command=self.refresh_source).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(actions, text="Apply to Canvas", command=self.apply_source).pack(side=tk.LEFT, padx=4, pady=4)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

    def _build_properties_panel(self) -> None:
        ttk.Label(self.right, text="Properties", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W, padx=8, pady=(8, 4))
        props = ttk.LabelFrame(self.right, text="Selected Object")
        props.pack(fill=tk.X, padx=8, pady=4)
        self.prop_text = tk.StringVar(value="No selection")
        ttk.Label(props, textvariable=self.prop_text, justify=tk.LEFT).pack(anchor=tk.W, padx=6, pady=6)
        ttk.Button(props, text="Edit Text...", command=self.edit_selected_text).pack(fill=tk.X, padx=6, pady=2)
        ttk.Button(props, text="Apply Current Style", command=self.apply_style_to_selected).pack(fill=tk.X, padx=6, pady=2)
        ttk.Button(props, text="Scale 110%", command=lambda: self.scale_selected(1.1, 1.1)).pack(fill=tk.X, padx=6, pady=2)
        ttk.Button(props, text="Scale 90%", command=lambda: self.scale_selected(0.9, 0.9)).pack(fill=tk.X, padx=6, pady=2)
        docbox = ttk.LabelFrame(self.right, text="Document")
        docbox.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(docbox, text="Resize Canvas...", command=self.resize_canvas_dialog).pack(fill=tk.X, padx=6, pady=6)
        layers = ttk.LabelFrame(self.right, text="Layers / SVG Objects")
        layers.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.layers = tk.Listbox(layers, exportselection=False)
        self.layers.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        ttk.Button(layers, text="Select Layer", command=self.select_from_layer).pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(layers, text="Toggle Visibility", command=self.toggle_visibility).pack(fill=tk.X, padx=4, pady=2)

    def _bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.layers.bind("<<ListboxSelect>>", lambda e: self.select_from_layer())
        self.source.bind("<<Modified>>", self.on_source_modified)
        self.bind("<Control-n>", lambda e: self.new_document())
        self.bind("<Control-o>", lambda e: self.open_document())
        self.bind("<Control-s>", lambda e: self.save_document())
        self.bind("<Control-S>", lambda e: self.save_as_document())
        self.bind("<Control-z>", lambda e: self.undo_action())
        self.bind("<Control-y>", lambda e: self.redo_action())
        self.bind("<Control-d>", lambda e: self.duplicate_selected())
        self.bind("<Delete>", lambda e: self.delete_selected())
        self.bind("<Escape>", lambda e: self.cancel_path())

    def screen_to_doc(self, x: float, y: float) -> Tuple[float, float]:
        z = self.zoom.get()
        dx = self.canvas.canvasx(x) / z
        dy = self.canvas.canvasy(y) / z
        if self.snap_enabled.get():
            grid = 10
            dx = round(dx / grid) * grid
            dy = round(dy / grid) * grid
        return dx, dy

    def doc_to_screen(self, x: float, y: float) -> Tuple[float, float]:
        z = self.zoom.get()
        return x * z, y * z

    def current_style(self) -> Style:
        return Style(self.fill_color.get(), self.stroke_color.get(), float(self.stroke_width.get()), float(self.opacity.get()))

    def tool_changed(self) -> None:
        self.cancel_path()
        self.status.set(f"Tool: {self.current_tool.get()}")

    def new_document(self) -> None:
        self.doc = SvgDocument()
        self.selected = None
        self.undo = UndoStack()
        self.current_path_points.clear()
        self.redraw()
        self.refresh_source()
        self.status.set("New SVG document")

    def open_document(self) -> None:
        path = filedialog.askopenfilename(title="Open SVG", filetypes=[("SVG files", "*.svg"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.doc = SvgDocument.load(path)
            self.selected = None
            self.undo = UndoStack()
            self.redraw()
            self.refresh_source()
            self.status.set(f"Opened {path}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open SVG:\n{exc}")

    def save_document(self) -> None:
        if self.doc.path:
            self._save_path(self.doc.path)
        else:
            self.save_as_document()

    def save_as_document(self) -> None:
        path = filedialog.asksaveasfilename(title="Save SVG As", defaultextension=".svg", filetypes=[("SVG files", "*.svg")])
        if path:
            self._save_path(path)

    def export_svg(self) -> None:
        self.save_as_document()

    def _save_path(self, path: str) -> None:
        try:
            self.doc.save(path)
            self.refresh_source()
            self.status.set(f"Saved {path}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not save SVG:\n{exc}")

    def refresh_source(self) -> None:
        self.source.delete("1.0", tk.END)
        self.source.insert("1.0", self.doc.to_svg())
        self.source.edit_modified(False)
        self.source_dirty = False

    def apply_source(self) -> None:
        raw = self.source.get("1.0", tk.END).strip()
        if not raw:
            return
        tmp = os.path.join(os.getcwd(), "_vectorweaver_source_apply_tmp.svg")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(raw)
            self.undo.snapshot(self.doc.objects)
            self.doc = SvgDocument.load(tmp)
            os.remove(tmp)
            self.selected = None
            self.redraw()
            self.refresh_source()
            self.status.set("Applied SVG source to canvas")
        except Exception as exc:
            try:
                os.remove(tmp)
            except Exception:
                pass
            messagebox.showerror(APP_NAME, f"Source could not be parsed as editable SVG:\n{exc}")

    def on_source_modified(self, event=None) -> None:
        self.source_dirty = True
        self.source.edit_modified(False)

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.canvas_items.clear()
        self.object_items.clear()
        z = self.zoom.get()
        self.canvas.configure(scrollregion=(0, 0, self.doc.width * z, self.doc.height * z))
        self.canvas.create_rectangle(0, 0, self.doc.width * z, self.doc.height * z, fill="white", outline="#cbd5e1", tags="page")
        if self.grid_enabled.get():
            step = 50 * z
            small = 10 * z
            for x in range(0, int(self.doc.width * z) + 1, max(1, int(small))):
                color = "#eef2f7" if x % int(step or 1) else "#dbe3ed"
                self.canvas.create_line(x, 0, x, self.doc.height * z, fill=color)
            for y in range(0, int(self.doc.height * z) + 1, max(1, int(small))):
                color = "#eef2f7" if y % int(step or 1) else "#dbe3ed"
                self.canvas.create_line(0, y, self.doc.width * z, y, fill=color)
        for obj in self.doc.objects:
            if obj.visible:
                item = self.draw_object(obj)
                ids = canvas_item_ids(item)
                if ids:
                    for item_id in ids:
                        self.canvas_items[item_id] = obj
                    self.object_items[obj.id] = ids[0]
        self.draw_selection()
        self.refresh_layers()
        self.update_properties()

    def draw_object(self, obj: SvgObject):
        z = self.zoom.get()
        style = obj.style
        fill = style.fill if style.fill != "none" else ""
        stroke = style.stroke if style.stroke != "none" else ""
        width = max(1, style.stroke_width * z)
        if obj.kind == "rect":
            x, y, w, h = obj.coords[:4]
            return self.canvas.create_rectangle(x*z, y*z, (x+w)*z, (y+h)*z, fill=fill, outline=stroke, width=width)
        if obj.kind == "ellipse":
            cx, cy, rx, ry = obj.coords[:4]
            return self.canvas.create_oval((cx-rx)*z, (cy-ry)*z, (cx+rx)*z, (cy+ry)*z, fill=fill, outline=stroke, width=width)
        if obj.kind == "line":
            x1, y1, x2, y2 = obj.coords[:4]
            return self.canvas.create_line(x1*z, y1*z, x2*z, y2*z, fill=stroke, width=width)
        if obj.kind == "path":
            polylines = path_to_polylines(obj.raw_d) if obj.raw_d else ([obj.points] if len(obj.points) >= 2 else [])
            item_ids = []
            has_fill = color_visible(fill)
            has_stroke = color_visible(stroke)
            outline = preview_outline_for_fill(fill, stroke)
            for line in polylines:
                if len(line) < 2:
                    continue
                pts = []
                for x, y in line:
                    pts.extend([x*z, y*z])
                # SVG fills apply to path geometry even when the path is not explicitly closed.
                # Tkinter has no SVG fill-rule, so approximate each subpath as a polygon for preview.
                if has_fill and len(line) >= 3:
                    item = self.canvas.create_polygon(*pts, fill=fill, outline=outline, width=width if outline else 0)
                    item_ids.append(item)
                    if has_stroke:
                        edge = self.canvas.create_line(*pts, fill=stroke, width=width, smooth=False, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                        item_ids.append(edge)
                elif has_stroke:
                    item = self.canvas.create_line(*pts, fill=stroke, width=width, smooth=False, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                    item_ids.append(item)
                else:
                    # Last-resort preview: make otherwise invisible geometry selectable/visible.
                    item = self.canvas.create_line(*pts, fill="#111827", width=1, smooth=False)
                    item_ids.append(item)
            return item_ids
        if obj.kind == "polyline" and len(obj.points) >= 2:
            pts = []
            for x, y in obj.points:
                pts.extend([x*z, y*z])
            return self.canvas.create_line(*pts, fill=stroke, width=width, smooth=False, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        if obj.kind == "text":
            x, y = obj.coords[:2]
            return self.canvas.create_text(x*z, y*z, text=obj.text, fill=fill if fill else stroke, anchor=tk.SW, font=("Arial", max(6, int(obj.font_size * z))))
        return None

    def draw_selection(self) -> None:
        if not self.selected:
            return
        x1, y1, x2, y2 = self.selected.bbox()
        z = self.zoom.get()
        self.canvas.create_rectangle(x1*z-4, y1*z-4, x2*z+4, y2*z+4, outline="#2563eb", width=2, dash=(4, 2), tags="selection")
        for x, y in [(x1,y1), (x2,y1), (x1,y2), (x2,y2)]:
            self.canvas.create_rectangle(x*z-4, y*z-4, x*z+4, y*z+4, fill="#2563eb", outline="white", tags="selection")

    def refresh_layers(self) -> None:
        self.layers.delete(0, tk.END)
        for obj in reversed(self.doc.objects):
            marker = "👁" if obj.visible else "—"
            self.layers.insert(tk.END, f"{marker} {obj.id} ({obj.kind})")

    def update_properties(self) -> None:
        if not self.selected:
            self.prop_text.set("No selection")
            return
        x1, y1, x2, y2 = self.selected.bbox()
        self.prop_text.set(f"ID: {self.selected.id}\nType: {self.selected.kind}\nBounds: {x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}\nFill: {self.selected.style.fill}\nStroke: {self.selected.style.stroke}\nStroke width: {self.selected.style.stroke_width}\nOpacity: {self.selected.style.opacity}")
        self.fill_color.set(self.selected.style.fill)
        self.stroke_color.set(self.selected.style.stroke)
        self.stroke_width.set(self.selected.style.stroke_width)
        self.opacity.set(self.selected.style.opacity)

    def object_at(self, sx: float, sy: float) -> Optional[SvgObject]:
        overlapping = self.canvas.find_overlapping(sx-3, sy-3, sx+3, sy+3)
        for item in reversed(overlapping):
            if item in self.canvas_items:
                return self.canvas_items[item]
        dx, dy = self.screen_to_doc(sx, sy)
        for obj in reversed(self.doc.objects):
            if not obj.visible:
                continue
            x1, y1, x2, y2 = obj.bbox()
            if x1 - 4 <= dx <= x2 + 4 and y1 - 4 <= dy <= y2 + 4:
                return obj
        return None

    def on_mouse_down(self, event) -> None:
        tool = self.current_tool.get()
        x, y = self.screen_to_doc(event.x, event.y)
        self.drag_start = (x, y)
        self.temp_item = None
        if tool == "select":
            self.selected = self.object_at(event.x, event.y)
            self.redraw()
            if self.selected:
                self.undo.snapshot(self.doc.objects)
        elif tool == "eraser":
            target = self.object_at(event.x, event.y)
            if target:
                self.undo.snapshot(self.doc.objects)
                self.doc.remove(target)
                self.selected = None
                self.redraw(); self.refresh_source()
        elif tool == "eyedropper":
            target = self.object_at(event.x, event.y)
            if target:
                self.fill_color.set(target.style.fill)
                self.stroke_color.set(target.style.stroke)
                self.stroke_width.set(target.style.stroke_width)
                self.opacity.set(target.style.opacity)
                self.status.set(f"Picked style from {target.id}")
        elif tool == "text":
            text = simpledialog.askstring(APP_NAME, "Text content:", initialvalue="Text")
            if text is not None:
                self.undo.snapshot(self.doc.objects)
                obj = SvgObject(self.doc.new_id("text"), "text", [x, y], self.current_style(), text=text, font_size=32)
                self.doc.add(obj); self.selected = obj; self.redraw(); self.refresh_source()
        elif tool in ("path", "brush"):
            self.undo.snapshot(self.doc.objects)
            self.current_path_points = [(x, y)]
        else:
            self.undo.snapshot(self.doc.objects)

    def on_mouse_drag(self, event) -> None:
        if not self.drag_start:
            return
        tool = self.current_tool.get()
        x, y = self.screen_to_doc(event.x, event.y)
        x0, y0 = self.drag_start
        z = self.zoom.get()
        if tool == "select" and self.selected:
            dx, dy = x - x0, y - y0
            self.selected.move(dx, dy)
            self.drag_start = (x, y)
            self.redraw()
        elif tool in ("rect", "ellipse", "line"):
            if self.temp_item:
                self.canvas.delete(self.temp_item)
            if tool == "rect":
                self.temp_item = self.canvas.create_rectangle(x0*z, y0*z, x*z, y*z, outline=self.stroke_color.get(), fill=self.fill_color.get(), dash=(3,2))
            elif tool == "ellipse":
                self.temp_item = self.canvas.create_oval(x0*z, y0*z, x*z, y*z, outline=self.stroke_color.get(), fill=self.fill_color.get(), dash=(3,2))
            else:
                self.temp_item = self.canvas.create_line(x0*z, y0*z, x*z, y*z, fill=self.stroke_color.get(), width=max(1, self.stroke_width.get()*z))
        elif tool in ("path", "brush"):
            self.current_path_points.append((x, y))
            if len(self.current_path_points) >= 2:
                if self.temp_item:
                    self.canvas.delete(self.temp_item)
                pts = []
                for px, py in self.current_path_points:
                    pts.extend([px*z, py*z])
                self.temp_item = self.canvas.create_line(*pts, fill=self.stroke_color.get(), width=max(1, self.stroke_width.get()*z), smooth=True, capstyle=tk.ROUND)

    def on_mouse_up(self, event) -> None:
        if not self.drag_start:
            return
        tool = self.current_tool.get()
        x, y = self.screen_to_doc(event.x, event.y)
        x0, y0 = self.drag_start
        self.drag_start = None
        if self.temp_item:
            self.canvas.delete(self.temp_item); self.temp_item = None
        if tool == "rect":
            if abs(x-x0) > 2 and abs(y-y0) > 2:
                obj = SvgObject(self.doc.new_id("rect"), "rect", [min(x0,x), min(y0,y), abs(x-x0), abs(y-y0)], self.current_style())
                self.doc.add(obj); self.selected = obj
        elif tool == "ellipse":
            if abs(x-x0) > 2 and abs(y-y0) > 2:
                obj = SvgObject(self.doc.new_id("ellipse"), "ellipse", [(x0+x)/2, (y0+y)/2, abs(x-x0)/2, abs(y-y0)/2], self.current_style())
                self.doc.add(obj); self.selected = obj
        elif tool == "line":
            if abs(x-x0) > 2 or abs(y-y0) > 2:
                style = self.current_style(); style.fill = "none"
                obj = SvgObject(self.doc.new_id("line"), "line", [x0, y0, x, y], style)
                self.doc.add(obj); self.selected = obj
        elif tool in ("path", "brush"):
            if len(self.current_path_points) >= 2:
                style = self.current_style(); style.fill = "none"
                obj = SvgObject(self.doc.new_id("path"), "path", [], style, points=self.current_path_points[:])
                self.doc.add(obj); self.selected = obj
            self.current_path_points.clear()
        self.redraw()
        self.refresh_source()

    def on_mouse_move(self, event) -> None:
        x, y = self.screen_to_doc(event.x, event.y)
        self.status.set(f"{self.current_tool.get()} | x={x:.1f}, y={y:.1f} | objects={len(self.doc.objects)}")

    def cancel_path(self) -> None:
        self.current_path_points.clear()
        if self.temp_item:
            self.canvas.delete(self.temp_item)
            self.temp_item = None

    def choose_fill(self) -> None:
        color = colorchooser.askcolor(color=self.fill_color.get(), title="Choose fill color")
        if color and color[1]:
            self.fill_color.set(color[1]); self.apply_style_to_selected()

    def choose_stroke(self) -> None:
        color = colorchooser.askcolor(color=self.stroke_color.get(), title="Choose stroke color")
        if color and color[1]:
            self.stroke_color.set(color[1]); self.apply_style_to_selected()

    def apply_style_to_selected(self) -> None:
        if self.selected:
            self.undo.snapshot(self.doc.objects)
            self.selected.style = self.current_style()
            if self.selected.kind in ("line", "path", "polyline"):
                self.selected.style.fill = "none"
            self.redraw(); self.refresh_source()

    def duplicate_selected(self) -> None:
        if not self.selected:
            return
        self.undo.snapshot(self.doc.objects)
        clone = self.selected.clone()
        clone.id = self.doc.new_id(clone.kind)
        clone.move(24, 24)
        self.doc.add(clone)
        self.selected = clone
        self.redraw(); self.refresh_source()

    def delete_selected(self) -> None:
        if not self.selected:
            return
        self.undo.snapshot(self.doc.objects)
        self.doc.remove(self.selected)
        self.selected = None
        self.redraw(); self.refresh_source()

    def reorder_selected(self, delta: int) -> None:
        if not self.selected or self.selected not in self.doc.objects:
            return
        self.undo.snapshot(self.doc.objects)
        index = self.doc.objects.index(self.selected)
        new_index = int(clamp(index + delta, 0, len(self.doc.objects) - 1))
        self.doc.objects.pop(index)
        self.doc.objects.insert(new_index, self.selected)
        self.redraw(); self.refresh_source()

    def select_from_layer(self) -> None:
        selection = self.layers.curselection()
        if not selection:
            return
        reversed_index = selection[0]
        index = len(self.doc.objects) - 1 - reversed_index
        if 0 <= index < len(self.doc.objects):
            self.selected = self.doc.objects[index]
            self.redraw()

    def toggle_visibility(self) -> None:
        selection = self.layers.curselection()
        if not selection:
            return
        index = len(self.doc.objects) - 1 - selection[0]
        if 0 <= index < len(self.doc.objects):
            self.undo.snapshot(self.doc.objects)
            self.doc.objects[index].visible = not self.doc.objects[index].visible
            if self.selected == self.doc.objects[index] and not self.doc.objects[index].visible:
                self.selected = None
            self.redraw(); self.refresh_source()

    def edit_selected_text(self) -> None:
        if not self.selected:
            return
        if self.selected.kind != "text":
            messagebox.showinfo(APP_NAME, "Select a text object first.")
            return
        text = simpledialog.askstring(APP_NAME, "Edit text:", initialvalue=self.selected.text)
        if text is not None:
            self.undo.snapshot(self.doc.objects)
            self.selected.text = text
            size = simpledialog.askfloat(APP_NAME, "Font size:", initialvalue=self.selected.font_size, minvalue=4, maxvalue=300)
            if size:
                self.selected.font_size = size
            self.redraw(); self.refresh_source()

    def scale_selected(self, sx: float, sy: float) -> None:
        if not self.selected:
            return
        self.undo.snapshot(self.doc.objects)
        self.selected.scale_from_bbox(sx, sy)
        self.redraw(); self.refresh_source()

    def resize_canvas_dialog(self) -> None:
        width = simpledialog.askinteger(APP_NAME, "Canvas width:", initialvalue=self.doc.width, minvalue=64, maxvalue=20000)
        if not width:
            return
        height = simpledialog.askinteger(APP_NAME, "Canvas height:", initialvalue=self.doc.height, minvalue=64, maxvalue=20000)
        if not height:
            return
        self.undo.snapshot(self.doc.objects)
        self.doc.width = width
        self.doc.height = height
        self.redraw(); self.refresh_source()

    def undo_action(self) -> None:
        self.doc.objects = self.undo.do_undo(self.doc.objects)
        self.selected = None
        self.redraw(); self.refresh_source()

    def redo_action(self) -> None:
        self.doc.objects = self.undo.do_redo(self.doc.objects)
        self.selected = None
        self.redraw(); self.refresh_source()

    def change_zoom(self, factor: float) -> None:
        self.set_zoom(self.zoom.get() * factor)

    def set_zoom(self, value: float) -> None:
        self.zoom.set(round(clamp(value, 0.1, 6.0), 2))
        self.redraw()

    def about(self) -> None:
        messagebox.showinfo(APP_NAME, f"{APP_NAME} {APP_VERSION}\n\nOffline WYSIWYG SVG editor.\nDreamweaver-style visual/source workflow for vector graphics.\nNo internet dependencies.")


def main() -> None:
    app = VectorWeaverApp()
    app.mainloop()


if __name__ == "__main__":
    main()
