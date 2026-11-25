# Contribuindo com a Agenda RioTech

## Regras de ouro

1. **Só eventos de tecnologia, startups ou inovação**, no estado do Rio ou online de comunidades do Rio.
2. **Confira na página oficial** a data, a hora, o local e o preço. Na dúvida, use `"status": "a-confirmar"`: o site mostra o selo «a confirmar».
3. **Descrição com as suas palavras**, em 1–2 frases (máx. 280 caracteres). Não copie o texto do organizador.
4. **Uma URL por evento.** Sem parâmetros de rastreio (`?tk=`, `utm_…`).

## Campos de `data/events.json`

| Campo | Obrigatório | Valores |
|---|---|---|
| `id` | sim | `AAAA-MM-DD-titulo-em-slug` |
| `title` | sim | como na página |
| `start` / `end` | `start` sim | ISO com fuso: `2026-11-14T19:00:00-03:00`; só a data (`2026-11-28`) se não houver hora |
| `time_known` | não | `false` se a página não mostra a hora |
| `venue`, `address`, `city` | não | local, rua e bairro, cidade |
| `format` | sim | `presencial` · `online` · `hibrido` |
| `cost` | sim | `{"type": "gratis" \| "pago" \| "desconhecido", "text": "R$ 50"}` |
| `registration` | sim | `livre` · `inscricao` · `aprovacao` · `ingresso` |
| `url` | sim | página oficial, `https://` |
| `image` | não | URL da capa (og:image). Sem imagem, o site desenha uma capa |
| `organizer` | não | quem organiza |
| `description` | não | `{"pt": "…", "en": "…"}`. Não use o texto genérico do ICS da Luma («Obtenha informações atualizadas em», «Get up-to-date information at», «Organizado por») |
| `descricao_completa` | não | texto integral da página, sem o corte de 220 caracteres. O aviso genérico da Luma não entra |
| `resumo` | não | `{"pt", "en", "es"}`: 1–2 frases, até 240 caracteres em cada idioma. Sai só do título e da descrição real; `scripts/resumir.py` preenche. Sem informação suficiente, o campo não existe |
| `tags` | sim | 1–6, do vocabulário de `data/tags.json` |
| `status` | não | `confirmado` (padrão) · `a-confirmar` · `cancelado` |
| `source`, `added`, `note` | não | origem legível, data em que entrou, observação. `source` fica por compatibilidade |
| `fonte` | sim | id estável: `luma:maravalley`, `meetup:mundo-lingo-rio`, `sympla`, `correio:sympla`, `whatsapp:riotech`, `manual`. O id dos calendários está em `fontes.json` e `fontes_roles.json`. Domínio solto (`luma.com`, `sympla.com.br`) vira `luma`, `sympla` |
| `via` | sim | `feed` · `correio` · `whatsapp` · `sugestao` · `manual`. `desconhecida` só no que a migração não conseguiu classificar |
| `vistos` | sim | lista de `{fonte, via, data}`: cada fonte que viu o evento, sem repetir o par fonte+via |
| `historico` | não | mudança de `start`, `end`, `venue` ou `status` depois da primeira gravação: `{campo, antes, depois, fonte, data, aplicado}`. A mesma URL da plataforma aplica a mudança (`aplicado: true`). Correio, WhatsApp e outra plataforma só registram (`aplicado: false`) e entram na lista «a revisar» da issue semanal |

## Agenda Rolês

A aba Rolês segue o mesmo cartão e a mesma faixa da semana. Os arquivos são outros.

1. **Festas, música ao vivo, cinema especial, comunidades, cultura ou rolê ao ar livre**, no Rio. Cinema especial é mostra, cineclube, pré-estreia ou festival. A grade diária de cinema não entra.
2. **Confira na página oficial** horário, preço e classificação etária. Sem um link público que confirme, o evento não entra.
3. **Descrição com as suas palavras**, em 1–2 frases (máx. 280 caracteres). Não copie o texto do organizador.
4. **O cartão aponta só para a página oficial.**

`data/roles.json` usa os mesmos campos de `events.json`, inclusive `fonte`, `via`, `vistos` e `historico`, mais estes, todos opcionais:

| Campo | Valores |
|---|---|
| `bairro` | nome do bairro, para o filtro de zona |
| `idade_minima` | número; o site mostra o selo «18+» |
| `idioma` | `pt` · `en` · `es` · `multi` (o selo «EN» aparece em `en` e `multi`) |
| `categoria` | `festas` · `shows` · `cinema` · `comunidades` · `cultura` · `ao-ar-livre` |
| `urls` | outras páginas do mesmo rolê, além de `url` |

As tags vêm de `data/tags_roles.json`. Concerto e show entram em Música ao vivo. Evento gratuito na rua ou na praia também leva a tag De graça.

`data/roles_fixos.json` guarda o que se repete. Cada item precisa de `rrule` (`FREQ=WEEKLY` ou `FREQ=MONTHLY`, com `BYDAY`), `time`, `fonte` (URL que confirma, não o id da origem) e `verificado_em` (`AAAA-MM-DD`). `end_time` no dia seguinte, como `00:00`, vale. A página gera as próximas 4 semanas. O cartão mostra «Fixo · confira antes».

O importador da Rolês é `python3 scripts/importar.py --agenda roles --fontes fontes_roles.json`. Só lê iCal ou JSON-LD, e só de fonte cujo `robots.txt` e termos deixam. **InterNations não se importa:** é só para membros. Quem for membro sugere o encontro pela issue, com a agenda Rolês.

## Tags e filtros

- `data/tags.json` define as tags (em PT, EN e Portunhol) e os filtros por intenção: «Sou dev», «Quero investir», «Tenho startup», etc.
- Para criar uma tag nova, adicione-a lá no mesmo PR.

## Importação automática

Tech, Rolês e o correio entram sozinhos na `main` quando `scripts/validar.py` e os testes passam. Não há PR de dados nesse caminho. Tech e Rolês rodam em série no mesmo job; o correio espera a vez, no grupo `dados-agenda`.

A mensagem do commit é `Importação automática (tech, AAAA-MM-DD)`, `Importação automática (roles, AAAA-MM-DD)` ou `Importação automática (correio, AAAA-MM-DD)`. A data é a de São Paulo. Se o push não entra porque a `main` andou, o job faz rebase e tenta de novo (até 3 vezes). Se o rebase conflita, importa outra vez em cima da `main` nova.

Se a validação falha, ninguém empurra a `main`. O robô abre um PR em `importador/revisar-<agenda>-AAAA-MM-DD` com o relatório e o erro. O relatório de toda rodada, verde ou não, fica no resumo do job e na issue «Saúde da agenda».

Sugestão pela issue e PR feito à mão continuam iguais. O checklist abaixo é para esses PRs.

## Antes do PR

```bash
python3 scripts/validar.py
python3 -m unittest discover -s scripts
```
