# Agenda RioTech

Eventos de tecnologia no Rio de Janeiro num lugar só: meetups, conferências, hackathons, encontros de founders e investidores. Feita e mantida pela comunidade RioTech.

*Rio's tech events in one place, made by the RioTech community. The page speaks Portuguese, English and Portunhol.*

## Como funciona

- **O site** é um `index.html` estático que lê `data/events.json` e `data/tags.json`. Sem framework e sem build.
- **Os dados** ficam em `data/events.json`, um evento por objeto. Todo PR passa pelo `scripts/validar.py` e pelos testes.
- **O importador** (`scripts/importar.py`, só biblioteca padrão do Python):
  - lê páginas de evento (Luma, Meetup, Sympla, Even3, Eventbrite) pelos dados estruturados `schema.org/Event`;
  - lê calendários iCal listados em `fontes.json`;
  - lê os links de uma exportação do grupo do WhatsApp.
  Nunca sobrescreve o que alguém corrigiu à mão: só completa campos vazios.
- **Automação no GitHub Actions:**
  - `importar.yml`: todo dia às 08:17 (Rio), lê `fontes.json` e abre um PR com os eventos novos;
  - `issue-para-pr.yml`: quem abre uma issue «Sugerir um evento» com o link recebe um PR pronto;
  - `validar.yml`: valida dados e roda os testes em todo PR;
  - `pages.yml`: publica o site no GitHub Pages a cada push na `main`.

## Como sugerir um evento

1. **Mais fácil:** abra uma issue com o modelo **Sugerir um evento** e cole o link. O robô abre o PR.
2. **Direto:** edite `data/events.json` e abra um PR. Veja os campos em [CONTRIBUTING.md](CONTRIBUTING.md).
3. **Pelo WhatsApp:** mande o link no grupo. Quem mantém a agenda roda o importador com a exportação do chat (abaixo).

## Rodar localmente

```bash
python3 -m http.server 8000      # abra http://localhost:8000
python3 scripts/validar.py       # valida os dados
python3 -m unittest discover -s scripts
```

Importar à mão:

```bash
python3 scripts/importar.py --url https://luma.com/xxxx
python3 scripts/importar.py --fontes fontes.json --dry-run
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

## Publicar

1. Crie o repositório e suba estes arquivos.
2. *Settings → Pages → Source: GitHub Actions*.
3. *Settings → Actions → General → Workflow permissions*:
   - marque «Read and write»;
   - marque «Allow GitHub Actions to create and approve pull requests».
4. Crie as etiquetas `novo-evento` e `importacao-automatica`.
5. Em `index.html`, preencha `<meta name="riotech:repo" content="https://github.com/ORG/REPO">`. Assim os botões «Sugerir pelo GitHub» passam a apontar para o repositório.

## Licença

Código sob MIT. Os dados de cada evento pertencem a quem organiza; a agenda só resume e aponta para a página oficial.
