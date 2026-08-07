#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Registra no repo a publicação do dia, sem rebase e sem conflito.

O step antigo fazia `git commit && git pull --rebase && git push`. Quando dois
runs publicavam na mesma manhã, o rebase batia de frente no mesmo arquivo e o
run morria com "could not apply" (2026-08-07), deixando a publicação sem
registro. Aqui a estratégia é outra: buscar o published.json do remoto, aplicar
só a entrada de hoje por cima e empurrar, repetindo se o remoto andar no meio.

Lê .registro-do-dia.json (escrito pelo publish_story.py). Sem esse arquivo,
não há nada a registrar e o script sai limpo.
"""

import json
import os
import subprocess
import sys

PISTA = ".registro-do-dia.json"
ARQ = "fila/published.json"


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True)


def main():
    if not os.path.exists(PISTA):
        print("Nada publicado neste run. Nada a registrar.")
        return

    with open(PISTA, encoding="utf-8") as f:
        novo = json.load(f)
    date, media_id = novo["date"], novo["media_id"]

    for tentativa in range(1, 4):
        # Sentar exatamente em cima do remoto atual. O reset descarta o que o
        # publish_story escreveu no arquivo versionado, e é essa a intenção:
        # a entrada de hoje é reaplicada logo abaixo. A pista é untracked,
        # então sobrevive ao reset.
        git("fetch", "origin", "main")
        git("reset", "--hard", "origin/main")

        with open(ARQ, encoding="utf-8") as f:
            published = json.load(f)
        if published.get(date) == media_id:
            print(f"{date} já registrado no remoto (media_id {media_id}).")
            return

        published[date] = media_id
        with open(ARQ, "w", encoding="utf-8") as f:
            json.dump(published, f, indent=2, ensure_ascii=False)
            f.write("\n")

        git("add", ARQ)
        git("commit", "-m", f"registro: story publicado ({date})")

        if git("push", "origin", "HEAD:main", check=False).returncode == 0:
            print(f"Registrado: {date} -> {media_id}")
            return
        print(f"Push recusado (tentativa {tentativa}); o remoto andou, refazendo.")

    sys.exit(f"ERRO: não consegui registrar {date} -> {media_id} em 3 tentativas.")


if __name__ == "__main__":
    main()
