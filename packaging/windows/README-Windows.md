# Karpathy KB Git Deployment

This is the Windows compatibility launcher set for a git checkout. The real cross-platform scripts live in `packaging/common/`; these files forward to them.

For the full current deployment guide, see `docs/git-deployment.md`.

## Requirements

- Windows 10/11 with Git Bash
- Python 3.11 or newer in `PATH`
- Internet access for dependency installation and CDN WebUI assets
- GitHub SSH access to `git@github.com:nanxiaoke/sunoxi-kb.git`
- Optional: Ollama already installed and running if you use local or hybrid mode

## First Run

Open Git Bash in the repository root:

```bash
./packaging/windows/install_deps.sh
./packaging/windows/configure_key.sh --key "your_key_here"
./packaging/windows/start_webui.sh
```

The equivalent common entrypoints are:

```bash
./packaging/common/install_deps.sh
./packaging/common/configure_key.sh --key "your_key_here"
./packaging/common/start_webui.sh
```

Then open:

```text
http://127.0.0.1:5080
```

## Online-Only Mode

For a Windows portable deployment without Ollama:

1. Configure `DEEPSEEK_API_KEY` with `configure_key.sh`.
2. Start WebUI.
3. Open `LLM Settings`.
4. Select `纯在线` / `Online`.

## Local Or Hybrid Mode

Local and hybrid modes require an external Ollama service. This package does not install Ollama or download model files.

Expected local endpoint:

```text
http://127.0.0.1:11434
```

Expected local model from current config:

```text
gemma4:e4b
```

## Secrets

`config/llm.env` is generated locally and should not be committed or shared.

Example:

```text
DEEPSEEK_API_KEY=...
```

## Runtime Data

Article data, generated wiki pages, indexes, embeddings, caches, logs, reports, and backups are local runtime data. They are intentionally excluded from git by `.gitignore`.

## Updates

From Git Bash in the repository root:

```bash
git pull
./packaging/common/install_deps.sh
./packaging/common/start_webui.sh
```

You do not normally need to re-run `configure_key.sh` because `config/llm.env` is local and ignored by git.

## Common Issues

If `python` is not found, reinstall Python 3.11+ and enable "Add python.exe to PATH".

If SSH clone fails, confirm the machine has a GitHub SSH key and test:

```bash
ssh -T git@github.com
```

If port `5080` is occupied:

```bash
PORT=5090 ./packaging/common/start_webui.sh
```
