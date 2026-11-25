# Agenda RioTech

Eventos de tecnologia no Rio: software, IA, ciência, biotech, energia, hardware, fintech, economia criativa…. Feita e mantida pela comunidade RioTech.

*Rio's tech events in one place, made by the RioTech community. The page speaks Portuguese, English and Portunhol.*

## Como funciona

- **O site** é um `index.html` estático, sem framework e sem build. A aba Tech lê `data/events.json` e `data/tags.json`. A aba Rolês lê `data/roles.json`, `data/tags_roles.json` e `data/roles_fixos.json` só quando abre.
- **Os dados** ficam em JSON, um evento por objeto. Todo PR passa pelo `scripts/validar.py` e pelos testes.
- **O importador** (`scripts/importar.py`, só biblioteca padrão do Python):
  - lê páginas de evento (Luma, Meetup, Sympla, Even3, Eventbrite) pelos dados estruturados `schema.org/Event`;
  - lê calendários iCal listados em `fontes.json` (Tech) ou `fontes_roles.json` (Rolês);
  - lê os links de uma exportação do grupo do WhatsApp, só na agenda Tech.
  Só completa campos vazios. Data, fim, local e status mudam quando a própria página do evento (Luma, Meetup, Sympla e os outros hosts oficiais) traz um valor novo; correio, WhatsApp e outra plataforma ficam no histórico, para a lista «a revisar». Evento cancelado continua no site, marcado como cancelado. Na agenda Rolês, uma fonte só entra se o `robots.txt` e os termos deixam ler, e se a página tem iCal ou `schema.org/Event` em JSON-LD.
- **Automação no GitHub Actions:**
  - `importar.yml`: todo dia às 08:17 (Rio), lê `fontes.json` (Tech) e, em seguida, no mesmo job, `fontes_roles.json` (Rolês). `scripts/resumir.py` preenche o resumo dos eventos futuros. Sem `ANTHROPIC_API_KEY`, essa etapa avisa e o job segue;
  - `importar-correio.yml`: todo dia às 08:47 (Rio), lê as duas caixas do Gmail. Se a senha de app falta, avisa e termina sem erro;
  - os dois usam o grupo `dados-agenda` (`cancel-in-progress: false`) e nunca rodam ao mesmo tempo. Cada um faz `git pull --rebase` na `main`, importa, resume e roda `scripts/validar.py` e os testes. Se está tudo verde e há mudança, o commit entra na `main`: `Importação automática (tech, AAAA-MM-DD)`, `Importação automática (roles, AAAA-MM-DD)` ou `Importação automática (correio, AAAA-MM-DD)`, com a data de São Paulo. Se o push falha porque a `main` andou, faz rebase e tenta de novo, até 3 vezes; se o rebase conflita, importa de novo. Se a validação falha, a `main` não muda e abre um PR em `importador/revisar-<agenda>-AAAA-MM-DD` (Tech e Rolês juntos: `tech-e-roles`), com o relatório e o erro. O mesmo relatório vai para o resumo do job e para a issue semanal «Saúde da agenda»;
  - um push feito com o `GITHUB_TOKEN` não dispara outros workflows. Depois de gravar na `main`, o job dispara o Pages com `gh workflow run pages.yml --ref main`. Push de gente continua publicando pelo `pages.yml`;
  - `issue-para-pr.yml`: quem abre uma issue «Sugerir um evento» com o link recebe um PR pronto, na agenda escolhida. Sugestão e PR feito à mão não mudaram;
  - `validar.yml`: valida dados e roda os testes em todo PR;
  - `pages.yml`: publica o site no GitHub Pages a cada push de gente na `main`, e quando o importador dispara o workflow.

## Agenda Rolês

A mesma página tem uma segunda agenda, **Rolês**: festas, rodas, cinema especial, comunidades, cultura e rolê ao ar livre. A aba fica embaixo do título. `#roles` abre Rolês; sem hash, a última aba escolhida (ou Tech).

Os dados são `data/roles.json`. Os encontros que se repetem toda semana ou todo mês ficam em `data/roles_fixos.json`, com a regra e o link que confirma. A página monta as próximas 4 semanas e marca o cartão com «Fixo · confira antes».

O importador da Rolês não raspa HTML, Instagram, Facebook nem WhatsApp de terceiros. Cada fonte em `fontes_roles.json` precisa de iCal ou de JSON-LD `schema.org/Event`, e o `robots.txt` e os termos precisam deixar ler. Se um dos dois falha, a fonte fica `"ativo": false` com o motivo em `"nota"`.

**InterNations é manual.** A comunidade é só para membros, então o importador não entra. Quem participa cola o link da página do encontro na issue «Sugerir um evento», escolhe a agenda **Rolês** e, se souber, a categoria.

```bash
python3 scripts/importar.py --agenda roles --fontes fontes_roles.json --dry-run
```

## Como sugerir um evento

1. **Mais fácil:** abra uma issue com o modelo **Sugerir um evento**, escolha **Tech** ou **Rolês** e cole o link. O robô abre o PR no arquivo certo.
2. **Direto:** edite `data/events.json` (Tech) ou `data/roles.json` (Rolês) e abra um PR. Veja os campos em [CONTRIBUTING.md](CONTRIBUTING.md).
3. **Pelo WhatsApp:** mande o link no grupo da RioTech. Quem mantém a agenda roda o importador com a exportação do chat (abaixo). Isso vale para a agenda Tech.

## Rodar localmente

```bash
python3 -m http.server 8000      # abra http://localhost:8000
python3 scripts/validar.py       # valida os dados
python3 -m unittest discover -s scripts
```

Importar à mão:

```bash
python3 scripts/importar.py --agenda tech --url https://luma.com/xxxx
python3 scripts/importar.py --agenda tech --fontes fontes.json --dry-run
python3 scripts/importar.py --agenda roles --fontes fontes_roles.json --dry-run
# WhatsApp → «Exportar conversa» (sem mídia) → _chat.txt
python3 scripts/importar.py --whatsapp ~/Downloads/_chat.txt --desde 2026-10-01
python3 scripts/importar_correio.py --dry-run
python3 scripts/resumir.py          # resumo dos eventos futuros; sem a chave, não faz nada
```

Toda semana, com o export do grupo salvo em `~/Downloads` (o `.zip` serve, não precisa descompactar):

```bash
scripts/semanal.sh            # acha o export mais novo, importa os últimos 14 dias e abre o PR
scripts/semanal.sh --onde     # só mostra qual export usaria; não mexe no git
```

O `_chat.txt` é lido para um arquivo temporário fora do repositório e apagado no fim. Se o export mais novo tiver mais de 2 dias, o script pergunta antes de seguir.

## WhatsApp: o que dá e o que não dá para automatizar

- O WhatsApp não tem API oficial para ler grupos. Bots não oficiais (whatsapp-web.js, Baileys) violam os termos e podem levar o número a ser banido. Por isso a agenda não usa bot.
- **O fluxo proposto:** toda semana, alguém exporta o chat para Downloads e roda `scripts/semanal.sh`. Ele extrai **só links** de plataformas de eventos.
- **Privacidade:** nenhum nome, telefone ou mensagem é gravado. O `.gitignore` bloqueia `_chat.txt`: **nunca suba a exportação do chat para o repositório.**

## Correio

Duas caixas no Gmail alimentam a agenda. `scripts/importar_correio.py` lê o conteúdo por IMAP (`imap.gmail.com`, porta 993) e grava pelo mesmo caminho do importador. O importador do WhatsApp continua.

- `agenda.rio.eventos@gmail.com` sugere a agenda Tech (`data/events.json`).
- `agenda.rio.roles@gmail.com` sugere a agenda Rolês (`data/roles.json`). Mensagem para `agenda.rio.roles+cultura@gmail.com` fica na Rolês, na categoria cultura.
- A caixa é uma dica. Se o evento é claramente da outra agenda, o script muda de arquivo e o relatório diz isso.
- Link de Luma, Meetup, Sympla, Eventbrite, Even3, Shotgun e dos outros hosts que o importador já lê segue o caminho `--url`, sem parâmetro de rastreio. Newsletter sem esse link (IMS, Sesc, Fever, Bandsintown e semelhantes) vai para o modelo `claude-haiku-5-5`, que não inventa data nem hora.
- Só entra evento futuro, presencial ou híbrido, na cidade configurada (Rio). Online fica de fora.
- Cada mensagem lida ganha a etiqueta `agenda/processado`. Nada é apagado nem movido. O repositório não guarda endereço, remetente nem o texto do e-mail: só o evento e o link público.
- Se a validação passa, o job grava na `main`. A data do commit é a de São Paulo: `Importação automática (correio, AAAA-MM-DD)`. A rodada seguinte começa dessa `main` (`git pull --rebase`), então não há PR de dados parado no meio do caminho. Se a validação falha, a `main` fica como está e abre um PR em `importador/revisar-correio-AAAA-MM-DD`, com o relatório e o erro.
- Link de descadastro, preferências ou «ver no navegador» não é aberto. O cabeçalho `List-Unsubscribe` também fica de fora. Link de conta também não: `confirm`, `confirmar`, `verify`, `verificar`, `activate`, `ativar`, `reset`, `password`, `login`, `signin` ou `token=` na URL.
- Se a página do evento falha (erro HTTP, `robots.txt` indisponível ou 503, sem JSON-LD), o texto do e-mail vai para o mesmo modelo, em vez de descartar o evento.
- E-mail do Songkick («concerts this week in Rio»), da Eventim e do Resident Advisor traz vários eventos. Entram todos, com data, local, artista e link.

Segredos no GitHub Actions, nunca no repositório:

- `GMAIL_EVENTOS_APP_PASSWORD` — senha de app da caixa Tech
- `GMAIL_ROLES_APP_PASSWORD` — senha de app da caixa Rolês
- `ANTHROPIC_API_KEY` — extração das newsletters sem link de evento e o resumo em «Detalhes»

Se uma senha falta, o job avisa e termina sem erro. A rodada também para se passar de 300 mil tokens de entrada.

## Estatísticas e feedback

As visitas vão para o [GoatCounter](https://agenda-riotech.goatcounter.com/), sem cookies e sem dados pessoais. O painel público mostra só totais: páginas vistas, cliques num evento, cliques em «Pôr no Google Agenda», retornos de quem volta, o botão «Sugerir evento» e a troca de idioma. Nada identifica quem entrou.

O feedback anônimo fica no Supabase, só para inserção: o navegador não lê a tabela. Não guardamos dados pessoais nem IP. A pessoa marca um semáforo (uso sempre, às vezes, não me serviu) e, se quiser, conta se já foi a um evento, o que falta e um comentário curto.

Quem preferir escreve pelo GitHub, no modelo **Feedback** (etiqueta `feedback`).

## Publicar

1. Crie o repositório e suba estes arquivos.
2. *Settings → Pages → Source: GitHub Actions*.
3. *Settings → Actions → General → Workflow permissions*:
   - marque «Read and write»;
   - marque «Allow GitHub Actions to create and approve pull requests».
4. Crie as etiquetas `novo-evento`, `importacao-automatica` e `feedback`.
5. Em `index.html`, preencha `<meta name="riotech:repo" content="https://github.com/ORG/REPO">`. Assim os botões «Sugerir pelo GitHub» passam a apontar para o repositório.

O importador automático também publica o site: depois do push na `main`, dispara `pages.yml` (`gh workflow run pages.yml --ref main`). O token das Actions não aciona outro workflow no push. Um push de gente continua caindo no `pages.yml` direto.

## Licença

Código sob MIT. Os dados de cada evento pertencem a quem organiza; a agenda só resume e aponta para a página oficial.
