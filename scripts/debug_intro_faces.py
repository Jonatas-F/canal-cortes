"""Debug: extrai rostos do intro de cada long e salva pra inspeção visual.

Uso: python scripts/debug_intro_faces.py <source_id>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from common import ROOT
from cover_html import detect_hosts_in_intro


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: debug_intro_faces.py <source_id>")
        sys.exit(1)
    source_id = sys.argv[1]
    cuts_dir = ROOT / "cuts" / source_id
    raw = ROOT / "raw" / source_id / "source.mp4"
    plan = json.loads((cuts_dir / "plan.json").read_text(encoding="utf-8"))

    for i, cut in enumerate(plan["cortes"]):
        if cut["tipo"] != "long":
            continue
        titulo = cut["titulo"][:50]
        print(f"=== long #{i}: {titulo}... (start={cut['start']}s, dur={cut['end']-cut['start']:.0f}s)")
        # Tenta janelas crescentes pra achar onde aparecem os hosts
        for window in [60, 120, 180, 300]:
            faces = detect_hosts_in_intro(raw, cut["start"], cut["end"],
                                          intro_duration=window, max_prints=20)
            if faces:
                print(f"  Janela {window}s funcionou")
                break
        else:
            faces = []
        debug_dir = cuts_dir / "thumbnails" / f"debug_intro_long_{i:02d}"
        debug_dir.mkdir(exist_ok=True, parents=True)
        for j, png in enumerate(faces):
            (debug_dir / f"host_{j+1}.png").write_bytes(png)
        print(f"  -> {len(faces)} hosts salvos em {debug_dir.relative_to(ROOT).as_posix()}")
        print()


if __name__ == "__main__":
    main()
