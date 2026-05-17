# Setup — Fase 0

Passo a passo para deixar o pipeline pronto pra rodar pela primeira vez.

## 1. Dependências de sistema (Windows)

```powershell
# ffmpeg
winget install Gyan.FFmpeg
# (ou choco install ffmpeg-full)

# Python 3.11+
winget install Python.Python.3.12

# Claude Code CLI já instalado (você está usando agora)
```

Confira:

```powershell
ffmpeg -version
python --version
claude --version
```

## 2. Ambiente Python

```powershell
cd C:\Users\jonat\Documents\Projetos-Git\canal-cortes
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> **Whisper na GPU (opcional, recomendado se você tem NVIDIA):**
> ```powershell
> pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
> ```
> E ajuste `whisper.device: cuda` no `config.yaml`.

## 3. Google Cloud — habilitar YouTube Data API v3

1. Acesse https://console.cloud.google.com/
2. Crie um projeto novo: **"Canal de Cortes"**.
3. Menu → **APIs & Services → Library** → busque **"YouTube Data API v3"** → **Enable**.
4. Menu → **APIs & Services → OAuth consent screen**:
   - User Type: **External**
   - App name: `Canal de Cortes Uploader`
   - User support email: seu email
   - Developer contact: seu email
   - Em **Test users**, adicione o email que vai postar no canal
5. Menu → **APIs & Services → Credentials → + CREATE CREDENTIALS → OAuth client ID**:
   - Application type: **Desktop app**
   - Name: `cli-uploader`
   - Baixe o JSON e salve como `client_secret.json` na **raiz do repo** (já está no `.gitignore`).

## 4. Primeira autenticação

```powershell
python scripts\auth_youtube.py
```

- Abre um browser → você loga com a conta dona do canal → autoriza.
- Salva `token.json` na raiz (também no `.gitignore`).
- Imprime o `youtube_channel_id` do canal — **cole em `config.yaml` → `canal.youtube_channel_id`**.

## 5. Preencher `config.yaml`

Edite pelo menos:
- `canal.nome`
- `canal.youtube_channel_id`
- `youtube.categoria_id` (ver lista: https://developers.google.com/youtube/v3/docs/videoCategories/list)

## 6. Teste end-to-end com 1 vídeo

```powershell
# 1. Colocar 1 link autorizado em inbox/links.txt
#    + criar inbox/<video_id>.json com {"autorizado": true, "canal_fonte": "...", "tema": "..."}
copy inbox\links.txt.example inbox\links.txt
# (edite e adicione 1 URL)

# 2. Ingest
python scripts\ingest.py

# 3. Analyze (chama Claude Code CLI — pode levar 30s-2min)
python scripts\analyze.py <source_id>

# 4. Revisar manualmente cuts/<source_id>/plan.json antes de renderizar

# 5. Render
python scripts\render.py <source_id>

# 6. Enfileirar
python scripts\schedule.py --enqueue <source_id>

# 7. Ver agenda proposta (sem publicar)
python scripts\schedule.py --dry-run

# 8. Quando estiver feliz, publicar
python scripts\schedule.py --publish
```

## 7. Quota da API (limites grátis)

- Default: **10.000 unidades/dia**.
- `videos.insert` = **1600 unidades por upload** → ~6 uploads/dia.
- Quota reseta meia-noite PT (~4h da manhã BRT).
- Pra aumentar (se necessário): pedir quota extra no console → leva ~2 semanas de revisão.

## 8. Próximos passos depois da Fase 0

- **Fase 1**: rodar 1 vídeo completo, ajustar prompts/parâmetros conforme qualidade dos cortes.
- **Fase 2**: melhorar shorts (reframe com mediapipe, legendas TikTok-style).
- **Fase 3**: cron diário + watcher do `inbox/` para loop autônomo.
