"""Gera capa (thumbnail YouTube) para vídeos longos.

Estratégia:
1. Extrai frame do source no momento ~30% do corte (geralmente mais expressivo)
2. Aplica gradiente escuro no rodapé pra legibilidade do texto
3. Adiciona título do corte em texto grande
4. Adiciona logo 14 Garras no canto

Resultado: cuts/<source_id>/thumbnails/<cut>_cover.jpg em 1280x720.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from common import ROOT, load_config


def _ffmpeg_path(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:")


def _drawtext_escape(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
         .replace(":", "\\:")
         .replace("'", "’")
         .replace(",", "\\,")
         .replace("%", "\\%")
    )


def _find_font() -> str:
    candidates = [
        r"C:\Windows\Fonts\impact.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise FileNotFoundError("nenhuma fonte TTF encontrada")


def _wrap_title(text: str, max_chars_per_line: int = 28, max_lines: int = 2) -> str:
    """Quebra título em até 2 linhas balanceadas pra thumbnail."""
    words = text.split()
    if not words:
        return text
    if len(text) <= max_chars_per_line:
        return text
    # Procura o melhor ponto de split (mais balanceado)
    best_split = 1
    best_diff = float("inf")
    for i in range(1, len(words)):
        l1 = " ".join(words[:i])
        l2 = " ".join(words[i:])
        if len(l1) > max_chars_per_line or len(l2) > max_chars_per_line:
            continue
        diff = abs(len(l1) - len(l2))
        if diff < best_diff:
            best_diff = diff
            best_split = i
    if best_diff == float("inf"):
        # Sem split que caiba — força corte
        return text[:max_chars_per_line * 2]
    return " ".join(words[:best_split]) + "\n" + " ".join(words[best_split:])


def find_custom_cover(source_id: str) -> Path | None:
    """Procura imagem custom da capa em inbox/<source_id>.cover.{jpg,png,jpeg}.

    Se existir, será usada como base da capa (em vez de extrair frame do vídeo).
    Útil pra arte de capa do designer (1280x720 ou 9:16 reescalado).
    """
    inbox = ROOT / "inbox"
    for ext in ("jpg", "jpeg", "png"):
        p = inbox / f"{source_id}.cover.{ext}"
        if p.exists():
            return p
    return None


def create_cover(
    source_video: Path,
    cut_start: float,
    cut_end: float,
    titulo: str,
    out_path: Path,
    cfg: dict,
    custom_cover: Path | None = None,
) -> None:
    """Gera capa 1280x720 (YouTube long padrão).

    Se `custom_cover` for fornecida (ex: arte criada à parte), usa ela como
    background diretamente — sem overlays de texto/banner. Útil quando o
    designer já entregou a capa pronta.

    Caso contrário, extrai frame do source no tempo cut_start + 30% e
    sobrepoõe banner laranja com título + tag '14 GARRAS'.
    """
    # Modo 1: capa custom já pronta — só escala/encaixa, sem overlay
    if custom_cover is not None and custom_cover.exists():
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(custom_cover),
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
            "-q:v", "2",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return

    # Modo 2: tenta Gemini (Nano Banana) — qualidade alta, custa ~$0.04/img
    cover_mode = cfg.get("render", {}).get("cover", {}).get("mode", "gemini")
    if cover_mode == "gemini":
        try:
            from cover_gemini import generate_cover as gen_gemini_cover
            gen_gemini_cover(source_video, cut_start, cut_end, titulo, out_path, cfg)
            return
        except Exception as e:
            print(f"[cover] Gemini falhou ({e}), tentando HTML")
            cover_mode = "html"

    # Modo 3: template HTML local + rembg (fallback)
    if cover_mode == "html":
        try:
            from cover_html import render_cover as render_html_cover
            render_html_cover(source_video, cut_start, cut_end, titulo, out_path)
            return
        except Exception as e:
            print(f"[cover] HTML falhou ({e}), caindo no fallback ffmpeg")

    # Modo 4 (fallback): gera capa a partir de frame + overlays ffmpeg
    duration = cut_end - cut_start
    snapshot_ts = cut_start + duration * 0.30
    font_path = _find_font()
    font_for_filter = _ffmpeg_path(font_path)

    wrapped = _wrap_title(titulo, max_chars_per_line=28, max_lines=2)
    titulo_safe = _drawtext_escape(wrapped)

    # Filter graph:
    # 1. Escala/croppa pra 1280x720 mantendo aspect 16:9
    # 2. Aplica gradiente preto no rodapé (overlay com gblur ou drawbox)
    # 3. Escreve título em destaque
    # 4. (opcional) Sobrepoõe logo
    # Coordenadas absolutas (1280x720)
    num_lines = wrapped.count("\n") + 1
    banner_h = 90 + (num_lines * 75)
    banner_y = 720 - banner_h     # absoluto
    text_y = banner_y + 40

    vf_parts = [
        "scale=1280:720:force_original_aspect_ratio=increase",
        "crop=1280:720",
        # Banner laranja sólido no rodapé
        f"drawbox=x=0:y={banner_y}:w=1280:h={banner_h}:color=0xFF6B00:t=fill",
        # Linha branca fina no topo do banner
        f"drawbox=x=0:y={banner_y}:w=1280:h=6:color=white:t=fill",
        # Título no banner
        f"drawtext=fontfile='{font_for_filter}':text='{titulo_safe}':"
        f"fontcolor=white:fontsize=58:bordercolor=black:borderw=4:"
        f"x=(w-text_w)/2:y={text_y}:line_spacing=16",
        # Banner '14 GARRAS' no topo esquerdo
        "drawbox=x=20:y=20:w=260:h=70:color=0x4A148C:t=fill",
        "drawbox=x=20:y=84:w=260:h=6:color=0xFF6B00:t=fill",
        f"drawtext=fontfile='{font_for_filter}':text='14 GARRAS':"
        f"fontcolor=white:fontsize=42:x=50:y=38",
    ]

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(snapshot_ts),
        "-i", str(source_video),
        "-frames:v", "1",
        "-vf", ",".join(vf_parts),
        "-q:v", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: cover_generator.py <source_id>")
        sys.exit(1)
    source_id = sys.argv[1]
    cfg = load_config()

    import json
    cuts_dir = ROOT / "cuts" / source_id
    raw_dir = ROOT / "raw" / source_id
    source_video = raw_dir / "source.mp4"
    plan = json.loads((cuts_dir / "plan.json").read_text(encoding="utf-8"))

    thumbs_dir = cuts_dir / "thumbnails"
    thumbs_dir.mkdir(exist_ok=True)

    longs_n = 0
    for cut in plan["cortes"]:
        if cut["tipo"] != "long":
            continue
        longs_n += 1
        out = thumbs_dir / f"long_{longs_n:02d}_cover.jpg"
        print(f"[cover] long_{longs_n:02d}: {cut['titulo'][:50]}...")
        try:
            create_cover(source_video, cut["start"], cut["end"], cut["titulo"], out, cfg)
            print(f"[cover]   ✅ {out.name}")
        except Exception as e:
            print(f"[cover]   ❌ {e}")


if __name__ == "__main__":
    main()
