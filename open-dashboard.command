#!/bin/bash
# Doble-click en Finder: regenera el dashboard con datos frescos y lo abre en el navegador.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "Actualizando PRs..."
if /usr/bin/python3 build.py; then
    open "dashboard.html"
else
    echo "Fallo el build (revisa que 'gh' esté autenticado)."
    read -r -p "Enter para cerrar..."
fi
