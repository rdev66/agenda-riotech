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

## Tags e filtros

- `data/tags.json` define as tags (em PT, EN e Portunhol) e os filtros por intenção: «Sou dev», «Quero investir», «Tenho startup», etc.
- Para criar uma tag nova, adicione-a lá no mesmo PR.

## Antes do PR

```bash
python3 scripts/validar.py
python3 -m unittest discover -s scripts
```
