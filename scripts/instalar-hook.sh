#!/bin/sh
# Instala el guardián anti-secretos en este clon del repositorio.
#   bash scripts/instalar-hook.sh
raiz=$(git rev-parse --show-toplevel) || { echo "No estas dentro de un repositorio git."; exit 1; }
cp "$raiz/scripts/pre-commit" "$raiz/.git/hooks/pre-commit"
chmod +x "$raiz/.git/hooks/pre-commit"
echo "Guardian instalado en .git/hooks/pre-commit"
echo "Cada commit se revisara automaticamente antes de guardarse."
