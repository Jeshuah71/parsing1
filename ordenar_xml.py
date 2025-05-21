#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ordenar_xml.py

1) Sort <object class="Page"> by id/title/datetime
2) Strip passwords & IPs
3) Promote <property name="title"> → <title>
4) Emit:
   • sorted XML → output_file
   • rich HTML report → output_file.html
"""

import argparse, sys, re, html
import xml.etree.ElementTree as ET
import xml.dom.minidom as md
from datetime import datetime
from pathlib import Path

IP_RE  = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_RE = re.compile(r"https?://[^\s<>\]]+")

def parse_args():
    p = argparse.ArgumentParser(
        description="Sort Confluence Page objects, strip sensitive data, promote title, emit HTML"
    )
    p.add_argument("input_file",  help="Original XML dump")
    p.add_argument("output_file", help="Basename for sorted XML & HTML")
    p.add_argument(
        "-k","--key",
        choices=["id","title","datetime"],
        default="id",
        help="Sort by 'id', 'title', or 'datetime'"
    )
    return p.parse_args()

def strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}",1)[1]
    return root

def remove_sensitive(obj):
    # Drop any property or attribute with "password" or an IP
    for p in list(obj.findall(".//property")):
        n = (p.get("name") or "").lower()
        t = p.text or ""
        if "password" in n or IP_RE.search(t):
            parent = next((pr for pr in obj.iter() for ch in pr if ch is p), None)
            if parent:
                parent.remove(p)
    for a,v in list(obj.attrib.items()):
        if "password" in a.lower() or IP_RE.search(v):
            del obj.attrib[a]

def promote_title(obj):
    # Promote <property name="title"> → <title>
    prop = obj.find(".//property[@name='title']")
    if not prop:
        return False
    t = ET.Element("title")
    t.text = (prop.text or "").strip()
    obj.insert(0, t)
    # remove the old <property>
    parent = next((pr for pr in obj.iter() for ch in pr if ch is prop), None)
    if parent:
        parent.remove(prop)
    return True

def get_sort_key(mode):
    if mode=="id":
        return lambda o: int(o.findtext("id[@name='id']","0") or 0)
    if mode=="title":
        return lambda o: (o.findtext("title","") or "").lower()
    if mode=="datetime":
        def fk(o):
            ds = o.get("datetime","")
            try:
                return datetime.strptime(ds, "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.min
        return fk
    return lambda o: 0

def linkify(txt):
    parts   = URL_RE.split(txt)
    matches = URL_RE.findall(txt)
    out = []
    for i,part in enumerate(parts):
        out.append(html.escape(part))
        if i < len(matches):
            u = html.escape(matches[i])
            out.append(f'<a href="{u}" target="_blank">{u}</a>')
    return "".join(out)

def serialize_children(elem):
    """Render all child nodes of <element> as HTML, or fallback to text."""
    frags = [ET.tostring(c, encoding="unicode", method="html") for c in elem]
    joined = "".join(frags).strip()
    if not joined:
        joined = html.escape((elem.text or "").strip())
    return joined

def main():
    args = parse_args()
    inp  = Path(args.input_file)
    outp = Path(args.output_file)

    # 1) parse & strip namespaces
    try:
        tree = ET.parse(inp)
    except Exception as e:
        print(f"[ERROR] parsing {inp}: {e}", file=sys.stderr)
        sys.exit(1)
    root = strip_ns(tree.getroot())

    # 2) collect all Page objects
    pages = [o for o in root.findall("object") if o.get("class")=="Page"]

    # 3) clean & promote title on every page
    for o in pages:
        remove_sensitive(o)
        promote_title(o)

    # 4) sort the pages
    pages.sort(key=get_sort_key(args.key))

    # 5) rebuild under root
    for old in root.findall("object"):
        if old in pages:
            root.remove(old)
    for p in pages:
        root.append(p)

    # 6) write sorted XML
    xml_bytes  = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    pretty_xml = md.parseString(xml_bytes).toprettyxml(indent="  ")
    outp.write_text(pretty_xml, encoding="utf-8")
    print(f"[OK] XML → {outp}")

    # 7) build HTML report
    html_out = outp.with_suffix(".html")
    print(f"[DEBUG] writing HTML report to {html_out}")

    lines = [
      "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Pages Report</title>",
      "<style>",
      " body{font:14px sans-serif;margin:1em;} ",
      " section{border:1px solid #ccc;padding:1em;margin:1em 0;} ",
      " strong.label{display:block;margin-top:1em;font-size:1.1em;} ",
      "</style></head><body>",
      f"<h1>Pages ({len(pages)})</h1>"
    ]

    for o in pages:
        # Title (from promoted <title> or fallback to lowerTitle or no title)
        title = o.findtext("title","").strip()
        if not title:
            title = o.findtext(".//property[@name='lowerTitle']","").strip()
        if not title:
            title = "(no title)"

        lines.append("<section>")
        lines.append(f"<h2>{html.escape(title)}</h2>")

        # ID & Datetime
        if (i:=o.findtext("id[@name='id']")):
            lines.append(f"<p><strong>ID:</strong> {html.escape(i)}</p>")
        if (dt:=o.get("datetime")):
            lines.append(f"<p><strong>Datetime:</strong> {html.escape(dt)}</p>")

        # Lower Title
        if (lt:=o.findtext(".//property[@name='lowerTitle']")):
            lines.append(f"<p><strong>Lower Title:</strong> {html.escape(lt)}</p>")

        # Body Contents
        if (bc:=o.find(".//collection[@name='bodyContents']")) is not None:
            lines.append('<strong class="label">Body Contents</strong><ul>')
            for el in bc.findall("element"):
                lines.append(f"<li>{serialize_children(el)}</li>")
            lines.append("</ul>")

        # bodyContent property
        if (bcp:=o.findtext(".//property[@name='bodyContent']")):
            lines.append(f"<p><strong>BodyContent:</strong> {html.escape(bcp)}</p>")

        # Full <property name="body">
        if (bp := o.find(".//property[@name='body']")) is not None:
            # capture text before any children
            body_html = bp.text or ""
            # capture each child (tags, CDATA macros, tails)
            for child in bp:
                body_html += ET.tostring(child, encoding="unicode", method="html")
                if child.tail:
                    body_html += child.tail
            lines.append('<strong class="label">Body</strong>')
            lines.append('<div style="white-space: pre-wrap; margin-left:1em;">')
            lines.append(body_html)
            lines.append("</div>")

        # Outgoing Links
        if (ol:=o.find(".//collection[@name='outgoingLinks']")) is not None:
            lines.append('<strong class="label">Outgoing Links</strong><ul>')
            for el in ol.findall("element"):
                lines.append(f"<li>{serialize_children(el)}</li>")
            lines.append("</ul>")

        # content property
        if (ct:=o.findtext(".//property[@name='content']")):
            lines.append(f"<p><strong>Content:</strong> {html.escape(ct)}</p>")

        # all other properties
        skip = {"title","lowertitle","body","bodycontent","content"}
        for p in o.findall(".//property"):
            nm = (p.get("name") or "").lower()
            if nm in skip:
                continue
            txt = (p.text or "").strip()
            lines.append(
              f"<p><strong>{html.escape(p.get('name',''))}:</strong> {linkify(txt)}</p>"
            )

        lines.append("</section>")

    lines.append("</body></html>")
    html_out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] HTML → {html_out}")

if __name__=="__main__":
    main()
