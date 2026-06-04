(function (global) {
    const defaultRssForm = () => ({
        url: '',
        name: '',
        category: 'articles',
        priority: 'medium',
        tags: '',
        notes: '',
        language: 'en',
        interval_minutes: 360,
        max_articles: 10,
        enabled: true
    });

    const defaultWechatSource = () => ({
        name: '',
        sample_url: '',
        tags: '',
        priority: 'normal'
    });

    function normalizeRssPayload(form) {
        const payload = { ...(form || {}) };
        if (typeof payload.tags === 'string') {
            payload.tags = payload.tags.split(',').map(t => t.trim()).filter(Boolean);
        }
        return payload;
    }

    async function loadRssFeeds(ctx) {
        ctx.loadingRssFeeds.value = true;
        try {
            const data = await KBApi.getJson('/api/rss/feeds');
            ctx.rssFeeds.value = data.feeds || [];
        } catch (e) {
            ctx.showToast('加载RSS订阅失败', 'error');
        } finally {
            ctx.loadingRssFeeds.value = false;
        }
    }

    async function saveRssFeed(ctx) {
        const payload = normalizeRssPayload(ctx.rssNewForm.value);
        try {
            await KBApi.sendJson('/api/rss/feeds', payload, { method: 'POST' });
            ctx.showToast('RSS订阅已保存', 'success');
            ctx.rssNewForm.value = defaultRssForm();
            await loadRssFeeds(ctx);
        } catch (e) {
            ctx.showToast(`保存失败: ${e.message}`, 'error');
        }
    }

    async function deleteRssFeed(ctx, key) {
        if (!confirm(`确认删除订阅源 "${key}"？`)) return;
        try {
            await KBApi.requestJson(`/api/rss/feeds/${encodeURIComponent(key)}`, { method: 'DELETE' });
            ctx.showToast('已删除', 'success');
            await loadRssFeeds(ctx);
        } catch (e) {
            ctx.showToast(`删除失败: ${e.message}`, 'error');
        }
    }

    async function toggleRssFeed(ctx, key) {
        try {
            const feed = ctx.rssFeeds.value.find(f => f.key === key);
            if (!feed) return;
            await KBApi.sendJson(
                `/api/rss/feeds/${encodeURIComponent(key)}`,
                { enabled: !feed.enabled },
                { method: 'PATCH' }
            );
            feed.enabled = !feed.enabled;
            ctx.showToast(`已${feed.enabled ? '启用' : '禁用'} ${feed.name || key}`, 'success');
        } catch (e) {
            ctx.showToast(`操作失败: ${e.message}`, 'error');
        }
    }

    async function syncRss(ctx, feedKey = null) {
        const normalizedFeedKey = typeof feedKey === 'string' ? feedKey : null;
        ctx.syncingRss.value = true;
        ctx.rssSyncResult.value = null;
        try {
            const payload = { limit: 5 };
            if (normalizedFeedKey) payload.feed_key = normalizedFeedKey;
            const data = await KBApi.sendJson('/api/rss/sync', payload, { method: 'POST' });
            ctx.rssSyncResult.value = data;
            ctx.showToast(
                `RSS同步完成: ${data.new} 新, ${data.skipped} 跳过, ${data.errors} 错误`,
                data.new > 0 ? 'success' : 'info',
                6000
            );
            await loadRssFeeds(ctx);
            await ctx.loadCandidates();
        } catch (e) {
            ctx.showToast(`RSS同步失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.syncingRss.value = false;
        }
    }

    async function loadWechatSources(ctx) {
        ctx.loadingWechatSources.value = true;
        try {
            const data = await KBApi.getJson('/api/wechat/sources');
            ctx.wechatSources.value = data.sources || [];
        } catch (e) {
            ctx.showToast('加载公众号订阅失败', 'error');
        } finally {
            ctx.loadingWechatSources.value = false;
        }
    }

    async function saveWechatSource(ctx) {
        ctx.savingWechatSource.value = true;
        try {
            await KBApi.sendJson('/api/wechat/sources', ctx.newWechatSource.value, { method: 'POST' });
            ctx.showToast('公众号订阅已保存', 'success');
            ctx.newWechatSource.value = defaultWechatSource();
            await loadWechatSources(ctx);
        } catch (e) {
            ctx.showToast(`保存失败: ${e.message}`, 'error');
        } finally {
            ctx.savingWechatSource.value = false;
        }
    }

    async function discoverWechat(ctx, sourceName = null) {
        const normalizedSourceName = sourceName && typeof sourceName === 'string' ? sourceName : null;
        ctx.discoveringWechat.value = true;
        ctx.wechatDiscoveryResult.value = null;
        try {
            const payload = { ...ctx.discoverForm.value };
            if (normalizedSourceName) payload.source = normalizedSourceName;
            const data = await KBApi.sendJson('/api/wechat/discover', payload, { method: 'POST' });
            ctx.wechatDiscoveryResult.value = data;
            ctx.showToast('搜索发现完成，候选已进入候选池', 'success', 6000);
            await loadWechatSources(ctx);
            await ctx.loadCandidates();
        } catch (e) {
            ctx.showToast(`发现失败: ${e.message}`, 'error', 8000);
        } finally {
            ctx.discoveringWechat.value = false;
        }
    }

    global.KBSources = {
        defaultRssForm,
        defaultWechatSource,
        deleteRssFeed,
        discoverWechat,
        loadRssFeeds,
        loadWechatSources,
        saveRssFeed,
        saveWechatSource,
        syncRss,
        toggleRssFeed
    };
})(window);
