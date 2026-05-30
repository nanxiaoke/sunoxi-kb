# Git Deployment Guide

This is the current primary deployment path for Karpathy KB.

The repository contains application code and empty runtime directory placeholders only. It does not include article data, generated wiki pages, caches, logs, backups, API keys, or release artifacts.

## Supported Modes

- Windows green deployment with Git Bash.
- Linux green deployment with `sh`.
- Online-only LLM mode.
- Hybrid/local mode only when Ollama is already installed and running externally.

This path does not install a Windows service, Windows Task Scheduler task, Ollama, local model files, offline CDN assets, or Docker.

## Requirements

Windows:

- Windows 10/11.
- Git for Windows, including Git Bash.
- Python 3.11 or newer, available in `PATH` as `python`.
- Network access for Python package installation and WebUI CDN assets.
- GitHub SSH key access to the repository, or an HTTPS clone URL if configured separately.

Linux:

- Git.
- Python 3.11 or newer, available as `python3`.
- POSIX shell.
- Network access for Python package installation and WebUI CDN assets.

## First Deployment

Clone the repository:

```bash
git clone git@github.com:nanxiaoke/sunoxi-kb.git karpathy-kb
cd karpathy-kb
```

Install the default runtime dependencies:

```bash
./packaging/common/install_deps.sh
```

On Linux, use `PYTHON_BIN=python3` when `python` is not Python 3:

```bash
PYTHON_BIN=python3 ./packaging/common/install_deps.sh
```

Configure the online key:

```bash
./packaging/common/configure_key.sh --key "your_deepseek_key"
```

Start WebUI:

```bash
./packaging/common/start_webui.sh
```

Open:

```text
http://127.0.0.1:5080
```

## Windows Notes

Run the commands in Git Bash from the repository root.

If `python` is not found:

- Reinstall Python and enable "Add python.exe to PATH"; or
- set `PYTHON_BIN` to the full Python path when running `install_deps.sh`.

If SSH clone fails:

- Confirm the deployment machine has a GitHub SSH key.
- Confirm the public key is added to GitHub.
- Test with `ssh -T git@github.com`.

If port `5080` is occupied:

```bash
PORT=5090 ./packaging/common/start_webui.sh
```

## Updating A Deployment

From the repository root:

```bash
git pull
./packaging/common/install_deps.sh
./packaging/common/start_webui.sh
```

You usually do not need to re-run `configure_key.sh` after updates, because `config/llm.env` is local runtime data and is not touched by git.

Use `--force` only when you want to rebuild the virtual environment:

```bash
./packaging/common/install_deps.sh --force
```

## Optional Embeddings

Default deployment does not install semantic embedding dependencies. Those dependencies may pull large ML runtimes such as Torch.

Install them only when you need semantic vector rebuilds:

```bash
./packaging/common/install_deps.sh --with-embeddings
```

Then run maintenance with embeddings enabled from WebUI or CLI as needed.

## Local Runtime Data

These are intentionally ignored by git:

- `config/llm.env`
- `raw/**`
- `wiki/**`
- `outputs/**`
- `reports/**`
- `logs/**`
- `backups/**`
- search indexes, embeddings, caches, candidate state, and release artifacts

Only `.keep` placeholders are tracked for empty runtime directories.

## Deployment Modes

After WebUI starts:

1. Open `LLM Settings`.
2. Select one of:
   - `纯本地` / `Local`
   - `纯在线` / `Online`
   - `混合` / `Hybrid`

Pure online mode needs only `config/llm.env` with `DEEPSEEK_API_KEY`. Local and hybrid modes need external Ollama if local providers are used.
