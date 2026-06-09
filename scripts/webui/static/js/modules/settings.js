(function (global) {
    function applyWebuiConfig(ctx, data) {
        ctx.webuiConfig.value = {
            app: data.app || ctx.webuiConfig.value.app,
            features: data.features || ctx.webuiConfig.value.features,
            translation_policy: ctx.mergeTranslationPolicy(data.translation_policy || ctx.webuiConfig.value.translation_policy)
        };
    }

    async function loadWebuiConfig(ctx) {
        ctx.loadingWebuiConfig.value = true;
        try {
            const data = await KBApi.getJson('/api/webui/config');
            applyWebuiConfig(ctx, data);
        } catch (e) {
            ctx.showToast(`加载系统设置失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.loadingWebuiConfig.value = false;
        }
    }

    async function saveWebuiConfig(ctx) {
        ctx.savingWebuiConfig.value = true;
        try {
            const data = await KBApi.sendJson('/api/webui/config', ctx.webuiConfig.value, { method: 'PATCH' });
            applyWebuiConfig(ctx, data);
            ctx.showToast('系统设置已保存', 'success');
        } catch (e) {
            ctx.showToast(`保存系统设置失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.savingWebuiConfig.value = false;
        }
    }

    async function applyLlmConfigPayload(ctx, data) {
        ctx.llmProviders.value = ctx.normalizeLlmProviders(data.providers);
        ctx.llmFlows.value = ctx.normalizeLlmFlows(data.flows);
        ctx.llmSecretSetup.value = data.secret_setup || ctx.llmSecretSetup.value;
        ctx.llmMode.value = data.mode || ctx.llmMode.value;
        ctx.llmModeOptions.value = data.mode_options || ctx.llmModeOptions.value;
        ctx.llmBackups.value = data.backups || [];
        await ctx.loadTranslationModels();
    }

    async function loadLlmConfig(ctx) {
        ctx.loadingLlmConfig.value = true;
        try {
            const data = await KBApi.getJson('/api/llm/config');
            ctx.llmProviders.value = ctx.normalizeLlmProviders(data.providers);
            ctx.llmFlows.value = ctx.normalizeLlmFlows(data.flows);
            ctx.llmSecretSetup.value = data.secret_setup || null;
            ctx.llmMode.value = data.mode || 'hybrid';
            ctx.llmModeOptions.value = data.mode_options || ctx.llmModeOptions.value || [];
            ctx.llmBackups.value = data.backups || ctx.llmBackups.value || [];
        } catch (e) {
            ctx.showToast(`加载模型配置失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.loadingLlmConfig.value = false;
        }
    }

    function llmConfigPayload(ctx) {
        return {
            providers: ctx.llmProviders.value.map(p => ({
                name: p.name,
                type: p.type,
                label: p.label,
                model: p.model,
                base_url: p.base_url,
                api_key_env: p.api_key_env,
                timeout_sec: p.timeout_sec,
                options: p.options || {}
            })),
            flows: ctx.llmFlows.value.map(f => ({
                name: f.name,
                label: f.label,
                providers: f.providers || [],
                allow_fallback: !!f.allow_fallback,
                allow_online: !!f.allow_online,
                fallback_notice: f.fallback_notice,
                chunk_chars: f.chunk_chars,
                intent: f.intent,
                notes: f.notes,
                options: f.options || {}
            }))
        };
    }

    async function saveLlmConfig(ctx) {
        ctx.savingLlmConfig.value = true;
        try {
            const data = await KBApi.sendJson('/api/llm/config', llmConfigPayload(ctx), { method: 'PATCH' });
            await applyLlmConfigPayload(ctx, data);
            ctx.showToast(`模型配置已保存${data.backup ? '，已自动备份' : ''}`, 'success', 5000);
        } catch (e) {
            ctx.showToast(`保存模型配置失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.savingLlmConfig.value = false;
        }
    }

    async function setLlmMode(ctx, mode) {
        if (!mode || ctx.settingLlmMode.value) return;
        ctx.settingLlmMode.value = mode;
        try {
            const data = await KBApi.sendJson('/api/llm/mode', { mode }, { method: 'POST' });
            await applyLlmConfigPayload(ctx, data);
            ctx.showToast(`已切换部署模式：${ctx.llmModeLabel.value}${data.backup ? '，已自动备份' : ''}`, 'success', 5000);
        } catch (e) {
            ctx.showToast(`切换部署模式失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.settingLlmMode.value = '';
        }
    }

    async function loadLlmBackups(ctx) {
        try {
            const data = await KBApi.getJson('/api/llm/config/backups');
            ctx.llmBackups.value = data.backups || [];
        } catch (e) {
            ctx.showToast(`加载配置备份失败: ${e.message}`, 'error', 7000);
        }
    }

    function llmAuditParams(filters, format = '') {
        const params = new URLSearchParams();
        Object.entries(filters).forEach(([key, value]) => {
            if (value) params.set(key, value === true ? 'true' : value);
        });
        if (format) params.set('format', format);
        return params;
    }

    async function loadLlmAudit(ctx) {
        ctx.loadingLlmAudit.value = true;
        try {
            const params = llmAuditParams(ctx.llmAuditFilters);
            const url = `/api/llm/audit${params.toString() ? `?${params}` : ''}`;
            ctx.llmAudit.value = await KBApi.getJson(url);
        } catch (e) {
            ctx.showToast(`加载 LLM 审计失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.loadingLlmAudit.value = false;
        }
    }

    function llmAuditExportUrl(ctx, format) {
        return `/api/llm/audit?${llmAuditParams(ctx.llmAuditFilters, format).toString()}`;
    }

    async function loadTranslationBackfillAudit(ctx) {
        ctx.loadingTranslationBackfill.value = true;
        try {
            ctx.translationBackfillAudit.value = await KBApi.getJson('/api/translation/backfill?limit=8');
        } catch (e) {
            ctx.showToast(`加载补译审计失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.loadingTranslationBackfill.value = false;
        }
    }

    async function previewTranslationBackfillDryRun(ctx) {
        ctx.loadingTranslationBackfill.value = true;
        try {
            const data = await KBApi.sendJson('/api/translation/backfill', { limit: 8, dry_run: true }, { method: 'POST' });
            ctx.translationBackfillDryRun.value = data;
            ctx.translationBackfillAudit.value = data.audit || ctx.translationBackfillAudit.value;
            ctx.showToast(`补译 dry-run：计划 ${data.planned || 0} 篇，已写入 ${data.applied || 0} 篇`, 'info', 5000);
        } catch (e) {
            ctx.showToast(`补译 dry-run 失败: ${e.message}`, 'error', 7000);
        } finally {
            ctx.loadingTranslationBackfill.value = false;
        }
    }

    async function restoreLlmBackup(ctx, name) {
        if (!name || !confirm(`确认恢复配置备份 ${name}？当前配置会先自动备份。`)) return;
        ctx.restoringLlmBackup.value = name;
        try {
            const data = await KBApi.requestJson(`/api/llm/config/backups/${encodeURIComponent(name)}/restore`, { method: 'POST' });
            await applyLlmConfigPayload(ctx, data);
            ctx.showToast(`已恢复配置：${data.restored_from || name}`, 'success', 6000);
        } catch (e) {
            ctx.showToast(`恢复配置失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.restoringLlmBackup.value = '';
        }
    }

    function providerLabel(ctx, name) {
        const provider = ctx.llmProviders.value.find(item => item.name === name);
        if (!provider) return ctx.t('settings.missingProvider') || 'Missing provider';
        return [provider.label, provider.model].filter(Boolean).join(' · ');
    }

    function providerTimeout(ctx, name) {
        const provider = ctx.llmProviders.value.find(item => item.name === name);
        return Number(provider?.timeout_sec || 60);
    }

    function nextProviderName(providers) {
        const used = new Set(providers.map(p => p.name));
        let idx = 1;
        let name = 'new_provider';
        while (used.has(name)) {
            idx += 1;
            name = `new_provider_${idx}`;
        }
        return name;
    }

    function addLlmProvider(ctx) {
        const name = nextProviderName(ctx.llmProviders.value);
        ctx.llmProviders.value.push({
            name,
            _original_name: name,
            type: 'ollama',
            label: 'New Provider',
            model: 'gemma4:e4b',
            base_url: 'http://127.0.0.1:11434',
            api_key_env: '',
            timeout_sec: 60,
            options: {},
            online: false,
            secret_configured: false
        });
        ctx.showToast(`已新增 Provider：${name}`, 'info', 4000);
    }

    function syncProviderName(ctx, provider) {
        const oldName = provider._original_name || '';
        const newName = String(provider.name || '').trim();
        if (!/^[A-Za-z0-9_-]+$/.test(newName)) {
            provider.name = oldName;
            ctx.showToast('Provider ID 只能包含字母、数字、下划线和短横线', 'error', 6000);
            return;
        }

        const duplicate = ctx.llmProviders.value.some(p => p !== provider && p.name === newName);
        if (duplicate) {
            provider.name = oldName;
            ctx.showToast(`Provider ID 已存在：${newName}`, 'error', 6000);
            return;
        }

        if (oldName && oldName !== newName) {
            ctx.llmFlows.value.forEach(flow => {
                flow.providers = (flow.providers || []).map(name => name === oldName ? newName : name);
            });
        }
        provider._original_name = newName;
    }

    function deleteLlmProvider(ctx, provider) {
        if (!provider?.name) return;
        const refs = ctx.llmFlows.value
            .filter(flow => (flow.providers || []).includes(provider.name))
            .map(flow => flow.name);
        const message = refs.length
            ? `确认删除 Provider ${provider.name}？它会同时从这些业务流移除：${refs.join(', ')}`
            : `确认删除 Provider ${provider.name}？`;
        if (!confirm(message)) return;

        ctx.llmProviders.value = ctx.llmProviders.value.filter(p => p !== provider);
        const fallback = ctx.llmProviders.value[0]?.name || '';
        ctx.llmFlows.value.forEach(flow => {
            flow.providers = (flow.providers || []).filter(name => name !== provider.name);
            if (!flow.providers.length && fallback) flow.providers = [fallback];
        });
        ctx.showToast(`已删除 Provider：${provider.name}`, 'info', 4000);
    }

    function availableProvidersForFlow(ctx, flow) {
        const selected = new Set(flow.providers || []);
        return ctx.llmProviders.value.filter(provider => !selected.has(provider.name));
    }

    function addProviderToFlow(flow) {
        if (!flow.new_provider) return;
        flow.providers = flow.providers || [];
        if (!flow.providers.includes(flow.new_provider)) {
            flow.providers.push(flow.new_provider);
        }
        flow.new_provider = '';
    }

    function removeFlowProvider(flow, idx) {
        if (!flow.providers || flow.providers.length <= 1) return;
        flow.providers.splice(idx, 1);
    }

    function moveFlowProvider(flow, idx, delta) {
        const providers = flow.providers || [];
        const target = idx + delta;
        if (target < 0 || target >= providers.length) return;
        const [item] = providers.splice(idx, 1);
        providers.splice(target, 0, item);
    }

    async function testLlmProvider(ctx, provider) {
        if (!provider?.name) return;
        provider.testing = true;
        provider.test_result = null;
        try {
            const data = await KBApi.requestJson(`/api/llm/providers/${encodeURIComponent(provider.name)}/test`, { method: 'POST' });
            provider.test_result = data;
            ctx.showToast(`${provider.name} 测试通过`, 'success', 4000);
        } catch (e) {
            provider.test_result = provider.test_result || { ok: false, error: e.message };
            ctx.showToast(`${provider.name} 测试失败: ${e.message}`, 'error', 7000);
        } finally {
            provider.testing = false;
        }
    }

    global.KBSettings = {
        addLlmProvider,
        addProviderToFlow,
        applyLlmConfigPayload,
        availableProvidersForFlow,
        deleteLlmProvider,
        llmAuditExportUrl,
        loadLlmAudit,
        loadLlmBackups,
        loadLlmConfig,
        loadTranslationBackfillAudit,
        loadWebuiConfig,
        moveFlowProvider,
        previewTranslationBackfillDryRun,
        providerLabel,
        providerTimeout,
        removeFlowProvider,
        restoreLlmBackup,
        saveLlmConfig,
        saveWebuiConfig,
        setLlmMode,
        syncProviderName,
        testLlmProvider
    };
})(window);
