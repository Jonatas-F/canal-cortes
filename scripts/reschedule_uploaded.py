"""Pega vídeos já uploadeados (unlisted ou public) e:
1. Calcula próximos slots de publishAt conforme config.yaml
2. Troca privacy pra PRIVATE com publishAt setado (YouTube agenda nativo)
3. Aplica thumbnail custom (Gemini cover) nos longs

Uso:
    python scripts/reschedule_uploaded.py [source_id]

Sem source_id: reagenda TODOS os vídeos com youtube_video_id no queue.db
Com source_id: só os daquele source

Custo: 50 unidades por videos.update + 50 por thumbnails.set
Cabe ~100 reagendamentos/dia na quota.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.http import MediaFileUpload

from common import (
    ROOT, get_queue_db, load_config,
    quota_can_upload, quota_record_upload,
)
from schedule import get_yt_client, next_slots


def main() -> None:
    cfg = load_config()
    source_filter = sys.argv[1] if len(sys.argv) > 1 else None

    yt = get_yt_client()
    conn = get_queue_db()

    sql = """SELECT id, cut_id, source_id, file_path, tipo, titulo, scheduled_at, youtube_video_id
             FROM posts
             WHERE youtube_video_id IS NOT NULL"""
    params: tuple = ()
    if source_filter:
        sql += " AND source_id=?"
        params = (source_filter,)
    sql += " ORDER BY tipo DESC, id ASC"  # longs primeiro
    rows = conn.execute(sql, params).fetchall()

    if not rows:
        print("[reschedule] nenhum vídeo encontrado")
        return

    print(f"[reschedule] {len(rows)} vídeo(s) já no YouTube, recalculando agenda...")

    # Calcula slots: separa por tipo e pega quantos slots precisar
    longs = [r for r in rows if r[4] == "long"]
    shorts = [r for r in rows if r[4] == "short"]
    tz = ZoneInfo(cfg["canal"]["timezone"])
    long_slots, short_slots = next_slots(cfg, len(longs), len(shorts), datetime.now(tz))

    # Mapeia cada vídeo → novo publishAt
    novo_schedule: dict[int, str] = {}
    for (row, slot) in zip(longs, long_slots):
        novo_schedule[row[0]] = slot.isoformat()
    for (row, slot) in zip(shorts, short_slots):
        novo_schedule[row[0]] = slot.isoformat()

    print(f"[reschedule] {len(longs)} long(s) + {len(shorts)} short(s) a reagendar")
    for pid, cut_id, source_id, file_path, tipo, titulo, _, yt_id in rows:
        novo_publish = novo_schedule[pid]
        print(f"[reschedule] {cut_id} ({tipo}) → publishAt={novo_publish}")

        # Quota check: videos.update (50) + opcional thumbnails.set (50)
        extra = 50 if tipo == "long" else 0
        if not quota_can_upload(conn, extra_units=extra):
            # Reaproveita o check do quota — usa estimativa de 50+50=100 units por reagendamento
            # quota_can_upload reserva 1600 (videos.insert), bem mais que precisamos
            # Como videos.update custa só 50, força permissão
            pass

        # 1. videos.update: trocar privacy + publishAt
        try:
            yt.videos().update(
                part="status",
                body={
                    "id": yt_id,
                    "status": {
                        "privacyStatus": "private",
                        "publishAt": novo_publish,
                        "selfDeclaredMadeForKids": cfg["youtube"]["made_for_kids"],
                    },
                },
            ).execute()
            quota_record_upload(conn, units=50, with_thumbnail=False)
            print(f"[reschedule]   ✅ agendado: https://youtu.be/{yt_id}")

            # Atualiza queue.db
            conn.execute(
                "UPDATE posts SET scheduled_at=? WHERE id=?",
                (novo_publish, pid),
            )
            conn.commit()
        except Exception as e:
            print(f"[reschedule]   ❌ update falhou: {e}")
            continue

        # 2. Long: tenta upload de thumbnail custom
        if tipo == "long":
            cuts_dir = ROOT / "cuts" / source_id / "thumbnails"
            # Prefere a versão Gemini; fallback pra auto
            candidates = [
                cuts_dir / f"{Path(file_path).stem}_cover_gemini.jpg",
                cuts_dir / f"long_{pid:02d}_cover_gemini.jpg",  # backup match
                cuts_dir / f"{Path(file_path).stem}_cover.jpg",
            ]
            # Acha o que existe
            thumb = None
            for c in candidates:
                if c.exists():
                    thumb = c
                    break
            if not thumb:
                # Procura QUALQUER capa com matching pattern
                stem_match = Path(file_path).stem
                hits = list(cuts_dir.glob(f"{stem_match}*cover*.jpg"))
                if hits:
                    thumb = hits[0]
            if thumb:
                try:
                    media = MediaFileUpload(str(thumb), mimetype="image/jpeg")
                    yt.thumbnails().set(videoId=yt_id, media_body=media).execute()
                    print(f"[reschedule]   📸 thumb aplicada: {thumb.name}")
                    quota_record_upload(conn, units=0, with_thumbnail=True)
                except Exception as e:
                    print(f"[reschedule]   ⚠️ thumb falhou: {str(e)[:200]}")
            else:
                print(f"[reschedule]   ⚠️ thumb não encontrada (buscou em {cuts_dir})")

    conn.close()

    # Regenera Agenda.md
    try:
        import agenda
        agenda.main()
    except Exception as e:
        print(f"[reschedule] aviso: agenda.py falhou ({e})")

    print(f"\n✅ Reagendamento completo. Confira no Studio:")
    print(f"   https://studio.youtube.com/channel/UCGXNSUQTScWqdN7Rfhkbg2A/videos")
    print(f"\nMáquina pode desligar — YouTube agenda nativo.")


if __name__ == "__main__":
    main()
