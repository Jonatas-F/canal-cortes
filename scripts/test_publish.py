"""Publica 1 corte específico como UNLISTED (teste end-to-end).

NÃO usar em produção — bypassa a fila de agenda. Serve só para validar
o pipeline de upload + cleanup + atualização Obsidian.

Uso:
    python scripts/test_publish.py            # pega o short mais leve
    python scripts/test_publish.py <cut_id>   # publica um cut_id específico
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from common import ROOT, get_queue_db, load_config
from schedule import (
    _cleanup_after_publish,
    _try_cleanup_raw,
    get_yt_client,
)


def pick_smallest_short(conn) -> tuple | None:
    rows = conn.execute(
        """SELECT id, cut_id, source_id, file_path, tipo, titulo, descricao, tags
           FROM posts
           WHERE tipo='short' AND status IN ('scheduled', 'pending')
                 AND file_path NOT LIKE '[deletado%'"""
    ).fetchall()
    if not rows:
        return None
    rows_with_size = []
    for r in rows:
        p = Path(r[3])
        if p.exists():
            rows_with_size.append((p.stat().st_size, r))
    if not rows_with_size:
        return None
    rows_with_size.sort()
    return rows_with_size[0][1]


def main() -> None:
    cfg = load_config()
    conn = get_queue_db()

    if len(sys.argv) > 1:
        target_cut_id = sys.argv[1]
        row = conn.execute(
            """SELECT id, cut_id, source_id, file_path, tipo, titulo, descricao, tags
               FROM posts WHERE cut_id=?""",
            (target_cut_id,),
        ).fetchone()
    else:
        row = pick_smallest_short(conn)

    if not row:
        print("[test] nenhum corte elegível na fila")
        sys.exit(1)

    pid, cut_id, source_id, file_path, tipo, titulo, descricao, tags_json = row
    tags = json.loads(tags_json) if tags_json else []
    file_size_mb = round(Path(file_path).stat().st_size / (1024 * 1024), 2)

    print(f"[test] alvo: {cut_id} ({tipo}, {file_size_mb}MB)")
    print(f"[test] título: {titulo}")
    print(f"[test] modo: UNLISTED (link-only)")
    print(f"[test] iniciando upload...")

    yt = get_yt_client()
    body = {
        "snippet": {
            "title": titulo[:100],
            "description": descricao or "",
            "tags": tags,
            "categoryId": cfg["youtube"]["categoria_id"],
            "defaultLanguage": "pt",
            "defaultAudioLanguage": "pt",
        },
        "status": {
            "privacyStatus": "unlisted",   # <-- override para teste
            "selfDeclaredMadeForKids": cfg["youtube"]["made_for_kids"],
            # SEM publishAt → publica imediatamente
        },
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    try:
        req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        resp = req.execute()
        yt_id = resp["id"]
        url = f"https://youtu.be/{yt_id}"
        print(f"[test] ✅ uploaded: {url}")

        conn.execute(
            "UPDATE posts SET status='published', youtube_video_id=? WHERE id=?",
            (yt_id, pid),
        )
        conn.commit()

        # Cleanup
        info = _cleanup_after_publish(file_path, cfg, source_id, ROOT / "cuts" / source_id)
        if info:
            conn.execute(
                "UPDATE posts SET file_path=? WHERE id=?",
                (f"[deletado-após-publicação] {file_path}", pid),
            )
            conn.commit()
        conn.close()

        _try_cleanup_raw(source_id, cfg)

        # Re-sync Obsidian
        import sync_obsidian
        sys.argv = ["sync_obsidian.py", source_id]
        sync_obsidian.main()

        # Atualiza agenda também
        import agenda
        agenda.main()

        print()
        print(f"🎬 Vídeo publicado: {url}")
        print(f"   Veja em: https://studio.youtube.com/video/{yt_id}/edit")
        print()
        print("⚠️ LEMBRETE: como é teste com conteúdo de terceiro (Market Makers),")
        print("   apague esse vídeo do YouTube Studio depois de validar.")

    except Exception as e:
        conn.execute("UPDATE posts SET status='failed', error=? WHERE id=?", (str(e), pid))
        conn.commit()
        conn.close()
        print(f"[test] ❌ ERRO: {e}")
        raise


if __name__ == "__main__":
    main()
