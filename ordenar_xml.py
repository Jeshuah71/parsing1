#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to sort <object> elements in an XML file, strip sensitive data,
promote <property name="title"> into <title>, and emit:

  • cleaned, namespace-stripped, sorted XML → output.xml
  • user-friendly HTML report             → output.html

In the HTML, any <link> elements or properties named “link” or “url” will be
rendered as clickable <a> tags, so you don’t lose those important URLs.
"""

import argparse
import sys
import re
import xml.etree.ElementTree as ET
import xml.dom.minidom as md
from datetime import datetime
from pathlib import Path
import html

IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_PATTERN = re.compile(r"https?://\S+")

def parse_args():
    p = argparse.ArgumentParser(
        description="Sort <object> in XML, remove sensitive fields, promote title, then export to HTML"
    )
    p.add_argument("input_file",  help="Path to the input XML file")
    p.add_argument("output_file", help="Path where the sorted XML will be saved")
    p.add_argument(
        "-k","--key",
        choices=["id","title","datetime"],
        default="id",
        help="Sort by: 'id' (numeric), 'title' (alphabetical), 'datetime' (timestamp)"
    )
    return p.parse_args()

def strip_namespaces(elem):
    """Drop any namespace prefixes in tags."""
    for e in elem.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}",1)[1]
    return elem

def promote_title(obj):
    """Turn the first descendant <property name="title"> into a direct <title> child."""
    prop = obj.find(".//property[@name='title']")
    if not prop:
        return
    title_el = ET.Element("title")
    if prop.text:
        title_el.text = prop.text
    for child in list(prop):
        title_el.append(child)
    obj.insert(0, title_el)
    # remove original title property
    parent_map = {c: p for p in obj.iter() for c in p}
    parent = parent_map.get(prop, obj)
    parent.remove(prop)

def remove_sensitive_data(obj):
    for prop in list(obj.findall(".//property")):
        n = prop.get("name","").lower()
        t = (prop.text or "").strip()
        if "password" in n or IP_PATTERN.search(t):
            parent_map = {c: p for p in obj.iter() for c in p}
            parent = parent_map.get(prop, obj)
            parent.remove(prop)
    for attr,val in list(obj.attrib.items()):
        if "password" in attr.lower() or IP_PATTERN.search(val):
            del obj.attrib[attr]

def get_key_func(key):
    if key=="id":
        return lambda o: int(o.findtext("id[@name='id']","0") or 0)
    if key=="title":
        return lambda o: o.findtext("title","").lower()
    if key=="datetime":
        def k(o):
            ds = o.get("datetime","")
            try: return datetime.strptime(ds,"%Y-%m-%d %H:%M:%S")
            except: return datetime.min
        return k
    return lambda o: 0

def main():
    args    = parse_args()
    inp     = Path(args.input_file)
    xml_out = Path(args.output_file)

    # 1) parse & strip namespaces
    try:
        tree = ET.parse(inp)
        root = strip_namespaces(tree.getroot())
    except Exception as e:
        print(f"[ERROR] parsing '{inp}': {e}", file=sys.stderr)
        sys.exit(1)

    # 2) clean + promote title
    objects = root.findall("object")
    for o in objects:
        remove_sensitive_data(o)
        promote_title(o)

    # 3) sort
    key_func    = get_key_func(args.key)
    sorted_objs = sorted(objects, key=key_func)

    # 4) rebuild
    for o in objects:     root.remove(o)
    for o in sorted_objs: root.append(o)

    # 5) write XML with pretty-print so you can see <title>
    rough = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    pretty_xml = md.parseString(rough).toprettyxml(indent="  ")
    try:
        xml_out.write_text(pretty_xml, encoding="utf-8")
        print(f"[OK] Sorted XML with <title> tags saved to {xml_out}")
    except Exception as e:
        print(f"[ERROR] writing XML: {e}", file=sys.stderr)
        sys.exit(1)

    # 6) build HTML report, rendering any link/url as <a href=...>
    html_out = xml_out.with_suffix(".html")
    lines = [
      "<!DOCTYPE html>",
      "<html><head><meta charset='utf-8'><title>Objects Report</title>",
      "<style>",
      " body{font-family:sans-serif;padding:1em;}",
      " section{border:1px solid #ccc; padding:1em; margin:1em 0;}",
      " h2{margin:0 0.5em 0.3em;} a{color:blue;}",
      "</style></head><body>",
      f"<h1>Objects ({len(sorted_objs)})</h1>"
    ]

    for o in sorted_objs:
        title = html.escape(o.findtext("title","(no title)"))
        oid   = html.escape(o.findtext("id[@name='id']","(no id)"))
        dt    = html.escape(o.get("datetime","(no datetime)"))
        lines += [
            "<section>",
            f"<h2>{title}</h2>",
            f"<p><strong>ID:</strong> {oid}</p>",
            f"<p><strong>Datetime:</strong> {dt}</p>"
        ]

        # first, any <link> child elements
        for link in o.findall(".//link"):
            url = (link.text or "").strip()
            if URL_PATTERN.match(url):
                lines.append(f'<p><strong>Link:</strong> <a href="{html.escape(url)}" target="_blank">{html.escape(url)}</a></p>')

        # then properties
        for p in o.findall(".//property"):
            name = p.get("name","(no name)")
            text = (p.text or "").strip()
            low = name.lower()
            # if it's a URL-valued property
            if low in ("link","url") and URL_PATTERN.match(text):
                lines.append(f'<p><strong>{html.escape(name)}:</strong> <a href="{html.escape(text)}" target="_blank">{html.escape(text)}</a></p>')
            else:
                lines.append(f"<p><strong>{html.escape(name)}:</strong> {html.escape(text)}</p>")

        lines.append("</section>")

    lines.append("</body></html>")

    try:
        html_out.write_text("\n".join(lines), encoding="utf-8")
        print(f"[OK] HTML report saved to {html_out}")
    except Exception as e:
        print(f"[ERROR] writing HTML: {e}", file=sys.stderr)
        sys.exit(1)


if __name__=="__main__":
    main()
