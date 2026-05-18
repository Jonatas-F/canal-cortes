"""Gera nota Canal de Cortes/Agenda.md com a fila de publicações cronológica.

Lê queue.db e renderiza uma view unificada: agenda futura, histórico, bloqueados.

Uso:
    python scripts/agenda.py
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from common import ROOT, get_queue_db

VAULT_PATH = Path(os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    r"C:\Users\jonat\Documents\BRAIN\Jonatas_brain",
))

AGENDA_PATH = VAULT_PATH / "Canal de Cortes" / "Agenda.md"
CORTES_INDEX_PATH = VAULT_PATH / "Canal de Cortes" / "Cortes" / "_Index.md"


STATUS_BADGE = {
    "scheduled": "⏰ agendado",
    "published": "✅ publicado",
    "pending":   "🕓 pendente",
    "blocked":   "⏸️ bloqueado",
    "failed":    "❌ falhou",
}


def project_link(source_id: str) -> str:
    """Wikilink para a página de projeto. Usa o nome do canal (não _Project)."""
    base = VAULT_PATH / "Canal de Cortes" / "Cortes"
    if base.exists():
        for sub in base.iterdir():
            if sub.is_dir() and sub.name.startswith(source_id):
                # Procura o project page (não é cut normal nem _Project legacy)
                cuts_names = {"long_01", "long_02", "long_03", "short_01", "short_02",
                              "short_03", "short_04", "short_05", "_Project", "_Index"}
                project_files = [
                    p for p in sub.glob("*.md")
                    if p.stem not in cuts_names and not p.stem.startswith(("long_", "short_"))
                ]
                if project_files:
                    name = project_files[0].stem
                    return f"[[Cortes/{sub.name}/{name}|{name}]]"
                # Fallback legacy
                return f"[[Cortes/{sub.name}/_Project|{sub.name}]]"
    return f"`{source_id}`"


def cut_note_link(source_id: str, cut_id: str) -> str:
    """Wikilink para o corte individual (mantém pra acesso direto na agenda)."""
    base = VAULT_PATH / "Canal de Cortes" / "Cortes"
    if base.exists():
        for sub in base.iterdir():
            if sub.is_dir() and sub.name.startswith(source_id):
                cut_name = cut_id.split("__", 1)[1]
                target = sub / f"{cut_name}.md"
                if target.exists():
                    return f"[[Cortes/{sub.name}/{cut_name}|{cut_name}]]"
    return f"`{cut_id}`"


def _safe_filename(text: str) -> str:
    """Sanitiza string pra usar como nome de arquivo (cross-platform)."""
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in text).strip()


def _read_source_meta(source_id: str) -> dict:
    """Lê raw/<source_id>/meta.json — tem canal_fonte, tema, etc."""
    meta_path = ROOT / "raw" / source_id / "meta.json"
    if meta_path.exists():
        import json
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def build_project_index(folder: Path, source_id: str, counts_for: dict) -> Path:
    """Gera Cortes/<folder>/<NomeDoCanal>.md — page do projeto.

    O arquivo é nomeado com o canal_fonte do source (não '_Project') pra
    aparecer com nome legível no graph view do Obsidian.
    """
    source_meta = _read_source_meta(source_id)
    canal_fonte = source_meta.get("canal_fonte", "").strip()
    display = canal_fonte if canal_fonte else folder.name

    # Filename = canal_fonte sanitizado + .md
    project_filename = _safe_filename(display) + ".md"
    project_path = folder / project_filename

    # Apaga _Project.md legado se existir e for diferente
    legacy = folder / "_Project.md"
    if legacy.exists() and legacy.name != project_filename:
        legacy.unlink()

    # Cortes = todos os .md exceto o próprio project page
    cuts = sorted(p for p in folder.glob("*.md") if p.name != project_filename)

    lines: list[str] = []
    lines.append("---")
    lines.append(f"titulo: \"{display}\"")
    lines.append(f"source_id: {source_id}")
    lines.append(f"canal_fonte: \"{canal_fonte}\"")
    lines.append("aliases:")
    lines.append(f"  - \"{display}\"")
    lines.append(f"  - \"{source_id}\"")
    lines.append(f"atualizado: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("---\n")
    lines.append(f"# 📺 {display}\n")
    lines.append("**Navegação:** [[00 - Index|🏠 Visão geral]] · [[Agenda|📅 Agenda]] · [[_Index|📁 Todos os projetos]]\n")

    published = counts_for.get("published", 0)
    scheduled = counts_for.get("scheduled", 0)
    total = sum(counts_for.values()) or len(cuts)
    lines.append(f"**{total} corte(s)** — ✅ {published} publicado(s) · ⏰ {scheduled} agendado(s)\n")
    if source_meta.get("source_url"):
        lines.append(f"**Vídeo-fonte:** [{source_meta.get('titulo_original', source_meta.get('source_url'))}]({source_meta['source_url']})\n")
    if source_meta.get("tema"):
        lines.append(f"**Tema:** {source_meta['tema']}\n")

    lines.append("## Cortes\n")
    if not cuts:
        lines.append("_Sem cortes ainda._\n")
    else:
        for cut in cuts:
            lines.append(f"- [[{cut.stem}]]")
    lines.append("")

    project_path.write_text("\n".join(lines), encoding="utf-8")
    return project_path


def build_cortes_index() -> None:
    """Gera Cortes/_Index.md listando projetos (não cortes individuais).

    Também gera 1 _Project.md por subpasta com a lista de cortes daquele projeto.
    Resultado: Index/Agenda → Projeto → Corte (hierarquia limpa no graph).
    """
    base = VAULT_PATH / "Canal de Cortes" / "Cortes"
    if not base.exists():
        return

    # Conta cortes por source via SQLite (opcional)
    counts: dict[str, dict] = {}
    try:
        conn = get_queue_db()
        rows = conn.execute(
            "SELECT source_id, status, COUNT(*) FROM posts GROUP BY source_id, status"
        ).fetchall()
        for sid, st, n in rows:
            counts.setdefault(sid, {})[st] = n
        conn.close()
    except Exception:
        pass

    lines: list[str] = []
    lines.append("---")
    lines.append("titulo: Projetos — Cortes")
    lines.append(f"atualizado: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("---\n")
    lines.append("# 📁 Projetos — Cortes\n")
    lines.append("**Navegação:** [[00 - Index|🏠 Visão geral]] · [[Agenda|📅 Agenda]]\n")
    lines.append("Cada projeto é um vídeo-fonte. Clica para ver os cortes dele.\n")

    subfolders = sorted(p for p in base.iterdir() if p.is_dir())
    if not subfolders:
        lines.append("_Nenhum vídeo processado ainda._\n")
    else:
        lines.append("| Projeto | Cortes | Publicados | Agendados |")
        lines.append("|---|---|---|---|")
        for folder in subfolders:
            source_id = folder.name.split(" - ")[0]
            counts_for = counts.get(source_id, {})
            project_path = build_project_index(folder, source_id, counts_for)
            project_name = project_path.stem  # nome legível do canal
            published = counts_for.get("published", 0)
            scheduled = counts_for.get("scheduled", 0)
            total = sum(counts_for.values()) or len(list(folder.glob("*.md")))
            # Link aponta pro nome do canal (não _Project), aparece bonito no graph
            link = f"[[{folder.name}/{project_name}|{project_name}]]"
            lines.append(f"| {link} | {total} | ✅ {published} | ⏰ {scheduled} |")
        lines.append("")

    CORTES_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORTES_INDEX_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[agenda] {CORTES_INDEX_PATH.relative_to(VAULT_PATH).as_posix()} ({len(subfolders)} projeto[s] + _Project.md)")


def main() -> None:
    AGENDA_PATH.parent.mkdir(parents=True, exist_ok=True)
    build_cortes_index()
    conn = get_queue_db()
    rows = conn.execute(
        """SELECT cut_id, source_id, tipo, titulo, scheduled_at, status,
                  youtube_video_id, source_authorized, created_at
           FROM posts ORDER BY scheduled_at ASC NULLS LAST, created_at ASC"""
    ).fetchall()
    conn.close()

    today = date.today().isoformat()
    future: dict[str, list] = defaultdict(list)
    past: list = []
    blocked: list = []
    failed: list = []

    for row in rows:
        cut_id, source_id, tipo, titulo, sched, status, yt_id, auth, created = row
        if status == "blocked":
            blocked.append(row)
            continue
        if status == "failed":
            failed.append(row)
            continue
        if sched:
            d = sched.split("T")[0]
            if d >= today and status in ("scheduled", "pending"):
                future[d].append(row)
            else:
                past.append(row)
        else:
            future["—"].append(row)

    lines: list[str] = []
    lines.append("---")
    lines.append("titulo: Agenda de publicações — Canal de Cortes")
    lines.append(f"atualizado: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("---\n")
    lines.append("# 📅 Agenda — Canal de Cortes\n")
    lines.append("> View unificada da fila de publicações. Regenerada a cada `schedule.py`.\n")
    lines.append("**Navegação:** [[00 - Index|🏠 Visão geral]] · [[Cortes/_Index|📁 Todos os cortes]]\n")

    # KPIs no topo
    total = len(rows)
    n_sched = sum(len(v) for v in future.values())
    n_pub = sum(1 for r in past if r[5] == "published")
    n_blk = len(blocked)
    n_fail = len(failed)
    lines.append(f"**Total na fila:** {total}  ·  ⏰ {n_sched} agendado(s)  ·  ✅ {n_pub} publicado(s)  ·  ⏸️ {n_blk} bloqueado(s)  ·  ❌ {n_fail} falha(s)\n")

    # Próximas publicações
    lines.append("## ⏰ Próximas publicações\n")
    if not future or all(d == "—" or not v for d, v in future.items()):
        lines.append("_Nada agendado._\n")
    else:
        for d in sorted(future.keys()):
            if d == "—":
                continue
            try:
                pretty = datetime.fromisoformat(d).strftime("%a %d/%m")
            except ValueError:
                pretty = d
            lines.append(f"### {pretty}\n")
            lines.append("| Hora | Tipo | Título | Status | Projeto |")
            lines.append("|---|---|---|---|---|")
            for row in sorted(future[d], key=lambda r: r[4] or ""):
                cut_id, source_id, tipo, titulo, sched, status, yt_id, auth, _ = row
                hora = sched.split("T")[1][:5] if sched else "—"
                badge = STATUS_BADGE.get(status, status)
                proj = project_link(source_id)
                titulo_short = titulo[:60] + ("…" if len(titulo) > 60 else "")
                lines.append(f"| {hora} | {tipo} | {titulo_short} | {badge} | {proj} |")
            lines.append("")

    # Histórico
    lines.append("## 📜 Histórico (publicados / passados)\n")
    if not past:
        lines.append("_Sem histórico ainda._\n")
    else:
        lines.append("| Data | Tipo | Título | Status | YouTube | Projeto |")
        lines.append("|---|---|---|---|---|---|")
        for row in sorted(past, key=lambda r: r[4] or "", reverse=True):
            cut_id, source_id, tipo, titulo, sched, status, yt_id, auth, _ = row
            d = sched.split("T")[0] if sched else "—"
            badge = STATUS_BADGE.get(status, status)
            yt = f"[link](https://youtu.be/{yt_id})" if yt_id else "—"
            proj = project_link(source_id)
            titulo_short = titulo[:60] + ("…" if len(titulo) > 60 else "")
            lines.append(f"| {d} | {tipo} | {titulo_short} | {badge} | {yt} | {proj} |")
        lines.append("")

    # Bloqueados
    if blocked:
        lines.append("## ⏸️ Bloqueados (score < mínimo ou sem autorização)\n")
        lines.append("| Tipo | Título | Motivo provável | Projeto |")
        lines.append("|---|---|---|---|")
        for row in blocked:
            cut_id, source_id, tipo, titulo, sched, status, yt_id, auth, _ = row
            motivo = "sem autorização" if not auth else "score < mínimo"
            proj = project_link(source_id)
            titulo_short = titulo[:60] + ("…" if len(titulo) > 60 else "")
            lines.append(f"| {tipo} | {titulo_short} | {motivo} | {proj} |")
        lines.append("")

    # Falhas
    if failed:
        lines.append("## ❌ Falhas de publicação\n")
        for row in failed:
            cut_id, source_id, tipo, titulo, sched, status, yt_id, auth, _ = row
            proj = project_link(source_id)
            lines.append(f"- {tipo} — {titulo} — {proj}")
        lines.append("")

    AGENDA_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[agenda] {AGENDA_PATH.relative_to(VAULT_PATH).as_posix()} ({total} item[s])")


if __name__ == "__main__":
    main()
