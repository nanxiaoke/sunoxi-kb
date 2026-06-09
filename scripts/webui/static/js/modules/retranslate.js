(function (global) {
    function selectedTranslationModel(models, providerId) {
        return (models || []).find(m => (
            m.provider === providerId ||
            m.provider_name === providerId ||
            m.id === providerId
        )) || null;
    }

    function translationProviderLabel(model, fallbackProvider = '') {
        if (!model) return fallbackProvider || '-';
        const kind = model.kind === 'online' ? '在线' : '本地';
        return `${model.label || model.provider_name || model.provider || kind} · ${model.model || '-'}`;
    }

    function fallbackTranslationModels() {
        return [
            { id: 'deepseek_pro', provider: 'deepseek_pro', provider_name: 'deepseek_pro', kind: 'online', label: 'DeepSeek Pro', model: 'deepseek-v4-pro', available: false, key_env: 'DEEPSEEK_API_KEY', timeout_sec: 90 },
            { id: 'local_gemma4', provider: 'local_gemma4', provider_name: 'local_gemma4', kind: 'local', label: 'Local Gemma4', model: 'gemma4:e4b', available: true, timeout_sec: 120 }
        ];
    }

    async function loadTranslationModels(ctx) {
        try {
            const data = await KBApi.getJson('/api/translation/models');
            ctx.translationModels.value = data.models || [];
            const current = ctx.selectedTranslationModel.value;
            if (!current || current.available === false) {
                const firstAvailable = ctx.translationModels.value.find(m => m.available);
                ctx.translationProvider.value = firstAvailable?.provider || ctx.translationModels.value[0]?.provider || 'local_gemma4';
            }
        } catch (e) {
            ctx.translationModels.value = fallbackTranslationModels();
            ctx.translationProvider.value = 'local_gemma4';
        }
    }

    function buildRetranslateAction(ctx) {
        const model = ctx.selectedTranslationModel.value;
        const disabled = (reason, title) => ({
            canRun: false,
            disabled: true,
            busy: ctx.isRetranslating.value,
            reason,
            title,
            model
        });

        if (ctx.isRetranslating.value) {
            return disabled('busy', ctx.t('doc.retranslate') || '重新翻译');
        }
        if (ctx.isEditingDoc.value) {
            return disabled('editing', ctx.t('doc.retranslateDisabledEdit') || '保存或取消编辑后才能重翻译');
        }
        if (!ctx.previewDocPath.value) {
            return disabled('missing_doc', ctx.t('doc.retranslateDisabledNoDoc') || '请先选择文档');
        }
        if (!model) {
            return disabled('missing_model', ctx.t('doc.retranslateDisabledNoModel') || '模型未加载');
        }
        if (model.available === false) {
            return disabled(
                'unavailable_model',
                `${model.label || model.provider_name || model.provider} 不可用${model.key_env ? '：缺少 ' + model.key_env : ''}`
            );
        }
        return {
            canRun: true,
            disabled: false,
            busy: false,
            reason: '',
            title: `${ctx.t('doc.retranslate') || '重新翻译'}：${ctx.translationProviderLabel(model)}`,
            model
        };
    }

    async function runRetranslate(ctx) {
        const action = ctx.retranslateAction.value;
        if (!action.canRun) {
            if (action.title) ctx.showToast(action.title, 'warning', 5000);
            return;
        }

        const selected = action.model;
        if (selected.available === false) {
            ctx.showToast(`${ctx.translationProviderLabel(selected)} 不可用${selected.key_env ? `：缺少 ${selected.key_env}` : ''}`, 'warning', 6000);
            return;
        }

        ctx.isRetranslating.value = true;
        ctx.showToast(`正在使用 ${ctx.translationProviderLabel(selected)} 生成重翻译预览...`, 'info', 6000);
        try {
            const translateUrl = `/api/documents/${encodeURIComponent(ctx.previewDocPath.value)}/translate`;
            const preview = await KBApi.sendJson(
                translateUrl,
                { provider: ctx.translationProvider.value, model: selected.model || '', dry_run: true },
                { method: 'POST' }
            );
            const translationPreview = (preview.preview?.translation || preview.preview?.summary || '').slice(0, 220);
            const sourceLang = preview.source_language || 'auto';
            const targetLang = preview.target_language || 'zh';
            const failedChunks = Array.isArray(preview.chunk_failures) ? preview.chunk_failures.length : 0;
            const failureNote = failedChunks > 0 ? `\n⚠️ ${failedChunks} 个分片失败，提交后仅写成功分片。` : '';
            const langNote = (sourceLang === targetLang) ? `\n⚠️ 源/目标语言均为 ${sourceLang}，策略不匹配，请检查 translation_policy。` : '';
            const confirmMsg = `确认应用重新翻译？\n模型：${preview.provider || ctx.translationProvider.value} / ${preview.model || selected.model || '-'}\n方向：${sourceLang} → ${targetLang}\nchunks：${preview.chunk_count || 0}${failureNote}${langNote}\n预览：${translationPreview}\n\n确认后会再次调用模型并写入文档。`;
            if (!confirm(confirmMsg)) {
                ctx.showToast('已取消重新翻译写入', 'info');
                return;
            }

            ctx.showToast('正在应用重新翻译...', 'info', 6000);
            const data = await KBApi.sendJson(
                translateUrl,
                { provider: ctx.translationProvider.value, model: selected.model || '', dry_run: false },
                { method: 'POST' }
            );
            ctx.showToast(`重新翻译完成：${data.source_language}→${data.target_language}`, 'success', 5000);
            await ctx.previewDoc(ctx.previewDocPath.value);
            await ctx.loadDocs();
        } catch (e) {
            ctx.showToast(`重新翻译失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.isRetranslating.value = false;
        }
    }

    global.KBRetranslate = {
        buildRetranslateAction,
        loadTranslationModels,
        runRetranslate,
        selectedTranslationModel,
        translationProviderLabel
    };
})(window);
