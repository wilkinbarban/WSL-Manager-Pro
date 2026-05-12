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
- [Como o Fluxo One-Click Funciona](#como-o-fluxo-one-click-funciona)
- [Instalação Manual](#instalação-manual)
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

> **O que este comando faz — passo a passo:**
>
> 1. **Baixa o `install_secure.ps1`** — Um script de inicialização leve (~6 KB)
>    obtido diretamente do branch `master` do repositório via GitHub raw.
> 2. **Baixa o repositório como ZIP** — O script baixa todo o código fonte do
>    WSL Manager Pro como um arquivo ZIP (não requer Git), extrai e copia os
>    arquivos para `%USERPROFILE%\Desktop\WSL-Manager-Pro`.
> 3. **Verifica arquivos críticos** — Confirma que `install.ps1` e `distros.json`
>    estão presentes e intactos. Se algo faltar, o script para com uma mensagem
>    de erro clara.
> 4. **Delega para `install.ps1`** — A cópia local verificada do instalador
>    assume o controle e executa a configuração completa: habilita recursos WSL,
>    instala Python 3.12 via winget, cria um ambiente virtual `.venv` e instala
>    todas as dependências do projeto.
> 5. **Pronto para executar** — Quando o processo termina, o aplicativo está
>    totalmente configurado e pode ser iniciado com
>    `.\.venv\Scripts\python.exe .\main.py` a partir do diretório de destino.
>
> **Requisitos:** Privilégios de Administrador (o script auto-eleva via UAC)
> e `winget` deve estar disponível (incluído com App Installer no Windows 10/11).
> **Não requer Git.**

### Instalação local (repositório já baixado)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\install.ps1
```

---

## Como o Fluxo One-Click Funciona

1. `install_secure.ps1` é baixado e executado remotamente.
2. O script baixa o repositório como ZIP (usando `Invoke-WebRequest` + `Expand-Archive`,
   cmdlets nativos do PowerShell) e extrai em `%USERPROFILE%\Desktop\WSL-Manager-Pro`.
3. Verifica arquivos críticos (`install.ps1` e `distros.json`).
4. Delega para `install.ps1`.
5. `install.ps1`:
   - valida contexto local de execução;
   - solicita elevação (UAC) quando necessário;
   - habilita recursos WSL;
   - instala Python 3.12 com winget;
   - cria `.venv` e instala dependências Python;
   - executa verificações finais.

Comando de execução após instalação:

```powershell
.\.venv\Scripts\python.exe .\main.py
```

---

## Instalação Manual

```powershell
# 1. Baixar o ZIP do GitHub ou clonar o repositório
#    ZIP: https://github.com/wilkinbarban/WSL-Manager-Pro/archive/refs/heads/master.zip
#    ou
#    git clone https://github.com/wilkinbarban/WSL-Manager-Pro.git

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
