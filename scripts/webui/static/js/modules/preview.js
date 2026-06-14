(function (global) {
    function resetPreviewState(ctx) {
        ctx.isEditingDoc.value = false;
        ctx.previewRelated.value = [];
        ctx.previewAssociation.value = null;
        ctx.previewMeta.value = {};
        ctx.previewAuditItem.value = null;
        ctx.previewMode.value = 'document';
        ctx.candidateWorkbenchItem.value = null;
    }

    function closePreview(ctx) {
        ctx.previewOpen.value = false;
        resetPreviewState(ctx);
    }

    async function previewDoc(ctx, path, options = {}) {
        ctx.previewDocPath.value = path;
        ctx.previewDocName.value = path.split('/').pop();
        ctx.previewOpen.value = true;
        ctx.previewLoading.value = true;
        ctx.previewContent.value = '';
        resetPreviewState(ctx);
        ctx.previewAuditItem.value = options.auditItem || null;

        try {
            const data = await KBApi.getJson(`/api/documents/${encodeURIComponent(path)}`);
            ctx.previewContent.value = data.content || '';
            ctx.previewRelated.value = data.related || [];
            ctx.previewAssociation.value = data.association || null;
            ctx.previewMeta.value = data.meta || {};
        } catch (e) {
            ctx.previewContent.value = '无法加载文档内容。';
            ctx.showToast('加载失败', 'error');
        } finally {
            ctx.previewLoading.value = false;
        }
    }

    async function focusDocInList(ctx, path) {
        if (!path) return;
        ctx.activeTab.value = 'docs';
        const parts = path.split('/');
        ctx.selectedDocFolder.value = parts.length > 1 ? parts.slice(0, -1).join('/') : '';
        ctx.docSearchText.value = parts[parts.length - 1] || path;
        ctx.docsPage.value = 1;
        await ctx.nextTick();
        await previewDoc(ctx, path);
    }

    async function openAuditDoc(ctx, item) {
        if (!item?.path) return;
        await previewDoc(ctx, item.path, { auditItem: item });
    }

    async function openDocAudit(ctx, path) {
        if (!path) return;
        ctx.activeTab.value = 'settings';
        if (!ctx.llmAudit.value && !ctx.loadingLlmAudit.value) await ctx.loadLlmAudit();
        const item = (ctx.llmAudit.value?.items || []).find(x => x.path === path);
        if (item) {
            await previewDoc(ctx, path, { auditItem: item });
            return;
        }
        await previewDoc(ctx, path);
        ctx.showToast('已打开文档；当前审计筛选中未找到对应条目', 'info', 5000);
    }

    async function saveDocContent(ctx) {
        try {
            await KBApi.sendJson(
                `/api/documents/${encodeURIComponent(ctx.previewDocPath.value)}`,
                { content: ctx.previewContent.value },
                { method: 'PUT' }
            );
            ctx.showToast('保存成功', 'success');
            ctx.isEditingDoc.value = false;
        } catch (e) {
            ctx.showToast(`保存出错: ${e.message}`, 'error');
        }
    }

    function resolveContext(ctx) {
        return typeof ctx === 'function' ? ctx() : ctx;
    }

    function createActions(ctx) {
        return {
            closePreview: () => closePreview(resolveContext(ctx)),
            previewDoc: async (path, options = {}) => previewDoc(resolveContext(ctx), path, options),
            focusDocInList: async (path) => focusDocInList(resolveContext(ctx), path),
            openAuditDoc: async (item) => openAuditDoc(resolveContext(ctx), item),
            openDocAudit: async (path) => openDocAudit(resolveContext(ctx), path),
            saveDocContent: async () => saveDocContent(resolveContext(ctx))
        };
    }

    global.KBPreview = {
        closePreview,
        createActions,
        focusDocInList,
        openAuditDoc,
        openDocAudit,
        previewDoc,
        saveDocContent
    };
})(window);
