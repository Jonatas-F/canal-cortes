"""Gera relatório de gastos consolidado em Canal de Cortes/Gastos.md.

Lê SQLite cost_log e produz:
- Total geral acumulado
- Totais por período (hoje, semana, mês, ano)
- Breakdown por serviço (Claude, Gemini, etc)
- Breakdown por projeto
- Detalhamento dos últimos N gastos

Uso:
    python scripts/gastos_report.py
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from common import get_queue_db, load_config

VAULT_PATH = Path(os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    r"C:\Users\jonat\Documents\BRAIN\Jonatas_brain",
))

OUT_PATH = VAULT_PATH / "Canal de Cortes" / "Gastos.md"


def _fmt_brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_usd(v: float) -> str:
    return f"$ {v:.4f}"


SERVICE_LABELS = {
    "claude_analyze": "🧠 Claude (análise transcript)",
    "gemini_cover": "🎨 Gemini (capas long)",
    "vertex_cover": "🎨 Vertex AI (capas long)",
    "youtube_upload": "📹 YouTube API (uploads)",
    "whisper_local": "🎤 Whisper (transcrição local)",
}


def main() -> None:
    cfg = load_config()
    usd_brl = float(cfg.get("moeda", {}).get("usd_brl_rate", 5.30))
    conn = get_queue_db()

    today = date.today()
    iso_today = today.isoformat()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    month_start = today.replace(day=1).isoformat()
    year_start = today.replace(month=1, day=1).isoformat()

    # Totais por período
    def total_periodo(filter_sql: str, params: tuple = ()) -> tuple[float, float, int]:
        r = conn.execute(
            f"SELECT COALESCE(SUM(cost_usd),0), COALESCE(SUM(cost_brl),0), COUNT(*) "
            f"FROM cost_log WHERE {filter_sql}",
            params,
        ).fetchone()
        return r[0], r[1], r[2]

    total_geral = total_periodo("1=1")
    total_ano = total_periodo("date >= ?", (year_start,))
    total_mes = total_periodo("date >= ?", (month_start,))
    total_semana = total_periodo("date >= ?", (week_start,))
    total_hoje = total_periodo("date = ?", (iso_today,))

    # Por serviço (total geral)
    rows_servico = conn.execute(
        """SELECT service, COUNT(*), SUM(cost_usd), SUM(cost_brl)
           FROM cost_log GROUP BY service ORDER BY SUM(cost_usd) DESC"""
    ).fetchall()

    # Por projeto (top 10)
    rows_projeto = conn.execute(
        """SELECT source_id, COUNT(*), SUM(cost_usd), SUM(cost_brl)
           FROM cost_log WHERE source_id IS NOT NULL
           GROUP BY source_id ORDER BY SUM(cost_usd) DESC LIMIT 10"""
    ).fetchall()

    # Últimos 50 gastos (detalhamento)
    rows_detalhe = conn.execute(
        """SELECT date, service, source_id, cut_id, cost_usd, cost_brl, units_info, description
           FROM cost_log ORDER BY id DESC LIMIT 50"""
    ).fetchall()

    # Histórico por dia (últimos 30)
    rows_dia = conn.execute(
        """SELECT date, COUNT(*), SUM(cost_usd), SUM(cost_brl)
           FROM cost_log WHERE date >= ?
           GROUP BY date ORDER BY date DESC""",
        ((today - timedelta(days=30)).isoformat(),),
    ).fetchall()

    conn.close()

    # === Geração markdown ===
    lines: list[str] = []
    lines.append("---")
    lines.append("titulo: Relatório de Gastos — Canal de Cortes")
    lines.append(f"atualizado: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"taxa_usd_brl: {usd_brl}")
    lines.append("---\n")

    lines.append("# 💰 Gastos — Canal de Cortes\n")
    lines.append("**Navegação:** [[00 - Index|🏠 Visão geral]] · [[Agenda|📅 Agenda]] · [[Workflow|🔄 Workflow]]\n")
    lines.append(f"_Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M')} · Taxa USD→BRL: {usd_brl}_\n")

    # KPIs no topo
    lines.append("## 📊 Resumo\n")
    lines.append("| Período | Operações | Custo USD | Custo BRL |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| **Hoje** ({today.strftime('%d/%m')}) | {total_hoje[2]} | {_fmt_usd(total_hoje[0])} | **{_fmt_brl(total_hoje[1])}** |")
    lines.append(f"| **Esta semana** (desde {datetime.fromisoformat(week_start).strftime('%d/%m')}) | {total_semana[2]} | {_fmt_usd(total_semana[0])} | **{_fmt_brl(total_semana[1])}** |")
    lines.append(f"| **Este mês** ({today.strftime('%B/%Y')}) | {total_mes[2]} | {_fmt_usd(total_mes[0])} | **{_fmt_brl(total_mes[1])}** |")
    lines.append(f"| **Este ano** ({today.year}) | {total_ano[2]} | {_fmt_usd(total_ano[0])} | **{_fmt_brl(total_ano[1])}** |")
    lines.append(f"| **TOTAL GERAL** | **{total_geral[2]}** | **{_fmt_usd(total_geral[0])}** | **{_fmt_brl(total_geral[1])}** |")
    lines.append("")

    # Saldo do crédito Google (R$250 prepaid)
    credito_inicial_brl = 250.00
    gasto_google = sum(r[3] for r in rows_servico if r[0] in ("gemini_cover", "vertex_cover"))
    saldo_google = credito_inicial_brl - gasto_google
    lines.append("## 💳 Crédito Google Cloud (R$250 prepaid)\n")
    lines.append(f"- **Inicial:** {_fmt_brl(credito_inicial_brl)}")
    lines.append(f"- **Gasto até hoje:** {_fmt_brl(gasto_google)} ({(gasto_google/credito_inicial_brl*100):.1f}%)")
    lines.append(f"- **Saldo restante:** **{_fmt_brl(saldo_google)}**")
    if saldo_google > 0 and total_mes[1] > 0:
        # Estima quantos meses de runway no ritmo atual
        runway_meses = saldo_google / max(total_mes[1], 0.01)
        lines.append(f"- **Runway estimado:** {runway_meses:.1f} meses no ritmo atual")
    lines.append("")

    # Breakdown por serviço
    lines.append("## 🔧 Gastos por serviço\n")
    if rows_servico:
        lines.append("| Serviço | Operações | Custo USD* | Custo BRL* | Custo REAL |")
        lines.append("|---|---:|---:|---:|---:|")
        gasto_real_total = 0.0
        for service, count, usd, brl in rows_servico:
            label = SERVICE_LABELS.get(service, service)
            # Claude via assinatura Max = R$0 real (já pago no fixo mensal)
            if service == "claude_analyze":
                real_brl = "**Incluído na assinatura Max**"
            elif service in ("gemini_cover", "vertex_cover"):
                # Debita do crédito Google R$250 prepaid
                real_brl = _fmt_brl(brl)
                gasto_real_total += brl
            else:
                real_brl = _fmt_brl(brl)
                gasto_real_total += brl
            lines.append(f"| {label} | {count} | {_fmt_usd(usd)} | {_fmt_brl(brl)} | {real_brl} |")
        lines.append(f"\n_*Custo USD/BRL = valor 'equivalente API' (informativo). Custo REAL = o que sai do bolso de fato._\n")
        lines.append(f"**💸 Custo real acumulado total: {_fmt_brl(gasto_real_total)}**\n")
    else:
        lines.append("_Sem gastos registrados ainda._")
    lines.append("")

    # Por projeto
    lines.append("## 📺 Gastos por projeto (top 10)\n")
    if rows_projeto:
        lines.append("| Projeto (source_id) | Operações | Custo USD | Custo BRL |")
        lines.append("|---|---:|---:|---:|")
        for source_id, count, usd, brl in rows_projeto:
            lines.append(f"| `{source_id}` | {count} | {_fmt_usd(usd)} | {_fmt_brl(brl)} |")
    else:
        lines.append("_Sem gastos por projeto ainda._")
    lines.append("")

    # Histórico diário (últimos 30 dias)
    lines.append("## 📅 Histórico diário (últimos 30 dias)\n")
    if rows_dia:
        lines.append("| Data | Operações | Custo USD | Custo BRL |")
        lines.append("|---|---:|---:|---:|")
        for d, count, usd, brl in rows_dia:
            pretty = datetime.fromisoformat(d).strftime("%a %d/%m")
            lines.append(f"| {pretty} | {count} | {_fmt_usd(usd)} | {_fmt_brl(brl)} |")
    else:
        lines.append("_Sem histórico._")
    lines.append("")

    # Detalhamento (últimos 50)
    lines.append("## 🔍 Detalhamento (últimos 50 gastos)\n")
    if rows_detalhe:
        lines.append("| Data | Serviço | Projeto | Corte | USD | BRL | Info |")
        lines.append("|---|---|---|---|---:|---:|---|")
        for d, service, sid, cid, usd, brl, units, desc in rows_detalhe:
            label = SERVICE_LABELS.get(service, service).split(" ", 1)[1] if " " in SERVICE_LABELS.get(service, service) else service
            sid_s = sid[:12] if sid else "—"
            cut_s = cid.split("__")[-1] if cid else "—"
            info = (units or desc or "")[:40]
            lines.append(f"| {d} | {label} | `{sid_s}` | `{cut_s}` | {_fmt_usd(usd)} | {_fmt_brl(brl)} | {info} |")
    else:
        lines.append("_Sem gastos registrados._")
    lines.append("")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[gastos] {OUT_PATH.relative_to(VAULT_PATH).as_posix()} (total {total_geral[2]} ops, {_fmt_brl(total_geral[1])})")


if __name__ == "__main__":
    main()
