"""Analisa transcript com Claude Code CLI e gera plan.json de cortes.

Uso:
    python scripts/analyze.py <source_id>
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from common import ROOT, load_config


def resolve_cli(name: str) -> str:
    """Resolve binário cross-platform — no Windows, claude vira claude.cmd."""
    resolved = shutil.which(name)
    if resolved:
        return resolved
    for ext in (".cmd", ".exe", ".ps1"):
        resolved = shutil.which(name + ext)
        if resolved:
            return resolved
    raise FileNotFoundError(f"binário '{name}' não encontrado no PATH")


def call_claude_cli(cli_binary: str, prompt: str, input_payload: str) -> tuple[str, dict]:
    """Chama `claude -p --output-format=json` e devolve (resposta, metadata_tokens)."""
    full_prompt = (
        f"{prompt}\n\n---\n"
        f"DADOS (JSON):\n{input_payload}\n\n"
        f"Retorne APENAS o JSON de saída, sem markdown, sem ```."
    )
    binary = resolve_cli(cli_binary)
    is_script = binary.lower().endswith((".cmd", ".ps1", ".bat"))
    if is_script:
        result = subprocess.run(
            f'"{binary}" -p --output-format json',
            input=full_prompt,
            capture_output=True, text=True, check=True,
            encoding="utf-8", shell=True,
        )
    else:
        result = subprocess.run(
            [binary, "-p", "--output-format", "json"],
            input=full_prompt,
            capture_output=True, text=True, check=True,
            encoding="utf-8",
        )
    envelope = json.loads(result.stdout)
    return envelope["result"].strip(), envelope


def extract_json(raw: str) -> dict:
    """Extrai JSON mesmo se o modelo vier com ```json envolto."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("` \n")
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Sem JSON válido na resposta:\n{raw[:500]}")
    return json.loads(raw[start : end + 1])


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: analyze.py <source_id>")
        sys.exit(1)
    source_id = sys.argv[1]
    cfg = load_config()

    raw_dir = ROOT / "raw" / source_id
    transcript_path = raw_dir / "transcript.json"
    meta_path = raw_dir / "meta.json"
    if not transcript_path.exists():
        print(f"[analyze] transcript não encontrado: {transcript_path}")
        sys.exit(1)

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    prompt = (ROOT / cfg["analyzer"]["prompt_file"]).read_text(encoding="utf-8")
    payload = json.dumps(
        {
            "metadata": {
                "duracao_total": transcript.get("duration"),
                "canal_fonte": meta.get("canal_fonte"),
                "tema": meta.get("tema"),
                "titulo_original": meta.get("titulo_original"),
            },
            "transcript": [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in transcript["segments"]
            ],
            "regras": {
                "cortes": cfg["cortes"],
            },
        },
        ensure_ascii=False,
    )

    print(f"[analyze] chamando {cfg['analyzer']['backend']}…")
    backend = cfg["analyzer"]["backend"]
    if backend == "claude_code_cli":
        raw, envelope = call_claude_cli(cfg["analyzer"]["cli_binary"], prompt, payload)
    else:
        raise NotImplementedError(f"backend {backend} não implementado")

    plan = extract_json(raw)

    score_min = cfg["cortes"]["score_viral_minimo"]
    plan["cortes"] = [c for c in plan.get("cortes", []) if c.get("score_viral", 0) >= score_min]

    # Tokens proporcionais por corte (rateio igualitário do custo da chamada Claude).
    n_cortes = max(1, len(plan["cortes"]))
    usage = envelope.get("usage", {})
    plan["analyze_meta"] = {
        "total_cost_usd": envelope.get("total_cost_usd"),
        "duration_ms": envelope.get("duration_ms"),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
        "per_cut_cost_usd": (envelope.get("total_cost_usd", 0) or 0) / n_cortes,
        "per_cut_input_tokens": usage.get("input_tokens", 0) // n_cortes,
        "per_cut_output_tokens": usage.get("output_tokens", 0) // n_cortes,
    }

    out_dir = ROOT / "cuts" / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[analyze] {len(plan['cortes'])} corte(s) >= {score_min} -> {out_dir / 'plan.json'}")
    # Hard-delete arquivos órfãos de runs anteriores que não estão no plan novo
    keep_files = set()
    for c in plan["cortes"]:
        # render.py nomeia por contador por tipo (long_01, short_01...). Sem render ainda,
        # não sabemos os nomes finais. Limpeza segura: só apaga se plan.json for novo
        # e nenhum corte do plan atual matchar (rare edge case).
        pass
    # Mais seguro: limpa apenas se publicacoes.json existir e divergir
    pub_path = out_dir / "publicacoes.json"
    if pub_path.exists():
        pub = json.loads(pub_path.read_text(encoding="utf-8"))
        plan_keys = {(round(c["start"], 2), round(c["end"], 2)) for c in plan["cortes"]}
        for p in pub:
            key = (round(p["start"], 2), round(p["end"], 2))
            if key not in plan_keys:
                # Esse corte estava no plan anterior mas saiu — apagar arquivos físicos
                fp = out_dir / p["file"]
                srt = fp.with_suffix(".srt")
                ass = fp.with_suffix(".ass")
                for f in (fp, srt, ass):
                    if f.exists():
                        f.unlink()
                        print(f"[analyze] 🗑️ removido (não está no plan novo): {f.name}")


if __name__ == "__main__":
    main()
