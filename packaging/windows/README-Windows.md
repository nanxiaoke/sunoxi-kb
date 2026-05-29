# Karpathy KB Git Deployment

This is the Windows compatibility launcher set for a git checkout. The real cross-platform scripts live in `packaging/common/`; these files forward to them.

## Requirements

- Windows 10/11 with Git Bash, or Linux with `sh`
- Python 3.11 or newer in `PATH`
- Internet access for dependency installation and CDN WebUI assets
- Optional: Ollama already installed and running if you use local or hybrid mode

## First Run

Open Git Bash or a Linux shell in the repository root:

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
