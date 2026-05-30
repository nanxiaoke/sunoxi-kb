# Productization Packaging Plan

Status: started on 2026-05-29.

## Goal

Turn the current Karpathy KB project into a git-managed, relocatable application that can be deployed from source on Windows first, then packaged formally later.

## Scope Order

1. Git-based Windows green deployment.
2. Git hygiene and code/data separation.
3. Linux green deployment.
4. Formal distribution packaging for Windows and Linux.
5. Docker distribution package.

Docker is intentionally last. The current target is a Windows machine that can `git clone` / `git pull`, install Python dependencies, configure an online key, and start WebUI without installing a Windows service.

## Current Windows Git Deployment Scope

Included:

- Source checkout deployment.
- Python virtual environment install script.
- Start script for WebUI.
- Key configuration script for online mode.
- Online-network WebUI mode using existing CDN resources.
- External Ollama support only when the user already has Ollama running.

Excluded for this phase:

- NSSM service installation.
- Windows Task Scheduler integration.
- Bundled Ollama installer or model files.
- Offline vendored WebUI assets.
- Docker packaging.
- Embedded API keys.
- Knowledge-base article data migration.
- Zip/release artifact generation.

## Windows Git Checkout Layout

```text
karpathy-kb/
  scripts/
  docs/
  static/
  config/
  packaging/common/
    install_deps.sh
    configure_key.sh
    start_webui.sh
  packaging/windows/
    install_deps.sh
    configure_key.sh
    start_webui.sh
    README-Windows.md
  wiki/
  raw/
  reports/
  backups/
  outputs/
  logs/
  llm_runtime.yaml
  requirements.txt
  config/
    llm.env
```

## Windows Runtime Rules

- The deployment runs from the git checkout directory.
- `packaging/common/install_deps.sh` creates `.venv` under the checkout root and installs `requirements.txt`.
- `packaging/common/install_deps.sh --with-embeddings` additionally installs `requirements-embeddings.txt` for semantic vector rebuilds.
- `packaging/common/configure_key.sh` writes `config/llm.env`.
- `packaging/common/start_webui.sh` loads `config/llm.env` into the current process environment, starts `scripts/web_ui.py`, and opens `http://127.0.0.1:5080`.
- `packaging/windows/*.sh` are compatibility wrappers around `packaging/common/*.sh`.
- Secrets stay out of source files and release manifests.
- For pure online mode, no local Ollama is required.
- For mixed/local mode, Ollama must already be running externally.

## Tasks

- [x] Mark LLM Phase 5 complete for the current scope.
- [x] Create this productization task tracker.
- [x] Add initial Windows portable `.sh` scripts.
- [x] Remove remaining hard-coded development-path assumptions from setup docs/scripts used by the portable package.
- [x] Add `.gitignore` for code/data separation before initializing git.
- [x] Move or adapt Windows `.sh` scripts so they work directly from a git checkout.
- [x] Move shared launcher logic into `packaging/common/` for Windows Git Bash and Linux.
- [x] Add empty runtime directory placeholders without tracking article data.
- [x] Add Windows git deployment documentation.
- [ ] Test on a real Windows host with Python installed.
- [x] Add Linux green deployment through the same POSIX `.sh` scripts.
- [x] Split heavyweight embedding dependencies out of default green deployment install.

## Acceptance Criteria For Windows Git Deployment V1

- On Windows with Python 3.11+ and Git Bash or a POSIX-compatible shell installed, the user can run:
  - `git clone <repo> karpathy-kb`
  - `cd karpathy-kb`
  - `./packaging/common/install_deps.sh`
  - `./packaging/common/configure_key.sh --key "..."`
  - `./packaging/common/start_webui.sh`
- WebUI opens at `http://127.0.0.1:5080`.
- LLM Settings can switch between pure local, pure online, and hybrid.
- No API key, article data, index, embedding, cache, log, backup, or release artifact is tracked in git.

## Linux Git Deployment

The same scripts are valid on Linux:

```bash
git clone <repo> karpathy-kb
cd karpathy-kb
PYTHON_BIN=python3 ./packaging/common/install_deps.sh
./packaging/common/configure_key.sh --key "..."
./packaging/common/start_webui.sh
```

The Windows directory remains as a compatibility alias for earlier notes, but the common directory is the preferred cross-platform entrypoint.

## Deferred Task: Formal Distribution Packaging (Windows & Linux)

Status: legacy/deferred.

This task covers downloadable release artifacts after git-based deployment is stable.

Planned items:

- Revisit `scripts/build_windows_portable.py` or replace it with a cleaner release builder.
- Produce Windows and Linux archives from a clean repository checkout.
- Add release manifests and checksums.
- Add optional data export/import tooling that excludes secrets.
- Add Docker distribution package after Windows/Linux archives are stable.
