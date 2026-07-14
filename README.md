# PR Dashboard

Dashboard personal de tus **Pull Requests abiertas** en GitHub. Genera un HTML
estático y autocontenido a partir de los datos que trae `gh`, sin servidor y sin
enviar nada a terceros: todo corre local con tu propio token de `gh`.

![tipo](https://img.shields.io/badge/tipo-herramienta_local-blueviolet)
![costo](https://img.shields.io/badge/costo-%240_/_sin_tokens-green)

---

## Qué muestra

- **KPIs**: abiertas, requiere mi acción, listas para merge, esperan review,
  CI en rojo, con conflictos, necesita rebase.
- **Triage "requiere mi acción"**: clasifica de quién es el turno — tu turno si
  hay CI en rojo, conflictos, branch detrás de base, cambios pedidos, comentarios
  sin resolver, o está lista para mergear; si solo falta review, es turno de otros.
  Se ve como tag `⚡ Tu turno: <motivo>` y ordena por atención.
- **Tarjetas** por PR con estado de CI, review, tamaño, antigüedad y branches.
- **Filtros** combinables: base (`master`/`development`/…/`stacked`), estado
  (requiere mi acción / sin aprobar / aprobado / con conflicto / necesita rebase)
  y grupos custom por nombre de repo.
- **Comentarios sin resolver**: panel desplegable + modal con el comentario
  completo renderizado en markdown y link directo a GitHub.
- **Suggested reviewers** (solo en PRs no aprobadas): top 6 contribuyentes del
  repo + los que sugiere GitHub.
- **Vista de stacks**: reconstruye el árbol de PRs apiladas (`base == head`).

---

## Requisitos

- **macOS** (para el auto-refresh vía `launchd`).
- **`gh`** (GitHub CLI) instalado y autenticado: `gh auth status` debe estar OK.
- **`python3`** (el de sistema, `/usr/bin/python3`, basta).

---

## Cómo se usa (día a día)

Los datos están "horneados" en el HTML, así que para ver info nueva hay que
**regenerar** el archivo. Hay un modo servidor (recomendado) y modos sin servidor.

### 1. Servidor local con botón (recomendado)
Un agente `launchd` mantiene vivo `server.py` en `http://127.0.0.1:8787`
(solo localhost = privado). Abre y guarda como bookmark:

```
http://localhost:8787/
```

Desde ahí tienes el botón **"↻ Actualizar"**: dispara el rebuild, muestra el
progreso en vivo y recarga solo al terminar (~50s). Además el server
**auto-refresca cada 30 min en horario laboral** (L–V 09:00–18:30). No necesitas
tener nada abierto para que se mantenga fresco.

### 2. Alias en la terminal
```bash
prdash          # regenera con datos frescos y lo abre (file://)
prdash-build    # solo regenera (sin abrir)
```
> Los alias viven en `~/.zshrc`.

### 3. Doble-click
Abre `open-dashboard.command` desde Finder → refresca y abre el archivo local.

> El botón "↻ Actualizar" **solo aparece servido por http** (modo 1). Si abres el
> archivo como `file://` (modos 2 y 3), el botón se oculta porque no hay server
> que atienda el `/refresh`.

---

## Arquitectura

```
navegador ──HTTP──▶ server.py (127.0.0.1:8787, launchd KeepAlive)
                       │  GET /            → sirve dashboard.html
                       │  POST /refresh    → dispara build en background
                       │  GET /status      → progreso (JSON, para el botón)
                       │  + auto-refresh cada 30 min en horario laboral
                       ▼
                    build.py  ──gh──▶ GitHub API  → escribe dashboard.html (atómico)
```

Sin dependencias: todo con la stdlib de Python y `gh`.

---

## Archivos

| Archivo | Qué es |
|---|---|
| `server.py` | Servidor local (localhost:8787): sirve el HTML, `/refresh`, `/status` y auto-refresh. |
| `build.py` | Genera el HTML: consulta `gh`, arma los datos y escribe `dashboard.html` (atómico). |
| `template.html` | Plantilla base (CSS + JS + botón + placeholders `__PR_DATA__` / `__GENERATED_AT__`). |
| `dashboard.html` | **El dashboard.** Se regenera en cada build. |
| `open-dashboard.command` | Doble-click: refresca + abre en modo `file://`. |
| `settings.example.py` | Plantilla de config local (org). Copiar a `settings.py` (gitignoreado). |
| `com.toku.pr-dashboard.plist` | Template del agente `launchd` (reemplaza `YOUR_USERNAME`). |
| `server.log` | Salida del server y de los builds (con tiempos). |
| `README.md` | Este archivo. |

El agente se instala en `~/Library/LaunchAgents/com.toku.pr-dashboard.plist`.

---

## Logs y tiempos

Cada corrida imprime checkpoints con tiempos:
```
[   0.0s] inicio
[   0.6s] usuario: <tu-usuario-gh>
[   4.1s] PRs abiertas encontradas: 17 (3.4s)
[  50.9s] PRs enriquecidas: 17 (46.9s)
[  50.9s] HTML escrito: 121,275 bytes (0.0s)
[  50.9s] desglose de llamadas a gh:
[  50.9s]     · gh pr view: 22.2s en 17 llamadas
[  50.9s]     · gh api graphql (threads+reviewers): 18.8s en 17 llamadas
[  50.9s]     · gh api contributors: 5.9s en 8 llamadas
[  50.9s] LISTO — 17 PRs en 50.9s totales
```
Casi todo el tiempo se va en las llamadas secuenciales a `gh` (~50s). El render
del HTML es instantáneo.

---

## Cómo lo usaría otra persona

El generador usa `--author=@me`, así que **automáticamente apunta a quien esté
autenticado en `gh`** — no hay que cambiar el usuario. Pasos para adoptarlo en
otro Mac:

1. **Requisitos**: `gh auth status` OK, `python3` disponible, macOS.

2. **Clonar el repo** a una ruta *fuera* de `~/Documents`, `~/Desktop` o
   `~/Downloads` (macOS bloquea el acceso de agentes en segundo plano a esas
   carpetas). Ubicación recomendada:
   ```bash
   git clone https://github.com/jvergara-sanguesa/pr-dashboard.git ~/Library/Application\ Support/pr-dashboard
   cd ~/Library/Application\ Support/pr-dashboard
   ```

3. **Config** (opcional): para filtrar por una org de GitHub,
   ```bash
   cp settings.example.py settings.py   # y edita ORG = "tu-org"
   ```
   Sin esto ves tus PRs de todos tus repos. `settings.py` está gitignoreado.

4. **Probar** (genera `dashboard.html` la primera vez):
   ```bash
   python3 build.py && open dashboard.html      # modo archivo
   # o el modo servidor con botón:
   python3 server.py    # luego abre http://localhost:8787/
   ```

5. **Instalar el servidor + auto-refresh** (recomendado): edita
   `com.toku.pr-dashboard.plist` **reemplazando `YOUR_USERNAME`** por tu usuario
   y ajustando el `PATH` de `gh`, cópialo y cárgalo:
   ```bash
   cp com.toku.pr-dashboard.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.toku.pr-dashboard.plist
   ```
   Deja `http://localhost:8787/` como bookmark. Listo: siempre fresco + botón ↻.

6. **Alias** (opcional) en tu `~/.zshrc` para refrescar desde la terminal:
   ```bash
   alias prdash='python3 "$HOME/Library/Application Support/pr-dashboard/build.py" && open "$HOME/Library/Application Support/pr-dashboard/dashboard.html"'
   ```

### Qué personalizar

- **Org**: crea tu `settings.py` (`cp settings.example.py settings.py`) y define
  `ORG = "tu-org"`, o usa la env var `PR_DASHBOARD_ORG`. Sin org configurada, ves
  tus PRs de todos tus repos. `settings.py` está gitignoreado.
- **Grupos custom**: en `template.html`, edita `const CUSTOM_GROUPS` (chips que
  filtran por substring en el nombre del repo).
- **Horario del auto-refresh**: en `build.py`, `within_work_hours()` (por defecto
  L–V 09:00–18:30). Lo usa el auto-refresh del server; los refresh manuales
  (botón ↻, `prdash`, doble-click) ignoran el horario.
- **Puerto**: en `server.py`, `PORT = 8787`.
- **Zona horaria del sello "generado"**: en `build.py`, `timezone(timedelta(hours=-4))`.
- **PATH de `gh`**: en el `.plist`, `EnvironmentVariables > PATH`. En Macs Intel
  `gh` suele estar en `/usr/local/bin`; en Apple Silicon en `/opt/homebrew/bin`.

---

## Administrar el agente launchd

```bash
# Pausar el auto-refresh
launchctl bootout gui/$(id -u)/com.toku.pr-dashboard

# Reactivar
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.toku.pr-dashboard.plist

# Ver estado
launchctl print gui/$(id -u)/com.toku.pr-dashboard
```

---

## Troubleshooting

- **`BUILD FAILED` / no genera nada** → revisa `gh auth status`. El generador no
  publica si `gh` no está autenticado o no hay red.
- **El agente no corre (`Operation not permitted` en `server.log`)** → la carpeta
  quedó dentro de `~/Documents`/`~/Desktop`/`~/Downloads` (protegidas por macOS).
  Muévela a `~/Library/Application Support/…` y recarga el agente.
- **Caracteres raros (`Â·`, `ðŸ§µ`)** → asegúrate de abrir `dashboard.html` (que
  ya trae `<meta charset="utf-8">`), no una versión vieja cacheada.
- **Tarda ~50s** → es normal: son ~34 llamadas secuenciales a `gh`. Se puede
  paralelizar para bajarlo a ~10-15s.

---

## Notas de privacidad

Todo es local: usa tu token de `gh`, corre en tu máquina y no manda datos a
ningún servicio externo. El HTML es estático y autocontenido (sin llamadas de red
en runtime).
