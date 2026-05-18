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


def _build_prompt(titulo: str, has_logo: bool, has_frame: bool) -> str:
    """Prompt viral estilo cortes de podcast político (template fornecido pelo user).

    Logo é OBRIGATÓRIO. Frame do vídeo dá contexto visual (rostos + cena).
    Título já vem contextualizado da transcrição (gerado pelo Claude).
    """
    return f"""Crie uma thumbnail de YouTube extremamente chamativa e profissional no estilo "podcast cortes viral", usando como referência visual o LOGO enviado e o FRAME do vídeo enviado.

═══ OBJETIVO ═══
Thumbnail de corte de podcast político/debate altamente viral. Estética agressiva, moderna, contraste forte, foco em CTR (alta taxa de clique).

═══ IDENTIDADE VISUAL ═══
- Manter TOTAL fidelidade ao logo enviado (NUNCA redesenhar)
- O logo deve aparecer integrado no topo ou canto
- Cores principais (do logo):
  * Roxo vibrante
  * Laranja/amarelo queimado
  * Preto profundo
  * Branco para contraste
- Estética: thumbnails virais de cortes de política/debate

═══ COMPOSIÇÃO ═══
- Recortar AUTOMATICAMENTE os participantes visíveis no FRAME enviado
- Aplicar glow/contorno neon nas pessoas (roxo de um lado, laranja do outro)
- Destacar expressões faciais fortes, emoções, tensão
- Fundo escuro com:
  * Textura grunge
  * Pinceladas agressivas
  * Arranhões/garras
  * Partículas
  * Contraste cinematográfico
- Profundidade e energia

═══ TIPOGRAFIA ═══
TÍTULO EXATO (não altere): "{titulo.upper()}"

- Texto curto, forte, polêmico, emocional, sensacionalista sem exagerar
- Destacar palavras-chave com amarelo/laranja, roxo ou branco
- Fonte: brush agressiva, bold extrema, impactante, legível em mobile
- Aplicar: sombra forte, stroke preto, glow leve, perspectiva leve

═══ REGRAS ═══
- Texto ocupa NO MÁXIMO 30% da thumbnail
- Rosto principal = maior elemento visual
- Sem poluição visual, premium e moderna
- Funciona em telas pequenas
- Impacto visual imediato
- Sensação de urgência e debate quente

═══ ESTILO FINAL ═══
- Thumbnail de corte político PREMIUM
- Visual agressivo, muito contraste, cinemático, viral
- Estilo "canal grande de cortes"
- YouTube CTR optimized

═══ FORMATO ═══
- 1280x720 (16:9 landscape, NUNCA quadrado ou vertical)
- Ultra detalhado, alta nitidez, qualidade profissional

═══ PROIBIDO (CRÍTICO) ═══
- NÃO incluir logos de outros canais (Os Sócios, Market Makers, Missão Avança, MBL, M3L, MTL, etc)
- NÃO inventar marcas, textos ou logos NÃO presentes no logo enviado
- NÃO adicionar labels [NOME], [PARTICIPANTE 1], placeholders
- NÃO redesenhar/estilizar o logo (use EXATO como na imagem 1)
- NÃO usar tagline diferente de "CORTES DO MISSÃO" se incluir tagline
- O LOGO DEVE APARECER 100% INTEIRO E VISÍVEL (não cortar nas bordas)
- Reservar espaço no topo ou canto pro logo INTEIRO caber

═══ TEXTO EM PORTUGUÊS (CRÍTICO) ═══
- O título tem que ser ESCRITO EXATAMENTE como fornecido acima
- NÃO traduza, NÃO altere palavras, NÃO mude ortografia
- Cuidado com acentos: ã, õ, ç, é, á, ó devem ser PRESERVADOS
- Atenção em palavras como: DESTRUIÇÃO (não DESTRUIÇÃN), AÇÃO, OPINIÃO
- Se a palavra termina com "ÇÃO", a letra final é O (não N)
- Verifique cada palavra do título caractere por caractere antes de renderizar
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

    # 1. Extrai 1 FRAME do meio do corte (visual de contexto: rostos + cena)
    import subprocess, tempfile
    snapshot_ts = cut_start + (cut_end - cut_start) * 0.5  # meio do corte
    tmpdir = Path(tempfile.mkdtemp(prefix="cover_frame_"))
    frame_path = tmpdir / "frame.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{snapshot_ts}", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", str(frame_path)],
        check=True, capture_output=True,
    )
    frame_bytes = frame_path.read_bytes() if frame_path.exists() else None
    try: frame_path.unlink()
    except Exception: pass
    try: tmpdir.rmdir()
    except Exception: pass
    if not frame_bytes:
        raise RuntimeError("Não consegui extrair frame do corte")
    print(f"[cover_gemini] frame extraído do timestamp {snapshot_ts:.1f}s ({len(frame_bytes)//1024} KB)")

    # 2. Anexa logo OBRIGATÓRIO (única referência além do frame)
    template_dir = ROOT / "assets" / "cover_template"
    logo_file = template_dir / "logo.png"
    if not logo_file.exists() and (template_dir / "logo_14garras.png").exists():
        logo_file = template_dir / "logo_14garras.png"
    has_logo = logo_file.exists()
    if not has_logo:
        raise RuntimeError(
            f"Logo OBRIGATÓRIO ausente. Salve em {logo_file}"
        )

    # 3. Monta prompt + contents (logo primeiro, frame depois)
    prompt_text = _build_prompt(titulo, has_logo=True, has_frame=True)
    client = _make_genai_client(cfg)

    contents = [
        prompt_text,
        types.Part.from_bytes(
            data=logo_file.read_bytes(),
            mime_type=f"image/{logo_file.suffix.lstrip('.').lower().replace('jpg','jpeg')}",
        ),
        types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg"),
    ]
    print(f"[cover_gemini] enviando: prompt + logo ({logo_file.name}) + 1 frame")

    model_id = cfg.get("render", {}).get("cover", {}).get("gemini_model", "gemini-2.5-flash-image")
    print(f"[cover_gemini] modelo: {model_id} ({len(prompt_text)} chars prompt)")

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
