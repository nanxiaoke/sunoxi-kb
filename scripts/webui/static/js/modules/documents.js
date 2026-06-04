(function (global) {
    const qualityIssueLabels = {
        summary_placeholder: '摘要缺失',
        keypoints_placeholder: '关键点缺失',
        entities_placeholder: '实体缺失',
        quality_scan_failed: '扫描失败'
    };

    function normalizeDocument(d) {
        const relpath = d.path || d.relpath;
        const parts = relpath.split('/');
        const folder = parts.length > 1 ? parts.slice(0, -1).join('/') : 'root';
        return {
            relpath,
            name: d.name,
            type: d.category || d.type || folder || 'root',
            folder,
            generated: !!d.generated,
            quality: d.quality || { ok: true, issues: [], score: 100 },
            size: d.size_bytes || d.size || 0,
            mtime: new Date(d.modified || d.mtime || Date.now()).getTime() / 1000
        };
    }

    function issueLabel(issue) {
        return qualityIssueLabels[issue] || issue;
    }

    function issueText(issues) {
        return (issues || []).map(issueLabel).join(' / ');
    }

    function filterDocs(docs, { query = '', qualityOnly = false } = {}) {
        const q = query.trim().toLowerCase();
        let list = docs.slice().sort((a, b) => b.mtime - a.mtime);
        if (qualityOnly) list = list.filter(d => d.quality && !d.quality.ok);
        if (!q) return list;
        return list.filter(d =>
            d.name.toLowerCase().includes(q) ||
            d.relpath.toLowerCase().includes(q) ||
            (d.type || '').toLowerCase().includes(q)
        );
    }

    function buildFolderRows(docs) {
        const dirs = new Map();
        const addDir = (path) => {
            if (!dirs.has(path)) {
                dirs.set(path, {
                    path,
                    label: path ? path.split('/').pop() : '全部文档',
                    depth: path ? path.split('/').length - 1 : 0,
                    count: 0
                });
            }
        };

        addDir('');
        docs.forEach(doc => {
            const parts = doc.relpath.split('/');
            if (parts.length > 1) {
                for (let i = 1; i < parts.length; i++) addDir(parts.slice(0, i).join('/'));
            }
        });

        dirs.forEach(folder => {
            folder.count = folder.path === ''
                ? docs.length
                : docs.filter(d => d.relpath.startsWith(folder.path + '/')).length;
        });

        return Array.from(dirs.values()).sort((a, b) => {
            if (a.path === '') return -1;
            if (b.path === '') return 1;
            return a.path.localeCompare(b.path, 'zh-Hans-CN');
        });
    }

    function visibleDocs(filteredDocs, folder) {
        return !folder ? filteredDocs : filteredDocs.filter(d => d.relpath.startsWith(folder + '/'));
    }

    function totalPages(items, pageSize) {
        return Math.max(1, Math.ceil(items.length / pageSize));
    }

    function pageItems(items, page, pageSize) {
        const start = (page - 1) * pageSize;
        return items.slice(start, start + pageSize);
    }

    function qualityBadCount(docs) {
        return docs.filter(d => d.quality && !d.quality.ok).length;
    }

    function qualityIssueSummary(docs) {
        const counts = {};
        docs.forEach(d => (d.quality?.issues || []).forEach(i => {
            counts[i] = (counts[i] || 0) + 1;
        }));
        return Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .map(([issue, count]) => `${issueLabel(issue)} ${count}`)
            .join('，');
    }

    function addFailedImport(ctx, item) {
        if (!item?.recovery?.can_retry) return;
        ctx.failedImports.value.unshift({
            raw_path: item.recovery.raw_path || item.raw_path,
            filename: item.filename,
            error: item.error || item.message || item.recovery.error,
            recovery: item.recovery,
            retrying: false
        });
    }

    async function loadDocs(ctx) {
        ctx.loadingDocs.value = true;
        try {
            const [docData, statData] = await Promise.all([
                KBApi.getJson('/api/documents'),
                KBApi.getJson('/api/stats')
            ]);
            ctx.docs.value = (docData.documents || []).map(normalizeDocument);
            ctx.stats.value = statData;
        } catch (e) {
            ctx.showToast('获取文档列表失败', 'error');
        } finally {
            ctx.loadingDocs.value = false;
        }
    }

    async function deleteDoc(ctx, path) {
        if (!confirm(`确定删除 ${path} 及其处理产生的Wiki文件吗？`)) return;
        try {
            await KBApi.requestJson(`/api/documents/${encodeURIComponent(path)}`, { method: 'DELETE' });
            ctx.showToast('删除成功', 'success');
            ctx.docs.value = ctx.docs.value.filter(d => d.relpath !== path);
            ctx.stats.value.wiki_documents = Math.max(0, (ctx.stats.value.wiki_documents || 1) - 1);
        } catch (e) {
            ctx.showToast(`删除失败: ${e.message}`, 'error');
        }
    }

    async function fetchUrl(ctx) {
        const url = ctx.fetchUrlInput.value.trim();
        if (!url) return;
        try {
            const u = new URL(url);
            if (!['http:', 'https:'].includes(u.protocol)) throw new Error('仅支持 http/https');
        } catch (e) {
            ctx.fetchUrlError.value = `URL 不合法: ${e.message}`;
            ctx.showToast(`URL 不合法: ${e.message}`, 'error');
            return;
        }

        ctx.isFetchingUrl.value = true;
        ctx.fetchUrlError.value = '';
        ctx.fetchUrlSuccess.value = false;
        ctx.showToast(`正在抓取: ${url}`, 'info', 5000);
        try {
            const data = await KBApi.sendJson('/api/documents/url', { url, auto_process: true }, { method: 'POST' });
            if (data.processed) {
                ctx.fetchUrlSuccess.value = true;
                ctx.showToast('✅ 抓取并导入成功！', 'success');
                await loadDocs(ctx);
                return;
            }
            addFailedImport(ctx, data);
            ctx.showToast(`❌ 抓取成功但处理失败: ${data.message || '未知错误'}`, 'warning');
        } catch (e) {
            ctx.fetchUrlError.value = e.message;
            ctx.showToast(`抓取失败: ${e.message}`, 'error');
        } finally {
            ctx.isFetchingUrl.value = false;
        }
    }

    async function uploadFiles(ctx, files) {
        ctx.showToast(`正在上传 ${files.length} 个文件...`, 'info');
        const summaries = [];
        for (let i = 0; i < files.length; i++) {
            const fd = new FormData();
            fd.append('files', files[i]);
            try {
                const res = await fetch('/api/documents', { method: 'POST', body: fd });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                const processed = data.processed || [];
                for (const item of processed) {
                    summaries.push(item);
                    if (item.processed) {
                        const model = item.llm?.provider ? ` · ${item.llm.provider} / ${item.llm.model || '-'}` : '';
                        ctx.showToast(`已处理 ${item.filename}${model}`, 'success', 7000);
                    } else {
                        addFailedImport(ctx, item);
                        ctx.showToast(`上传成功但处理失败 ${item.filename}: ${item.error || item.message || '未知错误'}`, 'warning', 9000);
                    }
                }
            } catch (e) {
                console.error('Upload error', e);
                ctx.showToast(`上传失败 ${files[i].name}: ${e.message}`, 'error', 9000);
            }
        }
        if (!summaries.length) ctx.showToast('上传请求已发送', 'success');
        await loadDocs(ctx);
    }

    async function retryFailedImport(ctx, item) {
        if (!item?.raw_path || item.retrying) return;
        item.retrying = true;
        try {
            const data = await KBApi.sendJson('/api/documents/retry-import', { raw_path: item.raw_path }, { method: 'POST' });
            if (!data.processed) throw new Error(data.error || data.message || '处理失败');
            ctx.failedImports.value = ctx.failedImports.value.filter(x => x !== item);
            ctx.showToast(`重试处理成功: ${data.wiki_path || item.raw_path}`, 'success', 7000);
            await loadDocs(ctx);
        } catch (e) {
            item.error = e.message;
            ctx.showToast(`重试处理失败: ${e.message}`, 'error', 9000);
        } finally {
            item.retrying = false;
        }
    }

    global.KBDocuments = {
        buildFolderRows,
        deleteDoc,
        filterDocs,
        fetchUrl,
        issueLabel,
        issueText,
        loadDocs,
        pageItems,
        qualityBadCount,
        qualityIssueSummary,
        retryFailedImport,
        totalPages,
        visibleDocs,
        uploadFiles
    };
})(window);
