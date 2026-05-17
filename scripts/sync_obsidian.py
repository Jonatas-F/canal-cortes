"""Cria/atualiza uma nota Obsidian por corte em `Canal de Cortes/Cortes/<cut_id>.md`.

Usa a Local REST API do plugin Obsidian (mesma que o Claude usa via MCP).
Configurada via env vars OBSIDIAN_API_URL e OBSIDIAN_API_TOKEN — se ausentes,
escreve direto no filesystem do vault (caminho em OBSIDIAN_VAULT_PATH).

Uso:
    python scripts/sync_obsidian.py <source_id>
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from common import ROOT, get_queue_db, load_config

VAULT_PATH = Path(os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    r"C:\Users\jonat\Documents\BRAIN\Jonatas_brain",
))


def cut_id_for(source_id: str, file_name: str) -> str:
    """ID interno (usado pelo SQLite). Mantém formato source__cut_name."""
    return f"{source_id}__{file_name.rsplit('.', 1)[0]}"


def source_folder(source_id: str, source_meta: dict) -> Path:
    """Pasta dedicada por vídeo-fonte. Nome legível se houver canal_fonte."""
    canal = source_meta.get("canal_fonte", "").strip()
    if canal:
        safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in canal)
        folder_name = f"{source_id} - {safe}"
    else:
        folder_name = source_id
    return VAULT_PATH / "Canal de Cortes" / "Cortes" / folder_name


def note_path(source_id: str, file_name: str, source_meta: dict) -> Path:
    """Nota fica em Cortes/<source_folder>/<cut_name>.md."""
    cut_name = file_name.rsplit(".", 1)[0]
    return source_folder(source_id, source_meta) / f"{cut_name}.md"


def build_note(cut: dict, source_id: str, source_meta: dict, analyze_meta: dict, cfg: dict) -> str:
    cut_id = cut_id_for(source_id, cut["file"])
    n_cortes_meta = analyze_meta or {}
    per_cost = n_cortes_meta.get("per_cut_cost_usd", 0) or 0
    per_in = n_cortes_meta.get("per_cut_input_tokens", 0) or 0
    per_out = n_cortes_meta.get("per_cut_output_tokens", 0) or 0
    cache_read = n_cortes_meta.get("cache_read_tokens", 0) or 0
    cache_create = n_cortes_meta.get("cache_creation_tokens", 0) or 0
    usd_brl = float(cfg.get("moeda", {}).get("usd_brl_rate", 5.30))
    per_cost_brl = per_cost * usd_brl

    tags_yaml = "\n".join(f"  - {t}" for t in cut.get("tags", []))
    hashtags = cut.get("hashtags", [])
    hashtags_yaml = "\n".join(f"  - {h}" for h in hashtags)
    hashtags_str = " ".join(f"#{h}" for h in hashtags)

    # Scoring Opus Clip rubrica (0-100)
    s_hook = cut.get("score_hook", "—")
    s_flow = cut.get("score_flow", "—")
    s_value = cut.get("score_value", "—")
    s_trend = cut.get("score_trend", "—")
    hook_analysis = cut.get("hook_analysis", "")
    flow_analysis = cut.get("flow_analysis", "")
    value_analysis = cut.get("value_analysis", "")
    trend_analysis = cut.get("trend_analysis", "")
    score_viral = cut.get("score_viral", 0)
    categoria = cut.get("categoria", "—")
    # Acima do threshold 85?
    publicavel = "✅ sim" if isinstance(score_viral, (int, float)) and score_viral >= 85 else "❌ não (< 85)"

    # Layout (apenas para shorts)
    layout = cut.get("layout", "—")
    layout_motivo = cut.get("layout_motivo", "")
    face_counts = cut.get("face_counts", [])

    yt_id = cut.get("youtube_video_id")
    yt_str = (
        f"https://youtu.be/{yt_id}"
        if yt_id and str(yt_id) != "None" and yt_id != "null"
        else "_não publicado_"
    )

    fm = f"""---
source_id: {source_id}
cut_id: {cut_id}
tipo: {cut['tipo']}
categoria: {categoria}
score_viral: {score_viral}
score_hook: {s_hook}
score_flow: {s_flow}
score_value: {s_value}
score_trend: {s_trend}
publicavel: {str(isinstance(score_viral, (int, float)) and score_viral >= 85).lower()}
duracao_seg: {round(cut['end'] - cut['start'], 2)}
layout: {layout}
status: {cut.get('status', 'rendered')}
render_seconds: {cut.get('render_seconds', 'null')}
file_size_mb: {cut.get('file_size_mb', 'null')}
tokens_analyze_input: {per_in}
tokens_analyze_output: {per_out}
cost_analyze_usd: {round(per_cost, 6)}
cost_analyze_brl: {round(per_cost_brl, 4)}
youtube_video_id: {yt_id if yt_id else 'null'}
scheduled_at: {cut.get('scheduled_at', 'null')}
canal_fonte: "{source_meta.get('canal_fonte', '')}"
autorizado: {str(source_meta.get('autorizado', False)).lower()}
tags:
{tags_yaml}
hashtags:
{hashtags_yaml}
---

# {cut['titulo']}

**Tipo:** {cut['tipo']} ({round(cut['end'] - cut['start'], 1)}s) · **Categoria:** {categoria}

## Score de viralidade — rubrica Opus Clip

| Dimensão | Nota (0-100) | Peso |
|---|---|---|
| 🪝 Hook | **{s_hook}** | 35% |
| 🌊 Fluxo | **{s_flow}** | 20% |
| 💎 Valor | **{s_value}** | 20% |
| 🔥 Trend | **{s_trend}** | 25% |
| **Score viral final** | **{score_viral}** | — |

**Publicável (≥ 85):** {publicavel}

### 🪝 Hook
{hook_analysis}

### 🌊 Fluxo
{flow_analysis}

### 💎 Valor
{value_analysis}

### 🔥 Trend
{trend_analysis}

## Hook (primeira frase)
> {cut['gancho']}

## Descrição YouTube
{cut.get('descricao', '')}

{hashtags_str}

## Motivo (por que esse corte funciona)
{cut.get('motivo', '')}

## Origem
- Vídeo-fonte: `{source_id}`
- Canal: {source_meta.get('canal_fonte', '?')}
- URL: {source_meta.get('source_url', '?')}
- Trecho original: `{cut['start']}s → {cut['end']}s`

## Layout (shorts)
- **Decisão:** {layout}
- **Motivo:** {layout_motivo}
- **Rostos detectados por frame:** {face_counts}

## Consumo
- **Tokens analyze** (rateio): {per_in} in + {per_out} out
- **Custo analyze**: **R$ {round(per_cost_brl, 4)}** (US$ {round(per_cost, 5)} · taxa {usd_brl})
- **Cache Claude (compartilhado)**: read={cache_read}, creation={cache_create}
- **Render**: {cut.get('render_seconds', '?')}s · {cut.get('file_size_mb', '?')}MB
- **Quota YouTube**: {cut.get('quota_units', 0)} unidades (1600 por upload)

## Arquivo
{f"⚠️ **arquivo local deletado após publicação** (thumbnail em `cuts/{source_id}/thumbnails/{cut['file'].rsplit('.', 1)[0]}.jpg`)" if cut.get("arquivo_deletado") else f"`cuts/{source_id}/{cut['file']}`"}

## YouTube
{yt_str}

---
_Última atualização: {datetime.now().isoformat(timespec='seconds')}_
"""
    return fm


def write_note(source_id: str, file_name: str, source_meta: dict, content: str) -> None:
    path = note_path(source_id, file_name, source_meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    rel = path.relative_to(VAULT_PATH)
    print(f"[obsidian] nota: {rel.as_posix()}")


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: sync_obsidian.py <source_id>")
        sys.exit(1)
    source_id = sys.argv[1]
    cfg = load_config()

    cuts_dir = ROOT / "cuts" / source_id
    plan_path = cuts_dir / "plan.json"
    pub_path = cuts_dir / "publicacoes.json"
    meta_path = ROOT / "raw" / source_id / "meta.json"

    if not plan_path.exists():
        print(f"[obsidian] plan.json ausente: {plan_path}")
        sys.exit(1)

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    analyze_meta = plan.get("analyze_meta", {})
    source_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    publicacoes = (
        json.loads(pub_path.read_text(encoding="utf-8")) if pub_path.exists() else []
    )

    # Indexa cortes renderizados por (tipo, start, end) — sincroniza com plan
    pub_index = {(p["tipo"], round(p["start"], 2), round(p["end"], 2)): p for p in publicacoes}

    # Mescla scheduled_at + youtube_video_id + status do SQLite (queue.db) por cut_id
    queue_index: dict[str, dict] = {}
    try:
        conn = get_queue_db()
        rows = conn.execute(
            """SELECT cut_id, scheduled_at, status, youtube_video_id, file_path
               FROM posts WHERE source_id=?""",
            (source_id,),
        ).fetchall()
        for cut_id, scheduled_at, status, yt_id, file_path in rows:
            queue_index[cut_id] = {
                "scheduled_at": scheduled_at,
                "status": status,
                "youtube_video_id": yt_id,
                "quota_units": 1600 if yt_id else 0,
                "arquivo_deletado": "deletado" in (file_path or "").lower(),
            }
        conn.close()
    except Exception as e:
        print(f"[obsidian] aviso: não consegui ler queue.db ({e})")

    longs_n = shorts_n = 0
    for cut in plan["cortes"]:
        key = (cut["tipo"], round(cut["start"], 2), round(cut["end"], 2))
        merged = {**cut}
        if key in pub_index:
            merged.update(pub_index[key])
        else:
            # Ainda não renderizado — usa contador por tipo (mesma convenção do render.py)
            if cut["tipo"] == "long":
                longs_n += 1
                merged["file"] = f"long_{longs_n:02d}.mp4"
            else:
                shorts_n += 1
                merged["file"] = f"short_{shorts_n:02d}.mp4"
        cut_id = cut_id_for(source_id, merged["file"])
        if cut_id in queue_index:
            merged.update(queue_index[cut_id])
        content = build_note(merged, source_id, source_meta, analyze_meta, cfg)
        write_note(source_id, merged["file"], source_meta, content)

    print(f"[obsidian] {len(plan['cortes'])} nota(s) sincronizada(s)")


if __name__ == "__main__":
    main()
