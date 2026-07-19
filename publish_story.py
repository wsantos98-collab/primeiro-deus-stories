#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica o story diário da série "Primeiro Deus" no @gestao.wellingtonjappa.

Roda no GitHub Actions (cron 09:30 UTC = 6h30 BRT). Lê fila/manifest.json,
acha a peça do dia (data em America/Sao_Paulo, UTC-3 fixo), cria o container
STORIES na Content Publishing API apontando pra URL pública do Drive e publica.

Idempotente: fila/published.json guarda as datas já publicadas; o workflow
commita esse arquivo de volta. DRY_RUN=true valida a ingestão (container até
FINISHED) sem publicar.

Env: IG_TOKEN (obrigatório), DRY_RUN (opcional, "true"/"false").
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

GRAPH = "https://graph.instagram.com/v21.0"
IG_USER_ID = "27616747751275055"  # @gestao.wellingtonjappa
BRT = timezone(timedelta(hours=-3))

TOKEN = os.environ.get("IG_TOKEN", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "false").strip().lower() == "true"


def call(method, path, params):
    params = dict(params)
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params)
    if method == "GET":
        req = urllib.request.Request(f"{GRAPH}/{path}?{data}")
    else:
        req = urllib.request.Request(f"{GRAPH}/{path}", data=data.encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"ERRO API {path}: HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"ERRO rede {path}: {e}")


def main():
    if not TOKEN:
        sys.exit("IG_TOKEN ausente.")

    today = datetime.now(BRT).strftime("%Y-%m-%d")
    print(f"Data (BRT): {today}  dry_run={DRY_RUN}")

    with open("fila/manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    entry = next((e for e in manifest if e["date"] == today), None)
    if entry is None:
        sys.exit(
            f"FILA VAZIA para {today}. Reabastecer: gerar a próxima semana no Mac "
            f"(task local 'reabastecer-primeiro-deus') e atualizar fila/manifest.json."
        )

    with open("fila/published.json", encoding="utf-8") as f:
        published = json.load(f)
    if today in published:
        print(f"Já publicado hoje (media_id {published[today]}). Nada a fazer.")
        return

    print(f"Peça: {entry['reference']}  trilha: {entry['track']}")
    if entry.get("video_url"):
        params = {"media_type": "STORIES", "video_url": entry["video_url"]}
        print("Formato: vídeo 59s com trilha")
    else:
        params = {"media_type": "STORIES", "image_url": entry["image_url"]}
        print("Formato: imagem")

    # O processamento de vídeo da Meta às vezes reporta ERROR transitório e
    # depois conclui (visto em 2026-07-19). Estratégia: por container, tolerar
    # ERROR por até 3min de poll extra; se persistir, criar container novo
    # (até 3 tentativas no total).
    cid = None
    for attempt in range(1, 4):
        container = call("POST", f"{IG_USER_ID}/media", params)
        cid = container.get("id")
        if not cid:
            sys.exit(f"Container sem id: {container}")
        print(f"Tentativa {attempt}: container {cid}")

        error_polls = 0
        finished = False
        for _ in range(120):  # até ~10min por tentativa
            st = call("GET", cid, {"fields": "status_code"})
            code = st.get("status_code")
            if code == "FINISHED":
                finished = True
                break
            if code == "ERROR":
                error_polls += 1
                if error_polls >= 36:  # ERROR persistente por ~3min
                    print(f"Container {cid} em ERROR persistente.")
                    break
            time.sleep(5)
        if finished:
            break
        if attempt < 3:
            print("Aguardando 60s antes da próxima tentativa...")
            time.sleep(60)
    else:
        sys.exit("3 tentativas de container falharam (ERROR/timeout).")
    print("Container FINISHED (Meta já baixou a mídia).")

    if DRY_RUN:
        print("DRY RUN: não publicando. Container expira sozinho em 24h.")
        return

    pub = call("POST", f"{IG_USER_ID}/media_publish", {"creation_id": cid})
    media_id = pub.get("id")
    if not media_id:
        sys.exit(f"media_publish sem id: {pub}")
    print(f"PUBLICADO. media_id: {media_id}")

    published[today] = media_id
    with open("fila/published.json", "w", encoding="utf-8") as f:
        json.dump(published, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main()
