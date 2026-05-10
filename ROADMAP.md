# Roadmap — WSL Manager Pro

Guía de ejecución por fases para las mejoras de arquitectura, diseño y producto. Cada bloque es un **issue** autocontenido: título + **criterios de aceptación** verificables. El orden dentro de una fase respeta dependencias lógicas.

**Convenciones**

- Al cerrar un issue, la app debe seguir arrancando y las funciones existentes deben comportarse igual salvo que el issue diga explícitamente un cambio de UX.
- Los criterios usan lenguaje testable (“existe”, “pasa”, “no rompe”, “documentado en …”).

---

## Fase A — Estructura UI y estilos (fundación sin cambiar comportamiento)

### A1. Extraer pestaña Dashboard a módulo propio

**Título:** `refactor(ui): extraer DashboardTab a ui/tabs/dashboard_tab.py`

**Criterios de aceptación**

- [ ] Existe un widget (p. ej. `DashboardTab`) que encapsula la tabla de distros, barra superior (título, contador, Refresh, Re-scan User Status) y la conexión al menú contextual.
- [ ] `MainWindow` instancia `DashboardTab` y delega en él la construcción de la UI del primer tab; no queda código duplicado de esa pestaña en `main_window.py`.
- [ ] Tras instalar/importar/exportar/unregister como hoy, la tabla y el menú contextual siguen funcionando igual.
- [ ] La señal o callback necesaria para que `MainWindow` lance `RefreshWorker` / `UserStatusProbeWorker` está documentada en docstring del widget hijo.

---

### A2. Extraer pestaña Manage a módulo propio

**Título:** `refactor(ui): extraer ManageTab a ui/tabs/manage_tab.py`

**Criterios de aceptación**

- [ ] `ManageTab` contiene Import/Export, Quick Actions y todos los botones que hoy vive en `_build_manage_tab`.
- [ ] `MainWindow` solo conecta señales o métodos públicos del tab (p. ej. `import_requested`, `export_requested`) sin duplicar layouts.
- [ ] Import manual, export, quick actions, deep clean y botones de repair visibles/ocultos se comportan igual que antes del refactor.

---

### A3. Extraer pestaña Settings a módulo propio

**Título:** `refactor(ui): extraer SettingsTab a ui/tabs/settings_tab.py`

**Criterios de aceptación**

- [ ] `SettingsTab` agrupa directorios por defecto, spinboxes de `.wslconfig` y botones Save / Apply.
- [ ] Guardar y aplicar `.wslconfig` producen el mismo `config.json` y mismo contenido en `%USERPROFILE%\.wslconfig` que antes para mismos valores de UI.
- [ ] `MainWindow` no contiene formularios inline de Settings duplicados.

---

### A4. Mover QSS oscuro a archivo externo y cargarlo en arranque

**Título:** `refactor(ui): externalizar tema oscuro a resources/styles/dark.qss`

**Criterios de aceptación**

- [ ] Existe `resources/styles/dark.qss` (o ruta equivalente bajo el repo) con el contenido equivalente al stylesheet actual de `main.py`.
- [ ] `main.py` carga el QSS desde disco (o desde `importlib.resources` si se empaqueta) y llama a `app.setStyleSheet(...)`; no queda un bloque masivo de QSS embebido en string multilínea en `main.py`.
- [ ] Visualmente la app es equivalente (mismas familias de widgets cubiertas: ventana, tabs, tabla, botones, inputs, statusbar, etc.).
- [ ] Si falta el archivo, la app arranca con un fallback documentado (stylesheet mínimo o log de advertencia).

---

### A5. Delgazar `MainWindow`: solo composición y cableado

**Título:** `refactor(ui): MainWindow como compositor de tabs + log + toolbar`

**Criterios de aceptación**

- [ ] `main_window.py` no supera un umbral acordado (p. ej. menos de 800 líneas) o, si aún es mayor, incluye un comentario de cabecera con plan residual y lista de métodos que aún deben migrarse.
- [ ] Toolbar, status bar, splitter, consola de log y registro de workers permanecen centralizados en `MainWindow` o en un único `MainLayoutBuilder` documentado.
- [ ] No hay regresión en: timer de auto-refresh, `closeEvent`, lista `_active_workers`.

---

## Fase B — Tooling, calidad y tests de núcleo

### B1. Añadir `pyproject.toml` y alinear dependencias

**Título:** `chore: pyproject.toml con proyecto, deps y extras dev`

**Criterios de aceptación**

- [ ] Existe `pyproject.toml` con nombre del proyecto, versión alineada con `main.py` (o fuente única de verdad documentada), Python requerido, y dependencias equivalentes a `requirements.txt`.
- [ ] Extra opcional `[project.optional-dependencies] dev` incluye al menos: `pytest`, `pytest-qt` (opcional), `ruff`.
- [ ] `pip install -e ".[dev]"` instala la app editable y dev tools, o está documentado el comando equivalente en `REDME.md` / README principal del repo.

---

### B2. Configurar Ruff (lint + format opcional)

**Título:** `chore: configurar Ruff y corregir issues en core/utils`

**Criterios de aceptación**

- [ ] Archivo de configuración Ruff en repo (en `pyproject.toml` o `ruff.toml`).
- [ ] `ruff check core utils` pasa en CI o local sin errores en carpetas acordadas.
- [ ] `ui/` puede quedar excluido temporalmente con justificación en comentario del config, o incluido si ya pasa.

---

### B3. Tests unitarios para parsers de salida WSL

**Título:** `test(core): fixtures para wsl --list --verbose y --online`

**Criterios de aceptación**

- [ ] Tras extraer parsers a funciones puras (ver Fase H / issue H1) **o** testeando métodos públicos con mocks de `_run`, existen tests que cubren: tabla en inglés, BOM, y al menos un caso de cabecera localizada (p. ej. español) sin falsos positivos.
- [ ] Tests para `list_online_distros` con salida mínima válida.
- [ ] `pytest` ejecuta en verde sin requerir `wsl.exe` en el agente CI.

---

### B4. Tests para `DownloadManager` (checksum + resume simulado)

**Título:** `test(core): DownloadManager con httmock o servidor local`

**Criterios de aceptación**

- [ ] Test de verificación de checksum correcto / incorrecto.
- [ ] Test de reanudación con `Range` usando respuestas HTTP simuladas (206/200) o mock de `requests`.
- [ ] Sin red externa obligatoria para CI.

---

### B5. CI mínimo (GitHub Actions u otro)

**Título:** `ci: workflow lint + pytest en push/PR`

**Criterios de aceptación**

- [ ] Workflow que instala deps, ejecuta `ruff check` y `pytest`.
- [ ] Rama principal / PRs fallan si rompe lint o tests.
- [ ] Documentado en README del repo cómo reproducir localmente.

---

## Fase C — Observabilidad y soporte

### C1. Logging estándar duplicado a archivo + UI

**Título:** `feat(obs): logging Python + handler hacia consola Qt`

**Criterios de aceptación**

- [ ] Se usa el módulo `logging` con niveles INFO/WARNING/ERROR.
- [ ] Handler personalizado o `QObject` que añade líneas al `QTextEdit` existente sin perder el formato actual de `_log` (o wrapper documentado).
- [ ] Handler `RotatingFileHandler` (o similar) escribe bajo `%LOCALAPPDATA%\WSLManagerPro\logs\` (o ruta documentada), con rotación por tamaño o fecha.
- [ ] Ningún secret (contraseñas) se escribe en log en flujos normales.

---

### C2. Acción “Exportar paquete de diagnóstico”

**Título:** `feat(obs): botón export diagnostic bundle (zip)`

**Criterios de aceptación**

- [ ] Desde la UI (Settings o menú Ayuda) un botón genera un ZIP con: versión de la app, últimas N líneas de log (configurable), salida de `wsl --version` y `wsl --status` si WSL está disponible.
- [ ] El ZIP excluye por defecto contraseñas y rutas marcadas como sensibles, o documenta qué incluye.
- [ ] Si un comando falla, el ZIP aún se crea con nota de error en un `README.txt` dentro del bundle.

---

## Fase D — Datos robustos y configuración versionada

### D1. Validación de esquema para `config.json`

**Título:** `feat(config): modelo tipado + migración schema_version`

**Criterios de aceptación**

- [ ] Al cargar `config.json`, valores inválidos producen mensaje claro al usuario o fallback seguro documentado (no silencio total).
- [ ] Campo `schema_version` entero; al añadir campos nuevos, migración trivial documentada (función `migrate_v1_to_v2` o similar).
- [ ] `ConfigManager.save()` solo persiste datos que pasan validación.

---

### D2. Validación de entradas de `distros.json`

**Título:** `feat(catalog): validar distros.json al arranque`

**Criterios de aceptación**

- [ ] Cada entrada del catálogo estático se valida contra reglas (campos obligatorios según `install_method`, `extract_type` permitidos, URLs no vacías cuando aplica).
- [ ] Entrada inválida: se omite con log WARNING que indica la clave; el resto del catálogo sigue disponible.
- [ ] Tests unitarios con JSON mínimo válido e inválido.

---

### D3. Catálogo remoto opcional con fallback local

**Título:** `feat(catalog): URL opcional de distros.json remoto + firma o timeout`

**Criterios de aceptación**

- [ ] Nuevo campo en config (o settings UI): URL del catálogo remoto; vacío = solo local.
- [ ] Descarga con timeout corto; fallo → uso de `distros.json` embebido/local sin crash.
- [ ] (Opcional fase 2 del mismo issue) verificación de hash/firma si se define mecanismo; si no, documentado como “sin verificación, uso bajo responsabilidad del usuario”.
- [ ] Criterio de aceptación mínimo sin firma: comportamiento anterior reproducible con URL vacía.

---

## Fase E — Privilegios, winget y motor

### E1. Modo “solo lectura” sin administrador (opcional)

**Título:** `feat(security): permitir arranque limitado sin UAC cuando el usuario elija`

**Criterios de aceptación**

- [ ] Primer arranque o setting persistente: “Ejecutar con privilegios elevados (recomendado)” vs “Modo limitado”.
- [ ] En modo limitado: no se relanza `runas`; operaciones que requieren admin (import, dism, winget, escritura en rutas protegidas) aparecen deshabilitadas con tooltip explicativo.
- [ ] Listar distros, abrir shells y refrescar siguen intentándose si `wsl.exe` funciona sin admin.
- [ ] Documentación en README/REDME del trade-off.

---

### E2. Cablear `winget_id` desde el catálogo a flujo UI

**Título:** `feat(install): opción instalar distro vía winget usando winget_id`

**Criterios de aceptación**

- [ ] Si la entrada del catálogo tiene `winget_id` no nulo, el wizard o Manage ofrece acción “Instalar con winget” (o paso opcional en el wizard).
- [ ] Reutiliza `WslEngine.install_via_winget` y muestra salida en la consola de log como otras operaciones largas.
- [ ] Si winget no está disponible, mensaje de error claro sin colgar la UI (worker en hilo de fondo).
- [ ] No elimina el flujo actual por rootfs/WSL online.

---

### E3. Constantes centralizadas de timeouts y reintentos

**Título:** `refactor(core): constants.py para timeouts WSL/descargas`

**Criterios de aceptación**

- [ ] Valores como timeouts de import/export, `UserStatusProbeWorker`, `DownloadManager.MAX_RETRIES` viven en un solo módulo o clase de configuración estática.
- [ ] Comportamiento numérico por defecto idéntico al actual salvo decisión explícita documentada en el issue.

---

### E4. Contrato unificado de cancelación en workers

**Título:** `refactor(workers): CancellableWorker + cancel() coherente`

**Criterios de aceptación**

- [ ] Workers largos (`InstallWorker`, `PostInstallWorker`, `DownloadWorker`) implementan interfaz o clase base común con `cancel()` documentada.
- [ ] Documentación en docstring de qué tan “rápida” es la cancelación (entre chunks, entre pasos).
- [ ] Botón Cancel en wizard corta descarga y post-install sin dejar proceso huérfano en casos normales.

---

## Fase F — Producto y experiencia avanzada

### F1. Sistema de diseño mínimo (tokens de color)

**Título:** `feat(ui): paleta centralizada para QSS y colores de log`

**Criterios de aceptación**

- [ ] Archivo Python o fragmento QSS comentado con variables de color usadas por la app.
- [ ] Colores hardcodeados en `_log(..., color=...)` se reducen a constantes con nombre (`COLOR_ERROR`, etc.).
- [ ] Sin cambio visual intencional; solo centralización.

---

### F2. Estados vacíos y onboarding WSL ausente

**Título:** `feat(ui): empty state cuando no hay distros o WSL no encontrado`

**Criterios de aceptación**

- [ ] Si `WslNotFoundError` o lista vacía: widget o panel con texto accionable (enlaces a docs Microsoft / pasos “habilitar WSL”) en lugar de solo línea en log.
- [ ] Botón “Reintentar detección” que vuelve a intentar crear `WslEngine`.

---

### F3. Mejoras de consola de log (filtro + copiar)

**Título:** `feat(ui): filtro de texto y copiar selección en consola de log`

**Criterios de aceptación**

- [ ] Campo de búsqueda o filtro que oculta/resalta líneas que no coinciden (implementación mínima aceptable).
- [ ] Acción “Copiar todo” o “Copiar selección” al portapapeles.
- [ ] No degrada rendimiento con logs de varios miles de líneas (documentar límite o virtualización si aplica).

---

### F4. Perfiles de instalación reutilizables (JSON)

**Título:** `feat(install): guardar/cargar perfil de paquetes y opciones post-install`

**Criterios de aceptación**

- [ ] El usuario puede exportar un JSON con: lista extra de paquetes, flags systemd, nombre sugerido de usuario (sin contraseña en claro en disco; si se guarda contraseña, cifrado OS o advertencia explícita y deshabilitado por defecto).
- [ ] Importar perfil rellena el wizard donde corresponda.
- [ ] Formato de archivo versionado (`profile_version`).

---

### F5. Abrir distro en Windows Terminal (`wt.exe`)

**Título:** `feat(ui): “Abrir en Windows Terminal” cuando wt.exe exista`

**Criterios de aceptación**

- [ ] Menú contextual o botón que lanza `wt.exe` con perfil o comando documentado para la distro seleccionada.
- [ ] Si `wt` no está instalado, mensaje informativo sin error no controlado.

---

### F6. Campos avanzados de `.wslconfig` en UI (plegable)

**Título:** `feat(settings): sección avanzada .wslconfig (localhostForwarding, vmIdleTimeout, …)`

**Criterios de aceptación**

- [ ] Grupo colapsable “Avanzado” con al menos dos campos nuevos respecto al estado actual, documentados con tooltip y enlace a docs Microsoft.
- [ ] `WslEngine.generate_wslconfig` extiende el archivo sin borrar claves desconocidas **o** documenta que sobrescribe completo y muestra preview antes de guardar (elegir una estrategia y cumplirla en tests manuales descritos en el issue).

---

## Fase G — Empaquetado y distribución (post‑estabilidad)

### G1. Build reproducible (PyInstaller o equivalente)

**Título:** `build: artefacto ejecutable Windows one-folder o one-file`

**Criterios de aceptación**

- [ ] Script o job CI que genera ejecutable que incluye `distros.json` y `dark.qss`.
- [ ] README con tamaño aproximado y antivirus false-positive note si aplica.
- [ ] Arranque smoke test documentado (manual o automatizado).

---

### G2. Comprobación de actualizaciones (solo notificación)

**Título:** `feat(meta): comprobar último release en GitHub y mostrar banner`

**Criterios de aceptación**

- [ ] Llamada HTTP opcional deshabilitada por defecto o con opt-in en Settings.
- [ ] No bloquea arranque; fallo de red silencioso o log DEBUG.
- [ ] Enlace abre el navegador en la release.

---

## Fase H — Refactor motor (cuando B3 lo desbloquee o en paralelo controlado)

### H1. Extraer parsers puros de `WslEngine`

**Título:** `refactor(core): wsl_list_parser.py con funciones puras`

**Criterios de aceptación**

- [ ] `parse_list_verbose(stdout: str) -> list[DistroInfo]` (o equivalente) sin I/O.
- [ ] `parse_list_online(stdout: str) -> list[OnlineDistro]`.
- [ ] `WslEngine` delega en estos parsers; tests de B3 apuntan aquí.
- [ ] Comportamiento idéntico en casos cubiertos por tests + prueba manual rápida en máquina con WSL.

---

### H2. Cola o mutex de operaciones largas mutuamente excluyentes

**Título:** `feat(ui): evitar instalaciones/import concurrentes`

**Criterios de aceptación**

- [ ] Si una instalación está en curso, segunda acción muestra mensaje no modal o deshabilita botones con explicación.
- [ ] Estado visible en status bar (“Operación en curso: …”).

---

### H3. Evaluación incremental de `QProcess` vs `subprocess` para streaming

**Título:** `spike(core): QProcess para install_online o winget con misma UX de log`

**Criterios de aceptación**

- [ ] Documento corto `docs/adrs/0001-qprocess-vs-subprocess.md` con decisión: adoptar / no adoptar y motivos.
- [ ] Si se adopta en un flujo: mismo formato de líneas en log que antes; cancelación igual o mejor.

---

## Orden de ejecución recomendado

1. **A1 → A2 → A3 → A4 → A5** (refactor UI incremental; commits pequeños por issue).
2. **B1 → B2 → B3/B4** (tooling y tests; B3 puede requerir **H1** primero — en ese caso hacer **H1** justo antes de B3 o dividir B3 en “tests con mocks de `_run`” primero y “tests de parser puro” después).
3. **B5** en cuanto haya un test mínimo verde.
4. **C1 → C2**.
5. **D1 → D2 → D3** (D3 puede ser último de la fase D).
6. **E3 → E4** en paralelo a D si hay capacidad; **E1** y **E2** tras estabilizar config (D1).
7. **F1–F6** según prioridad de producto.
8. **G1–G2** cuando la app esté estable en main.
9. **H2 → H3** cuando el refactor UI esté asentado.

---

## Leyenda de dependencias cruzadas

| Issue | Depende de |
|-------|------------|
| B3 (tests parsers) | Idealmente **H1**; alternativa: mocks de `_run` sin extraer parser aún |
| A5 | A1, A2, A3 (y idealmente A4) |
| C2 | C1 recomendado |
| D3 | D1 |
| E2 | D2 útil para validar `winget_id` en JSON |
| F6 | A4 + posible extensión de `WslEngine.generate_wslconfig` |

---

*Última actualización: alineado al informe de mejoras (estructura, diseño, observabilidad, datos, motor, producto, empaquetado). Ajusta numeración de fases si fusionas issues en un solo PR.*
