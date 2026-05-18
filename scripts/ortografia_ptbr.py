"""Validação ortográfica PT-BR pra títulos antes de gerar capas.

Camadas:
1. Regex rápido: detecta typos comuns sem custo (ÇÃN, duplo acento, etc).
2. Claude CLI (opcional): validação profunda quando regex acha suspeito OU sempre.

API:
    titulo_corrigido = validar_titulo(titulo, deep=True/False)
"""
from __future__ import annotations

import re
import shutil
import subprocess


# Padrões suspeitos com correção sugerida ou aviso
PATTERNS_BUG = [
    # Erros que o Gemini comete renderizando texto em PT-BR
    (re.compile(r"ÇÃN\b", re.IGNORECASE), "ção termina em O (não N)"),
    (re.compile(r"ÃÕ"),                "duplo til em ÃO"),
    (re.compile(r"Ã̃"),                 "duplo til em à (caractere combinante)"),
    (re.compile(r"\bACAO\b", re.IGNORECASE), "AÇÃO sem cedilha/acento"),
    (re.compile(r"\bNAO\b"),                 "NÃO sem til"),
    (re.compile(r"\bMAE\b"),                 "MÃE sem til"),
    (re.compile(r"\bAVO\b"),                 "AVÔ/AVÓ sem acento"),
    # ÃÕ ou ÕÃ (sequências impossíveis)
    (re.compile(r"ÃÕ|ÕÃ"),                   "sequência de til impossível"),
]

# Palavras comuns que costumam dar problema (lookup)
PALAVRAS_ESPERADAS = {
    "destruicao": "destruição",
    "construcao": "construção",
    "eleicao": "eleição",
    "eleicoes": "eleições",
    "nacao": "nação",
    "racao": "ração",
    "explicacao": "explicação",
    "candidato": "candidato",  # case-only check
    "pessimo": "péssimo",
    "ultimo": "último",
    "publico": "público",
    "politica": "política",
    "politico": "político",
}


def _regex_check(titulo: str) -> list[str]:
    """Retorna lista de avisos detectados via regex."""
    avisos = []
    for pat, descricao in PATTERNS_BUG:
        if pat.search(titulo):
            avisos.append(f"padrão suspeito: {descricao}")
    return avisos


def _claude_check(titulo: str, cli_binary: str = "claude") -> tuple[bool, str]:
    """Pergunta ao Claude se o título está ortograficamente correto.

    Retorna (esta_ok, titulo_final).
    """
    bin_path = shutil.which(cli_binary) or shutil.which(cli_binary + ".cmd")
    if not bin_path:
        return True, titulo  # sem CLI disponível, assume OK

    prompt = (
        f"Valide a ortografia PT-BR deste título de YouTube:\n"
        f'TÍTULO: "{titulo}"\n\n'
        f"Verifique APENAS:\n"
        f"- Acentos corretos (á, â, ã, é, ê, í, ó, ô, õ, ú, ç)\n"
        f"- Terminações 'ÇÃO' (nunca ÇÃN)\n"
        f"- Palavras em português padrão BR\n\n"
        f"Responda EXATAMENTE uma linha, nada mais:\n"
        f'- "OK" se o título está correto\n'
        f'- "CORRIGIR: <título corrigido>" se houver erro real (não estilo)\n\n'
        f"Ignore: caixa-alta, hashtags, gírias intencionais."
    )
    try:
        is_script = bin_path.lower().endswith((".cmd", ".ps1", ".bat"))
        cmd = f'"{bin_path}" -p --output-format text' if is_script else [bin_path, "-p", "--output-format", "text"]
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            encoding="utf-8", check=True, shell=is_script, timeout=30,
        )
        resp = result.stdout.strip()
    except Exception as e:
        print(f"[ortografia] Claude check falhou ({e}), seguindo com título original")
        return True, titulo

    if resp.upper().startswith("OK"):
        return True, titulo
    if resp.upper().startswith("CORRIGIR:"):
        corrigido = resp.split(":", 1)[1].strip().strip('"')
        # Sanity: corrigido não pode ser radicalmente diferente
        if abs(len(corrigido) - len(titulo)) < len(titulo) * 0.5:
            return False, corrigido
    # Resposta inesperada → mantém original
    return True, titulo


def validar_titulo(titulo: str, deep: bool = False) -> str:
    """Valida ortografia PT-BR. Retorna título original ou corrigido.

    deep=False: só regex (instantâneo, sem custo)
    deep=True: regex + Claude CLI quando regex acha suspeita
    """
    avisos = _regex_check(titulo)

    if avisos:
        print(f"[ortografia] avisos em '{titulo}': {avisos}")

    # Se não há suspeita e não pediu deep, retorna direto
    if not avisos and not deep:
        return titulo

    # Validação profunda via Claude
    ok, titulo_final = _claude_check(titulo)
    if not ok:
        print(f"[ortografia] CORRIGIDO: '{titulo}' → '{titulo_final}'")
    return titulo_final


if __name__ == "__main__":
    # Teste manual
    casos = [
        "A morte do Bolsonarismo: por que perdem do Lula em tudo",
        "Flávio, volta pra casa: a destruição do candidato",
        "FLÁVIO, VOLTA PRA CASA: A DESTRUIÇÃN DO CANDIDATO",  # bug do Gemini
        "Como Vorcaro comprou todo mundo no Brasil",
    ]
    for t in casos:
        print(f"\n→ {t}")
        corrigido = validar_titulo(t, deep=True)
        if corrigido != t:
            print(f"   CORRIGIDO: {corrigido}")
        else:
            print(f"   OK")
