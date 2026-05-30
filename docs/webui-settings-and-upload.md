# WebUI Settings And File Upload

This document covers the WebUI runtime settings center and the file upload import path.

## Runtime Settings

The WebUI reads local runtime UI settings from:

```text
config/webui.yaml
```

If the file is missing, built-in defaults are used. The file is local-only and should not be committed because it describes one deployment environment.

Current setting groups:

- `app`: knowledge-base name, browser title, subtitle, and logo path.
- `features`: runtime switches for Chat, Graph, Documents, Upload, URL import, Candidates, RSS, WeChat, LLM settings, and LLM audit.

The settings page is available as `System Settings` / `系统设置`. Saving the page creates a backup under:

```text
backups/webui/
```

Branding changes apply immediately in the WebUI. The startup console banner uses the configured app name on the next server restart.

## Feature Switches

Feature switches hide disabled menus in the WebUI and also gate backend APIs. Disabled APIs return HTTP 403 with a `feature disabled` error.

This is intended for deployments where some integrations are unavailable. For example, a pure local deployment can disable RSS or WeChat discovery without showing unusable menu items.

## File Upload

The upload path is:

```text
browser upload -> raw/<category>/ -> file parser -> file_import_structure flow -> wiki/<category>/ -> search index rebuild
```

Supported extensions include:

- `.txt`
- `.md`
- `.pdf`
- `.docx`
- common code/text formats such as `.py`, `.js`, `.ts`, `.go`, `.rs`, `.json`, `.yaml`, `.csv`

After auto-processing, the upload API returns per-file details:

- saved raw path
- processing stage
- generated wiki path
- LLM flow/provider/model/status/duration/fallback metadata when generation succeeds
- concrete parsing, missing key, provider, or LLM errors when generation fails

The upload page also shows the active `file_import_structure` provider chain and current local/online/hybrid mode so operators can see which model path will be used.

## Mode Expectations

- Pure local mode: file upload processing uses only `local_gemma4`.
- Pure online mode: file upload processing uses DeepSeek providers and does not fall back to local. If `DEEPSEEK_API_KEY` is missing, upload processing fails with a missing-key error.
- Hybrid mode: file upload processing follows the configured provider chain and records the actual provider/fallback path in generated wiki frontmatter.
