#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ordenar_xml.py

1) Sort <object class="Page"> by id/title/creationDate
2) Strip passwords & IPs
3) Promote <property name="title"> → <title>
4) Emit:
   • cleaned, sorted XML → output_file.xml
   • rich HTML report → output_file.html
"""

import argparse
import sys
import re
import html
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime

# Patterns to detect sensitive data and URLs
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_RE = re.compile(r"https?://[^\s<>\]]+")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Procesa XML de Confluence y genera XML ordenado y reporte HTML"
    )
    parser.add_argument("input_file", help="Archivo XML de entrada")
    parser.add_argument("output_base", help="Ruta base para salida (sin extensión)")
    parser.add_argument(
        "-k", "--key",
        choices=["id", "title", "creationDate"],
        default="id",
        help="Clave de orden: 'id', 'title' o 'creationDate'"
    )
    return parser.parse_args()


def strip_ns(elem):
    for e in elem.iter():
        if isinstance(e.tag, str) and '}' in e.tag:
            e.tag = e.tag.split('}', 1)[1]
    return elem


def remove_sensitive(obj):
    for p in list(obj.findall('.//property')):
        name = (p.get('name') or '').lower()
        text_all = ''.join(p.itertext())
        if 'password' in name or IP_RE.search(text_all):
            parent = next((pr for pr in obj.iter() if p in pr), None)
            if parent:
                parent.remove(p)
    for attr in list(obj.attrib):
        if 'password' in attr.lower() or IP_RE.search(obj.attrib[attr]):
            del obj.attrib[attr]


def promote_title(obj):
    prop = obj.find('./property[@name="title"]')
    if not prop:
        return
    title_el = ET.Element('title')
    title_el.text = (prop.text or '').strip()
    obj.insert(0, title_el)
    obj.remove(prop)


def get_sort_key(mode):
    if mode == 'id':
        return lambda o: int(o.findtext('id[@name="id"]', default='0') or 0)
    if mode == 'title':
        return lambda o: (o.findtext('title', default='') or '').lower()
    if mode == 'creationDate':
        def key_fn(o):
            s = o.findtext('property[@name="creationDate"]', default='')
            try:
                return datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return datetime.min
        return key_fn
    return lambda o: 0


def linkify(text):
    parts = URL_RE.split(text)
    urls = URL_RE.findall(text)
    out = []
    for i, part in enumerate(parts):
        out.append(html.escape(part))
        if i < len(urls):
            u = html.escape(urls[i])
            out.append(f'<a href="{u}" target="_blank">{u}</a>')
    return ''.join(out)


def serialize_children(elem):
    if list(elem):
        return ''.join(ET.tostring(c, encoding='unicode', method='html') for c in elem)
    return html.escape(elem.text or '')


def write_sorted_xml(tree, root, pages, out_xml):
    kept = [e for e in root if not (e.tag == 'object' and e.get('class') == 'Page')]
    root[:] = kept + pages
    if hasattr(ET, 'indent'):
        ET.indent(tree, space='  ')
    tree.write(out_xml, encoding='utf-8', xml_declaration=True)


def write_html_report(pages, body_map, out_html):
    lines = [
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8"><title>Reporte de Páginas</title>',
        '<style>',
        'body{font:14px sans-serif;margin:1em;}',
        'section{border:1px solid #ccc;padding:1em;margin:1em 0;}',
        '.label{font-weight:bold;margin-top:0.5em;display:block;}',
        '.body-content-block{border:1px dashed #999;padding:0.5em;margin:0.5em 0;}',
        '.body-content-block h4{margin:0.2em 0;}',
        'pre{background:#f8f8f8;padding:0.5em;overflow:auto;}',
        'details{margin-top:0.5em;}','summary{cursor:pointer;font-weight:bold;}',
        '</style></head><body>',
        f'<h1>Páginas ({len(pages)})</h1>'
    ]
    for o in pages:
        lines.append('<section>')
        # Determine title or fallback
        title = o.findtext('title')
        if title:
            title = title.strip()
        else:
            title = o.findtext('property[@name="lowerTitle"]', default='').strip()
        if not title:
            title = '(sin título)'
        lines.append(f'<h2>{html.escape(title)}</h2>')
        # ID and creation date
        if (idv := o.findtext('id[@name="id"]')):
            lines.append(f'<p><span class="label">ID:</span> {html.escape(idv)}</p>')
        if (cd := o.findtext('property[@name="creationDate"]')):
            lines.append(f'<p><span class="label">Fecha creación:</span> {html.escape(cd)}</p>')

        # Body content sections
        bc = o.find('.//collection[@name="bodyContents"]')
        if bc is not None:
            lines.append('<h3 class="label">Body Content</h3>')
            for elem in bc.findall('element'):
                bc_id = elem.findtext('id[@name="id"]')
                bc_obj = body_map.get(bc_id)
                if bc_obj is not None:
                    body_prop = bc_obj.find('property[@name="body"]')
                    if body_prop is not None:
                        lines.append('<div class="body-content-block">')
                        lines.append(f'<h4>Entry ID: {html.escape(bc_id)}</h4>')
                        raw = ET.tostring(body_prop, encoding='unicode')
                        lines.append('<details><summary>Raw body</summary>')
                        lines.append(f'<pre>{html.escape(raw)}</pre></details>' )
                        content = ''.join(ET.tostring(c, encoding='unicode', method='html') for c in body_prop)
                        if not content:
                            content = html.escape(body_prop.text or '')
                        lines.append('<details open><summary>Rendered body</summary>')
                        lines.append(f'<div style="white-space:pre-wrap;margin-left:1em;">{content}</div>')
                        lines.append('</details>')
                        lines.append('</div>')

        # Other properties
        skip = {'title','creationdate','lowertitle','body'}
        for prop in o.findall('property'):
            nm = prop.get('name','')
            if nm.lower() in skip:
                continue
            txt = ''.join(prop.itertext()).strip()
            if txt:
                lines.append(f'<p><span class="label">{html.escape(nm)}:</span> {linkify(txt)}</p>')

        # Other collections
        for coll in o.findall('collection'):
            nm = coll.get('name','')
            if nm == 'bodyContents':
                continue
            lines.append(f'<p><span class="label">Colección: {html.escape(nm)}</span></p><ul>')
            for el in coll.findall('element'):
                lines.append(f'<li>{serialize_children(el)}</li>')
            lines.append('</ul>')

        # Raw object XML
        rawobj = ET.tostring(o, encoding='unicode')
        lines.append('<details><summary>XML crudo de la sección</summary>')
        lines.append(f'<pre>{html.escape(rawobj)}</pre>')
        lines.append('</details></section>')

    lines.append('</body></html>')
    Path(out_html).write_text('\n'.join(lines), encoding='utf-8')


def main():
    args = parse_args()
    inp = Path(args.input_file)
    base = Path(args.output_base)
    try:
        tree = ET.parse(inp)
    except Exception as e:
        print(f"[ERROR] Failed parsing {{inp}}: {{e}}", file=sys.stderr)
        sys.exit(1)
    root = strip_ns(tree.getroot())

    pages = root.findall('.//object[@class="Page"]')
    body_objs = root.findall('.//object[@class="BodyContent"]')
    body_map = {bo.findtext('id[@name="id"]'): bo for bo in body_objs}

    for p in pages:
        remove_sensitive(p)
        promote_title(p)
    pages.sort(key=get_sort_key(args.key))

    out_xml = base.with_suffix('.xml')
    write_sorted_xml(tree, root, pages, out_xml)
    print(f"[OK] XML ordenado → {out_xml}")

    out_html = base.with_suffix('.html')
    write_html_report(pages, body_map, out_html)
    print(f"[OK] HTML generado → {out_html}")

if __name__ == '__main__':
    main()
