# LLM Flow Audit

Date: 2026-05-28

This audit records the current state and Phase 4 migration status for LLM-related flows.

## Current LLM-Adjacent Flows

### URL Import

- Entry point: `scripts/web_ui.py` route `POST /api/documents/url`
- Fetch layer: `WebCollector.fetch()`
- Import layer: `AutoImporter.process_file()`
- Processing layer: `BatchProcessor.process_file()`
- Phase 4 model path: `LLMService.chat("url_import_structure", ...)`
- Config source: `llm_runtime.yaml` flow `url_import_structure`
- Current policy: local Gemma4 first, DeepSeek Flash fallback.
- Current notes:
  - Phase 5 WebUI policy editing is complete for the current LLM configuration scope.
  - Phase 6 writes import provider/model/flow metadata into structured frontmatter.
  - Historical wiki documents were backfilled with `legacy_inferred` audit metadata.

### File Upload Import

- Entry point: `scripts/web_ui.py` upload routes
- Import layer: `AutoImporter.process_file()`
- Processing layer: `BatchProcessor.process_file()`
- Phase 4 model path: `LLMService.chat("file_import_structure", ...)`
- Config source: `llm_runtime.yaml` flow `file_import_structure`
- Current policy: local Gemma4 first, DeepSeek Flash fallback.
- Current notes: same as URL import.

### RSS Candidate Discovery And Preview

- Entry points:
  - `scripts/rss_sync.py`
  - `scripts/rss_review_queue.py`
  - WebUI candidate routes in `scripts/web_ui.py`
- Candidate translation: `CandidateTranslator`
- Phase 4 model path:
  - `LLMService.json_chat("candidate_preview", ...)`
  - `LLMService.chat("full_translation", ...)`
- Config source:
  - `llm_runtime.yaml`
  - `translation_terms.json`
- Current notes:
  - Candidate sidecar JSON now records preview provider/model/result metadata.
  - Full translation records provider/model and chunk metadata for new full-translation runs.

### Candidate Import

- Entry point: `CandidateManager.import_candidate()`
- Translation option: `translate=True`
- Processing layer: candidate manager plus import/maintenance paths
- Phase 4 migration:
  - Candidate translation now uses `LLMService`.
  - Final processing through `AutoImporter -> BatchProcessor` now uses `LLMService`.
- Current notes:
  - Phase 6 import payload now exposes the translation decision, preview provider/model, full-translation provider/model/chunks, and final processing provider/model when available.
  - Historical imported candidates may not have this metadata until re-imported or backfilled.

### Manual Re-translation

- Entry point: WebUI route `POST /api/documents/<path>/translate`
- Phase 4 model path:
  - User-selectable `online` or `local`, mapped to provider ids from `llm_runtime.yaml`.
  - Uses `LLMService.chat("retranslation", ..., provider_name=...)`.
- Config source: `llm_runtime.yaml`
- Issues:
  - It currently rejects missing online API keys explicitly, which is correct for quality-sensitive translation.

### QA

- Entry point: `scripts/qa.py`
- Default answer path: extractive answer, no chat LLM.
- Phase 4 LLM answer path:
  - `answer_mode=llm` uses `LLMService.chat("qa", ...)`
  - Config source: `llm_runtime.yaml` flow `qa`
  - Current policy: local Gemma4 first, DeepSeek Pro fallback.
- Issues:
  - Local LLM answer generation is slow when model is cold or busy; observed smoke-test latency was about 52.56s.
  - QA response JSON now exposes provider/model metadata for LLM answers.

### Processor-Based Summary, Category, Keypoints, Entities

- Entry point: `scripts/processor.py`
- Phase 4 provider layer: `LLMService`
- Compatibility class name: `OllamaClient` remains for older scripts, but internally calls `LLMService`.
- Current flow mapping:
  - `summarize()` -> `processor_summary`
  - `extract_keypoints()` -> `processor_keypoints`
  - `categorize()` -> `processor_category`
  - `extract_entities()` -> `entity_extraction`
- Issues:
  - Class names still imply Ollama for backward compatibility.
  - This processor path is now mostly a compatibility path; live URL/file import uses `BatchProcessor`.

### Maintenance

- Entry point: `scripts/maintenance.py`
- Steps:
  - Quality/lint checks
  - Linker rebuild
  - Search index rebuild
  - Optional embedding rebuild
- Current model usage:
  - Local Ollama health check only
  - Linker is primarily rule/entity/similarity based
  - Search index does not use LLM
  - Embedding rebuild uses embedding model, not chat LLM
- Issues:
  - If LLM-assisted linking is added later, it needs a dedicated flow policy.

### Wiki Linker And Association Report

- Entry points:
  - `scripts/wiki_linker.py`
  - `scripts/association_report.py`
- Current model usage: no chat LLM by default
- Approach: frontmatter/content parsing, entities, tags, similarity, Obsidian links
- Issues:
  - Auto-linking can damage text if not carefully scoped; LLM use should be explicit and policy-driven if added.

### Search And Semantic Search

- Entry points:
  - `scripts/search.py`
  - `scripts/embeddings.py`
  - WebUI search routes
- Current model usage:
  - Full-text search: no LLM
  - Semantic search: embedding model via sentence-transformers
- Issues:
  - Embedding provider is separate from chat LLM and should remain separate unless a future embedding service abstraction is needed.

## Immediate Design Implications

- The project needs a shared LLM call layer, but not one global usage policy.
- Every business flow needs its own policy because quality, cost, volume, latency, and privacy requirements differ.
- Fallback must be explicit in metadata and UI, especially for quality-sensitive flows like translation.
- Provider config must be non-sensitive. API keys must stay in environment variables or a secret manager.
