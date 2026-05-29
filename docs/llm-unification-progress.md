# LLM Unification Progress

## 2026-05-29 Phase 6 Start

Scope:

- Improve LLM observability and auditability across production flows.
- Record provider/model/flow metadata in machine-readable places, not only logs or footer text.
- Phase 5 is now complete for the current LLM configuration scope; product packaging work is tracked separately.

Progress:

- [x] Mark Phase 5 complete after WebUI provider/flow editing, backup/restore, secret setup, provider tests, and deployment-mode presets landed.
- [x] Start structured metadata work for generated wiki articles.
- [x] Add `llm` frontmatter to URL/file import wiki output with flow, provider, model, status, duration, fallback, and generation time.
- [x] Add per-chunk metadata for long full-document re-translations under `llm_retranslation.chunks`.
- [x] Add a lightweight LLM audit export endpoint: `GET /api/llm/audit`.
- [x] Add a WebUI LLM audit panel under LLM Settings for coverage, provider/flow/model distribution, fallback count, and recent LLM outputs.
- [x] Add clearer preview/full/import-processing provider visibility for candidate import results.
- [x] Include translation and final processing LLM metadata in batch import status items.

Verification:

- `python3 -m py_compile scripts/batch_processor.py scripts/web_ui.py scripts/llm_service.py scripts/qa.py` passed.
- Temp-dir import smoke with a monkeypatched LLM result generated wiki frontmatter containing `llm.flow=file_import_structure`, `llm.provider=test_provider`, and `llm.model=test-model`.
- `_llm_audit_payload()` scanned 157 current wiki docs and returned a valid audit payload before historical backfill.
- `python3 -m py_compile scripts/web_ui.py scripts/batch_processor.py scripts/llm_service.py scripts/qa.py scripts/translator.py` passed after the audit endpoint and retranslation chunk metadata changes.
- `python3 -m py_compile scripts/candidate_manager.py scripts/translator.py scripts/web_ui.py scripts/batch_processor.py scripts/llm_service.py` passed after candidate import visibility changes.
- Unit smoke for `CandidateManager._translation_import_meta()` confirmed full-translation decision, preview provider/model, full provider/model, and chunk count are returned in the import payload.

Current status:

- Phase 6 implementation tasks are complete for the current scope.
- Historical wiki documents have been backfilled with inferred legacy audit metadata.
- Audit coverage is now 100% for current wiki documents, with legacy entries clearly marked as `legacy_inferred`.

## 2026-05-29 Phase 6 UX Follow-up

Scope:

- Fix manual re-translation UX for already imported wiki articles when the configured online provider is unavailable.
- Add fast deployment-mode presets for pure local, pure online, and hybrid model routing.

Progress:

- [x] WebUI now auto-selects the first available re-translation provider. If `DEEPSEEK_API_KEY` is missing, it selects `local` instead of leaving the control on unavailable `online`.
- [x] Unavailable re-translation providers are disabled in the preview drawer selector and the button is disabled only when the selected provider is unavailable.
- [x] Added `POST /api/llm/mode` to apply `local`, `online`, or `hybrid` routing presets with automatic `llm_runtime.yaml` backup.
- [x] Added a deployment-mode panel in WebUI -> LLM Settings.
- [x] Documented deployment modes in `docs/llm-secret-setup.md`.

Verification:

- `python3 -m py_compile scripts/web_ui.py scripts/llm_service.py` passed.
- Flask test client `GET /api/llm/config` returned `mode=hybrid` and 3 mode options.
- Flask test client successfully applied `local`, `online`, then `hybrid`; final config was restored to `hybrid`.
- `/api/translation/models` reports `online=false` / `local=true` with the current missing DeepSeek key, so the WebUI will default re-translation to local.

## 2026-05-29 Phase 6 Historical Audit Backfill

Scope:

- Bring existing wiki documents into the LLM audit without reprocessing them through a model.
- Infer only from existing markdown evidence and mark all inferred fields as legacy metadata.

Progress:

- [x] Added `scripts/backfill_llm_audit.py`.
- [x] Backfilled `llm` frontmatter for 157 existing wiki documents.
- [x] Backfilled `llm_translation_legacy` for 133 documents that had an existing `翻译模型` line.
- [x] Extended `/api/llm/audit` to include `translation_legacy_count`, `by_translation_provider`, and `by_translation_model`.
- [x] Extended the WebUI LLM audit panel to show legacy translation distribution.

Verification:

- Dry run found `scanned=157`, `updated=157`, `translation_legacy=133`, `unknown=0`.
- Applied backfill successfully.
- `/api/llm/audit` now reports `total=157`, `with_llm=157`, `missing_llm=0`, `coverage=1.0`.
- Legacy translation distribution: `deepseek_pro=132`, `local_gemma4=1`.
- `python3 -m py_compile scripts/web_ui.py scripts/backfill_llm_audit.py` passed.

## 2026-05-29 Online Secret Runtime Setup

Decision:

- Keep online model secrets outside the project tree in `~/.config/karpathy-kb/llm.env`.
- Keep `llm_runtime.yaml` non-sensitive; it only names the env var through `api_key_env`.

Progress:

- [x] Added `scripts/install_llm_env.sh` to create the protected env file, configure a user systemd drop-in, reload systemd, and restart `karpathy-kb.service`.
- [x] Added `docs/llm-secret-setup.md` with migration and maintenance instructions.
- [x] Updated WebUI LLM Settings to show the secret env file path, file permission mode, systemd drop-in path, and one-shot setup command without exposing any key value.
- [x] Linked the setup guide from `README.md`.

## 2026-05-28 Phase 1-3 Start

Scope approved by user:

- Phase 1: audit existing LLM-related flows and record current behavior.
- Phase 2: add a unified LLM abstraction layer without changing existing business behavior.
- Phase 3: add per-flow policy definitions so each business flow can choose its own model strategy.

Constraints:

- Do not migrate production flows in Phase 1-3.
- Do not put API keys in WebUI or config files.
- Keep provider config non-sensitive; only reference environment variable names.
- Preserve current WebUI and import behavior until migration is explicitly approved.

Progress:

- [x] Confirmed WebUI health endpoint is OK before changes.
- [x] Scanned LLM-related scripts and config files.
- [x] Identified current split between hard-coded local Ollama, `ProviderFactory`, and `CandidateTranslator`.
- [x] Write flow audit document: `docs/llm-flow-audit.md`.
- [x] Add non-sensitive runtime config: `llm_runtime.yaml`.
- [x] Add `LLMService` abstraction: `scripts/llm_service.py`.
- [x] Add per-flow policy loader inside `LLMConfig`.
- [x] Run syntax checks for `scripts/llm_service.py`.

Verification:

- `python3 -m py_compile scripts/llm_service.py` passed.
- `python3 scripts/llm_service.py` loaded all provider and flow config successfully.
- Provider status correctly reports online DeepSeek providers as `secret_configured=false` when `DEEPSEEK_API_KEY` is absent.

Current implementation status:

- Phase 4 has started. Existing business flows are being migrated incrementally.
- WebUI service must be restarted after Phase 4 code changes to load the migrated routes.
- The new abstraction is now used by selected production paths.

## 2026-05-28 Phase 4 Start

Scope approved by user:

- Migrate existing business flows onto `LLMService` while keeping each flow's own `FlowPolicy`.
- Keep configuration non-sensitive; API keys remain environment-only.
- Record progress in this document and sync concise status to the chat.

Progress:

- [x] Migrate candidate preview translation to `LLMService` flow `candidate_preview`.
- [x] Migrate candidate full translation to `LLMService` flow `full_translation`.
- [x] Preserve quality-sensitive full translation behavior: missing online key returns an explicit error because `allow_fallback=false`.
- [x] Migrate manual WebUI re-translation to `LLMService` flow `retranslation`.
- [x] Preserve WebUI provider selection via `online` / `local`, mapped to configured provider ids.
- [x] Migrate URL import processing to `LLMService` flow `url_import_structure`.
- [x] Migrate file import processing to `LLMService` flow `file_import_structure`.
- [x] Update auto importer comments to reflect the new runtime path.
- [x] Migrate QA LLM answer generation to `LLMService` flow `qa`.
- [x] Keep default QA `extractive` mode unchanged and model-free.
- [x] Migrate legacy `processor.py` compatibility wrapper tasks to `LLMService`.
- [x] Add dedicated compatibility flows: `processor_summary`, `processor_keypoints`, `processor_category`.

Verification:

- `python3 -m py_compile scripts/llm_service.py scripts/translator.py scripts/batch_processor.py scripts/web_ui.py` passed.
- `python3 -m py_compile scripts/qa.py` passed.
- `python3 scripts/llm_service.py` loads all providers and flow policies.
- `_translation_models()` now reads `llm_runtime.yaml` and reports DeepSeek as unavailable when `DEEPSEEK_API_KEY` is missing.
- `BatchProcessor` initializes with provider status from `llm_runtime.yaml`.
- `full_translation` with missing `DEEPSEEK_API_KEY` returns an explicit error and does not silently fall back to local.
- `systemctl --user restart karpathy-kb.service` completed successfully.
- `/health` returns `{"status":"ok"}` after restart.
- `/api/translation/models` returns providers from `llm_runtime.yaml`.
- WebUI online re-translation endpoint returns `missing API key env: DEEPSEEK_API_KEY` when no online key is configured.
- `/api/search?q=LLM%20Harness&qa=true&answer_mode=extractive` returns 200 with `answer_mode=extractive` and about 0.01s latency.
- `/api/search?q=LLM%20Harness&qa=true&answer_mode=llm` returns 200 with `answer_mode=llm`; logs show `QA LLM provider: local_gemma4 / gemma4:e4b`; observed latency about 52.56s on local model.
- `OllamaClient().categorize(...)` compatibility call returns `技术`; logs show `Processor LLM provider: local_gemma4 / gemma4:e4b`.
- URL import smoke test against `https://example.com/?kb_phase4_smoke=...` returned 200 via `/api/documents/url`.
- URL import smoke created a wiki article using `url_import_structure`; generated footer recorded `local_gemma4 / gemma4:e4b`.
- Smoke-test raw/wiki artifacts were moved to `.trash/phase4-url-smoke-20260529T001352Z`, and the search index was rebuilt back to 157 docs.
- Post-cleanup search for `Example Domain` returns no smoke-test document; `/health` remains OK and service is active.

Remaining Phase 4 work:

- Expose provider/model metadata in QA API response and/or WebUI if needed.
- Phase 5 can start WebUI configuration page for non-sensitive provider and flow settings.

## 2026-05-29 Phase 5 Start

Status: complete for the current LLM configuration scope.

Scope:

- Add a WebUI configuration page for non-sensitive LLM provider and flow policy settings.
- API keys must not be shown or saved; WebUI may only display `api_key_env` and whether that env var is configured.

Progress:

- [x] Add `GET /api/llm/config` to return provider and flow config plus secret configured status.
- [x] Add `PATCH /api/llm/config` to update non-sensitive fields in `llm_runtime.yaml`.
- [x] Validate provider names, provider types, env var names, and flow provider references before saving.
- [x] Add sidebar tab `模型配置` / `LLM Settings`.
- [x] Add WebUI provider editor for label/type/model/base_url/api_key_env/timeout.
- [x] Add WebUI flow editor for label/provider order/fallback/online/chunk size/intent/notes.
- [x] Keep API key values out of responses and config writes.
- [x] Add `POST /api/llm/providers/<provider>/test` for provider connectivity tests.
- [x] Show provider test action/result in the LLM Settings provider cards.
- [x] Include QA LLM provider/model metadata in `/api/search?...answer_mode=llm` response and chat badges.
- [x] Add automatic `llm_runtime.yaml` backup before WebUI saves.
- [x] Add `GET /api/llm/config/backups` and restore endpoint for rollback.
- [x] Show recent config backups in the LLM Settings page with restore action.

Verification:

- `python3 -m py_compile scripts/web_ui.py scripts/llm_service.py` passed.
- Flask test client `GET /api/llm/config` returned 3 providers and 12 flows.
- Flask test client `PATCH /api/llm/config` round-trip returned 200 with 3 providers and 12 flows.
- Invalid PATCH with unknown provider returned 400 and did not replace the config.
- `python3 scripts/llm_service.py` still loads `llm_runtime.yaml` successfully after the save path.
- WebUI service restarted successfully; `/health` is OK and service is active.
- `/api/llm/config` shows DeepSeek secrets as unconfigured via `secret_configured=false`, without exposing key values.
- Provider test for `deepseek_pro` returns 500 with `missing API key env: DEEPSEEK_API_KEY`, without exposing a key.
- Provider test for `local_gemma4` returns 200 with content preview `OK`; observed duration about 22.35s.
- LLM QA smoke query returns `llm={flow: qa, provider: local_gemma4, model: gemma4:e4b, status: ok}`; observed latency about 16.68s.
- PATCH save now creates a backup under `backups/llm_runtime/`.
- Restore endpoint restored `llm_runtime_20260529T020809Z_before-webui-save.yaml` successfully and created a `before-restore` backup.
- `GET /api/llm/config/backups` returns recent backups with name/path/size/modified metadata.
- WebUI restarted after backup/restore changes; `/health` is OK and service is active.

## 2026-05-29 Phase 5 Provider CRUD And Ordered Flow Chains

Status: complete.

Scope:

- Complete the WebUI configuration page so providers are not limited to editing pre-existing entries.
- Make flow provider order explicit and reliable for mixed local/online policies.

Progress:

- [x] Add WebUI action to create a new provider with safe local defaults.
- [x] Add WebUI action to delete a provider.
- [x] When deleting a referenced provider, remove it from all flow provider chains and backfill a remaining provider when a flow would otherwise become empty.
- [x] Make provider IDs editable in the provider card.
- [x] On provider ID rename, update all flow references to the new provider ID.
- [x] Validate provider IDs client-side for the same safe name pattern enforced by the backend.
- [x] Replace flow provider multi-select with an ordered provider chain UI.
- [x] Add per-flow provider add/remove/up/down controls.
- [x] Keep backend validation as the source of truth before writing `llm_runtime.yaml`.

Verification:

- `python3 -m py_compile scripts/web_ui.py` passed.
- Flask test client `GET /api/llm/config` returned 3 providers and 12 flows.
- Flask test client added `ui_test_provider`, moved it to the front of the `qa` flow provider chain, and saved via `PATCH /api/llm/config`; response was 200 and the returned `qa.providers[0]` was `ui_test_provider`.
- Flask test client restored the original provider/flow config via `PATCH /api/llm/config`; response was 200.
- WebUI service restarted successfully; `systemctl --user is-active karpathy-kb.service` returned `active`.
- `/health` returned `{"status":"ok"}` after restart.
- `/api/llm/config` returned 3 providers and 12 flows after restore.
- Served WebUI HTML contains the new `addLlmProvider`, `deleteLlmProvider`, `syncProviderName`, and `moveFlowProvider` bindings.
