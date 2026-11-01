#!/usr/bin/env bash
# Importa links de eventos de um export do WhatsApp e abre um PR.
# Uso:
#   scripts/semanal.sh            pega o export mais novo do grupo em ~/Downloads
#   scripts/semanal.sh EXPORT     usa um export específico (.zip do WhatsApp ou _chat.txt)
#   scripts/semanal.sh --onde     só mostra qual export usaria; não mexe no git
# Variáveis opcionais:
#   AGENDA_DOWNLOADS   pasta onde procurar (padrão: ~/Downloads)
#   AGENDA_MAX_DIAS    idade máxima do export antes de perguntar (padrão: 2)
#   AGENDA_ABRIR_PR=1  abre o PR no navegador no fim
# Compatível com o bash 3.2 do macOS.
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

copia_script=$0
chat=""
limpar() {
  rm -f "$copia_script"
  if [[ -n "$chat" ]]; then rm -f "$chat"; fi
}
trap limpar EXIT
cd "$AGENDA_RAIZ"

uso="Uso: scripts/semanal.sh [--onde | EXPORT.zip | _chat.txt]"
so_onde=0
origem=""
case $# in
  0) ;;
  1)
    case $1 in
      --onde) so_onde=1 ;;
      -h|--help) echo "$uso"; exit 0 ;;
      *) origem=$1 ;;
    esac
    ;;
  *) echo "$uso" >&2; exit 2 ;;
esac

# O _chat.txt vai para um temporário fora do repositório e é apagado no fim.
chat="$(mktemp)"
chmod 600 "$chat"
info=$(python3 - "$chat" "$origem" <<'PY'
import datetime as d
import os
import sys
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

destino, origem = sys.argv[1], sys.argv[2]
LIMITE = 50 * 1024 * 1024  # um _chat.txt sem mídia tem poucos MB


def do_grupo(nome):
    nome = nome.lower().replace(" ", "")
    return "whatsapp" in nome and "riotech" in nome


def candidatos(pasta):
    achados = []
    if not pasta.is_dir():
        return achados
    for p in pasta.iterdir():
        if not do_grupo(p.name):
            continue
        if p.is_file() and p.suffix.lower() == ".zip":
            achados.append(p)
        elif p.is_dir() and (p / "_chat.txt").is_file():
            achados.append(p / "_chat.txt")
    solto = pasta / "riotech-export" / "_chat.txt"
    if solto.is_file():
        achados.append(solto)
    return achados


if origem:
    escolhido = Path(origem).expanduser()
    if not escolhido.is_file():
        sys.exit(f"Arquivo não encontrado: {escolhido}")
else:
    pasta = Path(os.environ.get("AGENDA_DOWNLOADS") or Path.home() / "Downloads").expanduser()
    achados = candidatos(pasta)
    if not achados:
        sys.exit(
            f"Não achei nenhum export do grupo RioTech em {pasta}.\n"
            "No WhatsApp: grupo › Exportar conversa › Sem mídia, e salve em Downloads."
        )
    escolhido = max(achados, key=lambda p: p.stat().st_mtime)

if escolhido.suffix.lower() == ".zip":
    with zipfile.ZipFile(escolhido) as z:
        membros = [m for m in z.infolist() if Path(m.filename).name == "_chat.txt"]
        if len(membros) != 1:
            sys.exit(f"O zip não tem um único _chat.txt: {escolhido}")
        if membros[0].file_size > LIMITE:
            sys.exit(f"_chat.txt grande demais ({membros[0].file_size} bytes): {escolhido}")
        dados = z.read(membros[0])
else:
    if escolhido.stat().st_size > LIMITE:
        sys.exit(f"Arquivo grande demais: {escolhido}")
    dados = escolhido.read_bytes()

with open(destino, "wb") as f:
    f.write(dados)

fuso = ZoneInfo("America/Sao_Paulo")
quando = d.datetime.fromtimestamp(escolhido.stat().st_mtime, fuso)
idade = (d.datetime.now(fuso) - quando).total_seconds() / 86400
print(escolhido)
print(quando.strftime("%d/%m/%Y %H:%M"))
print(f"{idade:.1f}")
print(dados.count(b"\n"))
PY
)
escolhido=$(printf '%s\n' "$info" | sed -n '1p')
quando=$(printf '%s\n' "$info" | sed -n '2p')
idade=$(printf '%s\n' "$info" | sed -n '3p')
linhas=$(printf '%s\n' "$info" | sed -n '4p')
echo "Export: $escolhido"
echo "Exportado em $quando (há $idade dias), $linhas linhas."

if [[ $so_onde -eq 1 ]]; then
  exit 0
fi

max_dias=${AGENDA_MAX_DIAS:-2}
if python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > float(sys.argv[2]) else 1)' "$idade" "$max_dias"; then
  if [[ -t 0 ]]; then
    read -r -p "Este export tem mais de $max_dias dias. Usar mesmo assim? [s/N] " resposta
    case $resposta in
      s|S|sim|Sim|SIM) ;;
      *) echo "Exporte a conversa de novo e rode outra vez."; exit 1 ;;
    esac
  else
    echo "Este export tem mais de $max_dias dias. Exporte a conversa de novo." >&2
    exit 1
  fi
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
url=$(gh pr create --title "Eventos do WhatsApp ($data)" --body "Importação do chat do grupo (links de eventos, desde $desde).

Para descartar um evento, acrescente a URL dele em data/descartados.json neste mesmo PR.")
echo "$url"
if [[ "${AGENDA_ABRIR_PR:-}" == "1" ]] && command -v open >/dev/null 2>&1; then
  open "$url"
fi
