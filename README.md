# Primeiro Deus — publicador diário de stories

Publica 1 story por dia às 6h30 BRT no @gestao.wellingtonjappa (série "Primeiro Deus":
versículo CNBB + reflexão do Jappa), via GitHub Actions + Instagram Content Publishing API.
Roda 100% na nuvem: o Mac do Jappa pode estar desligado.

- `fila/manifest.json`: fila de peças (data → URL pública do PNG no Drive + referência + trilha).
- `fila/published.json`: registro do que já foi publicado (idempotência; o workflow commita).
- `publish_story.py`: pega a peça do dia (fuso BRT), cria container STORIES, publica.
- Secret `IG_TOKEN`: token long-lived da conta (renovado pela task local semanal).

Reabastecimento: a task local `reabastecer-primeiro-deus` (Mac, semanal) gera as próximas 7
peças pela skill designer-carrossel, sobe no Drive (pasta "Primeiro Deus - Fila"), atualiza o
manifest e renova o token. Se a fila secar, o workflow falha com aviso (e-mail do GitHub).

Criado em 2026-07-18 pela sessão do Naka. Contexto completo na memória
`project_story_primeiro_deus.md` do Claude do Jappa.
