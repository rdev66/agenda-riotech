# Agenda RioTech

Eventos de tecnologia no Rio de Janeiro num lugar só: meetups, conferências, hackathons, encontros de founders e investidores. Feita e mantida pela comunidade RioTech.

*Rio's tech events in one place, made by the RioTech community. The page speaks Portuguese, English and Portunhol.*

## Como funciona

- **O site** é um `index.html` estático, sem framework e sem build. A aba Tech lê `data/events.json` e `data/tags.json`. A aba Rolês lê `data/roles.json`, `data/tags_roles.json` e `data/roles_fixos.json` só quando abre.
- **Os dados** ficam em JSON, um evento por objeto. Todo PR passa pelo `scripts/validar.py` e pelos testes.
- **O importador** (`scripts/importar.py`, só biblioteca padrão do Python):
  - lê páginas de evento (Luma, Meetup, Sympla, Even3, Eventbrite) pelos dados estruturados `schema.org/Event`;
  - lê calendários iCal listados em `fontes.json` (Tech) ou `fontes_roles.json` (Rolês);
  - lê os links de uma exportação do grupo do WhatsApp, só na agenda Tech.
  Nunca sobrescreve o que alguém corrigiu à mão: só completa campos vazios. Na agenda Rolês, uma fonte só entra se o `robots.txt` e os termos deixam ler, e se a página tem iCal ou `schema.org/Event` em JSON-LD.
- **Automação no GitHub Actions:**
  - `importar.yml`: todo dia às 08:17 (Rio), lê `fontes.json` e abre um PR em `importador/diario`; no mesmo horário lê `fontes_roles.json` e abre outro PR em `importador/roles-diario`;
  - `issue-para-pr.yml`: quem abre uma issue «Sugerir um evento» com o link recebe um PR pronto, na agenda escolhida;
  - `validar.yml`: valida dados e roda os testes em todo PR;
  - `pages.yml`: publica o site no GitHub Pages a cada push na `main`.

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

## Licença

Código sob MIT. Os dados de cada evento pertencem a quem organiza; a agenda só resume e aponta para a página oficial.
