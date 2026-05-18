"""Importa custos históricos dos plan.json (Claude) + estima Gemini covers já feitos.

Roda 1x pra popular cost_log com gastos anteriores antes da implementação.
"""
from __future__ import annotations

import json
from pathlib import Path

from common import ROOT, get_queue_db, cost_log_record, load_config


def main() -> None:
    cfg = load_config()
    usd_brl = float(cfg.get("moeda", {}).get("usd_brl_rate", 5.30))

    # Limpa registros antigos pra evitar duplicação
    conn = get_queue_db()
    conn.execute("DELETE FROM cost_log WHERE description LIKE '%[backfill]%'")
    conn.commit()
    conn.close()

    cuts_root = ROOT / "cuts"
    if not cuts_root.exists():
        print("[backfill] nenhuma pasta cuts/")
        return

    n_claude = n_gemini = 0
    for source_dir in cuts_root.iterdir():
        if not source_dir.is_dir():
            continue
        source_id = source_dir.name
        plan_file = source_dir / "plan.json"

        # Custo Claude analyze
        if plan_file.exists():
            try:
                plan = json.loads(plan_file.read_text(encoding="utf-8"))
                meta = plan.get("analyze_meta", {})
                cost = meta.get("total_cost_usd")
                if cost:
                    usage = {
                        "input_tokens": meta.get("input_tokens", 0),
                        "output_tokens": meta.get("output_tokens", 0),
                        "cache_read_input_tokens": meta.get("cache_read_tokens", 0),
                    }
                    cost_log_record(
                        service="claude_analyze",
                        cost_usd=cost,
                        source_id=source_id,
                        units_info=f"in={usage['input_tokens']} out={usage['output_tokens']} cache_read={usage['cache_read_input_tokens']}",
                        description=f"[backfill] {len(plan.get('cortes', []))} cortes",
                        usd_brl_rate=usd_brl,
                    )
                    n_claude += 1
                    print(f"[backfill] claude_analyze: {source_id} = ${cost:.4f}")
            except Exception as e:
                print(f"[backfill] erro lendo {plan_file}: {e}")

        # Custo Gemini cover (estima por arquivo de cover encontrado)
        thumbs_dir = source_dir / "thumbnails"
        if thumbs_dir.exists():
            for cover in thumbs_dir.glob("long_*_cover_gemini.jpg"):
                # Estima $0.04 por imagem gemini-2.5-flash-image (modelo usado nos testes)
                cut_name = cover.stem.replace("_cover_gemini", "")
                cid = f"{source_id}__{cut_name}"
                cost_log_record(
                    service="gemini_cover",
                    cost_usd=0.04,
                    source_id=source_id,
                    cut_id=cid,
                    units_info="model=gemini-2.5-flash-image (estimativa)",
                    description=f"[backfill] capa {cover.name}",
                    usd_brl_rate=usd_brl,
                )
                n_gemini += 1
                print(f"[backfill] gemini_cover: {cover.name}")

    print(f"\n✅ Backfill completo: {n_claude} analyze + {n_gemini} covers")


if __name__ == "__main__":
    main()
