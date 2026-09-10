"""Render Markdown to PDF via HTML + CSS (python-markdown + WeasyPrint).

Pandoc's LaTeX backend gives Markdown tables fixed, equal-width columns with
no wrapping, which falls apart on this report's wide tables (11 columns in
Device Interfaces). Going through HTML/CSS instead gives real control over
column wrapping, font size, and page orientation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PDF_CSS = """
@page {
    size: A4 landscape;
    margin: 1.3cm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-size: 8pt;
        color: #666;
    }
}

body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.35;
    color: #111;
}

h1 { font-size: 20pt; margin-bottom: 0.2em; bookmark-level: 1; }
h2 {
    font-size: 15pt;
    margin-top: 1.2em;
    border-bottom: 1.5pt solid #333;
    padding-bottom: 0.15em;
    page-break-after: avoid;
    bookmark-level: 2;
}
h3 {
    font-size: 12pt;
    margin-top: 1em;
    margin-bottom: 0.3em;
    page-break-after: avoid;
    bookmark-level: 3;
}

em { color: #555; }

table {
    width: 100%;
    border-collapse: collapse;
    table-layout: auto;
    margin: 0.4em 0 1em 0;
    page-break-inside: auto;
}
th, td {
    border: 0.75pt solid #bbb;
    padding: 3px 5px;
    font-size: 8pt;
    text-align: left;
    vertical-align: top;
    word-wrap: break-word;
    overflow-wrap: anywhere;
}
th {
    background: #eee;
    font-weight: 600;
}
tr { page-break-inside: avoid; }

ul { margin: 0.3em 0; }
"""

HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


class PdfDependencyError(RuntimeError):
    pass


class PdfRenderError(RuntimeError):
    pass


def _add_homebrew_lib_path() -> None:
    """Homebrew's lib directory isn't on macOS's default dynamic linker
    search path, so WeasyPrint's cffi-based loader fails to find
    Homebrew-installed Pango/Cairo/GDK-Pixbuf even when they're on disk
    (`brew install pango`). Point DYLD_LIBRARY_PATH at it before WeasyPrint
    runs its dlopen() calls at import time.

    Sets at most one directory rather than merging in existing/further
    candidates: dyld reliably honors a single-entry DYLD_LIBRARY_PATH set
    from within the running process, but a multi-entry value set the same
    way (after process start, as opposed to being present at exec time)
    was observed to be silently ignored -- so a machine carrying both a
    stale Intel Homebrew at /usr/local and the real one at /opt/homebrew
    would end up with neither honored. Leaves an existing value alone,
    on the assumption the user or shell set it deliberately.
    """
    if sys.platform != "darwin" or "DYLD_LIBRARY_PATH" in os.environ:
        return
    for prefix in ("/opt/homebrew", "/usr/local"):
        lib_dir = f"{prefix}/lib"
        if os.path.isdir(lib_dir):
            os.environ["DYLD_LIBRARY_PATH"] = lib_dir
            return


def render_pdf(markdown_path: str, pdf_path: str) -> None:
    _add_homebrew_lib_path()
    try:
        import markdown as markdown_lib
        from weasyprint import HTML
    except ImportError as exc:
        raise PdfDependencyError(
            "PDF rendering requires the 'pdf' extra. Install it with:\n"
            '  pip install -e ".[pdf]"\n'
            f"(missing dependency: {exc.name})"
        ) from exc
    except OSError as exc:
        raise PdfDependencyError(
            "WeasyPrint could not load its native dependencies (Pango, "
            "Cairo, GDK-Pixbuf). On macOS: brew install pango. See "
            "https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation\n"
            f"(underlying error: {exc})"
        ) from exc

    markdown_text = Path(markdown_path).read_text(encoding="utf-8")
    # "toc" is used only for its side effect of assigning an id to every
    # heading (matching the #anchor links in the Table of Contents) -- no
    # [TOC] marker is in the source, so it doesn't also inject its own div.
    body_html = markdown_lib.markdown(markdown_text, extensions=["tables", "toc"])
    full_html = HTML_TEMPLATE.format(css=PDF_CSS, body=body_html)

    try:
        HTML(string=full_html, base_url=str(Path(markdown_path).parent)).write_pdf(pdf_path)
    except Exception as exc:  # weasyprint raises assorted errors on bad input
        raise PdfRenderError(f"WeasyPrint failed to render PDF: {exc}") from exc
