"""Local config (opcional). Copia este archivo a settings.py y ajusta.

    cp settings.example.py settings.py

settings.py está gitignoreado, así que tus valores no se versionan.
También puedes usar la variable de entorno PR_DASHBOARD_ORG (tiene prioridad).
"""

# Filtra las PRs por esta organización de GitHub.
# Déjalo en "" (o borra la línea) para ver tus PRs de todos tus repos.
ORG = "YOUR_ORG"
