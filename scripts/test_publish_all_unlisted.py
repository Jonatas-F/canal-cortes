"""Publica TODOS os cortes scheduled como UNLISTED imediatamente (sem publishAt).

Pra testes seguros — vídeos vão pro YouTube como link-only, não aparecem em
busca/feed. Você valida no Studio e apaga depois.

Uso:
    python scripts/test_publish_all_unlisted.py [source_id]

Se source_id omitido, publica todos os scheduled de qualquer source.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from common import (
    ROOT, get_queue_db, load_config,
    quota_can_upload, quota_record_upload, quota_get_used_today,
    QUOTA_PER_UPLOAD,
)
from schedule import get_yt_client, _cleanup_after_publish


def main() -> None:
    cfg = load_config()
    source_filter = sys.argv[1] if len(sys.argv) > 1 else None

    yt = get_yt_client()
    conn = get_queue_db()

    sql = """SELECT id, cut_id, source_id, file_path, tipo, titulo, descricao, tags
             FROM posts
             WHERE status='scheduled'"""
    params: tuple = ()
    if source_filter:
        sql += " AND source_id=?"
        params = (source_filter,)
    sql += " ORDER BY id ASC"
    rows = conn.execute(sql, params).fetchall()

    print(f"[test-all] {len(rows)} corte(s) pra publicar como UNLISTED")
    quota_limit = cfg.get("youtube_quota", {}).get("daily_limit", 10000)
    used, count_today = quota_get_used_today(conn)
    print(f"[test-all] quota hoje: {used}/{quota_limit} (margem pra {(quota_limit - used) // 1650} uploads)")

    published_urls = []
    for pid, cut_id, source_id, file_path, tipo, titulo, descricao, tags_json in rows:
        extra = 50 if tipo == "long" else 0
        if not quota_can_upload(conn, daily_limit=quota_limit, extra_units=extra):
            print(f"[test-all] quota cheia, parando. {cut_id} fica pendente")
            break
        if not Path(file_path).exists():
            print(f"[test-all] arquivo ausente, pulando: {file_path}")
            continue
        tags = json.loads(tags_json) if tags_json else []
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
                "privacyStatus": "unlisted",   # <-- override pra teste
                "selfDeclaredMadeForKids": cfg["youtube"]["made_for_kids"],
                # Sem publishAt — unlisted vai live na hora
            },
        }
        media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
        print(f"[test-all] uploading {cut_id} ({tipo}, {Path(file_path).stat().st_size // 1024}KB)...")
        try:
            resp = yt.videos().insert(part="snippet,status", body=body, media_body=media).execute()
            yt_id = resp["id"]
            url = f"https://youtu.be/{yt_id}"
            published_urls.append((cut_id, url, tipo))
            conn.execute(
                "UPDATE posts SET status='published', youtube_video_id=? WHERE id=?",
                (yt_id, pid),
            )
            conn.commit()
            quota_record_upload(conn, units=QUOTA_PER_UPLOAD, with_thumbnail=(tipo == "long"))
            print(f"[test-all]   ✅ {url}")

            # Libera handle Windows antes do cleanup
            try: media._fd.close()
            except Exception: pass
            del media, resp
            import gc; gc.collect()

            cleanup_info = _cleanup_after_publish(file_path, cfg, source_id, ROOT / "cuts" / source_id)
            if cleanup_info:
                conn.execute(
                    "UPDATE posts SET file_path=? WHERE id=?",
                    (f"[deletado-apos-publicacao] {file_path}", pid),
                )
                conn.commit()

            # Long: tenta upload de capa custom
            if tipo == "long":
                cover = ROOT / "cuts" / source_id / "thumbnails" / f"{Path(file_path).stem}_cover.jpg"
                if not cover.exists():
                    cover = ROOT / "cuts" / source_id / "thumbnails" / f"{Path(file_path).stem}_cover_gemini.jpg"
                if cover.exists():
                    try:
                        thumb_media = MediaFileUpload(str(cover), mimetype="image/jpeg")
                        yt.thumbnails().set(videoId=yt_id, media_body=thumb_media).execute()
                        print(f"[test-all]   capa: {cover.name}")
                    except Exception as e:
                        print(f"[test-all]   aviso capa: {e}")
        except Exception as e:
            conn.execute("UPDATE posts SET status='failed', error=? WHERE id=?", (str(e), pid))
            conn.commit()
            print(f"[test-all]   ❌ {e}")

    conn.close()

    if published_urls:
        print(f"\n🎬 {len(published_urls)} vídeo(s) publicados como UNLISTED:")
        for cid, url, tipo in published_urls:
            print(f"   {tipo}: {url}")
        print(f"\n⚠️ Vídeos são UNLISTED (só visíveis com link). Valide no Studio e apague depois:")
        print(f"   https://studio.youtube.com/channel/UCGXNSUQTScWqdN7Rfhkbg2A/videos")


if __name__ == "__main__":
    main()
