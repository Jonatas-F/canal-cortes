"""Converte docs/technical-documentation.html → PDF usando Playwright/Chromium."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
html_path = ROOT / "docs" / "technical-documentation.html"
pdf_path = ROOT / "docs" / "technical-documentation.pdf"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(f"file:///{html_path.as_posix()}", wait_until="networkidle")
    page.pdf(
        path=str(pdf_path),
        format="A4",
        margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
        print_background=True,
    )
    browser.close()

size_kb = pdf_path.stat().st_size / 1024
print(f"OK PDF gerado: {pdf_path}")
print(f"Tamanho: {size_kb:.1f} KB ({size_kb/1024:.2f} MB)")
