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
    """Chama a Graph API, com backoff em erro transitório.

    A Meta devolve HTTP 4xx/5xx com is_transient=true quando o app bate no
    limite de requisições ("Application request limit reached", code 4).
    Morrer na hora nesse caso derruba uma publicação por um erro que passa
    sozinho em minutos, então aqui espera e tenta de novo antes de desistir.
    """
    params = dict(params)
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params)

    for tentativa in range(4):
        if method == "GET":
            req = urllib.request.Request(f"{GRAPH}/{path}?{data}")
        else:
            req = urllib.request.Request(f"{GRAPH}/{path}", data=data.encode(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")
            transitorio = '"is_transient":true' in corpo.replace(" ", "") or e.code in (429, 500, 502, 503)
            if not transitorio or tentativa == 3:
                sys.exit(f"ERRO API {path}: HTTP {e.code}: {corpo}")
            espera = 60 * (tentativa + 1)
            print(f"API transitória ({e.code}) em {path}; nova tentativa em {espera}s.")
            time.sleep(espera)
        except urllib.error.URLError as e:
            if tentativa == 3:
                sys.exit(f"ERRO rede {path}: {e}")
            print(f"Rede instável em {path} ({e}); nova tentativa em 30s.")
            time.sleep(30)


def story_publicado_hoje(today, published):
    """Pergunta à própria API se a SÉRIE já foi publicada na data BRT de hoje.

    Guard real de idempotência. O fila/published.json sozinho não protege:
    o actions/checkout materializa o SHA do evento, então um run disparado
    ANTES da publicação lê um published.json congelado e não enxerga o
    registro que outro run acabou de commitar (foi o que duplicou o story de
    2026-08-07). O edge /stories lista os stories ativos das últimas 24h, que
    cobre com folga a janela dos 4 despertares.

    Só conta como duplicata story que seja nosso, por um dos dois sinais:
    id já registrado no published.json, ou publicado na janela em que só o bot
    publica (05:28-05:44 BRT; a garantia da sede parte às 05:35 e pode levar
    alguns minutos de ingestão do vídeo, por isso a janela vai até 05:44). Story que o Jappa posta na mão fora dessa janela
    não é da série e não pode bloquear a publicação (foi o que segurou o story
    de 2026-08-17: ele postou às 05:17 e o guard achou que era o da série).
    """
    try:
        r = call("GET", f"{IG_USER_ID}/stories", {"fields": "id,timestamp"})
    except SystemExit:
        print("AVISO: não deu pra consultar /stories; seguindo com o guard do arquivo.")
        return None
    nossos = set(published.values())
    for item in r.get("data", []):
        ts = item.get("timestamp", "")
        try:
            quando = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(BRT)
        except ValueError:
            continue
        if quando.strftime("%Y-%m-%d") != today:
            continue
        na_janela = (quando.hour, quando.minute) >= (5, 28) and (quando.hour, quando.minute) < (5, 45)
        if item.get("id") in nossos or na_janela:
            return item.get("id")
        print(f"Story de hoje às {quando:%H:%M} não é da série (postado na mão); seguindo.")
    return None


def ingerir(params):
    """Cria o container e espera ficar FINISHED. Devolve o id, ou None.

    O processamento de vídeo da Meta às vezes reporta ERROR transitório e
    depois conclui (visto em 2026-07-19). Estratégia: por container, tolerar
    ERROR por até 3min de poll extra; se persistir, criar container novo
    (até 3 tentativas no total).
    """
    for attempt in range(1, 4):
        container = call("POST", f"{IG_USER_ID}/media", params)
        cid = container.get("id")
        if not cid:
            sys.exit(f"Container sem id: {container}")
        print(f"Tentativa {attempt}: container {cid}")

        # Poll a cada 10s, não 5s: 360 chamadas numa manhã ruim é o que faz o
        # app bater no limite de requisições da Meta (visto em 2026-08-07).
        error_polls = 0
        for _ in range(60):  # até ~10min por tentativa
            st = call("GET", cid, {"fields": "status_code"})
            code = st.get("status_code")
            if code == "FINISHED":
                return cid
            if code == "ERROR":
                error_polls += 1
                if error_polls >= 18:  # ERROR persistente por ~3min
                    print(f"Container {cid} em ERROR persistente.")
                    break
            time.sleep(10)
        if attempt < 3:
            print("Aguardando 60s antes da próxima tentativa...")
            time.sleep(60)
    print("3 tentativas de container falharam (ERROR/timeout).")
    return None


def registrar(published, today, media_id):
    published[today] = media_id
    with open("fila/published.json", "w", encoding="utf-8") as f:
        json.dump(published, f, indent=2, ensure_ascii=False)
        f.write("\n")
    # Pista pro step de registro do workflow reconstruir o arquivo a partir do
    # remoto (evita o conflito de rebase que derrubou o run de 2026-08-07).
    with open(".registro-do-dia.json", "w", encoding="utf-8") as f:
        json.dump({"date": today, "media_id": media_id}, f)


def main():
    if not TOKEN:
        sys.exit("IG_TOKEN ausente.")

    # Runs agendadas acordam ~40min antes e seguram até as 5h30 BRT em ponto
    # (o atraso do scheduler do GitHub cai dentro dessa folga). Runs manuais
    # (workflow_dispatch) publicam imediatamente.
    if os.environ.get("WAIT_FOR_TARGET", "false").strip().lower() == "true":
        now = datetime.now(BRT)
        target = now.replace(hour=5, minute=30, second=0, microsecond=0)
        wait = (target - now).total_seconds()
        if wait > 0:
            print(f"Aguardando {int(wait)}s até as 05:30 BRT...")
            time.sleep(wait)
        else:
            print("Já passou das 05:30 BRT; publicando imediatamente.")

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

    ja = story_publicado_hoje(today, published)
    if ja:
        print(f"A API já tem story de hoje no ar (media_id {ja}). Registrando e saindo.")
        registrar(published, today, ja)
        return

    print(f"Peça: {entry['reference']}  trilha: {entry['track']}")

    cid = None
    if entry.get("video_url"):
        print("Formato: vídeo 59s com trilha")
        cid = ingerir({"media_type": "STORIES", "video_url": entry["video_url"]})
        if cid is None and entry.get("image_url"):
            # Decisão do Jappa (2026-08-07): story sem trilha é melhor que
            # série furada. O vídeo depende de a Meta conseguir baixar o MP4
            # do Drive, que já falhou com o arquivo íntegro (o file id de
            # 08/08 parou de servir). O PNG ingere em segundos e salva o dia.
            print("FALLBACK: vídeo não ingeriu; publicando a imagem sem trilha.")
            cid = ingerir({"media_type": "STORIES", "image_url": entry["image_url"]})
    else:
        print("Formato: imagem")
        cid = ingerir({"media_type": "STORIES", "image_url": entry["image_url"]})

    if cid is None:
        sys.exit("Nenhum container ficou pronto (vídeo e imagem falharam).")
    print("Container FINISHED (Meta já baixou a mídia).")

    if DRY_RUN:
        print("DRY RUN: não publicando. Container expira sozinho em 24h.")
        return

    # Segunda checagem colada no publish: a ingestão do vídeo leva minutos e
    # outro run pode ter publicado nesse intervalo.
    ja = story_publicado_hoje(today, published)
    if ja:
        print(f"Outro run publicou durante a ingestão (media_id {ja}). Abortando publish.")
        registrar(published, today, ja)
        return

    pub = call("POST", f"{IG_USER_ID}/media_publish", {"creation_id": cid})
    media_id = pub.get("id")
    if not media_id:
        sys.exit(f"media_publish sem id: {pub}")
    print(f"PUBLICADO. media_id: {media_id}")
    registrar(published, today, media_id)


if __name__ == "__main__":
    main()
