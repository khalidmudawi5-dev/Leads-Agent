"""Build docs/SETUP_GUIDE_AR.pdf from docs/SETUP_GUIDE_AR.html (A4, light, print layout).

Uses the Playwright Chromium the agent already installs (01_install.bat), so Arabic shaping is
correct. The Tajawal font is embedded from app/static/fonts (works offline).

    .venv\\Scripts\\python.exe docs\\make_guide_pdf.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parent
FONTS = DOCS.parent / "app" / "static" / "fonts"
SRC = DOCS / "SETUP_GUIDE_AR.html"
OUT = DOCS / "SETUP_GUIDE_AR.pdf"

PRINT_CSS = """
@page { size: A4; margin: 14mm 12mm 16mm 12mm; }
html, body { background: #ffffff !important; }
body { font-size: 12.5px; line-height: 1.7; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.wrap { max-width: none; padding-block: 0; padding-inline: 0; }
.progress, .reset, .copy button { display: none !important; }
.copy pre { white-space: pre-wrap; word-break: break-all; }
.step, .note, .glossary div, tr, .phase-head { break-inside: avoid; }
.phase-head, .phase-intro { break-after: avoid; }
.phase { margin-top: 18px; }
.phase:has(> .phase-head .letter) { break-before: page; margin-top: 0; }
.phase.tail { break-before: auto; margin-top: 22px; }
.step { padding: 9px 12px; }
a { color: inherit; text-decoration: none; }
h1 { font-size: 22px; }
footer { display: none; }
"""


def font_css() -> str:
    css = (FONTS / "tajawal.css").read_text(encoding="utf-8")
    return re.sub(r"url\('([^']+)'\)", lambda m: f"url('{(FONTS / m.group(1)).as_uri()}')", css)


def main(executable: str | None = None) -> Path:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        page = browser.new_page()
        page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"), lambda route: route.abort())
        page.goto(SRC.as_uri(), wait_until="load")
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        page.add_style_tag(content=font_css() + PRINT_CSS)
        page.evaluate("document.fonts.ready")
        page.emulate_media(media="print")
        page.pdf(
            path=str(OUT), format="A4", print_background=True, prefer_css_page_size=True,
            display_header_footer=True, header_template="<span></span>",
            footer_template=(
                '<div style="width:100%;font-size:8px;color:#767b96;text-align:center;font-family:sans-serif">'
                'Khalid Leads Agent · Setup guide · <span class="pageNumber"></span> / <span class="totalPages"></span></div>'
            ),
        )
        browser.close()
    return OUT


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else None))
