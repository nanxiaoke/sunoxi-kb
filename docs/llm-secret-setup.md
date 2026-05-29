# LLM Secret Setup

`llm_runtime.yaml` only stores non-sensitive routing settings. Online model keys are loaded from the service process environment.

## Default Location

Use this user-level file:

```bash
~/.config/karpathy-kb/llm.env
```

The file should be owned by the service user and mode `600`.

Example content:

```bash
DEEPSEEK_API_KEY=your_key_here
```

This file intentionally lives under `~/.config`, not inside the project tree, so project backups, git copies, and migrations do not accidentally include secrets.

## One-Shot Setup

From the project directory:

```bash
cd /path/to/karpathy-kb
DEEPSEEK_API_KEY=your_key_here ./scripts/install_llm_env.sh
```

The script will:

- create `~/.config/karpathy-kb/llm.env`
- set directory/file permissions to `700`/`600`
- create the systemd user drop-in `~/.config/systemd/user/karpathy-kb.service.d/10-llm-env.conf`
- run `systemctl --user daemon-reload`
- restart `karpathy-kb.service`

If you do not pass `DEEPSEEK_API_KEY`, the script creates a protected template file. Fill it in manually, then run:

```bash
systemctl --user restart karpathy-kb.service
```

## Migration Checklist

On a new host:

1. Copy or deploy the project code.
2. Install Python dependencies and local model runtime as usual.
3. Run the one-shot setup command above with the new host's online model key.
4. Open WebUI -> LLM Settings and confirm online providers show `Secret ready`.
5. Test `deepseek_flash` or `deepseek_pro` from the Provider card.

## Deployment Modes

WebUI -> LLM Settings provides three one-click deployment presets:

- `纯本地` / local: every LLM flow uses `local_gemma4` only. No online model calls are made.
- `纯在线` / online: every LLM flow uses DeepSeek only. Bulk flows use `deepseek_flash`; quality-sensitive flows use `deepseek_pro`. This requires `DEEPSEEK_API_KEY`.
- `混合` / hybrid: bulk flows use local first with DeepSeek Flash fallback; full document translation and manual re-translation prefer DeepSeek Pro, with explicit local selection still available.

Each mode change backs up `llm_runtime.yaml` under `backups/llm_runtime/` before writing the new non-sensitive flow policy. Secrets remain in `~/.config/karpathy-kb/llm.env`.

## Runtime Rules

- Do not put API keys in `llm_runtime.yaml`.
- Do not put API keys in WebUI fields.
- Use `api_key_env` in provider config to name the environment variable, normally `DEEPSEEK_API_KEY`.
- `KB_LLM_API_KEY` remains a fallback compatibility variable, but provider-specific env names are preferred.
