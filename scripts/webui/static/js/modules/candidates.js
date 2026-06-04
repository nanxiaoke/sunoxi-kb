(function (global) {
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

    global.KBCandidates = {
        batchTranslatePreview,
        loadCandidates,
        restoreCandidate,
        skipCandidate,
        translateCandidate
    };
})(window);
