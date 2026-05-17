"""Renderiza cortes a partir de cuts/<id>/plan.json usando ffmpeg.

Uso:
    python scripts/render.py <source_id>
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from common import ROOT, load_config
from layout_analyzer import decide_layout


def srt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _wrap_two_lines(text: str, max_chars: int = 22) -> str:
    """Quebra texto em no máximo 2 linhas, balanceadas, com max_chars por linha.

    Para legenda burn-in vertical 9:16, ~22 chars/linha cabe confortável.
    Se o texto não couber em 2 linhas, trunca a 2 linhas + reticências.
    """
    words = text.split()
    if not words:
        return text
    # Tenta 1 linha
    if sum(len(w) for w in words) + len(words) - 1 <= max_chars:
        return " ".join(words)
    # Distribui em 2 linhas o mais balanceadas possível
    best_split = 1
    best_diff = float("inf")
    for split in range(1, len(words)):
        l1 = " ".join(words[:split])
        l2 = " ".join(words[split:])
        if len(l1) > max_chars or len(l2) > max_chars:
            continue
        diff = abs(len(l1) - len(l2))
        if diff < best_diff:
            best_diff = diff
            best_split = split
    if best_diff == float("inf"):
        # Não cabe em 2 linhas — pega as primeiras que couberem e adiciona ...
        l1_words: list[str] = []
        for w in words:
            candidate = " ".join(l1_words + [w])
            if len(candidate) > max_chars:
                break
            l1_words.append(w)
        rest = words[len(l1_words):]
        l2_words: list[str] = []
        for w in rest:
            candidate = " ".join(l2_words + [w])
            if len(candidate) > max_chars - 1:  # -1 para o ...
                break
            l2_words.append(w)
        if len(rest) > len(l2_words):
            return " ".join(l1_words) + "\n" + " ".join(l2_words) + "…"
        return " ".join(l1_words) + "\n" + " ".join(l2_words)
    return " ".join(words[:best_split]) + "\n" + " ".join(words[best_split:])


def write_srt(transcript_segments: list[dict], start: float, end: float, out_path: Path) -> None:
    lines = []
    idx = 1
    for seg in transcript_segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        s = max(seg["start"], start) - start
        e = min(seg["end"], end) - start
        wrapped = _wrap_two_lines(seg["text"], max_chars=22)
        lines.append(f"{idx}\n{srt_timestamp(s)} --> {srt_timestamp(e)}\n{wrapped}\n")
        idx += 1
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _ass_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:01d}:{m:02d}:{s:05.2f}"


def write_ass_karaoke(
    transcript_segments: list[dict],
    start: float,
    end: float,
    out_path: Path,
    max_chars_per_phrase: int = 42,
    max_phrase_duration: float = 3.5,
) -> None:
    """Gera .ass com legendas frase-a-frase + destaque karaoke word-by-word.

    Estratégia (estilo Opus Clip):
    1. Coleta todas palavras com timestamps relativos.
    2. Agrupa em FRASES (~42 chars / 3.5s máx). A frase fica visível enquanto
       o falante a percorre.
    3. Para cada palavra DA FRASE, gera 1 evento com a frase completa e a
       palavra ativa destacada. Os eventos cobrem 100% do tempo (sem gaps):
       end do evento N = start do evento N+1.
    4. Quando troca de frase, refresh instantâneo.

    Resultado: usuário lê a frase enquanto o highlight move, sem cortar.
    """
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Impact,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&HC0000000,1,0,0,0,100,100,0,0,3,4,2,2,80,80,260,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []

    # Coleta todas as palavras com timestamps relativos ao corte
    words: list[dict] = []
    for seg in transcript_segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        for w in seg.get("words", []):
            ws, we = w["start"], w["end"]
            if we <= start or ws >= end:
                continue
            words.append({
                "start": max(ws, start) - start,
                "end": min(we, end) - start,
                "text": w["text"].strip(),
            })

    if not words:
        out_path.write_text(header, encoding="utf-8")
        return

    # Agrupa em frases: respeita pausa longa (>700ms) OU max chars OU max duration
    phrases: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    for i, w in enumerate(words):
        gap_before = (w["start"] - words[i - 1]["end"]) if i > 0 and cur else 0
        cur_dur = (w["end"] - cur[0]["start"]) if cur else 0
        would_overflow = (
            cur and (
                cur_chars + len(w["text"]) + 1 > max_chars_per_phrase
                or cur_dur > max_phrase_duration
                or gap_before > 0.7
            )
        )
        if would_overflow:
            phrases.append(cur)
            cur = []
            cur_chars = 0
        cur.append(w)
        cur_chars += len(w["text"]) + 1
    if cur:
        phrases.append(cur)

    # Gera eventos: 1 por palavra DENTRO da frase, todos com mesmo texto base
    # mas com a palavra ativa destacada. Sem gaps entre eventos da MESMA frase.
    for p_idx, phrase in enumerate(phrases):
        phrase_end = phrase[-1]["end"]
        # Pra evitar buracos visuais entre frases, estende a última palavra
        # da frase até a primeira palavra da próxima (ou +0.3s no final)
        next_phrase_start = (
            phrases[p_idx + 1][0]["start"] if p_idx + 1 < len(phrases) else phrase_end + 0.3
        )

        for w_idx, w in enumerate(phrase):
            ev_start = w["start"]
            # Evento dessa palavra cobre até o início da próxima
            if w_idx + 1 < len(phrase):
                ev_end = phrase[w_idx + 1]["start"]
            else:
                ev_end = next_phrase_start

            # Texto: frase completa com palavra atual destacada
            text_parts = []
            for j, ww in enumerate(phrase):
                txt = ww["text"].replace("{", "(").replace("}", ")")
                if j == w_idx:
                    # Amarelo + scale 110%
                    text_parts.append(r"{\c&H00FFFF&\fscx110\fscy110}" + txt + r"{\r}")
                else:
                    text_parts.append(txt)
            text = " ".join(text_parts)

            events.append(
                f"Dialogue: 0,{_ass_timestamp(ev_start)},{_ass_timestamp(ev_end)},"
                f"Default,,0,0,0,,{text}"
            )

    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def render_long(source: Path, start: float, end: float, out: Path) -> None:
    # -ss ANTES do -i: input fica seekado, stream começa em 0. Re-encode garante exatidão.
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start}",
        "-i", str(source),
        "-t", f"{duration}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def _ffmpeg_path(p: str) -> str:
    """Converte path Windows para forma aceita por filtros ffmpeg (subtitles/drawtext)."""
    return p.replace("\\", "/").replace(":", "\\:")


def _drawtext_escape(s: str) -> str:
    """Escapa caracteres especiais no texto do drawtext."""
    return (
        s.replace("\\", "\\\\")
         .replace(":", "\\:")
         .replace("'", "’")  # apóstrofo curvo evita conflito com aspas do filtro
         .replace(",", "\\,")
         .replace("%", "\\%")
    )


def _probe_video(path: Path) -> dict:
    """Retorna {width, height, fps} via ffprobe."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    info = {}
    for line in r.stdout.strip().splitlines():
        k, _, v = line.partition("=")
        info[k] = v
    num, _, den = info.get("r_frame_rate", "30/1").partition("/")
    fps = int(round(float(num) / float(den or 1)))
    return {"width": int(info["width"]), "height": int(info["height"]), "fps": fps}


def append_end_card(main_path: Path, end_card_img: Path, out_path: Path, duration_sec: int) -> None:
    """Concatena `duration_sec` da imagem end_card ao final do vídeo `main_path`.

    Detecta resolução/fps do main_path e gera o end card com as MESMAS specs,
    permitindo concat sem reencode bruto.
    """
    info = _probe_video(main_path)
    w, h, fps = info["width"], info["height"], info["fps"]

    # Adapta a imagem ao aspect do vídeo. End card é vertical (~9:16).
    if h >= w:  # vertical (short)
        scale_filter = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={fps}"
        )
    else:  # horizontal (long): mostra a imagem centralizada com letterbox
        scale_filter = (
            f"scale=-1:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}"
        )

    # Sample rate do áudio do main pra casar com o silêncio do end_card
    ar_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels",
         "-of", "default=noprint_wrappers=1:nokey=1", str(main_path)],
        check=True, capture_output=True, text=True,
    )
    lines = ar_probe.stdout.strip().splitlines()
    sample_rate = int(lines[0]) if lines else 48000
    channels = int(lines[1]) if len(lines) > 1 else 2
    ch_layout = "stereo" if channels == 2 else "mono"

    end_card_mp4 = main_path.with_suffix(".endcard.mp4")
    cmd_ec = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", str(fps), "-t", str(duration_sec),
        "-i", str(end_card_img),
        "-f", "lavfi", "-t", str(duration_sec),
        "-i", f"anullsrc=channel_layout={ch_layout}:sample_rate={sample_rate}",
        "-vf", scale_filter,
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(sample_rate), "-ac", str(channels),
        "-shortest",
        str(end_card_mp4),
    ]
    subprocess.run(cmd_ec, check=True, capture_output=True)

    # Concat via filter — força SAR=1 e aresample para garantir match dos inputs
    cmd_concat = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(main_path),
        "-i", str(end_card_mp4),
        "-filter_complex",
        f"[0:v]setsar=1[v0];"
        f"[1:v]setsar=1[v1];"
        f"[0:a]aresample={sample_rate}[a0];"
        f"[1:a]aresample={sample_rate}[a1];"
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]",
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(sample_rate),
        str(out_path),
    ]
    subprocess.run(cmd_concat, check=True, capture_output=True)
    end_card_mp4.unlink(missing_ok=True)


def _maybe_append_end_card(out_path: Path, tipo: str, cfg: dict) -> None:
    """Se end_card estiver habilitado pra esse tipo, regrava out_path com a imagem concatenada."""
    ec = cfg.get("render", {}).get("end_card", {})
    if not ec.get("enabled"):
        return
    if tipo not in ec.get("aplicar_em", []):
        return
    img = ROOT / ec.get("path", "assets/end_card.png")
    if not img.exists():
        print(f"[render] aviso: end_card não encontrado em {img}")
        return
    tmp = out_path.with_suffix(".main.mp4")
    # Garante que nenhum handle Windows segurou o arquivo do render anterior
    import gc, time as _time
    gc.collect()
    for _ in range(5):
        try:
            out_path.rename(tmp)
            break
        except PermissionError:
            _time.sleep(0.3)
    else:
        print(f"[render] aviso: file lock persistente em {out_path.name}, pulando end_card")
        return
    try:
        append_end_card(tmp, img, out_path, ec.get("duracao_seg", 3))
        # Valida — output deve ter tamanho razoável (>= 90% do tmp)
        if not out_path.exists() or out_path.stat().st_size < tmp.stat().st_size * 0.9:
            raise RuntimeError(f"output inválido ({out_path.stat().st_size if out_path.exists() else 0} bytes)")
        tmp.unlink(missing_ok=True)
        (tmp.with_suffix(".endcard.mp4")).unlink(missing_ok=True)
    except Exception as e:
        # Restaura: apaga output inválido e renomeia tmp de volta
        if out_path.exists():
            out_path.unlink()
        if tmp.exists():
            tmp.rename(out_path)
        (tmp.with_suffix(".endcard.mp4")).unlink(missing_ok=True)
        print(f"[render] aviso: falhou append_end_card para {out_path.name} ({e})")


def _find_font() -> str:
    """Acha uma fonte TTF que o ffmpeg consegue carregar no Windows."""
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise FileNotFoundError("nenhuma fonte TTF encontrada para drawtext")


def render_short(
    source: Path, start: float, end: float, out: Path,
    srt_path: Path, titulo: str, cfg: dict, layout: str = "preencher",
) -> None:
    """Short 9:16 com layout PREENCHER (crop) ou AJUSTAR (blur background).

    layout="preencher": crop vertical 9:16 (zoom no falante)
    layout="ajustar":   vídeo 16:9 sobre fundo blur (estilo Opus Clip)
    Legendas: ASS karaoke word-by-word com destaque amarelo na palavra ativa.
    """
    w, h = cfg["render"]["short"]["resolucao"]
    fps = cfg["render"]["short"]["fps"]
    titulo_seg = cfg["render"]["short"]["titulo_overlay_seg"]

    font_path = _find_font()
    titulo_safe = _drawtext_escape(titulo)
    # srt_path agora é tratado como .ass karaoke (mesmo path, extensão trocada)
    ass_path = srt_path.with_suffix(".ass")
    srt_for_filter = _ffmpeg_path(str(ass_path if ass_path.exists() else srt_path))
    font_for_filter = _ffmpeg_path(font_path)

    if layout == "ajustar":
        # Estilo Opus Clip: fundo do mesmo vídeo com gaussian blur preenchendo 9:16,
        # com o vídeo original 16:9 sobreposto centralizado. Resultado: zero barra preta,
        # contexto preservado, todos os falantes visíveis, look profissional.
        base = (
            f"split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma=25,setsar=1[bgblur];"
            f"[fg]scale={w}:-2,setsar=1[fgscaled];"
            f"[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2,fps={fps}"
        )
        # Legenda na zona inferior (sobre o blur, fica destacada)
        margin_v = 350
        # Título no topo (acima do vídeo, sobre o blur)
        title_y = 280
    else:  # preencher
        base = f"crop=ih*9/16:ih,scale={w}:{h},fps={fps}"
        margin_v = 240
        title_y = 140

    # Se for .ass, usamos sub_filter direto (ele respeita os estilos do header).
    # Se for .srt, aplicamos force_style.
    is_ass = ass_path.exists()
    if is_ass:
        sub_filter = f"ass='{srt_for_filter}'"
    else:
        sub_filter = (
            f"subtitles='{srt_for_filter}'"
            f":force_style='Fontname=Arial,Fontsize=22,Bold=1,PrimaryColour=&H00FFFFFF&,"
            f"OutlineColour=&H00000000&,BackColour=&H80000000&,BorderStyle=3,Outline=3,Shadow=0,"
            f"Alignment=2,MarginV={margin_v},WrapStyle=0'"
        )
    vf = (
        f"{base},"
        f"{sub_filter},"
        f"drawtext=fontfile='{font_for_filter}':text='{titulo_safe}':fontcolor=white:fontsize=52:"
        f"box=1:boxcolor=black@0.75:boxborderw=24:x=(w-text_w)/2:y={title_y}:"
        f"line_spacing=12:enable='lt(t,{titulo_seg})'"
    )
    # -ss ANTES do -i: stream começa em 0 quando entra no filter, então ASS/SRT
    # com timestamps relativos a `start` ficam sincronizados perfeitamente.
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start}",
        "-i", str(source),
        "-t", f"{duration}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: render.py <source_id>")
        sys.exit(1)
    source_id = sys.argv[1]
    cfg = load_config()

    raw_dir = ROOT / "raw" / source_id
    cuts_dir = ROOT / "cuts" / source_id
    source = raw_dir / "source.mp4"
    plan_path = cuts_dir / "plan.json"
    transcript_path = raw_dir / "transcript.json"

    if not plan_path.exists():
        print(f"[render] plan.json não encontrado: {plan_path}")
        sys.exit(1)

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    longs_n = shorts_n = 0
    publicacoes = []
    for cut in plan["cortes"]:
        tipo = cut["tipo"]
        if tipo == "long":
            longs_n += 1
            out = cuts_dir / f"long_{longs_n:02d}.mp4"
            print(f"[render] long {longs_n} {cut['start']}-{cut['end']}  ->  {out.name}")
            t0 = time.monotonic()
            render_long(source, cut["start"], cut["end"], out)
            _maybe_append_end_card(out, "long", cfg)
            # Gera capa pro long (custom do manifest, ou auto a partir de frame)
            try:
                from cover_generator import create_cover, find_custom_cover
                thumbs_dir = cuts_dir / "thumbnails"
                thumbs_dir.mkdir(exist_ok=True)
                cover_out = thumbs_dir / f"long_{longs_n:02d}_cover.jpg"
                custom = find_custom_cover(source_id)
                create_cover(source, cut["start"], cut["end"], cut["titulo"],
                             cover_out, cfg, custom_cover=custom)
                origem = "custom" if custom else "auto"
                print(f"[render]   capa ({origem}): {cover_out.name}")
            except Exception as e:
                print(f"[render]   aviso: capa falhou ({e})")
            elapsed = time.monotonic() - t0
        else:
            shorts_n += 1
            out = cuts_dir / f"short_{shorts_n:02d}.mp4"
            srt = cuts_dir / f"short_{shorts_n:02d}.srt"
            ass = cuts_dir / f"short_{shorts_n:02d}.ass"
            write_srt(transcript["segments"], cut["start"], cut["end"], srt)
            write_ass_karaoke(transcript["segments"], cut["start"], cut["end"], ass)
            # Decide layout (preencher/ajustar) por detecção facial
            layout_info = decide_layout(source, cut["start"], cut["end"])
            layout = layout_info["layout"]
            print(f"[render] short {shorts_n} {cut['start']}-{cut['end']}  layout={layout} ({layout_info['motivo']})  ->  {out.name}")
            t0 = time.monotonic()
            render_short(source, cut["start"], cut["end"], out, srt, cut["titulo"], cfg, layout=layout)
            _maybe_append_end_card(out, "short", cfg)
            elapsed = time.monotonic() - t0
        info = {
            **cut,
            "file": out.name,
            "render_seconds": round(elapsed, 1),
            "file_size_mb": round(out.stat().st_size / (1024 * 1024), 2),
        }
        if tipo == "short":
            info["layout"] = layout
            info["layout_motivo"] = layout_info["motivo"]
            info["face_counts"] = layout_info["face_counts"]
        publicacoes.append(info)

    (cuts_dir / "publicacoes.json").write_text(
        json.dumps(publicacoes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[render] {longs_n} long + {shorts_n} short -> {cuts_dir}")


if __name__ == "__main__":
    main()
