# Knowledge Base Feature Optimization Plan

Status: planning, pending user confirmation on 2026-05-30.

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

- [ ] Add backend WebUI settings loader with defaults.
- [ ] Add `GET /api/webui/config`.
- [ ] Add `PATCH /api/webui/config` with validation and backup.
- [ ] Add feature-gate helper for backend routes.
- [ ] Gate RSS, WeChat, candidates, upload, URL import, graph, LLM settings, and LLM audit routes.
- [ ] Refactor navigation so disabled features are hidden.
- [ ] Rename the current settings navigation from LLM Settings/模型配置 to System Settings/系统设置.
- [ ] Add Basic Settings UI for knowledge-base branding.
- [ ] Apply configured branding to document title, sidebar header, and startup output.
- [ ] Add Feature Switches UI.
- [ ] Keep existing model provider/flow editor inside System Settings.
- [ ] Show `file_import_structure` provider chain and active mode near upload controls.
- [ ] Make upload API return generated wiki path, processing stage, and LLM metadata.
- [ ] Improve upload error messages for unsupported format, file size, parsing failure, missing key, provider failure, and LLM failure.
- [ ] Run file upload E2E smoke for `.txt`.
- [ ] Run file upload E2E smoke for `.md`.
- [ ] Run file upload E2E smoke for `.pdf`.
- [ ] Run file upload E2E smoke for `.docx`.
- [ ] Verify pure online mode uses only DeepSeek for file upload processing.
- [ ] Verify pure local mode uses only local Gemma/Ollama for file upload processing.
- [ ] Verify hybrid mode reports the actual provider/fallback path.
- [ ] Update progress notes and user-facing docs for settings and upload behavior.

### Confirmation Needed

- Confirm the Task A scope before implementation starts.
- Confirm whether feature switches should default to all enabled for backward compatibility. Current recommendation: yes.
- Confirm whether branding changes should apply immediately after save without a server restart. Current recommendation: yes for WebUI-visible text; startup console text updates on next restart.
