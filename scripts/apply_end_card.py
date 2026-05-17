"""Aplica end card aos cortes já renderizados de um source_id (in-place).

Usado uma vez quando o end card é adicionado depois que os cortes já foram
renderizados — evita re-rodar todo o pipeline.

Uso:
    python scripts/apply_end_card.py <source_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

from common import ROOT, load_config
from render import append_end_card


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: apply_end_card.py <source_id>")
        sys.exit(1)
    source_id = sys.argv[1]
    cfg = load_config()
    ec = cfg.get("render", {}).get("end_card", {})
    if not ec.get("enabled"):
        print("[end_card] desativado em config.yaml")
        sys.exit(0)

    img = ROOT / ec.get("path", "assets/end_card.png")
    if not img.exists():
        print(f"[end_card] não encontrado: {img}")
        sys.exit(1)

    duracao = ec.get("duracao_seg", 3)
    cuts_dir = ROOT / "cuts" / source_id
    aplicar_em = ec.get("aplicar_em", ["short", "long"])

    files = sorted(cuts_dir.glob("*.mp4"))
    # Pula thumbnails subfolder (não é mp4 mesmo, mas garante)
    files = [f for f in files if not f.name.endswith(".endcard.mp4") and not f.name.endswith(".main.mp4")]

    for f in files:
        tipo = "long" if f.name.startswith("long_") else "short" if f.name.startswith("short_") else None
        if tipo not in aplicar_em:
            print(f"[end_card] skip {f.name} (tipo={tipo} não em aplicar_em)")
            continue
        # Já tem end card? heurística simples: se duração > duração esperada + 2.5s, provavelmente já tem
        # Pra simplificar, sempre reaplicar — usuário pode rodar manualmente quando quiser
        print(f"[end_card] aplicando em {f.name}...")
        tmp = f.with_suffix(".main.mp4")
        f.rename(tmp)
        try:
            append_end_card(tmp, img, f, duracao)
            # Valida que o output é maior que o original (proxy pra ter funcionado)
            if not f.exists() or f.stat().st_size < tmp.stat().st_size * 0.9:
                raise RuntimeError(f"saída inválida ({f.stat().st_size if f.exists() else 0} bytes)")
            tmp.unlink(missing_ok=True)
            # Limpa endcard temp residual se ainda existir
            (tmp.with_suffix(".endcard.mp4")).unlink(missing_ok=True)
            print(f"[end_card]   ✅ {f.name}")
        except Exception as e:
            # Restaura: se output não vale, apaga e renomeia tmp de volta
            if f.exists():
                f.unlink()
            if tmp.exists():
                tmp.rename(f)
            (tmp.with_suffix(".endcard.mp4")).unlink(missing_ok=True)
            print(f"[end_card]   ❌ {f.name}: {e}")


if __name__ == "__main__":
    main()
