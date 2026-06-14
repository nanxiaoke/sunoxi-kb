(function (global) {
    async function repairDocQuality(ctx, path) {
        ctx.repairingQuality.value = true;
        try {
            const repairUrl = `/api/documents/${encodeURIComponent(path)}/repair-quality`;
            const preview = await KBApi.sendJson(repairUrl, { dry_run: true }, { method: 'POST' });
            if (!preview.changed) {
                ctx.showToast('文档无需修复', 'info');
                return;
            }
            const planned = ctx.issueText(preview.before?.issues || []);
            const summaryPreview = (preview.sections?.summary || '').slice(0, 160);
            if (!confirm(`确认应用质量修复？\n文档：${path}\n问题：${planned || '未知'}\n摘要预览：${summaryPreview}`)) return;

            const data = await KBApi.sendJson(repairUrl, { dry_run: false }, { method: 'POST' });
            ctx.showToast(data.changed ? '文档质量已修复' : '文档无需修复', data.changed ? 'success' : 'info');
            await ctx.loadDocs();
            if (ctx.previewDocPath.value === path) await ctx.previewDoc(path);
        } catch (e) {
            ctx.showToast(`质量修复失败: ${e.message}`, 'error');
        } finally {
            ctx.repairingQuality.value = false;
        }
    }

    async function repairAllQuality(ctx) {
        if (!ctx.qualityBadCount.value) return;
        ctx.repairingQuality.value = true;
        try {
            const preview = await KBApi.sendJson('/api/quality/repair', { limit: 50, dry_run: true }, { method: 'POST' });
            const sample = (preview.results || []).slice(0, 5).map(x => `${x.path}: ${ctx.issueText(x.before?.issues || [])}`).join('\n');
            if (!preview.planned) {
                ctx.showToast('没有需要修复的文档', 'info');
                return;
            }
            if (!confirm(`确认批量应用质量修复？\n计划修复：${preview.planned} 篇\n\n${sample}`)) return;

            const data = await KBApi.sendJson('/api/quality/repair', { limit: 50, dry_run: false }, { method: 'POST' });
            ctx.showToast(`已修复 ${data.repaired || 0} 个文档`, 'success');
            await ctx.loadDocs();
        } catch (e) {
            ctx.showToast(`批量修复失败: ${e.message}`, 'error');
        } finally {
            ctx.repairingQuality.value = false;
        }
    }

    async function runMaintenance(ctx) {
        if (ctx.isMaintaining.value) return;
        ctx.isMaintaining.value = true;
        ctx.maintenanceReport.value = null;
        ctx.showToast('正在维护知识库：按当前 LLM 模式检查 / 重建链接 / lint / 索引...', 'info', 5000);
        try {
            const report = await KBApi.sendJson('/api/maintenance', { update_embeddings: false }, { method: 'POST' });
            ctx.maintenanceReport.value = report;
            const lint = report.summary?.lint || {};
            const model = report.summary?.model || {};
            const assoc = report.summary?.associations || {};
            const msg = `维护完成：模型 ${model.model || 'local'} ${model.status || ''}，坏链 ${lint.broken_links ?? '?'}，孤立页 ${lint.orphans ?? '?'}，重复组 ${assoc.duplicate_groups ?? '?'}，真实文档 ${report.summary?.real_wiki_docs ?? '?'}`;
            ctx.showToast(msg, report.status === 'ok' ? 'success' : 'warning', 6000);
            await ctx.loadDocs();
            if (ctx.activeTab.value === 'graph') await ctx.nextTick(() => ctx.initGraph());
        } catch (e) {
            ctx.showToast(`维护失败: ${e.message}`, 'error', 6000);
        } finally {
            ctx.isMaintaining.value = false;
        }
    }

    async function loadAssociations(ctx, rebuild = false) {
        ctx.loadingAssociations.value = true;
        try {
            ctx.associationReport.value = await KBApi.requestJson('/api/associations', { method: rebuild ? 'POST' : 'GET' });
            if (rebuild) ctx.showToast('知识关联报告已重建', 'success');
        } catch (e) {
            ctx.showToast(`知识关联报告失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.loadingAssociations.value = false;
        }
    }

    function createActions(ctx) {
        return {
            repairDocQuality: async (path) => repairDocQuality(ctx, path),
            repairAllQuality: async () => repairAllQuality(ctx),
            runMaintenance: async () => runMaintenance(ctx),
            loadAssociations: async (rebuild = false) => loadAssociations(ctx, rebuild)
        };
    }

    global.KBMaintenance = {
        createActions,
        loadAssociations,
        repairAllQuality,
        repairDocQuality,
        runMaintenance
    };
})(window);
