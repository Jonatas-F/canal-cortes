"""Gera capas usando Gemini 2.5 Flash Image (Nano Banana).

Pipeline:
1. Extrai N rostos dos hosts do vídeo (OpenCV — reusa lógica do cover_html)
2. Monta prompt descritivo com identidade 14 Garras + título + destaque
3. Chama Gemini 2.5 Flash Image com prompt + imagens de referência
4. Salva resposta como JPG 1280x720

Pricing: ~$0.039/imagem (1024x1024). Free tier generoso na inicialização.
API key: env var GEMINI_API_KEY ou config.yaml → analyzer.gemini_api_key.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

from common import ROOT, load_config


def _get_api_key(cfg: dict) -> str:
    """Procura API key em env, .env file, ou config.yaml."""
    # Prioridade 1: env var
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    # Prioridade 2: .env na raiz do repo
    env_path = ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import dotenv_values
            values = dotenv_values(env_path)
            for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                if values.get(k):
                    return values[k]
        except ImportError:
            pass
    # Prioridade 3: config.yaml
    cover_cfg = cfg.get("render", {}).get("cover", {})
    if cover_cfg.get("gemini_api_key"):
        return cover_cfg["gemini_api_key"]
    raise RuntimeError(
        "Gemini API key não encontrada. Defina GEMINI_API_KEY no env, em .env, "
        "ou em config.yaml → render.cover.gemini_api_key. "
        "Crie sua key gratuita em https://aistudio.google.com/apikey"
    )


def _make_genai_client(cfg: dict):
    """Cria cliente Gemini, preferindo Vertex AI (quota maior) se configurado.

    Vertex AI: usa Service Account JSON, mesmo modelo, quota muito maior.
    Setup: vertex-sa.json na raiz do repo + Vertex AI API habilitada.

    Fallback: Gemini API direta com API key (quota mais restrita).
    """
    from google import genai

    cover_cfg = cfg.get("render", {}).get("cover", {})
    use_vertex = cover_cfg.get("use_vertex", True)
    sa_path = ROOT / cover_cfg.get("vertex_sa_path", "vertex-sa.json")
    project = cover_cfg.get("vertex_project", "garras-496602")
    location = cover_cfg.get("vertex_location", "us-central1")

    if use_vertex and sa_path.exists():
        # Vertex AI mode (Service Account auth)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)
        try:
            client = genai.Client(vertexai=True, project=project, location=location)
            print(f"[cover_gemini] usando Vertex AI (projeto {project}, região {location})")
            return client
        except Exception as e:
            print(f"[cover_gemini] Vertex falhou ({e}), caindo pra Gemini API direta")

    # Fallback: Gemini API direta
    api_key = _get_api_key(cfg)
    print(f"[cover_gemini] usando Gemini API direta (quota restrita em previews)")
    return genai.Client(api_key=api_key)


def _build_prompt(titulo: str, n_faces: int, has_style_ref: bool, has_logo: bool) -> str:
    """Prompt focado: deixa as referências visuais fazerem o trabalho pesado."""
    words = [w for w in titulo.split() if len(w) >= 5]
    highlight = max(words, key=len) if words else (titulo.split()[0] if titulo.split() else "")

    ref_instructions = []
    if has_style_ref:
        ref_instructions.append(
            "IMAGEM 1: capa de REFERÊNCIA visual do canal '14 GARRAS' — copie EXATAMENTE "
            "esta identidade: layout, paleta de cores (roxo + laranja + preto), brush strokes, "
            "posição do logo, estilo do título, labels laranja embaixo de cada pessoa."
        )
    if has_logo:
        ref_instructions.append(
            "IMAGEM 2: logo da onça 14 GARRAS — use EXATAMENTE este logo (não recrie), "
            "preserve cores, forma, e posicione grande no topo central."
        )
    n_face_imgs_start = (1 if has_style_ref else 0) + (1 if has_logo else 0) + 1
    ref_instructions.append(
        f"IMAGENS {n_face_imgs_start} a {n_face_imgs_start + n_faces - 1}: os {n_faces} PARTICIPANTES do podcast. "
        f"USE ESTES ROSTOS EXATOS, sem mudar identidade. Mantenha cabelo, barba, óculos, "
        f"feições reconhecíveis. Cada pessoa entra como CUTOUT (fundo removido), lado a lado."
    )

    refs_text = "\n".join(f"- {r}" for r in ref_instructions)

    return f"""Gere uma THUMBNAIL 16:9 LANDSCAPE (1920x1080) para o canal "14 GARRAS" de cortes de podcast.

REFERÊNCIAS FORNECIDAS:
{refs_text}

INSTRUÇÕES:
1. Copie 100% o ESTILO VISUAL da imagem 1 (referência).
2. Use o LOGO da imagem 2 sem alterar. A tagline EXATA embaixo do logo é "CORTES DO MISSÃO" (nunca "CORTES DO PODCAST" ou outro texto).
3. Coloque os {n_faces} participantes (imagens seguintes) como cutouts grandes lado a lado, ocupando a metade central da capa.
4. PRESERVE IDENTIDADE dos rostos: as pessoas devem ser RECONHECÍVEIS.
5. NÃO adicione labels com nomes embaixo das pessoas. NÃO escreva "PARTICIPANTE 1/2/3", "NOME", ou qualquer placeholder. Os cutouts ficam sem nenhum texto identificando-os.
6. No rodapé, banner com o título: "{titulo.upper()}"
7. Destaque a palavra "{highlight.upper()}" em cor contrastante (laranja sobre branco ou preto sobre laranja).
8. Formato OBRIGATÓRIO: landscape 16:9, NUNCA quadrado ou vertical.
9. NÃO inclua o logo do podcast original (Os Sócios, Market Makers, etc).
10. Texto do título em FONTE BOLD/IMPACT com outline preto grosso.
"""


def generate_cover(
    video: Path,
    cut_start: float,
    cut_end: float,
    titulo: str,
    out_path: Path,
    cfg: dict,
    n_faces: int = 0,  # 0 = autodetect número de participantes
) -> None:
    """Gera capa via Gemini Image (Pro ou Flash).

    Workflow:
    1. Detecta TODOS os participantes do podcast (autodetect)
    2. Anexa logo + style reference (se existirem em assets/cover_template/)
    3. Envia tudo pro Gemini com prompt minimalista
    """
    from google import genai
    from google.genai import types
    from PIL import Image

    # 1. Detecta participantes do INTRO do corte (primeiros 30s, max 20 prints)
    from cover_html import (
        detect_hosts_in_intro, detect_recurring_hosts,
        detect_all_participants, extract_speaker_faces,
    )
    cover_cfg = cfg.get("render", {}).get("cover", {})
    if n_faces > 0:
        face_png_list = extract_speaker_faces(video, cut_start, cut_end, n_faces=n_faces)
    else:
        max_h = cover_cfg.get("max_participantes", 4)
        intro_sec = cover_cfg.get("intro_duracao_seg", 60.0)
        max_prints = cover_cfg.get("intro_max_prints", 20)
        intro_source = cover_cfg.get("intro_source", "video")
        # Estratégia A (preferida): hosts do INTRO do source.mp4. Tenta janela inicial e
        # amplia 2x se não achar (vinheta longa = hosts aparecem mais tarde).
        face_png_list = []
        for window in (intro_sec, intro_sec * 2, intro_sec * 4, intro_sec * 8):
            face_png_list = detect_hosts_in_intro(
                video, cut_start, cut_end,
                intro_duration=window, max_prints=max_prints, max_hosts=max_h,
                source=intro_source,
            )
            if face_png_list:
                if window > intro_sec:
                    print(f"[cover_gemini] hosts achados ampliando janela pra {int(window)}s")
                break
        # Estratégia B (fallback): hosts recorrentes no vídeo inteiro
        if not face_png_list:
            face_png_list = detect_recurring_hosts(video, max_hosts=max_h)
        # Estratégia C: qualquer grid com N rostos
        if not face_png_list:
            face_png_list = detect_all_participants(video, max_faces=max_h, min_faces=2)
        # Estratégia D: rostos do corte
        if not face_png_list:
            face_png_list = extract_speaker_faces(video, cut_start, cut_end, n_faces=3)
    if not face_png_list:
        raise RuntimeError("Nenhum rosto detectado — não posso compor capa Gemini")
    print(f"[cover_gemini] {len(face_png_list)} host(s) selecionado(s) (melhor angle por host)")

    # 2. Anexa referências visuais (logo + style)
    template_dir = ROOT / "assets" / "cover_template"
    logo_file = template_dir / "logo.png"
    style_ref_file = template_dir / "style_reference.png"
    # Fallback pra logo antigo se 'logo.png' não existe
    if not logo_file.exists() and (template_dir / "logo_14garras.png").exists():
        logo_file = template_dir / "logo_14garras.png"
    has_style_ref = style_ref_file.exists()
    has_logo = logo_file.exists()

    # 3. Monta prompt + contents
    prompt_text = _build_prompt(titulo, len(face_png_list), has_style_ref, has_logo)
    client = _make_genai_client(cfg)

    contents = [prompt_text]
    if has_style_ref:
        contents.append(types.Part.from_bytes(
            data=style_ref_file.read_bytes(),
            mime_type=f"image/{style_ref_file.suffix.lstrip('.').lower().replace('jpg','jpeg')}",
        ))
        print(f"[cover_gemini] anexada style reference: {style_ref_file.name}")
    if has_logo:
        contents.append(types.Part.from_bytes(
            data=logo_file.read_bytes(),
            mime_type=f"image/{logo_file.suffix.lstrip('.').lower().replace('jpg','jpeg')}",
        ))
        print(f"[cover_gemini] anexado logo: {logo_file.name}")
    for png in face_png_list:
        contents.append(types.Part.from_bytes(data=png, mime_type="image/png"))

    print(f"[cover_gemini] enviando {len(face_png_list)} rostos + prompt ({len(prompt_text)} chars)...")
    model_id = cfg.get("render", {}).get("cover", {}).get("gemini_model", "gemini-2.5-flash-image")

    def _call_gemini(model: str):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    image_config=types.ImageConfig(aspect_ratio="16:9"),
                ),
            )
        except (AttributeError, TypeError) as e:
            if "image_config" in str(e) or "aspect_ratio" in str(e):
                return client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
                )
            raise

    # Retry com backoff exponencial em caso de rate limit (429)
    import re
    import time
    max_retries = 4
    response = None
    last_error = None
    for attempt in range(max_retries):
        try:
            response = _call_gemini(model_id)
            break
        except Exception as e:
            msg = str(e)
            last_error = e
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                # Extrai retryDelay sugerido pela API se possível
                m = re.search(r"retry in (\d+)", msg) or re.search(r"'retryDelay': '(\d+)", msg)
                wait_s = int(m.group(1)) if m else (30 * (attempt + 1))
                wait_s = min(wait_s + 5, 120)
                if attempt < max_retries - 1:
                    print(f"[cover_gemini] rate limited, retry em {wait_s}s (tentativa {attempt + 1}/{max_retries})...")
                    time.sleep(wait_s)
                    continue
            raise
    if response is None:
        raise last_error or RuntimeError("Gemini não respondeu após retries")

    # 4. Extrai a imagem retornada
    image_bytes = None
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            image_bytes = part.inline_data.data
            break
        if part.text:
            print(f"[cover_gemini] Gemini texto: {part.text[:200]}")

    if not image_bytes:
        raise RuntimeError("Gemini não retornou imagem (apenas texto). Verifique permissões/billing.")

    # 5. Salva raw pra debug + processa para 1280x720
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out_path.with_suffix(".raw.png")
    raw_path.write_bytes(image_bytes)
    img = Image.open(io.BytesIO(image_bytes))
    print(f"[cover_gemini] Gemini retornou {img.width}x{img.height} (raw em {raw_path.name})")

    img_ratio = img.width / img.height
    target_ratio = 1280 / 720
    if abs(img_ratio - target_ratio) > 0.05:
        # Em vez de cropar (e perder informação), PAD letterbox preservando tudo
        # Calcula escala que cabe completamente em 1280x720
        scale = min(1280 / img.width, 720 / img.height)
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        # Cria canvas preto 1280x720 e cola centralizado
        canvas = Image.new("RGB", (1280, 720), (10, 10, 10))
        canvas.paste(resized, ((1280 - new_w) // 2, (720 - new_h) // 2))
        img = canvas
    else:
        img = img.resize((1280, 720), Image.LANCZOS)
    img.convert("RGB").save(out_path, "JPEG", quality=92)


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: cover_gemini.py <source_id>")
        sys.exit(1)
    source_id = sys.argv[1]
    cfg = load_config()

    import json
    cuts_dir = ROOT / "cuts" / source_id
    raw_dir = ROOT / "raw" / source_id
    source = raw_dir / "source.mp4"
    plan = json.loads((cuts_dir / "plan.json").read_text(encoding="utf-8"))
    thumbs_dir = cuts_dir / "thumbnails"
    thumbs_dir.mkdir(exist_ok=True)

    longs_n = 0
    for cut in plan["cortes"]:
        if cut["tipo"] != "long":
            continue
        longs_n += 1
        out = thumbs_dir / f"long_{longs_n:02d}_cover_gemini.jpg"
        print(f"[cover_gemini] long_{longs_n:02d}: {cut['titulo'][:60]}...")
        try:
            generate_cover(source, cut["start"], cut["end"], cut["titulo"], out, cfg)
            print(f"[cover_gemini]   ✅ {out.name}")
        except Exception as e:
            print(f"[cover_gemini]   ❌ {e}")


if __name__ == "__main__":
    main()
