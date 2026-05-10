# WSL Manager Pro

[![CI](https://github.com/wilkinbarban/WSL-Manager-Pro/actions/workflows/ci.yml/badge.svg)](https://github.com/wilkinbarban/WSL-Manager-Pro/actions/workflows/ci.yml)
[![Licença: GPL v3](https://img.shields.io/badge/Licença-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-green.svg)](https://pypi.org/project/PySide6/)

> 📖 Também disponível em: [English](README.md) · [Español](README_es.md)

Aplicativo desktop para **Windows** que centraliza o gerenciamento do **WSL**:
listar distribuições, instalar do catálogo online ou de rootfs local,
importar/exportar, configurar usuário e pós-instalação, aplicar limites via
`.wslconfig` e executar ações de manutenção.

**Versão do aplicativo:** 1.0.0

---

## Índice

- [Requisitos do Sistema](#requisitos-do-sistema)
- [Início Rápido](#início-rápido)
- [Estrutura do Repositório](#estrutura-do-repositório)
- [Como o Fluxo One-Click Funciona](#como-o-fluxo-one-click-funciona)
- [Execução Manual](#execução-manual)
- [Observações de Segurança](#observações-de-segurança)
- [Licença](#licença)

---

## Requisitos do Sistema

| Requisito | Detalhes |
|-----------|----------|
| **Sistema Operacional** | Windows 10 build 19041+ (suporte WSL 2) |
| **WSL** | `wsl.exe` acessível em `%SystemRoot%\System32\wsl.exe` |
| **PowerShell** | `pwsh.exe` (PS 7+) ou `powershell.exe` (PS 5.1) |
| **Python** | 3.10 ou superior |
| **Permissões** | Privilégios de Administrador recomendados para WSL e winget |

---

## Início Rápido

### Instalação com um único comando (recomendada)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; irm https://raw.githubusercontent.com/wilkinbarban/WSL-Manager-Pro/master/install_secure.ps1 | iex
```

### Instalação local (repositório já clonado)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\install.ps1
```

---

## Estrutura do Repositório

```text
WSL Manager Pro/
├── main.py
├── install.ps1
├── install_secure.ps1
├── distros.json
├── requirements.txt
├── core/
├── utils/
├── ui/
├── resources/
└── tests/
```

---

## Como o Fluxo One-Click Funciona

1. `install_secure.ps1` é baixado e executado remotamente.
2. O script clona (ou atualiza) o repositório em `%USERPROFILE%\Desktop\WSL-Manager-Pro`.
3. Verifica arquivos críticos (`install.ps1` e `distros.json`).
4. Delega para `install.ps1`.
5. `install.ps1`:
   - valida contexto local de execução;
   - solicita elevação (UAC) quando necessário;
   - habilita recursos WSL;
   - instala Python 3.12 e Node.js LTS com winget;
   - cria `.venv` e instala dependências;
   - executa verificações finais.

Comando de execução após instalação:

```powershell
.\.venv\Scripts\python.exe .\main.py
```

---

## Execução Manual

```powershell
git clone https://github.com/wilkinbarban/WSL-Manager-Pro.git
cd WSL-Manager-Pro
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

## Observações de Segurança

- O instalador usa `Set-ExecutionPolicy -Scope Process`, sem alteração permanente global.
- Senhas Linux não devem ser registradas em logs.
- O fluxo recomendado evita `install.ps1` via pipe direto (`irm ... install.ps1 | iex`).

---

## Licença

Projeto distribuído sob **GNU GPL v3**.

Veja [`LICENSE`](LICENSE).
