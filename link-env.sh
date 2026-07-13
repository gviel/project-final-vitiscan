#!/usr/bin/env bash
# Centralise les .env réels (non commités, cf. .gitignore) dans ~/.vitiscan/ et les remplace ici
# par des symlinks - évite de perdre ou de faire diverger ces fichiers entre plusieurs worktrees
# Git (chacun a sa propre copie de travail, mais un seul jeu de fichiers réels doit exister).
#
# Idempotent : relançable dans n'importe quel worktree (actuel ou futur). Si ~/.vitiscan/<chemin>
# existe déjà, ce worktree est simplement (re)lié dessus (un fichier réel local préexistant est
# sauvegardé en <chemin>.bak.<timestamp>, jamais écrasé silencieusement). Sinon, si ce worktree a
# le fichier réel, il devient la version canonique dans ~/.vitiscan/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CENTRAL="$HOME/.vitiscan"
mkdir -p "$CENTRAL"
chmod 700 "$CENTRAL"

# Un chemin par fichier .env.template suivi par Git (cf. .env.template dans chacun de ces dossiers).
PATHS=(
    ".env"
    "api/.env"
    "ui/.env"
    "labeling/.env"
    "rag-llm/.env.dev"
    "airflow/.env"
    "training/.env"
)

for path in "${PATHS[@]}"; do
    central="$CENTRAL/$path"

    if [ -e "$central" ]; then
        if [ -L "$path" ]; then
            rm "$path"
        elif [ -e "$path" ]; then
            backup="${path}.bak.$(date +%Y%m%d%H%M%S)"
            mv "$path" "$backup"
            echo "existant sauvegardé : $path -> $backup"
        fi
        mkdir -p "$(dirname "$path")"
        ln -s "$central" "$path"
        echo "lié : $path -> $central"
    elif [ -e "$path" ] && [ ! -L "$path" ]; then
        mkdir -p "$(dirname "$central")"
        mv "$path" "$central"
        chmod 600 "$central"
        ln -s "$central" "$path"
        echo "centralisé : $path -> $central (nouvelle référence canonique)"
    else
        echo "ignoré : $path (ni fichier local, ni référence déjà centralisée)"
    fi
done
