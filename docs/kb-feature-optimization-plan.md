# Knowledge Base Feature Optimization Plan

Status: Task B in progress as of 2026-05-30.

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
