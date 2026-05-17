"""Recupera o estado pós-publicação quando o cleanup falha (ex: file lock no Windows).

Lê o output do test_publish para extrair o YouTube ID real, e atualiza o
SQLite + chama sync_obsidian + agenda. Garante que o ID vem do log de uma
chamada real ao videos.insert, não de input arbitrário.

Uso:
    python scripts/recover_publish.py <output_log_path> <cut_id>
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from common import ROOT


def main() -> None:
    if len(sys.argv) < 3:
        print("uso: recover_publish.py <output_log_path> <cut_id>")
        sys.exit(1)
    log_path = Path(sys.argv[1])
    cut_id = sys.argv[2]

    if not log_path.exists():
        print(f"[recover] log não encontrado: {log_path}")
        sys.exit(1)

    content = log_path.read_text(encoding="utf-8", errors="replace")
    # Procura padrão: "✅ uploaded: https://youtu.be/<ID>"
    m = re.search(r"uploaded:\s*https://youtu\.be/([A-Za-z0-9_-]{11})", content)
    if not m:
        print(f"[recover] nenhum upload bem-sucedido encontrado no log")
        sys.exit(1)
    yt_id = m.group(1)
    print(f"[recover] YouTube ID extraído do log: {yt_id}")
    print(f"[recover] cut_id alvo: {cut_id}")

    conn = sqlite3.connect(ROOT / "queue.db")
    # Verifica que o cut existe e está como scheduled/pending (não atropela algo já publicado)
    row = conn.execute(
        "SELECT cut_id, status, file_path FROM posts WHERE cut_id=?",
        (cut_id,),
    ).fetchone()
    if not row:
        print(f"[recover] cut_id não encontrado em queue.db")
        sys.exit(1)
    if row[1] == "published":
        print(f"[recover] já está como published — nada a fazer")
        sys.exit(0)

    original_path = row[2]
    new_path = f"[deletado-apos-publicacao] {original_path}"
    conn.execute(
        "UPDATE posts SET status='published', youtube_video_id=?, file_path=? WHERE cut_id=?",
        (yt_id, new_path, cut_id),
    )
    conn.commit()
    updated = conn.execute(
        "SELECT cut_id, status, youtube_video_id FROM posts WHERE cut_id=?",
        (cut_id,),
    ).fetchone()
    conn.close()
    print(f"[recover] DB atualizado: {updated}")

    # Source_id para sync
    source_id = cut_id.split("__")[0]

    import sync_obsidian
    sys.argv = ["sync_obsidian.py", source_id]
    sync_obsidian.main()

    import agenda
    agenda.main()

    print(f"[recover] recuperação completa. Vídeo: https://youtu.be/{yt_id}")


if __name__ == "__main__":
    main()
