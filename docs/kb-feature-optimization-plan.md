# Knowledge Base Feature Optimization Plan

Status: Task H in progress as of 2026-05-31.

## Decision

Git-based Windows/Linux green deployment V1 is accepted as the current deployment baseline. Productization and distribution tasks are frozen and moved to the end of the backlog. The active workstream moves back to knowledge-base product and feature optimization.

During implementation, task progress should be recorded here and concise status updates should be sent to the WeChat conversation.

## Core Task Backlog

### 1. System Settings And Environment Configuration

- Add a WebUI settings center for product/runtime configuration.
- Move existing LLM Settings into this settings center.
- Add editable knowledge-base branding: name, title, subtitle, and logo path/upload.
- Add runtime feature switches for menus and APIs.
- Keep UI/runtime settings in `config/webui.yaml`; keep model routing in `llm_runtime.yaml`.

### 2. File Upload End-To-End Reliability

- Treat file upload as an end-to-end product flow, not only an endpoint.
- Verify upload, raw save, parsing, LLM processing, wiki generation, list refresh, and searchability.
- Cover `.txt`, `.md`, `.pdf`, `.docx`, and representative code/text files.
- Surface processing stage, generated wiki path, LLM provider/model, duration, fallback, and concrete errors in API and WebUI.
- Ensure pure online mode does not call local Gemma/Ollama; pure local mode does not call online providers.

### 3. Search And QA Quality

- Improve Chinese keyword search recall and ranking.
- Improve context selection for LLM QA.
- Make extractive vs LLM answer modes clearer in the UI.
- Improve citations, source previews, and answer grounding.

### 4. QA Performance And Runtime Behavior

- Reduce perceived latency for cold or busy local models.
- Improve timeout handling and fallback visibility.
- Show model/provider status and user-facing loading states.
- Review routing policies for local, online, and hybrid QA.

### 5. Import Quality For URL, RSS, WeChat, And Files

- Improve title, summary, tags, category, and entity extraction stability.
- Add clearer retry and recovery behavior for failed imports.
- Make source-specific limitations visible in the UI.
- Avoid misleading menus in environments where RSS/WeChat discovery is unavailable.

### 6. Knowledge Maintenance And Cleanup

- Detect duplicate or near-duplicate documents.
- Recommend related documents.
- Improve internal link suggestions and safe auto-linking.
- Add low-quality article detection and repair suggestions.

### 7. Post-Import Reprocessing

- Support re-summary, re-tagging, re-categorization, and re-translation.
- Support single-document and batch reprocessing.
- Show preview/diff before applying destructive or large content changes.
- Record LLM metadata for each reprocessing pass.

### 8. Audit And Observability Enhancements

- Add filters for LLM audit by provider, model, flow, status, and fallback.
- Add CSV/JSON export for audit data.
- Show per-document generation chain, fallback, duration, and future cost estimates.

### 9. WebUI Usability

- Make search results and document previews feel like a knowledge base, not a plain file list.
- Improve long-task progress, errors, and retry actions.
- Improve mobile/desktop layout for dense operational use.

### 10. Deferred Productization Tasks

- Cross-platform regression script.
- Windows FAQ/troubleshooting expansion.
- Runtime data export/import migration tooling.
- Formal Windows/Linux release archives.
- Windows service startup integration.
- Docker distribution package.

These stay last until the feature optimization workstream stabilizes.

## Current Planned Task A

Task A: System settings center, environment feature switches, branding configuration, and file upload end-to-end validation.

### Scope

- Add `config/webui.yaml` as local runtime UI configuration.
- Add defaults when `config/webui.yaml` is missing.
- Add WebUI APIs to read and save web UI settings.
- Upgrade the current LLM Settings menu item into a broader system settings area.
- Add a Basic Settings panel for knowledge-base name/title/subtitle/logo.
- Add a Feature Switches panel for menu/API availability.
- Keep the current provider/flow editor under the settings area.
- Add backend feature gates for disabled features, not only front-end hidden menus.
- Enhance file upload response details.
- Verify file upload end to end across local, online, and hybrid modes.

### Initial `config/webui.yaml` Shape

```yaml
app:
  name: Sunoxi KB
  title: Sunoxi 知识库
  subtitle: Personal Knowledge Base
  logo: /static/favicon.svg
features:
  chat: true
  graph: true
  documents: true
  upload: true
  url_import: true
  candidates: true
  rss: true
  wechat: true
  llm_settings: true
  llm_audit: true
```

### Task A Subtasks

- [x] Add backend WebUI settings loader with defaults.
- [x] Add `GET /api/webui/config`.
- [x] Add `PATCH /api/webui/config` with validation and backup.
- [x] Add feature-gate helper for backend routes.
- [x] Gate RSS, WeChat, candidates, upload, URL import, graph, LLM settings, and LLM audit routes.
- [x] Refactor navigation so disabled features are hidden.
- [x] Rename the current settings navigation from LLM Settings/模型配置 to System Settings/系统设置.
- [x] Add Basic Settings UI for knowledge-base branding.
- [x] Apply configured branding to document title, sidebar header, and startup output.
- [x] Add Feature Switches UI.
- [x] Keep existing model provider/flow editor inside System Settings.
- [x] Show `file_import_structure` provider chain and active mode near upload controls.
- [x] Make upload API return generated wiki path, processing stage, and LLM metadata.
- [x] Improve upload error messages for unsupported format, file size, parsing failure, missing key, provider failure, and LLM failure.
- [x] Run file upload E2E smoke for `.txt`.
- [x] Run file upload E2E smoke for `.md`.
- [x] Run file upload E2E smoke for `.pdf`.
- [x] Run file upload E2E smoke for `.docx`.
- [x] Verify pure online mode uses only DeepSeek for file upload processing.
- [x] Verify pure local mode uses only local Gemma/Ollama for file upload processing.
- [x] Verify hybrid mode reports the actual provider/fallback path.
- [x] Update progress notes and user-facing docs for settings and upload behavior.

### Implementation Progress

- 2026-05-30: User confirmed Task A scope. Feature switches default to enabled, branding updates should apply immediately in the WebUI, and startup console branding can update on next restart.
- 2026-05-30: Added `config/webui.yaml` runtime config support with defaults and local backup-on-save behavior.
- 2026-05-30: Added WebUI settings APIs: `GET /api/webui/config` and `PATCH /api/webui/config`.
- 2026-05-30: Added backend feature gates for upload, URL import, chat/search, graph, RSS, WeChat, candidates, LLM settings, and LLM audit.
- 2026-05-30: Renamed the settings menu to System Settings / 系统设置 and added Basic Settings plus Feature Switches panels.
- 2026-05-30: Wired configurable branding into the sidebar/header, browser title, and startup console output.
- 2026-05-30: Kept existing LLM provider/flow configuration inside System Settings and gated it behind the `llm_settings` switch.
- 2026-05-30: Added upload panel visibility gates and displayed the active `file_import_structure` provider chain/mode near upload controls.
- 2026-05-30: Enhanced upload API auto-processing results with stage, generated wiki path, and LLM metadata when available.
- 2026-05-30: Smoke verification passed for Python compile, WebUI config API, feature-gated 403 responses, and frontend script syntax.
- 2026-05-30: File upload E2E smoke passed in temporary knowledge-base directories for `.txt`, `.md`, `.pdf`, and `.docx`; each generated wiki output and searchable indexes without polluting the real library.
- 2026-05-30: Upload mode routing verified. Pure local used `local_gemma4 / gemma4:e4b`; pure online selected `deepseek_flash` and failed with `missing API key env: DEEPSEEK_API_KEY` without local fallback; default hybrid reported the actual local provider used.
- 2026-05-30: Improved upload processing failures so missing key/provider/LLM errors are returned in the API response instead of only appearing in backend logs.
- 2026-05-30: Added `docs/webui-settings-and-upload.md` and linked it from the README.
- 2026-05-30: Task A follow-up fixes: chat bubble bot name now uses configured branding; maintenance LLM check now follows the current `maintenance_links` flow instead of hardcoded local Ollama; document retranslation action remains clickable so unavailable model/missing-key errors are shown explicitly.

## Current Planned Task B

Task B: Search and QA quality optimization.

### Scope

- Improve Chinese and mixed Chinese/English keyword recall.
- Make query cleaning, token expansion, and ranking easier to inspect.
- Improve QA context selection so answers cite stronger source snippets.
- Make extractive vs LLM answer mode behavior clearer in WebUI responses.
- Add focused smoke cases for common questions such as Harness, 横纵分析法, model switching, and uploaded documents.

### Task B Subtasks

- [x] Audit current `WikiSearcher.search()` scoring and tokenization behavior.
- [x] Add query diagnostics in search/QA responses for debugging ranking problems.
- [x] Improve query token expansion for Chinese compound terms and mixed English terms.
- [x] Improve result snippets so matched content is visible, not only document opening text.
- [x] Improve QA context scoring and citations.
- [x] Add focused search/QA smoke tests against the current wiki corpus.

### Implementation Progress

- 2026-05-30: Task B started after Task A follow-up fixes. Initial inspection target: `scripts/search.py`, `scripts/qa.py`, and `/api/search` response shape.
- 2026-05-30: Search/QA baseline run covered Harness, 横纵分析法, CC Switch, 模型切换, and Hermes 多 Agent queries. Main issues found: duplicate same-title search results, previews showing document openings instead of matched snippets, crawler metadata leaking into extractive QA, and noisy question words affecting Chinese queries.
- 2026-05-30: First Task B fix landed: search now cleans source body/frontmatter noise, expands Chinese/mixed query tokens, deduplicates same-title results, returns matched source snippets plus query diagnostics, and WebUI search results use matched snippets when available.
- 2026-05-30: Extractive QA now strips crawler metadata and prioritizes relevant source snippets before generated summary/keypoint text, improving answers for queries such as `横纵分析法是什么`.
- 2026-05-30: Added reusable non-LLM smoke checks in `scripts/smoke_search_qa.py` for Harness, 横纵分析法, CC Switch, and model switching queries. The script rebuilds/loads the current wiki search index, verifies top search hits, matched snippets, extractive QA grounding, and metadata-noise cleanup.
- 2026-05-30: `/api/search` diagnostics now include expanded keyword query tokens so ranking problems can be inspected from the WebUI/API response without attaching a debugger.
- 2026-05-30: QA responses now carry matched snippets and query diagnostics through to the chat UI, with the QA cache signature bumped so older cached answers do not hide the new metadata. Source cards show the actual matched passage used for grounding, and the chat metadata badges show answer mode, latency, citations, provider/model when present, and core query tokens.
- 2026-05-30: Search/QA smoke now includes a synthetic uploaded-document case in an isolated temporary knowledge base. This verifies that upload-style wiki pages are searchable, extractive QA can answer from their source body, and ingestion metadata such as hashes/extraction method does not leak into answers.

## Current Planned Task C

Task C: QA performance and runtime behavior.

### Scope

- Reduce surprises around local/online model latency and timeout behavior.
- Make provider timeout settings actually affect runtime calls.
- Improve user-facing QA loading, fallback, and error visibility.
- Keep extractive QA fast and non-LLM by default; keep LLM QA explicitly user-triggered.
- Add focused smoke checks for routing/timeout metadata where possible without requiring live providers.

### Task C Subtasks

- [x] Audit provider timeout wiring for Ollama and OpenAI-compatible clients.
- [x] Pass configured `timeout_sec` from `llm_runtime.yaml` into provider HTTP calls.
- [x] Surface provider timeout/fallback failures more clearly in WebUI QA responses.
- [x] Add a lightweight runtime smoke for provider config metadata without live network calls.
- [x] Review QA loading states and retry guidance for slow/failing LLM mode.

### Implementation Progress

- 2026-05-30: Task C started after Task B regression baseline landed. First issue found: provider `timeout_sec` was editable in settings and present in `llm_runtime.yaml`, but both Ollama and OpenAI-compatible clients still used hardcoded request timeouts.
- 2026-05-30: Provider timeout wiring fixed: `LLMService` now passes each provider's configured `timeout_sec` into `OllamaProvider` and `OpenAIProvider`, and both clients use that value for HTTP calls.
- 2026-05-30: Added `scripts/smoke_llm_runtime.py` to validate provider client construction and timeout wiring without contacting live Ollama/DeepSeek services.
- 2026-05-30: WebUI chat now surfaces LLM QA runtime status more explicitly: provider/model badge turns error-colored on failures, fallback path is shown when present, and model errors such as timeout or missing key are displayed inline in the answer bubble.
- 2026-05-30: LLM QA loading state now shows the active `qa` provider chain when model generation is selected, so users can see which local/online route is being attempted before a slow call completes.

## Current Planned Task D

Task D: Import quality for URL, RSS, WeChat, and files.

### Scope

- Improve title, summary, tags, category, and entity extraction stability.
- Normalize LLM-generated metadata before saving wiki files.
- Add clearer retry and recovery behavior for failed imports.
- Make source-specific limitations visible in the UI.
- Avoid misleading menus in environments where RSS/WeChat discovery is unavailable.

### Task D Subtasks

- [x] Normalize generated category, tags, and entities before wiki save.
- [x] Harden wiki frontmatter quoting for imported documents.
- [x] Add non-network smoke for import metadata quality.
- [x] Improve title cleanup across URL/RSS/WeChat/file import paths.
- [x] Add clearer failed-import retry/recovery state in WebUI.
- [x] Surface source-specific limitations and disabled-environment guidance in UI.

### Implementation Progress

- 2026-05-30: Task D started after user confirmed the recommended next mainline. First target is the shared import processor because it affects file, URL, RSS, and reviewed candidate imports downstream.
- 2026-05-30: Added normalization for LLM-generated categories, tags, and entities. Verbose or mixed category outputs such as `分类：技术文章 / AI 工具` now map to stable categories such as `技术`; entity/tag lists are split, cleaned, deduplicated, and capped.
- 2026-05-30: Hardened generated wiki frontmatter by YAML-quoting title, category, date, model, source, and tags, reducing risk from Windows paths, colons, quotes, and multiline LLM outputs.
- 2026-05-30: Added `scripts/smoke_import_quality.py`, a no-network smoke test with a dirty fake LLM response that verifies category normalization, entity deduplication, tag insertion, and valid YAML frontmatter.
- 2026-05-30: Extended the same metadata normalization to the batch import path used by uploaded files and URL-imported raw pages. Batch import now cleans title suffixes, normalizes generated category/entities/tags, safely quotes YAML tags, and is covered by the import-quality smoke test.
- 2026-05-30: Added shared raw-import title cleanup helpers and applied them to URL, RSS, and WeChat raw save paths. Titles and generated filenames now strip common source suffixes before the batch processor sees them.
- 2026-05-30: Added failed-import recovery metadata and a retry endpoint for raw files. Upload and URL import failures now keep the raw path plus retry hint, and the WebUI shows a retry panel that can re-run processing after model config/dependency fixes.
- 2026-05-30: RSS and WeChat subscription pages now show source-specific environment guidance. RSS explains outbound feed access, candidate-pool behavior, and retryable network/feed errors; WeChat explains public-search/redirect limitations and recommends direct article URLs when possible.

## Current Planned Task E

Task E: Knowledge maintenance and cleanup.

### Scope

- Detect duplicate or near-duplicate documents.
- Recommend related documents and missing cross-links.
- Keep auto-linking conservative and explain why a suggestion is or is not safe to apply.
- Surface low-quality or repairable documents in maintenance views.

### Task E Subtasks

- [x] Add duplicate document detection to the knowledge association report.
- [x] Surface duplicate counts in WebUI association and maintenance feedback.
- [x] Add a focused smoke test for duplicate detection.
- [x] Improve low-quality document report visibility in the Docs tab.
- [x] Add safer review-first cleanup actions for duplicate groups.

### Implementation Progress

- 2026-05-30: Task E started after Task D first pass completed. First batch adds duplicate detection to the existing association/maintenance pipeline instead of creating a separate maintenance flow.
- 2026-05-30: Association reports now detect duplicate groups by exact content fingerprint, repeated source URL, and normalized title. Reports include duplicate group count, affected document count, reason, and a conservative keep suggestion based on newest/largest document.
- 2026-05-30: WebUI association badges and maintenance completion messages now include duplicate group counts so cleanup problems are visible after normal maintenance runs.
- 2026-05-30: Added `scripts/smoke_association_report.py`, which builds an isolated temporary wiki and verifies duplicate group summary, reason, affected docs, and keep suggestion without touching the real knowledge base.
- 2026-05-30: Docs tab quality visibility improved with a warning summary, issue breakdown, `only repairable` filter, and per-document issue labels for missing summaries, keypoints, entities, or scan failures.
- 2026-05-30: Duplicate groups in the association report now provide review-first buttons for every affected document, with the suggested keep document highlighted. Cleanup remains manual until a safe diff/trash flow is added.

## Current Planned Task F

Task F: Post-import reprocessing.

### Scope

- Support re-summary, re-tagging, re-categorization, and re-translation.
- Start with single-document review-first flows before batch operations.
- Show preview/diff before applying content changes.
- Record LLM/rule metadata for each reprocessing pass.

### Task F Subtasks

- [x] Make rule-based quality repair support dry-run preview.
- [x] Add WebUI confirmation before applying single-document quality repair.
- [x] Add explicit single-document re-summary/re-keypoints/re-entities action metadata.
- [x] Add preview/diff UI for LLM retranslation.
- [x] Add batch reprocessing only after single-document flows are safe.

### Implementation Progress

- 2026-05-30: Task F started after Task E first pass completed. First change targets the existing quality repair action so re-summary/re-keypoints/re-entities no longer writes immediately.
- 2026-05-30: `POST /api/documents/<path>/repair-quality` now supports `dry_run: true`, returning planned replacement sections and before/after quality status without modifying the document.
- 2026-05-30: WebUI single-document quality repair now requests a dry-run preview first and asks for confirmation with issue labels plus generated summary preview before applying changes.
- 2026-05-30: `POST /api/documents/<path>/translate` now supports `dry_run: true`, returning generated retranslation previews and LLM metadata without writing. WebUI retranslation now previews first and asks for confirmation before applying.
- 2026-05-30: Applied rule-based quality repairs now write `quality_repair` frontmatter metadata with method, repaired issue list, status, and timestamp for later audit.
- 2026-05-31: Batch quality repair now also supports `dry_run: true`. The WebUI one-click quality repair first previews the planned document list and issue labels, then asks for confirmation before applying changes.

## Current Planned Task G

Task G: Audit and observability enhancements.

### Scope

- Add filters for LLM audit by provider, model, flow, status, fallback, and retranslation state.
- Add JSON/CSV export for audit data.
- Keep audit useful for deployment debugging without exposing secrets.

### Task G Subtasks

- [x] Add backend LLM audit filters.
- [x] Add CSV/JSON export for filtered LLM audit data.
- [x] Add WebUI controls for LLM audit filtering and export.
- [x] Surface rule-based `quality_repair` metadata in audit.
- [x] Add per-document generation chain view.

### Implementation Progress

- 2026-05-31: Task G started after Task F first pass. `/api/llm/audit` now supports filters for flow, provider, model, status, missing metadata, fallback-only, and retranslated-only.
- 2026-05-31: LLM audit supports filtered export with `format=csv` and JSON responses using the same filters.
- 2026-05-31: System Settings LLM audit panel now includes filter controls plus JSON/CSV export buttons.
- 2026-05-31: LLM audit items now include `quality_repair` metadata plus a compact `generation_chain` covering import LLM metadata, retranslation, rule-based quality repair, and legacy translation. The audit table and CSV export expose these fields.

## Current Planned Task H

Task H: WebUI usability polish.

### Scope

- Make document preview more useful as an operational knowledge-base surface.
- Reduce switching between document preview, quality status, and audit panels.
- Keep dense document lists readable while preserving repair/retry actions.

### Task H Subtasks

- [x] Add document quality and LLM metadata to the document preview API.
- [x] Show quality, import LLM, retranslation, and quality repair badges in the document preview drawer.
- [x] Improve search result and document list actions.
- [x] Add audit table to document preview reverse navigation.
- [x] Add smoke regression coverage for audit/export, preview metadata, and quality repair dry-run.
- [x] Review mobile drawer layout for dense metadata.

### Implementation Progress

- 2026-05-31: Document preview API now returns a `meta` object with title, category, quality status, import LLM metadata, retranslation metadata, and rule-based quality repair metadata.
- 2026-05-31: Document preview drawer now shows compact badges for quality state, import LLM chain, retranslation, and quality repair before the markdown body/related-doc recommendations.
- 2026-06-01: Search/QA source cards now expose preview, document-list focus, and audit actions. Document list rows now expose preview, quality repair, and audit actions without relying only on row clicks.
- 2026-06-01: LLM audit rows now have an explicit open action that passes the audit item into the document preview drawer. The drawer shows a compact generation-chain audit panel when opened from audit context.
- 2026-06-01: Added `scripts/smoke_webui_audit.py` to cover WebUI action tokens, document preview metadata, LLM audit filters/export, generation-chain presence, and quality repair dry-run.
- 2026-06-01: Mobile layout hardening pass: source cards use full width on small screens, document rows wrap before narrow overflow, row actions align to the trailing edge, and the preview drawer header stacks title/actions on small screens.
- 2026-06-01: QA answer language now follows the question language. Extractive answers use Chinese or English section/source labels, LLM QA prompts are language-aware, cache keys include response language, `/api/search?qa=true` returns `response_language`, and search/QA smoke coverage includes an English bilingual-answer case.
- 2026-06-01: QA model-generated answers no longer use the persistent QA cache; only extractive answers remain cacheable. Existing `qa_cache.json` was backed up and cleared to remove stale bad answers.
