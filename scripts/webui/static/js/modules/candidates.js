(function (global) {
    let batchImportPollTimer = null;

    async function loadCandidates(ctx) {
        if (ctx.loadingCandidates.value) return;
        ctx.loadingCandidates.value = true;
        try {
            const params = new URLSearchParams({ sort: 'quality' });
            if (ctx.candidateTierFilter.value) params.set('tier', ctx.candidateTierFilter.value);
            if (ctx.candidateTypeFilter.value) params.set('type', ctx.candidateTypeFilter.value);
            if (ctx.candidateIncludeSkipped.value) params.set('include_skipped', 'true');
            const data = await KBApi.getJson(`/api/candidates?${params.toString()}`);
            ctx.candidates.value = data.candidates || [];
            ctx.candidateSummary.value = data.summary || null;
        } catch (e) {
            ctx.showToast(`加载候选失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.loadingCandidates.value = false;
        }
    }

    async function translateCandidate(ctx, id, options = {}) {
        if (!id) return;
        ctx.translatingCandidateId.value = id;
        ctx.showToast('正在生成候选池中文预览...', 'info', 5000);
        try {
            await KBApi.sendJson(
                `/api/candidates/${encodeURIComponent(id)}/translate`,
                { force: false, preview: true },
                { method: 'POST' }
            );
            ctx.showToast('中文预览已生成，质量评分会优先使用中文内容', 'success', 5000);
            await loadCandidates(ctx);
            if (options.refreshPreview) await ctx.previewCandidate(id);
        } catch (e) {
            ctx.showToast(`预翻译失败: ${e.message}`, 'error', 6000);
        } finally {
            ctx.translatingCandidateId.value = '';
        }
    }

    async function batchTranslatePreview(ctx) {
        if (!confirm('批量补齐当前筛选条件下最多20篇候选的中文预览？')) return;
        ctx.batchTranslatingPreview.value = true;
        ctx.showToast('正在批量生成中文预览...', 'info', 6000);
        try {
            const data = await KBApi.sendJson(
                '/api/candidates/translate-preview',
                {
                    limit: 20,
                    tier: ctx.candidateTierFilter.value,
                    type: ctx.candidateTypeFilter.value,
                    force: false
                },
                { method: 'POST' }
            );
            ctx.showToast(`批量预翻译完成：${data.translated || 0} 篇，失败 ${data.failed?.length || 0} 篇`, 'success', 7000);
            await loadCandidates(ctx);
        } catch (e) {
            ctx.showToast(`批量预翻译失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.batchTranslatingPreview.value = false;
        }
    }

    async function skipCandidate(ctx, id) {
        const reason = prompt('跳过原因（可选）', '不导入');
        if (reason === null) return;
        try {
            await KBApi.sendJson(`/api/candidates/${encodeURIComponent(id)}/skip`, { reason }, { method: 'POST' });
            ctx.showToast('已跳过候选', 'success');
            if (ctx.previewMode.value === 'candidate') ctx.closePreview();
            await loadCandidates(ctx);
        } catch (e) {
            ctx.showToast(`跳过失败: ${e.message}`, 'error');
        }
    }

    async function restoreCandidate(ctx, id) {
        if (!confirm('恢复这个已跳过候选？恢复后会重新出现在默认候选池。')) return;
        try {
            const data = await KBApi.requestJson(`/api/candidates/${encodeURIComponent(id)}/restore`, { method: 'POST' });
            ctx.showToast(data.restored ? '已恢复候选' : (data.message || '候选无需恢复'), data.restored ? 'success' : 'info');
            await loadCandidates(ctx);
        } catch (e) {
            ctx.showToast(`恢复失败: ${e.message}`, 'error');
        }
    }

    function setCandidateEditForm(ctx, item) {
        ctx.candidateEditItem.value = item;
        ctx.candidateEditOriginalTitle.value = item.title || '';
        ctx.candidateEditForm.id = item.id;
        ctx.candidateEditForm.title = item.review_title || item.translated_title || item.title || '';
        ctx.candidateEditForm.category = item.review_category || '技术';
        ctx.candidateEditForm.tagsText = (item.review_tags?.length ? item.review_tags : (item.translated_topics || item.translation?.topics || [])).join(', ');
        ctx.candidateEditForm.notes = item.edited_metadata?.notes || '';
    }

    function editCandidate(ctx, item) {
        setCandidateEditForm(ctx, item);
        ctx.candidateEditOpen.value = true;
    }

    function closeCandidateEdit(ctx) {
        ctx.candidateEditOpen.value = false;
        ctx.savingCandidateEdit.value = false;
        ctx.candidateEditItem.value = null;
    }

    function candidateReviewPayload(ctx) {
        return {
            title: ctx.candidateEditForm.title,
            category: ctx.candidateEditForm.category,
            tags: ctx.candidateEditForm.tagsText,
            notes: ctx.candidateEditForm.notes
        };
    }

    async function saveCandidateEdit(ctx) {
        if (!ctx.candidateEditForm.id) return;
        ctx.savingCandidateEdit.value = true;
        try {
            await KBApi.sendJson(
                `/api/candidates/${encodeURIComponent(ctx.candidateEditForm.id)}/metadata`,
                candidateReviewPayload(ctx),
                { method: 'PATCH' }
            );
            ctx.showToast('审核信息已保存，导入时会优先使用', 'success', 5000);
            closeCandidateEdit(ctx);
            await loadCandidates(ctx);
        } catch (e) {
            ctx.showToast(`保存审核信息失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.savingCandidateEdit.value = false;
        }
    }

    async function saveCandidateReviewInline(ctx) {
        if (!ctx.candidateEditForm.id) return;
        ctx.savingCandidateEdit.value = true;
        try {
            await KBApi.sendJson(
                `/api/candidates/${encodeURIComponent(ctx.candidateEditForm.id)}/metadata`,
                candidateReviewPayload(ctx),
                { method: 'PATCH' }
            );
            ctx.showToast('审核信息已保存，导入时会优先使用', 'success', 5000);
            await loadCandidates(ctx);
            await ctx.previewCandidate(ctx.candidateEditForm.id);
        } catch (e) {
            ctx.showToast(`保存审核信息失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.savingCandidateEdit.value = false;
        }
    }

    async function loadBatchImportStatus(ctx) {
        const job = await KBApi.getJson('/api/candidates/batch-import/status');
        ctx.batchImportJob.value = job;
        ctx.batchImportingA.value = !!job.running;
        return job;
    }

    function startBatchImportPolling(ctx) {
        if (batchImportPollTimer) clearInterval(batchImportPollTimer);
        batchImportPollTimer = setInterval(async () => {
            try {
                const job = await loadBatchImportStatus(ctx);
                if (!job.running) {
                    clearInterval(batchImportPollTimer);
                    batchImportPollTimer = null;
                    if (job.status === 'done') {
                        const result = job.result || {};
                        const maint = result.maintenance?.status ? `，维护状态：${result.maintenance.status}` : '';
                        ctx.showToast(`队列导入完成: ${result.imported || 0}/${result.total || 0} 成功，失败 ${result.errors || 0}${maint}`, 'success', 10000);
                        await loadCandidates(ctx);
                    } else if (job.status === 'error') {
                        ctx.showToast(`队列导入失败: ${job.error || '未知错误'}`, 'error', 10000);
                    }
                }
            } catch (e) {
                // Polling should stay quiet unless the final job reports an error.
            }
        }, 5000);
    }

    async function batchImportA(ctx) {
        const limit = Math.max(1, Math.min(Number(ctx.batchImportLimit.value) || 20, 200));
        const maxRetries = Math.max(0, Math.min(Number(ctx.batchImportRetries.value) || 0, 5));
        if (!confirm(`确认启动 A 级候选队列导入？\n数量：${limit} 篇\n失败自动重试：${maxRetries} 次\n完成后统一跑轻量维护（不重建语义向量）。`)) return;
        ctx.batchImportingA.value = true;
        ctx.showToast('队列导入任务已提交，后台串行处理，可在进度卡片查看状态。', 'info', 10000);
        try {
            const data = await KBApi.sendJson(
                '/api/candidates/batch-import',
                {
                    tier: 'A',
                    limit,
                    max_retries: maxRetries,
                    retry_delay_sec: 10,
                    run_maintenance: true,
                    update_embeddings: false
                },
                { method: 'POST' }
            );
            ctx.batchImportJob.value = data.job || { status: 'started', running: true };
            startBatchImportPolling(ctx);
        } catch (e) {
            ctx.batchImportingA.value = false;
            ctx.showToast(`队列导入启动失败: ${e.message}`, 'error', 9000);
        }
    }

    async function batchSkipLowQuality(ctx) {
        const tier = ctx.candidateTierFilter.value || 'C,D';
        if (!confirm(`将批量跳过当前来源过滤下的 ${tier || 'C,D'} 候选。此操作可在 candidate_state.json 中追溯，但会从默认候选池隐藏。继续？`)) return;
        const code = prompt('二次确认：请输入 SKIP_LOW_QUALITY');
        if (code !== 'SKIP_LOW_QUALITY') {
            ctx.showToast('确认码不匹配，已取消', 'info');
            return;
        }
        ctx.batchSkippingCandidates.value = true;
        try {
            const data = await KBApi.sendJson(
                '/api/candidates/batch-skip',
                {
                    tier,
                    type: ctx.candidateTypeFilter.value,
                    confirm: code,
                    reason: 'WebUI批量跳过低质量候选'
                },
                { method: 'POST' }
            );
            ctx.showToast(`已批量跳过 ${data.skipped || 0} 篇候选`, 'success', 7000);
            await loadCandidates(ctx);
        } catch (e) {
            ctx.showToast(`批量跳过失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.batchSkippingCandidates.value = false;
        }
    }

    async function importCandidate(ctx, id) {
        if (!confirm('确认导入这篇候选文章？A/B候选会复用/生成中文译文，并自动维护知识库。')) return;
        ctx.importingCandidateId.value = id;
        ctx.showToast('正在导入候选文章，可能会生成全文译文并维护知识库...', 'info', 6000);
        try {
            const data = await KBApi.sendJson(
                `/api/candidates/${encodeURIComponent(id)}/import`,
                { process: true, run_maintenance: true, translate: true },
                { method: 'POST' }
            );
            const wikiPath = data.wiki_path || data.processed?.wiki_path || '';
            const searchQuery = (data.validation?.checks?.edited_title_applied && data.validation?.path)
                ? data.validation.path
                : (wikiPath ? wikiPath.split('/').pop().replace(/_[a-f0-9]{8}\.md$/, '').replace(/\.md$/, '') : '');
            ctx.lastImportResult.value = { ...data, wiki_path: wikiPath, search_query: searchQuery };
            if (ctx.previewMode.value === 'candidate') ctx.closePreview();
            ctx.showToast('候选文章已导入知识库，可继续查看文档/搜索验证', 'success', 8000);
            await loadCandidates(ctx);
            await ctx.loadDocs();
            ctx.stats.value = await KBApi.getJson('/api/stats');
        } catch (e) {
            ctx.showToast(`导入失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.importingCandidateId.value = '';
        }
    }

    global.KBCandidates = {
        batchTranslatePreview,
        batchImportA,
        batchSkipLowQuality,
        closeCandidateEdit,
        editCandidate,
        importCandidate,
        loadBatchImportStatus,
        loadCandidates,
        restoreCandidate,
        saveCandidateEdit,
        saveCandidateReviewInline,
        setCandidateEditForm,
        skipCandidate,
        startBatchImportPolling,
        translateCandidate
    };
})(window);
