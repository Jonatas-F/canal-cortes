"""OAuth 2.0 setup do YouTube — rodar UMA VEZ para gerar token.json.

Pré-requisito:
1. Criar projeto no Google Cloud (console.cloud.google.com)
2. Habilitar "YouTube Data API v3"
3. Criar credencial "OAuth client ID" tipo "Desktop app"
4. Baixar como client_secret.json e colocar na raiz do repo

Uso:
    python scripts/auth_youtube.py
"""
from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from common import ROOT

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN_PATH = ROOT / "token.json"


def main() -> None:
    if not CLIENT_SECRET.exists():
        raise SystemExit(
            f"client_secret.json não encontrado em {CLIENT_SECRET}.\n"
            f"Baixe do Google Cloud Console (OAuth client ID, tipo Desktop app)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"[auth] token salvo em {TOKEN_PATH}")

    yt = build("youtube", "v3", credentials=creds)
    resp = yt.channels().list(part="snippet,contentDetails", mine=True).execute()
    for ch in resp.get("items", []):
        print(f"[auth] canal: {ch['snippet']['title']}  id={ch['id']}")
        print("[auth] cole esse id em config.yaml -> canal.youtube_channel_id")


if __name__ == "__main__":
    main()
