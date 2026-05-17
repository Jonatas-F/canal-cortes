"""Ingere vídeos de inbox/ — baixa (yt-dlp) e transcreve (faster-whisper).

Uso:
    python scripts/ingest.py           # processa tudo em inbox/
    python scripts/ingest.py <url>     # processa uma URL específica
    python scripts/ingest.py <file>    # processa um arquivo local específico
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from common import ROOT, load_config, read_manifest, slug_from_filename, video_id_from_url


def download_url(url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = out_dir / "source.mp4"
    if existing.exists():
        return existing
    out_file = out_dir / "source.%(ext)s"
    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]",
        "--merge-output-format", "mp4",
        "--write-info-json",
        "--write-thumbnail",
        "-o", str(out_file),
        url,
    ]
    subprocess.run(cmd, check=True)
    return next(out_dir.glob("source.mp4"))


def copy_local(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "source.mp4"
    if not dst.exists():
        import shutil
        shutil.copy(src, dst)
    return dst


def transcribe(audio_path: Path, out_path: Path, cfg: dict) -> None:
    from faster_whisper import WhisperModel

    model = WhisperModel(
        cfg["whisper"]["modelo"],
        device=cfg["whisper"]["device"],
        compute_type=cfg["whisper"].get("compute_type", "auto"),
    )
    segments, info = model.transcribe(
        str(audio_path),
        language=cfg["whisper"]["language"],
        vad_filter=True,
        word_timestamps=True,
    )
    out = {
        "language": info.language,
        "duration": info.duration,
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text.strip(),
                "words": [
                    {"start": w.start, "end": w.end, "text": w.word}
                    for w in (s.words or [])
                ],
            }
            for s in segments
        ],
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def process_one(source_id: str, source_kind: str, source_ref: str, cfg: dict) -> None:
    raw_dir = ROOT / "raw" / source_id
    print(f"[ingest] {source_id} ({source_kind})")
    if source_kind == "url":
        video_path = download_url(source_ref, raw_dir)
    else:
        video_path = copy_local(Path(source_ref), raw_dir)

    transcript_path = raw_dir / "transcript.json"
    if transcript_path.exists():
        print(f"[ingest] transcript já existe: {transcript_path}")
    else:
        print(f"[ingest] transcrevendo {video_path.name}…")
        transcribe(video_path, transcript_path, cfg)

    manifest = read_manifest(source_id)
    meta = {
        "source_id": source_id,
        "source_kind": source_kind,
        "source_ref": source_ref,
        **manifest,
    }
    (raw_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[ingest] ok -> {raw_dir}")


def iter_inbox() -> list[tuple[str, str, str]]:
    inbox = ROOT / "inbox"
    items: list[tuple[str, str, str]] = []
    links_file = inbox / "links.txt"
    if links_file.exists():
        for line in links_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            items.append((video_id_from_url(line), "url", line))
    for f in inbox.glob("*.mp4"):
        items.append((slug_from_filename(f), "file", str(f)))
    for f in inbox.glob("*.mov"):
        items.append((slug_from_filename(f), "file", str(f)))
    return items


def main() -> None:
    cfg = load_config()
    args = sys.argv[1:]
    if args:
        ref = args[0]
        if ref.startswith("http"):
            process_one(video_id_from_url(ref), "url", ref, cfg)
        else:
            p = Path(ref)
            process_one(slug_from_filename(p), "file", str(p), cfg)
        return
    items = iter_inbox()
    if not items:
        print("[ingest] inbox vazia. Adicione URLs em inbox/links.txt ou arquivos .mp4/.mov.")
        return
    for source_id, kind, ref in items:
        process_one(source_id, kind, ref, cfg)


if __name__ == "__main__":
    main()
