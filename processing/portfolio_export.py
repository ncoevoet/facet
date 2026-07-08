"""Static portfolio export — turn an album into a self-contained HTML gallery.

``export_portfolio`` writes a target directory the photographer can drop on any
web host: an ``index.html`` (responsive CSS-only thumbnail grid plus an inline
vanilla-JS lightbox), an ``assets/`` folder of sequentially-named JPEGs, and a
``manifest.json`` recording the export. There are ZERO external or CDN
references — no fonts, scripts or stylesheets are fetched — so the page works
fully offline.

Per photo the renderer prefers the ORIGINAL file on disk (downscaled to a
configurable long edge via ``utils.image_loading.load_image_from_path``, EXIF
orientation applied) and falls back to the stored 640px thumbnail BLOB when the
original is unreachable (offline network shares). The source used is recorded per
photo in the manifest.

Output filenames are sequential and sanitized so no library path is leaked.
Generation is deterministic (no timestamps) and idempotent — a re-export rewrites
only its own ``index.html``, ``manifest.json`` and ``assets/`` directory.
"""

import html
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image

from utils.image_loading import load_image_from_path

logger = logging.getLogger("facet.portfolio_export")

SOURCE_ORIGINAL = "original"
SOURCE_THUMBNAIL = "thumbnail"

ASSETS_DIR_NAME = "assets"
INDEX_FILE_NAME = "index.html"
MANIFEST_FILE_NAME = "manifest.json"
ASSET_PREFIX = "photo"


def _contained(root, *parts):
    """Join ``parts`` under ``root`` and require the result to stay inside it.

    Defense-in-depth behind the API-level ``allowed_target_dirs`` validation:
    every path this module writes is normalized and refused if it resolves
    outside the export directory (e.g. through a symlinked subpath).
    """
    root_real = os.path.realpath(root)
    if not parts:
        return root_real
    candidate = os.path.realpath(os.path.join(root_real, *parts))
    if candidate != root_real and not candidate.startswith(root_real + os.sep):
        raise ValueError("path escapes the export directory")
    return candidate


@dataclass
class PortfolioOptions:
    """Rendering options for a portfolio export."""

    title: str = "Portfolio"
    subtitle: str = ""
    max_edge: int = 2048
    jpeg_quality: int = 88
    include_captions: bool = True
    group_by_date: bool = False


@dataclass
class _RenderedEntry:
    file: str
    caption: str
    date: str
    source: str = field(default=SOURCE_ORIGINAL)


def export_portfolio(photos, output_dir, options):
    """Write a self-contained static portfolio into ``output_dir``.

    Args:
        photos: Ordered list of dict-like rows. Each row may carry ``path`` (a
            filesystem path to the original to attempt, or ``None``), ``caption``,
            ``date`` and ``thumbnail`` (a JPEG BLOB fallback, ``bytes`` or ``None``).
        output_dir: Destination directory (created if missing).
        options: A ``PortfolioOptions`` instance.

    Returns:
        dict with ``exported``, ``from_original``, ``from_thumbnail`` and
        ``output_dir``.
    """
    output_dir = _contained(output_dir)
    assets_dir = _contained(output_dir, ASSETS_DIR_NAME)
    os.makedirs(output_dir, exist_ok=True)
    shutil.rmtree(assets_dir, ignore_errors=True)
    os.makedirs(assets_dir, exist_ok=True)

    entries = []
    from_original = 0
    from_thumbnail = 0

    for photo in photos:
        image, source = _load_source_image(photo, options.max_edge)
        if image is None:
            continue
        seq = len(entries) + 1
        asset_name = f"{ASSET_PREFIX}-{seq:04d}.jpg"
        image.save(
            _contained(assets_dir, asset_name),
            format="JPEG",
            quality=options.jpeg_quality,
        )
        entries.append(
            _RenderedEntry(
                file=f"{ASSETS_DIR_NAME}/{asset_name}",
                caption=str(photo.get("caption") or "") if options.include_captions else "",
                date=str(photo.get("date") or ""),
                source=source,
            )
        )
        if source == SOURCE_ORIGINAL:
            from_original += 1
        else:
            from_thumbnail += 1

    _write_index(output_dir, entries, options)
    _write_manifest(output_dir, entries, options, from_original, from_thumbnail)

    return {
        "exported": len(entries),
        "from_original": from_original,
        "from_thumbnail": from_thumbnail,
        "output_dir": output_dir,
    }


def _load_source_image(photo, max_edge):
    """Return ``(pil_image, source)`` for a row, or ``(None, None)`` when unusable.

    Prefers the on-disk original, falling back to the stored thumbnail BLOB.
    """
    path = photo.get("path")
    if path and os.path.isfile(path):
        pil_img, _ = load_image_from_path(path)
        if pil_img is not None:
            return _fit(pil_img.convert("RGB"), max_edge), SOURCE_ORIGINAL

    thumbnail = photo.get("thumbnail")
    if thumbnail:
        try:
            img = Image.open(BytesIO(thumbnail)).convert("RGB")
            return _fit(img, max_edge), SOURCE_THUMBNAIL
        except (OSError, ValueError):
            logger.debug("Failed to decode thumbnail BLOB", exc_info=True)

    return None, None


def _fit(image, max_edge):
    """Downscale ``image`` in place so its longest edge is at most ``max_edge``."""
    if max_edge and max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return image


def _write_manifest(output_dir, entries, options, from_original, from_thumbnail):
    manifest = {
        "title": options.title,
        "subtitle": options.subtitle,
        "exported": len(entries),
        "from_original": from_original,
        "from_thumbnail": from_thumbnail,
        "photos": [
            {"file": e.file, "caption": e.caption, "date": e.date, "source": e.source}
            for e in entries
        ],
    }
    with open(_contained(output_dir, MANIFEST_FILE_NAME), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _write_index(output_dir, entries, options):
    with open(_contained(output_dir, INDEX_FILE_NAME), "w", encoding="utf-8") as fh:
        fh.write(_render_html(entries, options))


def _render_html(entries, options):
    header = f'<h1>{html.escape(options.title)}</h1>'
    if options.subtitle:
        header += f'<p class="subtitle">{html.escape(options.subtitle)}</p>'

    grid = "".join(_render_cell(e, options) for e in entries)
    if options.group_by_date:
        grid = _render_grouped(entries, options)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(options.title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        f'<header>{header}</header>\n'
        f'<main class="grid">{grid}</main>\n'
        f'{_LIGHTBOX_MARKUP}\n'
        f"<script>{_LIGHTBOX_JS}</script>\n"
        "</body>\n</html>\n"
    )


def _render_grouped(entries, options):
    groups = []
    current_date = None
    for e in entries:
        if e.date != current_date:
            current_date = e.date
            label = html.escape(e.date) if e.date else ""
            groups.append(f'<h2 class="group">{label}</h2>')
        groups.append(_render_cell(e, options))
    return "".join(groups)


def _render_cell(entry, options):
    caption_attr = f' data-caption="{html.escape(entry.caption, quote=True)}"' if entry.caption else ""
    cap_html = ""
    if options.include_captions and entry.caption:
        cap_html = f'<figcaption>{html.escape(entry.caption)}</figcaption>'
    return (
        f'<figure class="cell"><a href="{html.escape(entry.file, quote=True)}"{caption_attr}>'
        f'<img loading="lazy" src="{html.escape(entry.file, quote=True)}" alt="">'
        f"</a>{cap_html}</figure>"
    )


_CSS = (
    ":root{--bg:#fafafa;--fg:#1a1a1a;--muted:#666;--cell:#eee}"
    "@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--muted:#999;--cell:#1e1e1e}}"
    "*{box-sizing:border-box}"
    "body{margin:0;background:var(--bg);color:var(--fg);"
    "font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}"
    "header{padding:2.5rem 1.5rem 1rem;text-align:center}"
    "h1{margin:0;font-weight:600;font-size:1.9rem;letter-spacing:.01em}"
    ".subtitle{margin:.4rem 0 0;color:var(--muted)}"
    "h2.group{grid-column:1/-1;margin:1.5rem 0 .25rem;font-size:1rem;font-weight:600;color:var(--muted)}"
    ".grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));"
    "padding:1.5rem;max-width:1600px;margin:0 auto}"
    ".cell{margin:0}"
    ".cell a{display:block;overflow:hidden;border-radius:6px;background:var(--cell)}"
    ".cell img{display:block;width:100%;aspect-ratio:3/2;object-fit:cover;cursor:zoom-in;"
    "transition:transform .25s ease}"
    ".cell a:hover img{transform:scale(1.04)}"
    ".cell figcaption{margin-top:.35rem;font-size:.82rem;color:var(--muted);line-height:1.3}"
    "#lb{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;"
    "align-items:center;justify-content:center;z-index:100}"
    "#lb.open{display:flex}"
    "#lb img{max-width:94vw;max-height:88vh;object-fit:contain;border-radius:4px}"
    "#lb figcaption{position:fixed;bottom:1.2rem;left:0;right:0;text-align:center;"
    "color:#eee;font-size:.9rem;padding:0 1rem}"
    "#lb button{position:fixed;top:0;bottom:0;border:0;background:none;color:#fff;"
    "font-size:2.4rem;cursor:pointer;padding:0 1.2rem;opacity:.7}"
    "#lb button:hover{opacity:1}"
    "#lb .prev{left:0}#lb .next{right:0}"
    "#lb .close{top:.5rem;bottom:auto;right:.5rem;left:auto;font-size:2rem}"
)

_LIGHTBOX_MARKUP = (
    '<div id="lb" role="dialog" aria-modal="true">'
    '<button class="prev" aria-label="Previous">&#8249;</button>'
    '<img alt="">'
    '<button class="next" aria-label="Next">&#8250;</button>'
    '<button class="close" aria-label="Close">&#215;</button>'
    "<figcaption></figcaption></div>"
)

_LIGHTBOX_JS = (
    "(function(){"
    "var cells=[].slice.call(document.querySelectorAll('.cell a'));"
    "var lb=document.getElementById('lb');"
    "var img=lb.querySelector('img');var cap=lb.querySelector('figcaption');var i=0;"
    "function show(n){i=(n+cells.length)%cells.length;var a=cells[i];"
    "img.src=a.getAttribute('href');cap.textContent=a.getAttribute('data-caption')||'';"
    "lb.classList.add('open');}"
    "function close(){lb.classList.remove('open');img.src='';}"
    "cells.forEach(function(a,n){a.addEventListener('click',function(e){e.preventDefault();show(n);});});"
    "lb.querySelector('.prev').addEventListener('click',function(e){e.stopPropagation();show(i-1);});"
    "lb.querySelector('.next').addEventListener('click',function(e){e.stopPropagation();show(i+1);});"
    "lb.querySelector('.close').addEventListener('click',close);"
    "lb.addEventListener('click',function(e){if(e.target===lb)close();});"
    "document.addEventListener('keydown',function(e){if(!lb.classList.contains('open'))return;"
    "if(e.key==='Escape')close();else if(e.key==='ArrowLeft')show(i-1);"
    "else if(e.key==='ArrowRight')show(i+1);});"
    "})();"
)
