# Primeiro Deus — publicador diário de stories

Publica 1 story por dia às 5h30 BRT no @gestao.wellingtonjappa (série "Primeiro Deus":
versículo CNBB + reflexão do Jappa), via GitHub Actions + Instagram Content Publishing API.
Roda 100% na nuvem: o Mac do Jappa pode estar desligado.

- `fila/manifest.json`: fila de peças (data → URL pública do PNG no Drive + referência + trilha).
- `fila/published.json`: registro do que já foi publicado (idempotência; o workflow commita).
- `publish_story.py`: pega a peça do dia (fuso BRT), cria container STORIES, publica.
- Secret `IG_TOKEN`: token long-lived da conta (renovado pela task local semanal).

Horário: o cron do GitHub é best-effort e o atraso varia (25min num dia bom;
5-12h desde 26/08/2026, e em 27/08 e 02/09 nenhum despertar chegou na manhã — o
story só saiu porque o Jappa disparou na mão). Por isso o workflow tem uma dúzia
de despertares espalhados pelo dia: quem acorda até 3h30 antes do alvo dorme e
publica às 5h30 em ponto, quem acorda depois publica atrasado, quem acorda cedo
demais sai limpo. Passou das 20h BRT sem publicar, o run falha de propósito (o
dia está perdido; um story da série às 22h é ruído). Todos são idempotentes.

Se um dia furar de novo, o resgate é `workflow_dispatch` na aba Actions
(publica na hora, sem esperar o alvo).

Reabastecimento: a task local `reabastecer-primeiro-deus` (Mac, semanal) gera as próximas 7
peças pela skill designer-carrossel, sobe no Drive (pasta "Primeiro Deus - Fila"), atualiza o
manifest e renova o token. Se a fila secar, o workflow falha com aviso (e-mail do GitHub).

Criado em 2026-07-18 pela sessão do Naka. Contexto completo na memória
`project_story_primeiro_deus.md` do Claude do Jappa.
