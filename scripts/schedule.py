"""Popula fila a partir de cuts/<id>/publicacoes.json, calcula slots,
e publica no YouTube como `private` com `publishAt` (agendamento nativo).

Uso:
    python scripts/schedule.py --enqueue <source_id>  # adiciona à fila
    python scripts/schedule.py --dry-run              # mostra agenda proposta
    python scripts/schedule.py --publish              # publica o que vence hoje
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from common import (
    ROOT, get_queue_db, load_config, read_manifest,
    quota_can_upload, quota_record_upload, quota_get_used_today,
    QUOTA_PER_UPLOAD,
)

TOKEN_PATH = ROOT / "token.json"

DAY_MAP = {
    "segunda": 0, "terça": 1, "terca": 1, "quarta": 2, "quinta": 3,
    "sexta": 4, "sábado": 5, "sabado": 5, "domingo": 6,
}


def get_yt_client():
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def build_youtube_description(cut: dict, source_url: str = "") -> str:
    """Monta descrição final pro YouTube: descrição + créditos + hashtags."""
    parts = [cut.get("descricao", "").strip()]
    if source_url:
        parts.append(f"\nVídeo original: {source_url}")
    hashtags = cut.get("hashtags", [])
    if hashtags:
        parts.append("\n" + " ".join(f"#{h}" for h in hashtags))
    return "\n".join(p for p in parts if p)


def enqueue(source_id: str, cfg: dict) -> int:
    cuts_dir = ROOT / "cuts" / source_id
    pub_path = cuts_dir / "publicacoes.json"
    if not pub_path.exists():
        print(f"[schedule] publicacoes.json não encontrado: {pub_path}")
        return 0

    manifest = read_manifest(source_id)
    authorized = bool(manifest.get("autorizado", False))
    source_url = manifest.get("source_url") or manifest.get("url", "")

    pubs = json.loads(pub_path.read_text(encoding="utf-8"))
    score_minimo = cfg.get("cortes", {}).get("score_viral_minimo", 85)
    conn = get_queue_db()
    added = 0
    deleted_low_score = 0
    for p in pubs:
        cut_id = f"{source_id}__{p['file'].rsplit('.', 1)[0]}"
        descricao_final = build_youtube_description(p, source_url)
        all_tags = list(p.get("tags", [])) + list(p.get("hashtags", []))
        # Título: shorts ganham " #shorts" no final (padrão Opus Clip)
        titulo = p["titulo"]
        if p["tipo"] == "short" and "#shorts" not in titulo.lower():
            titulo = (titulo[:90] + " #shorts").strip()
        # Hard-delete cortes com score < threshold (não enfileira, não guarda no disco)
        score = p.get("score_viral", 0) or 0
        if score < score_minimo:
            file_to_delete = cuts_dir / p["file"]
            srt_to_delete = file_to_delete.with_suffix(".srt")
            ass_to_delete = file_to_delete.with_suffix(".ass")
            for fp in (file_to_delete, srt_to_delete, ass_to_delete):
                try:
                    if fp.exists():
                        fp.unlink()
                except Exception as e:
                    print(f"[schedule] aviso: não consegui apagar {fp.name} ({e})")
            print(f"[schedule] 🗑️ HARD-DELETE {cut_id} (score {score} < {score_minimo})")
            deleted_low_score += 1
            continue
        if not authorized:
            status = "blocked"
        else:
            status = "pending"
        try:
            conn.execute(
                """INSERT INTO posts
                (cut_id, source_id, file_path, tipo, titulo, descricao, tags,
                 source_url, source_authorized, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cut_id, source_id, str(cuts_dir / p["file"]), p["tipo"],
                    titulo, descricao_final,
                    json.dumps(all_tags, ensure_ascii=False),
                    source_url, int(authorized), status,
                ),
            )
            added += 1
        except Exception as e:
            print(f"[schedule] já existe (skip): {cut_id} - {e}")
    if deleted_low_score:
        print(f"[schedule] {deleted_low_score} corte(s) HARD-DELETADOS por score < {score_minimo}")
    conn.commit()
    conn.close()
    print(f"[schedule] +{added} item(ns) na fila (autorizado={authorized})")
    return added


def next_slots(cfg: dict, n_long: int, n_short: int, after: datetime) -> tuple[list[datetime], list[datetime]]:
    """Calcula slots futuros para N longs + N shorts a partir de `after`.

    Aceita `agenda.shorts.horas` como lista (3 picos/dia) ou `agenda.shorts.hora` (1/dia legado).
    Aceita `agenda.longos.horas` como lista ou `agenda.longos.hora` (1/dia legado).
    """
    tz = ZoneInfo(cfg["canal"]["timezone"])
    long_days = [DAY_MAP[d.lower()] for d in cfg["agenda"]["longos"]["dias"]]
    # Aceita horas como lista ou string única (back-compat)
    long_cfg = cfg["agenda"]["longos"]
    long_hours = [time.fromisoformat(h) for h in (long_cfg.get("horas") or [long_cfg.get("hora", "19:00")])]
    short_cfg = cfg["agenda"]["shorts"]
    short_hours = [time.fromisoformat(h) for h in (short_cfg.get("horas") or [short_cfg.get("hora", "12:00")])]

    longs: list[datetime] = []
    d = after.astimezone(tz).date()
    after_t = after.astimezone(tz)
    while len(longs) < n_long:
        if d.weekday() in long_days:
            for h in long_hours:
                slot = datetime.combine(d, h, tz)
                if slot > after_t and len(longs) < n_long:
                    longs.append(slot)
        d += timedelta(days=1)
        if (d - after.astimezone(tz).date()).days > 365:
            break

    shorts: list[datetime] = []
    d = after.astimezone(tz).date()
    while len(shorts) < n_short:
        for h in short_hours:
            slot = datetime.combine(d, h, tz)
            if slot > after_t and len(shorts) < n_short:
                shorts.append(slot)
        d += timedelta(days=1)
        if (d - after.astimezone(tz).date()).days > 365:
            break

    return longs, shorts


def assign_schedule(cfg: dict, dry_run: bool) -> None:
    conn = get_queue_db()
    pending_long = conn.execute(
        "SELECT id FROM posts WHERE status='pending' AND tipo='long' AND scheduled_at IS NULL ORDER BY id"
    ).fetchall()
    pending_short = conn.execute(
        "SELECT id FROM posts WHERE status='pending' AND tipo='short' AND scheduled_at IS NULL ORDER BY id"
    ).fetchall()

    last_long = conn.execute(
        "SELECT MAX(scheduled_at) FROM posts WHERE tipo='long' AND scheduled_at IS NOT NULL"
    ).fetchone()[0]
    last_short = conn.execute(
        "SELECT MAX(scheduled_at) FROM posts WHERE tipo='short' AND scheduled_at IS NOT NULL"
    ).fetchone()[0]

    tz = ZoneInfo(cfg["canal"]["timezone"])
    after_long = datetime.fromisoformat(last_long).astimezone(tz) if last_long else datetime.now(tz)
    after_short = datetime.fromisoformat(last_short).astimezone(tz) if last_short else datetime.now(tz)

    long_slots, _ = next_slots(cfg, len(pending_long), 0, after_long)
    _, short_slots = next_slots(cfg, 0, len(pending_short), after_short)

    print(f"[schedule] {len(pending_long)} long(s) + {len(pending_short)} short(s) para agendar")
    for (pid,), slot in zip(pending_long, long_slots):
        print(f"  long  id={pid}  ->  {slot.isoformat()}")
        if not dry_run:
            conn.execute("UPDATE posts SET scheduled_at=?, status='scheduled' WHERE id=?",
                         (slot.isoformat(), pid))
    for (pid,), slot in zip(pending_short, short_slots):
        print(f"  short id={pid}  ->  {slot.isoformat()}")
        if not dry_run:
            conn.execute("UPDATE posts SET scheduled_at=?, status='scheduled' WHERE id=?",
                         (slot.isoformat(), pid))
    conn.commit()
    conn.close()


def _extract_thumbnail(video_path: Path, out_path: Path) -> bool:
    """Extrai 1 frame do meio do vídeo como thumbnail JPG."""
    try:
        # Pega frame em 50% da duração (mais representativo que o início)
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-ss", "00:00:02",
             "-frames:v", "1", "-q:v", "3", str(out_path)],
            check=True, capture_output=True,
        )
        return out_path.exists()
    except Exception as e:
        print(f"[publish] aviso: não consegui extrair thumbnail ({e})")
        return False


def _cleanup_after_publish(file_path: str, cfg: dict, source_id: str, cuts_dir: Path) -> dict:
    """Apaga .mp4 + .srt do corte, opcionalmente extrai thumbnail antes.

    Retorna info do cleanup pra log/Obsidian: {thumbnail_path?, size_freed_mb}.
    """
    info: dict = {}
    if not cfg.get("cleanup", {}).get("apos_publicacao", False):
        return info

    p = Path(file_path)
    size_freed = 0

    # Thumbnail antes de apagar
    if cfg["cleanup"].get("manter_thumbnail", True) and p.exists():
        thumbs_dir = p.parent / "thumbnails"
        thumbs_dir.mkdir(exist_ok=True)
        thumb = thumbs_dir / (p.stem + ".jpg")
        if _extract_thumbnail(p, thumb):
            info["thumbnail_path"] = str(thumb)

    # Apaga mp4
    if p.exists():
        size_freed += p.stat().st_size
        p.unlink()
        info["mp4_deleted"] = True

    # Apaga srt correspondente (mesmo stem)
    srt = p.with_suffix(".srt")
    if srt.exists():
        size_freed += srt.stat().st_size
        srt.unlink()
        info["srt_deleted"] = True

    info["size_freed_mb"] = round(size_freed / (1024 * 1024), 2)
    print(f"[publish] cleanup: liberou {info['size_freed_mb']}MB ({p.name})")
    return info


def _try_cleanup_raw(source_id: str, cfg: dict) -> None:
    """Se TODOS os cortes do source_id foram publicados, apaga raw/<source_id>/source.mp4."""
    if not cfg.get("cleanup", {}).get("apagar_raw_quando_tudo_publicado", False):
        return
    conn = get_queue_db()
    pending = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE source_id=? AND status != 'published'",
        (source_id,),
    ).fetchone()[0]
    conn.close()
    if pending == 0:
        raw_source = ROOT / "raw" / source_id / "source.mp4"
        if raw_source.exists():
            freed_mb = round(raw_source.stat().st_size / (1024 * 1024), 2)
            raw_source.unlink()
            print(f"[publish] raw source apagado ({freed_mb}MB liberados) — todos os cortes de {source_id} publicados")


def upload_to_youtube(cfg: dict, mode: str = "due") -> None:
    """mode='due': sobe só o que vence hoje. mode='all': sobe TUDO scheduled (respeita quota)."""
    yt = get_yt_client()
    conn = get_queue_db()
    quota_limit = cfg.get("youtube_quota", {}).get("daily_limit", 10000)

    if mode == "all":
        # Sobe TUDO scheduled (qualquer data futura), até bater quota do dia
        rows = conn.execute(
            """SELECT id, cut_id, source_id, file_path, tipo, titulo, descricao, tags, scheduled_at
               FROM posts
               WHERE status='scheduled'
               ORDER BY scheduled_at ASC"""
        ).fetchall()
        print(f"[publish] modo ALL: {len(rows)} item(ns) scheduled candidatos")
    else:
        # Modo legado: só o que vence hoje
        today = date.today().isoformat()
        rows = conn.execute(
            """SELECT id, cut_id, source_id, file_path, tipo, titulo, descricao, tags, scheduled_at
               FROM posts
               WHERE status='scheduled' AND date(scheduled_at) <= ?""",
            (today,),
        ).fetchall()

    used, count_today = quota_get_used_today(conn)
    print(f"[publish] quota hoje: {used}/{quota_limit} unidades usadas ({count_today} uploads)")

    sources_touched = set()
    blocked_by_quota = 0
    for pid, cut_id, source_id, file_path, tipo, titulo, descricao, tags_json, scheduled_at in rows:
        # Checa quota ANTES de cada upload (videos.insert + opcional thumbnail.set)
        extra = 50 if tipo == "long" else 0  # thumbnail só pra long
        if not quota_can_upload(conn, daily_limit=quota_limit, extra_units=extra):
            blocked_by_quota += 1
            print(f"[publish] quota cheia, pulando {cut_id} (sobe amanhã)")
            continue
        # File ainda existe? (pode ter sido deletado em cleanup anterior)
        if not Path(file_path).exists():
            print(f"[publish] arquivo não existe (pulando): {file_path}")
            conn.execute("UPDATE posts SET status='failed', error=? WHERE id=?",
                         ("arquivo local ausente", pid))
            conn.commit()
            continue
        tags = json.loads(tags_json) if tags_json else []
        print(f"[publish] uploading {cut_id} ({tipo}) -> publishAt={scheduled_at}")
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
                "privacyStatus": cfg["youtube"]["privacidade_default"],
                "publishAt": scheduled_at,
                "selfDeclaredMadeForKids": cfg["youtube"]["made_for_kids"],
            },
        }
        media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
        try:
            req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
            resp = req.execute()
            yt_id = resp["id"]
            conn.execute(
                "UPDATE posts SET status='published', youtube_video_id=? WHERE id=?",
                (yt_id, pid),
            )
            conn.commit()
            print(f"[publish] ok {cut_id} -> https://youtu.be/{yt_id}")
            # Registra consumo de quota
            quota_record_upload(conn, units=QUOTA_PER_UPLOAD, with_thumbnail=(tipo == "long"))

            # Long: faz upload da capa custom se existir (1280x720 jpg)
            if tipo == "long":
                cuts_dir = ROOT / "cuts" / source_id
                file_stem = Path(file_path).stem
                cover_path = cuts_dir / "thumbnails" / f"{file_stem}_cover.jpg"
                if cover_path.exists():
                    try:
                        thumb_media = MediaFileUpload(str(cover_path), mimetype="image/jpeg")
                        yt.thumbnails().set(videoId=yt_id, media_body=thumb_media).execute()
                        try:
                            thumb_media._fd.close()
                        except Exception:
                            pass
                        del thumb_media
                        print(f"[publish]   capa enviada: {cover_path.name}")
                    except Exception as ce:
                        print(f"[publish]   aviso: upload de capa falhou ({ce})")

            # Libera file handle do upload antes do cleanup (evita WinError 32)
            try:
                media._fd.close()
            except Exception:
                pass
            del media, req, resp
            import gc
            gc.collect()

            # Cleanup pós-publicação (economia de disco)
            cleanup_info = _cleanup_after_publish(file_path, cfg, source_id, ROOT / "cuts" / source_id)
            if cleanup_info:
                conn.execute(
                    "UPDATE posts SET file_path=? WHERE id=?",
                    (f"[deletado-após-publicação] {file_path}", pid),
                )
                conn.commit()
            sources_touched.add(source_id)
        except Exception as e:
            conn.execute("UPDATE posts SET status='failed', error=? WHERE id=?", (str(e), pid))
            conn.commit()
            print(f"[publish] ERRO {cut_id}: {e}")

    if blocked_by_quota:
        used_final, _ = quota_get_used_today(conn)
        print(f"[publish] {blocked_by_quota} upload(s) bloqueado(s) por quota. "
              f"Usadas {used_final}/{quota_limit}. Rode amanhã pra subir o resto.")
    conn.close()

    # Tenta apagar raw/<source>/source.mp4 se todos os cortes do source foram publicados
    for sid in sources_touched:
        _try_cleanup_raw(sid, cfg)

    # Re-sync Obsidian pra refletir o status published + arquivos deletados
    for sid in sources_touched:
        try:
            import sync_obsidian
            sys.argv = ["sync_obsidian.py", sid]
            sync_obsidian.main()
        except Exception as e:
            print(f"[publish] aviso: sync_obsidian falhou para {sid} ({e})")


def main() -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--enqueue", metavar="SOURCE_ID")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="sobe só o que vence HOJE (modo legado)")
    ap.add_argument("--upload-all-now", action="store_true",
                    help="sobe TUDO scheduled (qualquer data futura), respeitando quota")
    args = ap.parse_args()

    if args.enqueue:
        enqueue(args.enqueue, cfg)
    assign_schedule(cfg, dry_run=args.dry_run and not (args.publish or args.upload_all_now))

    if args.upload_all_now:
        upload_to_youtube(cfg, mode="all")
    elif args.publish:
        upload_to_youtube(cfg, mode="due")

    # Sempre regenera Agenda.md (a menos que seja dry-run sem mudanças)
    if not args.dry_run or args.publish or args.upload_all_now or args.enqueue:
        try:
            import agenda
            agenda.main()
        except Exception as e:
            print(f"[schedule] aviso: agenda.py falhou ({e})")


if __name__ == "__main__":
    main()
