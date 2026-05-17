"""Converte docs/technical-documentation.md para HTML estilizado e tenta gerar PDF."""
from pathlib import Path
import markdown

ROOT = Path(__file__).resolve().parent.parent
md_path = ROOT / "docs" / "technical-documentation.md"
html_path = ROOT / "docs" / "technical-documentation.html"
pdf_path = ROOT / "docs" / "technical-documentation.pdf"

md_text = md_path.read_text(encoding="utf-8")
html_body = markdown.markdown(md_text, extensions=["fenced_code", "tables", "codehilite"])

style = """
body { font-family: -apple-system, Segoe UI, sans-serif; max-width: 850px; margin: 40px auto; padding: 20px; line-height: 1.5; color: #222; }
h1 { color: #0a0a0a; border-bottom: 3px solid #ff6b00; padding-bottom: 8px; }
h2 { color: #4a148c; margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
h3 { color: #ff6b00; }
code, pre { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; font-family: Consolas, Monaco, monospace; }
pre { padding: 12px; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; }
th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
th { background: #4a148c; color: white; }
a { color: #ff6b00; }
blockquote { border-left: 4px solid #ff6b00; padding-left: 12px; color: #555; margin: 12px 0; }
"""

full_html = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<title>14 Garras Auto-Publisher — Technical Documentation</title>"
    f"<style>{style}</style></head><body>{html_body}</body></html>"
)
html_path.write_text(full_html, encoding="utf-8")
print(f"HTML gerado: {html_path}")
print(f"Tamanho: {html_path.stat().st_size / 1024:.1f} KB")

# Tenta gerar PDF via WeasyPrint (pode falhar no Windows sem GTK)
try:
    from weasyprint import HTML
    HTML(string=full_html).write_pdf(str(pdf_path))
    print(f"PDF gerado: {pdf_path}")
    print(f"Tamanho: {pdf_path.stat().st_size / 1024:.1f} KB")
except Exception as e:
    print(f"PDF via WeasyPrint falhou: {e}")
    print("\nALTERNATIVA: abra o HTML no browser e use Ctrl+P → 'Salvar como PDF'")
    print(f"  start {html_path}")
