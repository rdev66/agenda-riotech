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
| `description` | não | `{"pt": "…", "en": "…"}` |
| `tags` | sim | 1–6, do vocabulário de `data/tags.json` |
| `status` | não | `confirmado` (padrão) · `a-confirmar` |
| `source`, `added`, `note` | não | origem, data em que entrou, observação |

## Agenda Rolês

A aba Rolês segue o mesmo cartão e a mesma faixa da semana. Os arquivos são outros.

1. **Festas, música ao vivo, cinema especial, comunidades, cultura ou rolê ao ar livre**, no Rio. Cinema especial é mostra, cineclube, pré-estreia ou festival. A grade diária de cinema não entra.
2. **Confira na página oficial** horário, preço e classificação etária. Sem um link público que confirme, o evento não entra.
3. **Descrição com as suas palavras**, em 1–2 frases (máx. 280 caracteres). Não copie o texto do organizador.
4. **O cartão aponta só para a página oficial.**

`data/roles.json` usa os mesmos campos de `events.json`, mais estes, todos opcionais:

| Campo | Valores |
|---|---|
| `bairro` | nome do bairro, para o filtro de zona |
| `idade_minima` | número; o site mostra o selo «18+» |
| `idioma` | `pt` · `en` · `es` · `multi` (o selo «EN» aparece em `en` e `multi`) |
| `categoria` | `festas` · `shows` · `cinema` · `comunidades` · `cultura` · `ao-ar-livre` |
| `urls` | outras páginas do mesmo rolê, além de `url` |

As tags vêm de `data/tags_roles.json`.

`data/roles_fixos.json` guarda o que se repete. Cada item precisa de `rrule` (`FREQ=WEEKLY` ou `FREQ=MONTHLY`, com `BYDAY`), `time`, `fonte` (URL que confirma) e `verificado_em` (`AAAA-MM-DD`). `end_time` no dia seguinte, como `00:00`, vale. A página gera as próximas 4 semanas. O cartão mostra «Fixo · confira antes».

O importador da Rolês é `python3 scripts/importar.py --agenda roles --fontes fontes_roles.json`. Só lê iCal ou JSON-LD, e só de fonte cujo `robots.txt` e termos deixam. **InterNations não se importa:** é só para membros. Quem for membro sugere o encontro pela issue, com a agenda Rolês.

## Tags e filtros

- `data/tags.json` define as tags (em PT, EN e Portunhol) e os filtros por intenção: «Sou dev», «Quero investir», «Tenho startup», etc.
- Para criar uma tag nova, adicione-a lá no mesmo PR.

## Antes do PR

```bash
python3 scripts/validar.py
python3 -m unittest discover -s scripts
```
