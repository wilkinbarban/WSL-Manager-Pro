# WSL Manager Pro

[![CI](https://github.com/wilkinbarban/WSL-Manager-Pro/actions/workflows/ci.yml/badge.svg)](https://github.com/wilkinbarban/WSL-Manager-Pro/actions/workflows/ci.yml)
[![Licença: GPL v3](https://img.shields.io/badge/Licença-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-green.svg)](https://pypi.org/project/PySide6/)

> 📖 Também disponível em: [English](README.md) · [Español](README_es.md)

Aplicativo de desktop para **Windows** que centraliza o gerenciamento do
**Subsistema Windows para Linux (WSL)**: listar distribuições, instalar a
partir do catálogo online ou de um rootfs baixado, importar/exportar,
provisionamento pós-instalação (conta de usuário, pacotes, `wsl.conf`),
limites de recursos via `.wslconfig` e utilitários de manutenção.

**Versão do aplicativo:** 1.0.0

---

## Índice

- [Requisitos do Sistema](#requisitos-do-sistema)
- [Tecnologias](#tecnologias)
- [Início Rápido](#início-rápido)
- [Estrutura do Repositório](#estrutura-do-repositório)
- [Como o Aplicativo é Executado](#como-o-aplicativo-é-executado)
- [Arquitetura e Fluxo de Dados](#arquitetura-e-fluxo-de-dados)
- [Módulos do Código](#módulos-do-código)
  - [Ponto de Entrada (`main.py`)](#ponto-de-entrada-mainpy)
  - [Pacote Core (`core/`)](#pacote-core-core)
  - [Pacote Utils (`utils/`)](#pacote-utils-utils)
  - [Pacote UI (`ui/`)](#pacote-ui-ui)
- [O Catálogo `distros.json`](#o-catálogo-distrosjson)
- [Configuração Persistente](#configuração-persistente)
- [Funcionalidades da Interface](#funcionalidades-da-interface)
- [Motor WSL (`WslEngine`)](#motor-wsl-wslengine)
- [Gerenciador de Downloads (`DownloadManager`)](#gerenciador-de-downloads-downloadmanager)
- [Threads de Trabalho (Qt)](#threads-de-trabalho-qt)
- [Internacionalização (i18n)](#internacionalização-i18n)
- [Observabilidade (Logging e Diagnóstico)](#observabilidade-logging-e-diagnóstico)
- [Privilégios e Segurança](#privilégios-e-segurança)
- [Build e Distribuição](#build-e-distribuição)
- [Desenvolvimento, Testes e CI](#desenvolvimento-testes-e-ci)
- [Roteiro](#roteiro)
- [Licença](#licença)

---

## Requisitos do Sistema

| Requisito | Detalhes |
|-----------|----------|
| **Sistema Operacional** | Windows 10 build 19041+ (suporte WSL 2) |
| **WSL** | `wsl.exe` acessível em `%SystemRoot%\System32\wsl.exe` |
| **PowerShell** | `pwsh.exe` (PS 7+) ou `powershell.exe` (PS 5.1) no PATH |
| **Python** | 3.10 ou superior (usa anotações de tipo modernas: `list[str]`, `dict[str, str]`) |
| **Permissões** | Privilégios de Administrador recomendados para operações WSL e winget. O app suporta modo limitado (somente leitura) se o usuário recusar a elevação. |

---

## Tecnologias

| Área | Tecnologia |
|------|------------|
| Linguagem | **Python 3.10+** |
| Framework GUI | **PySide6** (bindings oficiais Qt 6 para widgets) |
| Concorrência UI | **QThread** + sinais/slots Qt |
| Cliente HTTP | **requests** (downloads com streaming, retentativas e suporte Range) |
| Compressão | **zstandard** (bootstrap `.tar.zst` do Arch Linux — evita dependência do `tar --zstd` do sistema no Windows) |
| Formato de dados | **JSON** (`distros.json`, `config.json`, catálogos i18n) |
| Integração do sistema | **subprocess** (`wsl.exe`, PowerShell, winget); **ctypes** (elevação UAC); **zipfile** / **tarfile** (manipulação de arquivos) |
| Estilização | Tema escuro via QSS (`resources/styles/dark.qss`) |

---

## Início Rápido

### Instalador de Um Clique (Recomendado)

```powershell
.\install.ps1
```

Este script PowerShell totalmente automatizado provisiona todas as
dependências: habilita recursos WSL, instala Python 3.12 e Node.js LTS via
winget, cria um `.venv` e instala todas as dependências do projeto.

### Instalação Manual

```powershell
# 1. Criar e ativar um ambiente virtual
python -m venv .venv
.\.venv\Scripts\activate

# 2. Instalar dependências de execução
pip install -r requirements.txt

# 3. Executar o aplicativo
python main.py
```

### Instalação Editável (para Contribuidores)

```powershell
pip install -e ".[dev]"
```

Instala o projeto em modo editável com ferramentas de desenvolvimento
(pytest, ruff, pytest-qt).

---

## Estrutura do Repositório

```
WSL Manager Pro/
├── main.py                     # Ponto de entrada: path, elevação, QApplication, MainWindow
├── pyproject.toml              # Metadados, dependências, configuração ruff e pytest
├── requirements.txt            # Dependências de execução
├── distros.json                # Catálogo estático de distros (URLs, gerenciadores de pacotes, pós-install)
├── ROADMAP.md                  # Plano de desenvolvimento multifásico (150+ tarefas)
├── build.ps1                   # Gatilho de build PyInstaller (EXE único)
├── install.ps1                 # Instalador de ambiente de um clique
├── wsl_manager_pro.spec        # Arquivo spec do PyInstaller
├── wsl_manager_pro.rc          # Arquivo de recursos Windows (incorporação de ícone)
│
├── core/                       # Lógica de negócio
│   ├── __init__.py
│   ├── wsl_engine.py           # Fachada sobre wsl.exe, PowerShell, pós-install, .wslconfig
│   ├── wsl_list_parser.py      # Parsers puros para saída wsl --list (testáveis sem WSL)
│   ├── downloader.py           # Downloads HTTP retomáveis + verificação de checksum
│   ├── catalog_loader.py       # Validação, carregamento e mesclagem remota de catálogos
│   └── constants.py            # Constantes de timeout, retentativa, chunk e limites de UI
│
├── utils/                      # Serviços transversais
│   ├── __init__.py
│   ├── config_manager.py       # Config JSON persistente
│   ├── app_logging.py          # Logger de arquivo rotativo
│   ├── i18n.py                 # i18n em tempo de execução (en/es/pt) com troca ao vivo
│   ├── diagnostic_bundle.py    # Gerador de pacote ZIP de diagnóstico
│   └── worker_threads.py       # Workers QThread: refresh, install, download, etc.
│
├── ui/                         # Interface gráfica PySide6
│   ├── __init__.py
│   ├── main_window.py          # QMainWindow: abas, barra de ferramentas, workers, logging
│   ├── dialogs.py              # Diálogos modais + Assistente de Instalação de 5 páginas
│   ├── icons.py                # Ícones de status programáticos (círculos) para o Dashboard
│   ├── theme.py                # Constantes de cor centralizadas da UI
│   └── tabs/
│       ├── __init__.py
│       ├── dashboard_tab.py    # Tabela de status de distros
│       ├── manage_tab.py       # Importar/exportar e ações rápidas
│       └── settings_tab.py     # Caminhos, opções de inicialização, limites WSL2
│
├── resources/                  # Ativos empacotados
│   ├── i18n/
│   │   ├── en.json             # Traduções em inglês (500+ chaves)
│   │   ├── es.json             # Traduções em espanhol
│   │   └── pt.json             # Traduções em português (brasileiro)
│   └── styles/
│       └── dark.qss            # Folha de estilo escura Qt (~250 linhas)
│
├── assets/                     # Ícones do aplicativo
│   ├── icon.ico
│   └── icon.png
│
├── tests/                      # Testes unitários (32 testes, não requerem WSL)
│   ├── __init__.py
│   ├── test_app_logging.py
│   ├── test_catalog_loader.py
│   ├── test_config_manager.py
│   ├── test_diagnostic_bundle.py
│   ├── test_dialogs.py
│   ├── test_downloader.py
│   ├── test_i18n.py
│   ├── test_wsl_engine.py
│   └── test_wsl_list_parser.py
│
└── docs/                       # Documentos de design
    └── adrs/
        └── 0001-qprocess-vs-subprocess.md
```

---

## Como o Aplicativo é Executado

1. **Configuração de path** — `main.py` insere a raiz do projeto no
   `sys.path` para que os imports absolutos (`core`, `utils`, `ui`) funcionem
   independentemente do diretório de trabalho.
2. **Fallback venv** — Se o PySide6 estiver ausente no interpretador atual,
   o script tenta relançar usando `.venv\Scripts\python.exe`.
3. **Verificação de dependências** — Detecta pacotes ausentes e exibe um
   diálogo de erro com comandos de instalação.
4. **Inicialização Qt** — Cria `QApplication`, aplica escala de fonte DPI,
   carrega a folha de estilo escura (`dark.qss`) e define o ícone do app.
5. **Logging** — `configure_logging()` anexa um handler rotativo em
   `%LOCALAPPDATA%\WSLManagerPro\logs\app.log`.
6. **Config e i18n** — Carrega `ConfigManager` (salva automaticamente na
   migração de schema) e inicializa o gerenciador de idiomas.
7. **Elevação de admin** — Se não estiver executando como administrador e a
   configuração solicitar, pergunta ao usuário se deseja relançar elevado.
   Escolher "Não" desativa `run_as_admin` e continua em modo limitado.
8. **MainWindow** — Cria e exibe a janela principal.
9. **Loop de eventos** — Entra em `app.exec()` até que a janela seja fechada.

```powershell
python main.py
```

---

## Arquitetura e Fluxo de Dados

```mermaid
flowchart TB
    subgraph UI [Thread Principal Qt]
        MW[MainWindow]
        D[Diálogos / InstallWizard]
        MW --> D
    end
    subgraph Workers [Workers QThread]
        RW[RefreshWorker]
        IW[InstallWorker]
        DW[DownloadWorker]
        PIW[PostInstallWorker]
        USPW[UserStatusProbeWorker]
    end
    subgraph Core [Lógica de Negócio]
        WE[WslEngine]
        DM[DownloadManager]
        CL[Catalog Loader]
        WP[WSL List Parser]
    end
    subgraph Disk [Persistência]
        CFG[config.json]
        DJ[distros.json]
        I18N[i18n/*.json]
    end
    MW --> RW
    MW --> IW
    IW --> DM
    IW --> WE
    RW --> WE
    PIW --> WE
    USPW --> WE
    MW --> CFG
    D --> DJ
    MW --> I18N
    WE --> WP
```

- A **UI nunca bloqueia** em operações longas — todo trabalho pesado é
  delegado a **workers QThread** que comunicam via sinais Qt.
- **`WslEngine`** é o único módulo que lança processos do SO. Decodifica
  saída (UTF-16 LE para metacomandos, UTF-8 para bash).
- **`DownloadManager`** suporta retomada HTTP, verificação de checksum e
  extração multi-formato (APPX, bootstrap Arch).
- **`Catalog Loader`** valida e mescla catálogos locais + remotos.
- **`ConfigManager`** persiste configurações, estados de download e registro
  de distros instalados.

---

## Módulos do Código

### Ponto de Entrada (`main.py`)

Funções principais: `_is_admin()`, `_elevate_windows()`,
`_relaunch_with_workspace_venv()`, `_load_dark_stylesheet()`,
`_detect_missing_runtime_dependencies()`, `_resource_path()`, `main()`.

A função `main()` executa uma inicialização de 13 etapas: app ID → import
PySide6 → QApplication → verificação de dependências → escala de fonte →
folha de estilo escura → ícone → logging → config → i18n → aviso de admin →
MainWindow → loop de eventos.

### Pacote Core (`core/`)

**`core/constants.py`** — Constantes centralizadas de timeout, retentativa,
tamanho de chunk e limites de UI usadas por todos os módulos.

**`core/wsl_engine.py`** — `WslEngine`: fachada de alto nível sobre `wsl.exe`,
winget, DISM e PowerShell.  Modelos de dados: `DistroInfo`, `OnlineDistro`.
Exceções: `WslNotFoundError`, `WslCommandError`.  Operações de ciclo de vida
de distros (import/export/unregister/set-default/terminate/shutdown), execução
de comandos em tempo real (`run_command`/`run_command_as_root`), pipeline de
provisionamento pós-instalação (`build_post_install_steps`/`inject_post_install`)
compatível com apt/dnf/zypper/pacman/apk, e geração de `.wslconfig`.  Senhas
são escritas via arquivo temporário dentro do convidado e excluídas
imediatamente após `chpasswd` — nunca visíveis via `ps`.

**`core/wsl_list_parser.py`** — Funções puras (sem dependência de subprocess):
`parse_wsl_list_verbose()` e `parse_wsl_list_online()`.  Tratam BOM UTF-16 LE,
cabeçalhos localizados (en/es/pt) e o marcador `*` de distro padrão.

**`core/downloader.py`** — `DownloadManager`: download HTTP com streaming,
retomada Range, até 3 retentativas, callback de progresso, verificação de
checksum (SHA-256/SHA-512/MD5) e cancelamento cooperativo via `threading.Event`.
Também: `extract_appx()` para arquivos APPX/ZIP e `extract_arch_bootstrap()`
para `.tar.zst` (descompressão zstandard → reempacotamento como `tar.gz`).

**`core/catalog_loader.py`** — Dataclass `CatalogLoadResult`.  `load_catalog()`
valida e mescla catálogos de distros locais + remotos.  Entradas inválidas
são ignoradas com avisos.

### Pacote Utils (`utils/`)

**`utils/config_manager.py`** — `ConfigManager`: JSON persistente em
`%APPDATA%\WSLManagerPro\config.json`.  Dataclass `AppConfig` com todas as
configurações.  Migração de schema v1→v2 com salvamento automático.  Modelos
`InstalledDistro` e `DownloadState`.  Validação estrita ao salvar, carregamento
tolerante com fallbacks.

**`utils/app_logging.py`** — Handler de arquivo rotativo: 2 MB máx, 5 backups,
codificação UTF-8.  Sanitização de senhas por convenção.

**`utils/i18n.py`** — Singleton `I18nManager` com sinal Qt `language_changed`
para troca de idioma ao vivo.  Cadeia de fallback: idioma atual → inglês →
chave original.  Suporta `str.format(**kwargs)`.  Resolução de recursos
compatível com PyInstaller.

**`utils/diagnostic_bundle.py`** — Gerador ZIP: `README.txt`, `log_tail.txt`,
`wsl_version.txt`, `wsl_status.txt`.  Sem segredos por design.

**`utils/worker_threads.py`** — 12 classes worker QThread: `BaseWorker`,
`CancellableWorker`, `RefreshWorker`, `UserStatusProbeWorker`,
`WslCommandWorker`, `ExportWorker`, `ImportWorker`, `DownloadWorker`,
`PostInstallWorker`, `InstallWorker` (pipeline completo de 5 etapas +
alternativa `wsl_online`), `WslConfigWorker`, `WingetInstallWorker`.

### Pacote UI (`ui/`)

**`ui/main_window.py`** — `MainWindow` (QMainWindow): barra de ferramentas
(Install, Refresh, Shutdown All, seletor de idioma), splitter de 3 abas +
console de log, temporizador de atualização automática (configurável,
mínimo 15 s), construção de catálogo de distros (mescla `wsl --list --online`
com metadados do `distros.json`), menu de contexto na tabela Dashboard, fluxo
completo do assistente de instalação com suporte PowerShell externo para
distros legacy.  `closeEvent` finaliza processos rastreados.

**`ui/dialogs.py`** — Diálogos modais: `UserCreationDialog` (nome de usuário
regex `^[a-z_][a-z0-9_-]{0,30}$`, senha ≥ 4 caracteres, checkbox sudo),
`DirectoryDialog`, `SwapConfigDialog` e `InstallWizard` (fluxo guiado de 5
páginas: Seleção de Distro → Caminhos → Conta de Usuário → Resumo →
Progresso).  Suporta salvar/carregar perfis e detecção de distros interativos
legacy.

**`ui/icons.py`** — Fábrica programática de `QIcon` via `QPainter`: running
(verde), stopped (cinza), installing (laranja), default (azul).

**`ui/theme.py`** — 9 constantes de cor nomeadas: `COLOR_TEXT`, `COLOR_MUTED`,
`COLOR_INFO`, `COLOR_SUCCESS`, `COLOR_WARNING`, `COLOR_ERROR`, `COLOR_ACCENT`,
`COLOR_STOPPED`, `COLOR_BG_PANEL`.

**`ui/tabs/`** — Widgets de aba desacoplados (fase A do ROADMAP):
- `DashboardTab` — Tabela de distros de 7 colunas com controles de cabeçalho.
- `ManageTab` — Importar/exportar e botões de ação rápida.
- `SettingsTab` — Caminhos, opções de inicialização, limites WSL2, diagnóstico.

---

## O Catálogo `distros.json`

Catálogo JSON estático na raiz do projeto. Cada chave é um ID interno de
distro (ex. `ubuntu-2404`):

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `display_name` | `string` | Nome legível para a UI |
| `description` | `string` | Descrição curta |
| `url` | `string` | URL de download do rootfs (obrigatório para método `rootfs`) |
| `checksum_url` | `string?` | URL do arquivo de índice de checksum |
| `checksum_file_pattern` | `string?` | Padrão de nome no arquivo de checksum |
| `algo` | `string?` | Algoritmo de hash: `sha256`, `sha512`, `md5` |
| `pkg_manager` | `string?` | `apt`, `dnf`, `zypper`, `pacman`, `apk` |
| `sudo_group` | `string?` | `sudo` (Debian/Ubuntu) ou `wheel` (Fedora/Arch/Alpine) |
| `packages` | `string[]?` | Pacotes instalados durante pós-install |
| `extract_type` | `string` | Formato: `tar.gz`, `tar`, `tar.xz`, `tar.zst`, `appx`, `zip` |
| `systemd` | `boolean?` | Se o suporte de boot systemd está disponível |
| `install_method` | `string` | `rootfs` (download + import) ou `wsl_online` (catálogo Store) |
| `online_name` | `string?` | Nome exato em `wsl --list --online` |
| `legacy_non_interactive_disable` | `boolean?` | Marca distros que exigem primeiro boot interativo (Oracle, SUSE) |
| `winget_id` | `string?` | Identificador do Windows Package Manager (reservado) |
| `notes` | `string?` | Notas livres para o mantenedor |

**Distribuições incluídas:** Ubuntu 22.04/24.04 LTS, Debian 12, Fedora 40,
Alpine Linux 3.19, Arch Linux, AlmaLinux 9, SUSE Linux Enterprise 15 SP6,
Oracle Linux 9.5.

---

## Configuração Persistente

**Arquivo:** `%APPDATA%\WSLManagerPro\config.json`

| Configuração | Padrão | Descrição |
|-------------|--------|-----------|
| `language` | `"en"` | Idioma da UI (`en`, `es`, `pt`) |
| `install_dir` | `C:\WSL\Distros` | Diretório de instalação padrão |
| `download_dir` | `C:\WSL\Cache` | Diretório de cache de downloads |
| `remote_catalog_url` | `""` | URL opcional de catálogo remoto |
| `run_as_admin` | `true` | Solicitar elevação ao iniciar |
| `check_for_updates` | `false` | Verificar atualizações ao iniciar (GitHub releases) |
| `memory_limit_gb` | `4` | Limite de memória VM WSL 2 (1–256 GB) |
| `swap_size_gb` | `2` | Espaço swap WSL 2 (0–128 GB) |
| `processors` | `2` | Núcleos CPU lógicos para WSL 2 (1–256) |
| `localhost_forwarding` | `true` | Encaminhamento de portas Windows→WSL |
| `vm_idle_timeout_sec` | `60` | Tempo ocioso para desligamento automático da VM |
| `auto_refresh_interval_sec` | `15` | Intervalo de atualização do Dashboard |
| `wsl_version` | `2` | Versão WSL preferida (1 ou 2) |
| `diagnostic_log_tail_lines` | `200` | Linhas de log no ZIP de diagnóstico |
| `download_states` | `{}` | Metadados de retomada de downloads |
| `installed_distros` | `[]` | Registro de distros instalados por este app |

---

## Funcionalidades da Interface

### Barra de Ferramentas

- **Install** — Abre o Assistente de Instalação de 5 páginas.
- **Refresh** — Atualiza a lista de distros.
- **Shutdown All** — Executa `wsl --shutdown`.
- **Seletor de idioma** — Alterna o idioma da UI ao vivo (en / es / pt).

### Aba Dashboard

- Tabela de 7 colunas: ícone de status, nome, estado, versão WSL, marcador
  de padrão, status do usuário, botão de ação.
- Atualização manual e automática (intervalo configurável, mínimo 15 s).
- Botão Re-scan User Status para sondar usuários padrão.
- Menu de contexto: Set Default, Terminate, Export, Open Shell (user/root),
  Full System Update, Repair (condicional), Unregister.
- Estado vazio com Retry Detection quando WSL não está disponível.

### Aba Manage

- **Import:** caminho tar, nome WSL, diretório de instalação → `wsl --import`.
- **Export:** seletor de distro + caminho de salvamento → `wsl --export`.
- **Quick Actions:** Set Default, Terminate, Shutdown All, Open Shell
  (user/root), Full System Update, Install via winget, Repair (Oracle/SUSE),
  Unregister, Deep Clean.

### Aba Settings

- Diretórios padrão de instalação e download.
- Opções de inicialização: executar como admin, verificar atualizações, URL
  do repositório de atualizações.
- Limites de recursos WSL 2: memória, swap, processadores, encaminhamento
  localhost, tempo ocioso da VM (toggle avançado).
- Botão **Apply & Write .wslconfig** (worker em segundo plano).
- Botão **Export Diagnostic Bundle** (ZIP com versão do app, final do log,
  `wsl --version`, `wsl --status`).
- Botão **Save Settings** (persiste em `config.json`).

### Assistente de Instalação

- **Página 1** — Selecionar distro do catálogo mesclado (local + online).
- **Página 2** — Configurar caminhos e nome WSL.
- **Página 3** — Conta de usuário (opcional), atualização do sistema,
  systemd, salvar/carregar perfil.
- **Página 4** — Revisão do resumo.
- **Página 5** — Log de progresso ao vivo com transições de etapa
  (Download → Extract → Import → Post-install → Complete).

Para Oracle Linux e SUSE Enterprise (distros interativos legacy), o
assistente pode delegar para uma janela externa do PowerShell.

---

## Motor WSL (`WslEngine`)

- Resolve o caminho do `wsl.exe` de `System32`, `SysNative` ou `PATH`.
- Usa `CREATE_NO_WINDOW` em todos os subprocessos para evitar janelas de console.
- Decodifica saída com UTF-16 LE primeiro (metacomandos), depois UTF-8 (bash).
- Geradores de streaming (`_popen_stream`, `_popen_stream_checked`) para
  saída em tempo real.
- Timeouts explícitos: 600 s para import/export, 300 s para set-version,
  120 s para validação de usuário, 20 s para sondagem de usuário.
- Suporta todos os subcomandos `wsl.exe`: import, export, unregister,
  set-default, set-version, terminate, shutdown, mount.

---

## Gerenciador de Downloads (`DownloadManager`)

- **Tamanho do chunk:** 128 KiB.
- **Retomada:** HTTP Range; auto-detecta tamanho do arquivo existente.
- **Retentativas:** até 3 tentativas em erros de rede/IO.
- **Progresso:** callback `(bytes_done, total_bytes)`; `total_bytes` pode
  ser 0 se o servidor omitir `Content-Length`.
- **Cancelamento:** cooperativo via `threading.Event`.
- **HTTP 416:** tratado como "arquivo já completo" — verifica checksum se
  fornecido e retorna.
- **Extração de arquivos:** APPX (ZIP → localizar rootfs tar) e bootstrap
  Arch (`.tar.zst` → reempacotar como `tar.gz` simples).

---

## Threads de Trabalho (Qt)

Todos os workers herdam de `BaseWorker` (ou `CancellableWorker`) e executam
em `QThread`.  `MainWindow` mantém referências em `_active_workers` para
evitar que o coletor de lixo destrua threads ativas.

Padrão de comunicação:

```
Worker thread  ── sinal ──▶  Slot da thread principal
────────────────────────────────────────────────────
log_message(str)        → anexar ao console de log
error_occurred(str)     → exibir erro no log + barra de status
progress(int, int)      → atualizar barra de progresso
stage_changed(str)      → atualizar rótulo de status
finished_ok()           → notificar conclusão + limpeza
```

---

## Internacionalização (i18n)

O aplicativo suporta **três idiomas** com troca ao vivo (sem reinicialização):

| Código | Idioma | Arquivo |
|--------|--------|---------|
| `en` | English | `resources/i18n/en.json` |
| `es` | Español | `resources/i18n/es.json` |
| `pt` | Português (Brasil) | `resources/i18n/pt.json` |

**Características principais:**
- **Cadeia de fallback:** idioma atual → inglês → chave original.
- **Formatação de strings:** `t("Baixado {pct}%", pct=75)`.
- **Troca ao vivo:** sinal Qt `language_changed` aciona `retranslate_ui()`
  em todas as abas e diálogos.
- **Compatível com PyInstaller** via `sys._MEIPASS`.
- **Degradação graciosa:** erros de parse JSON produzem catálogos vazios
  (chaves usam fallback em inglês).

---

## Observabilidade (Logging e Diagnóstico)

### Logging

- **Arquivo rotativo:** `%LOCALAPPDATA%\WSLManagerPro\logs\app.log`
  (2 MB máx, 5 backups, UTF-8).
- **Formato:** `YYYY-MM-DD HH:MM:SS | LEVEL | message`.
- **Configuração idempotente:** `configure_logging()` pode ser chamado várias
  vezes; apenas um handler é anexado.
- **Console de log UI:** suporta filtragem por palavra-chave, copiar tudo,
  copiar seleção e codificação de cores HTML.
- **Segurança:** senhas nunca são registradas em operação normal (aplicado
  por convenção em cada ponto de chamada).

### Pacote de Diagnóstico (ZIP)

Gerado pela aba Settings. Conteúdo:
- `README.txt` — Timestamp, versão do app, status dos comandos, aviso de
  privacidade.
- `log_tail.txt` — Últimas N linhas do console de log (configurável).
- `wsl_version.txt` — Saída de `wsl --version`.
- `wsl_status.txt` — Saída de `wsl --status`.

Sem segredos por design. O README inclui um lembrete para revisar o conteúdo
do log antes de compartilhar.

---

## Privilégios e Segurança

- **Elevação de administrador:** o aplicativo pergunta se deseja relançar
  elevado ao iniciar. Se o usuário recusar, executa em modo limitado (somente
  leitura) e desativa a preferência `run_as_admin`.
- **Senhas Linux:** durante pós-install, a senha é escrita em um arquivo
  temporário dentro do convidado e excluída imediatamente após o `chpasswd`
  lê-la. Nunca é visível via `ps` nem registrada no console.
- **Validação de nome de usuário:** aplicada tanto na UI (`UserCreationDialog`)
  quanto no motor (`build_post_install_steps`) com a expressão regular
  `^[a-z_][a-z0-9_-]{0,30}$`.
- **Sem segredos hardcoded:** o código não contém chaves de API, tokens ou
  credenciais fixas.

---

## Build e Distribuição

### EXE Único (PyInstaller)

```powershell
.\build.ps1
```

Invoca o PyInstaller com `wsl_manager_pro.spec`, produzindo um
`WSLManagerPro.exe` independente em `dist/`.  O executável inclui todos os
módulos Python (arquivo `.pyz`), `distros.json`, traduções
(`resources/i18n/*.json`), folha de estilo escura (`resources/styles/dark.qss`)
e o ícone do aplicativo (`assets/icon.ico`, incorporado via `.rc`).

### Build Manual

```powershell
python -m PyInstaller --clean wsl_manager_pro.spec
```

---

## Desenvolvimento, Testes e CI

### Executar Testes

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

Os **32 testes passam** sem exigir `wsl.exe` — os parsers são funções puras
e os testes do downloader/engine usam mocks.

### Linting

```bash
ruff check core/ utils/ tests/ main.py
```

Ruff está configurado em `pyproject.toml` (Python 3.10, linha de 100 caracteres).
O diretório `ui/` está temporariamente excluído pendente de revisão de estilo.

### Pipeline CI

Em cada push ou pull request para `main` ou `master`, o fluxo de CI:
1. Instala o projeto com o extra `dev`.
2. Executa `ruff check core utils tests`.
3. Executa `pytest`.

---

## Roteiro

Consulte [`ROADMAP.md`](ROADMAP.md) para o plano de desenvolvimento multifásico
completo (150+ tarefas em 8 fases: refatoração UI, ferramentas, observabilidade,
configuração, privilégios, UX, empacotamento e melhorias do motor).

---

## Licença

Este projeto está licenciado sob a **GNU General Public License v3.0 (GPL-3.0)**.
Consulte o arquivo [LICENSE](LICENSE) para o texto completo.

Copyright (C) 2026 Contribuidores do WSL Manager Pro.

Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo sob os
termos da Licença Pública Geral GNU publicada pela Free Software Foundation,
seja a versão 3 da Licença, ou (à sua escolha) qualquer versão posterior.
