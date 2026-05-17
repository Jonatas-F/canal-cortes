# Canal de Cortes

Pipeline para virar vídeos longos (próprios ou de terceiros autorizados) em **cortes longos (3–10min)** + **YouTube Shorts (≤60s)** publicados em agenda controlada.

## Stack

- `yt-dlp` — download
- `faster-whisper` — transcrição local (PT)
- **Claude Code CLI** (`claude -p`) — análise dos cortes (zero custo extra de API)
- `ffmpeg` — render
- SQLite — fila
- YouTube Data API v3 — publicação com `publishAt` nativo

## Fluxo

```
inbox/  →  ingest.py  →  raw/<id>/transcript.json
                                    ↓
                              analyze.py  →  cuts/<id>/plan.json
                                                ↓
                                          render.py  →  cuts/<id>/{long,short}_N.mp4
                                                            ↓
                                                      schedule.py  →  YouTube (agendado)
```

## Comandos

```bash
# 1. Jogar links em inbox/links.txt OU arquivos .mp4 em inbox/
# 2. Pipeline manual:
python scripts/ingest.py
python scripts/analyze.py <id>
python scripts/render.py <id>
python scripts/schedule.py --dry-run
python scripts/schedule.py --publish
```

## Política de agenda

- **Longos**: ter/qui 19h (2/semana)
- **Shorts**: 1/dia às 12h
- Espaçamento mínimo: 18h por surface

## Direitos autorais

Todo vídeo-fonte exige `autorizado: true` no manifesto antes de entrar na fila. Sem isso, fica só local.

## Setup

Ver [docs/SETUP.md](docs/SETUP.md) (Fase 0).
