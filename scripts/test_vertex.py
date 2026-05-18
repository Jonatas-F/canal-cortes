"""Smoke test: gera 1 imagem simples via Vertex AI pra validar credenciais."""
import os
from pathlib import Path

from common import ROOT, load_config
from cover_gemini import _make_genai_client
from google.genai import types

cfg = load_config()
client = _make_genai_client(cfg)

print("[test_vertex] enviando prompt simples...")
try:
    resp = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=["Generate a simple colorful image: orange circle on black background, 1024x1024"],
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )
    img_bytes = None
    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            img_bytes = part.inline_data.data
            break
        if part.text:
            print(f"[test_vertex] texto: {part.text[:100]}")
    if img_bytes:
        out = ROOT / "vertex_test.jpg"
        out.write_bytes(img_bytes)
        print(f"[test_vertex] ✅ imagem salva: {out} ({len(img_bytes)//1024} KB)")
    else:
        print("[test_vertex] ❌ sem imagem na resposta")
except Exception as e:
    print(f"[test_vertex] ❌ {type(e).__name__}: {e}")
