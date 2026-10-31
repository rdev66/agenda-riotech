#!/usr/bin/env bash
# Importa links de eventos de um export do WhatsApp e abre um PR.
# Uso: scripts/semanal.sh ~/Downloads/riotech-export/_chat.txt
set -euo pipefail

# git switch main troca o arquivo debaixo dos pés se esta cópia ainda não está na main.
if [[ -z "${AGENDA_SEMANAL_COPIA:-}" ]]; then
  raiz="$(cd "$(dirname "$0")/.." && pwd)"
  copia="$(mktemp)"
  cp "$0" "$copia"
  export AGENDA_SEMANAL_COPIA=1
  export AGENDA_RAIZ="$raiz"
  exec bash "$copia" "$@"
fi

trap 'rm -f "$0"' EXIT
cd "$AGENDA_RAIZ"

if [[ $# -ne 1 ]]; then
  echo "Uso: scripts/semanal.sh ~/Downloads/riotech-export/_chat.txt" >&2
  exit 2
fi

chat=$1
if [[ ! -f "$chat" ]]; then
  echo "Arquivo não encontrado: $chat" >&2
  exit 2
fi

git switch main
git pull --ff-only

leitura=$(python3 - <<'PY'
import datetime as d
from zoneinfo import ZoneInfo
hoje = d.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
print(hoje.isoformat())
print((hoje - d.timedelta(days=14)).isoformat())
PY
)
data=$(printf '%s\n' "$leitura" | sed -n '1p')
desde=$(printf '%s\n' "$leitura" | sed -n '2p')

log=$(python3 scripts/importar.py --whatsapp "$chat" --desde "$desde" --dry-run)
printf '%s\n' "$log"
if ! printf '%s\n' "$log" | grep -Eq '(novo|completado): [1-9][0-9]*'; then
  echo "Nada novo. Não criei a rama."
  exit 0
fi

rama="importador/whatsapp-$data"
if git show-ref --verify --quiet "refs/heads/$rama"; then
  echo "A rama $rama já existe. Não continuei." >&2
  exit 1
fi

git switch -c "$rama"
python3 scripts/importar.py --whatsapp "$chat" --desde "$desde"
python3 scripts/validar.py

git add -- data/events.json
if git diff --cached --name-only | grep -q '_chat.txt'; then
  echo "Abortado: _chat.txt está no stage." >&2
  exit 1
fi
outros=$(git diff --cached --name-only | grep -v '^data/events.json$' || true)
if [[ -n "${outros}" ]]; then
  echo "Abortado: só data/events.json pode entrar no commit." >&2
  printf '%s\n' "$outros" >&2
  exit 1
fi
if git diff --cached --quiet; then
  echo "Nada novo. Não criei a rama."
  git switch main
  git branch -D "$rama"
  exit 0
fi

git commit -m "Importa eventos do WhatsApp ($data)."
git push -u origin "$rama"
gh pr create --title "Eventos do WhatsApp ($data)" --body "Importação do chat do grupo (links de eventos, desde $desde).

Para descartar um evento, acrescente a URL dele em data/descartados.json neste mesmo PR."
