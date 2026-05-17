"""Pipeline completo: link YouTube → cortes prontos no YouTube agendados.

Uso:
    python scripts/pipeline.py <URL>             # baixa, corta, agenda, NÃO publica
    python scripts/pipeline.py <URL> --upload    # baixa, corta, agenda e PUBLICA tudo
    python scripts/pipeline.py --upload-only     # só publica fila pendente

Workflow padrão (--upload incluso):
1. ingest:   yt-dlp + faster-whisper transcription
2. analyze:  Claude lê transcript → plan.json com cortes virais
3. sync:     gera notas iniciais no Obsidian
4. render:   ffmpeg + Gemini cover (longs) + end card
5. enqueue:  insere fila SQLite + calcula slots (publishAt)
6. publish:  videos.insert com publishAt → YouTube agenda nativamente
7. sync2:    atualiza Obsidian com youtube_video_id

Após upload bem-sucedido, máquina pode ser DESLIGADA — YouTube publica sozinho.

Necessário manifesto autorizado em inbox/<id>.json (autorizado=true) pra publicar.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from common import ROOT, load_config, video_id_from_url


PYTHON = sys.executable


def step(name: str, args: list[str]) -> None:
    print(f"\n{'=' * 60}\n=== {name}\n{'=' * 60}")
    t0 = time.monotonic()
    r = subprocess.run([PYTHON, "scripts/" + args[0]] + args[1:], cwd=ROOT)
    elapsed = time.monotonic() - t0
    print(f"=== {name} concluído em {elapsed:.1f}s (exit {r.returncode})")
    if r.returncode != 0:
        raise SystemExit(f"FALHA em {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Pipeline canal-cortes end-to-end")
    ap.add_argument("url", nargs="?", help="URL do vídeo YouTube (ou omita com --upload-only)")
    ap.add_argument("--upload", action="store_true",
                    help="após gerar cortes, publica TUDO no YouTube (publishAt agendado)")
    ap.add_argument("--upload-only", action="store_true",
                    help="pula ingest/analyze/render, só roda upload da fila pendente")
    ap.add_argument("--no-render", action="store_true",
                    help="pula render (usa cortes já existentes — debug)")
    args = ap.parse_args()

    cfg = load_config()

    if args.upload_only:
        step("PUBLISH (fila pendente)", ["schedule.py", "--upload-all-now"])
        return

    if not args.url:
        ap.error("preciso de URL (ou use --upload-only)")
    source_id = video_id_from_url(args.url)
    print(f"\n🎬 Pipeline para source_id = {source_id}\n   URL: {args.url}\n")

    # 1. Ingest
    step("1/6 INGEST (download + transcrição)", ["ingest.py", args.url])

    # 2. Analyze
    step("2/6 ANALYZE (Claude → plan.json)", ["analyze.py", source_id])

    # 3. Sync inicial Obsidian
    step("3/6 SYNC inicial Obsidian", ["sync_obsidian.py", source_id])

    # 4. Render
    if not args.no_render:
        step("4/6 RENDER (ffmpeg + cover Gemini + end card)", ["render.py", source_id])

    # 5. Enqueue + agenda
    step("5/6 ENQUEUE (fila + slots publishAt)", ["schedule.py", "--enqueue", source_id])

    # 6. Upload (opcional)
    if args.upload:
        step("6/6 PUBLISH (videos.insert + publishAt → YouTube agenda)",
             ["schedule.py", "--upload-all-now"])
        step("7/7 SYNC final Obsidian", ["sync_obsidian.py", source_id])
        print(f"\n✅ Tudo agendado. Você pode DESLIGAR a máquina — YouTube publica sozinho.\n")
    else:
        print(f"\n✅ Cortes prontos na fila. Quando quiser publicar:\n"
              f"   python scripts/pipeline.py --upload-only\n"
              f"(Você pode desligar a máquina APÓS o upload-only completar.)\n")


if __name__ == "__main__":
    main()
