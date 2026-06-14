(function (global) {
    let chartInstance = null;

    function graphDocCategory(docNode) {
        if (docNode.path && docNode.path.includes('/')) return docNode.path.split('/').slice(0, -1).join('/');
        const cats = Array.isArray(docNode.categories) ? docNode.categories : (docNode.category ? [docNode.category] : []);
        return (cats[0] && cats[0] !== '文档') ? cats[0] : 'root';
    }

    async function initGraph(ctx) {
        const container = document.getElementById('graph-container');
        if (!container) return;

        if (chartInstance) chartInstance.dispose();
        chartInstance = echarts.init(container, ctx.theme.value === 'dark' ? 'dark' : null);
        chartInstance.showLoading({
            color: '#3b82f6',
            maskColor: ctx.theme.value === 'dark' ? 'rgba(29,35,42,0.8)' : 'rgba(255,255,255,0.8)'
        });

        try {
            let apiUrl = '/api/graph?limit=50';
            const q = ctx.graphSearchText.value.trim();
            if (q) apiUrl += '&entity=' + encodeURIComponent(q) + '&mode=neighbors';
            const data = await KBApi.getJson(apiUrl);

            if (!data.nodes || data.nodes.length === 0) {
                chartInstance.hideLoading();
                return;
            }

            const isDark = ctx.theme.value === 'dark';
            const textColor = isDark ? '#a6adbb' : '#1f2937';
            const lineColor = isDark ? '#4b5563' : '#d1d5db';

            if (ctx.graphLayout.value === 'sankey') {
                renderSankey(ctx, data, isDark);
            } else if (ctx.graphLayout.value === 'tree') {
                renderTree(ctx, data, isDark);
            } else if (ctx.graphLayout.value === 'chord') {
                renderChord(ctx, data, isDark, textColor);
            } else {
                renderForceOrCircular(ctx, data, isDark, textColor, lineColor);
            }
        } catch (e) {
            console.error('Graph error:', e);
            chartInstance.hideLoading();
            ctx.showToast('加载图谱失败', 'error');
        }
    }

    function renderForceOrCircular(ctx, data, isDark, textColor, lineColor) {
        const totalNodes = data.nodes.length;
        const nodes = data.nodes.map(n => {
            let size = n.type === 'document' ? 35 : 18;
            if (n.freq) size += Math.min(n.freq * 3, 28);
            return {
                id: n.id,
                name: n.name || n.id,
                symbolSize: size,
                draggable: true,
                itemStyle: {
                    color: n.type === 'document' ? '#3b82f6' : '#10b981',
                    borderColor: isDark ? '#1d232a' : '#fff',
                    borderWidth: 2,
                    shadowBlur: 10,
                    shadowColor: 'rgba(0,0,0,0.3)'
                },
                label: {
                    show: ctx.graphLayout.value === 'circular' || totalNodes < 60,
                    position: ctx.graphLayout.value === 'circular' ? 'right' : 'bottom',
                    rotate: ctx.graphLayout.value === 'circular' ? 0 : 0,
                    formatter: '{b}',
                    color: textColor,
                    fontSize: 12,
                    backgroundColor: isDark ? 'rgba(0,0,0,0.5)' : 'rgba(255,255,255,0.7)',
                    padding: [2, 4],
                    borderRadius: 4
                },
                type: n.type,
                categories: n.categories || [n.category || '其他'],
                path: n.path
            };
        });

        const option = {
            backgroundColor: 'transparent',
            tooltip: { trigger: 'item' },
            series: [{
                type: 'graph',
                layout: ctx.graphLayout.value,
                data: nodes,
                links: data.links.map(l => ({
                    source: l.source,
                    target: l.target,
                    lineStyle: { width: 1.5, opacity: 0.4, curveness: 0.1 }
                })),
                roam: true,
                focusNodeAdjacency: true,
                force: {
                    repulsion: 1000,
                    gravity: 0.05,
                    edgeLength: [80, 200],
                    friction: 0.8
                },
                circular: { rotateLabel: true },
                lineStyle: { color: lineColor, curveness: 0.3 },
                emphasis: { lineStyle: { width: 4, opacity: 1 }, label: { show: true } }
            }]
        };
        chartInstance.hideLoading();
        chartInstance.setOption(option);
        chartInstance.on('click', (p) => {
            if (p.dataType === 'node' && p.data.path) ctx.previewDoc(p.data.path);
            else if (p.dataType === 'node') {
                ctx.ask(p.data.name);
                ctx.switchTab('chat');
            }
        });
    }

    function renderTree(ctx, data, isDark) {
        const docNodes = data.nodes.filter(n => n.type === 'document');
        const nodeById = new Map(data.nodes.map(n => [n.id, n]));
        const entitiesByDoc = new Map();
        data.links.forEach(l => {
            const src = nodeById.get(l.source);
            const tgt = nodeById.get(l.target);
            if (src && tgt && src.type === 'document' && tgt.type !== 'document') {
                if (!entitiesByDoc.has(src.id)) entitiesByDoc.set(src.id, []);
                entitiesByDoc.get(src.id).push(tgt);
            } else if (src && tgt && tgt.type === 'document' && src.type !== 'document') {
                if (!entitiesByDoc.has(tgt.id)) entitiesByDoc.set(tgt.id, []);
                entitiesByDoc.get(tgt.id).push(src);
            }
        });

        const root = { name: ctx.webuiApp.value.name || 'Knowledge Base', children: [] };
        const folders = new Map();
        const ensureFolder = (path) => {
            if (!path || path === 'root') {
                if (!folders.has('root')) {
                    const node = { name: 'root', children: [] };
                    folders.set('root', node);
                    root.children.push(node);
                }
                return folders.get('root');
            }
            const parts = path.split('/');
            let currentPath = '';
            let parent = root;
            parts.forEach(part => {
                currentPath = currentPath ? currentPath + '/' + part : part;
                if (!folders.has(currentPath)) {
                    const node = { name: part, children: [] };
                    folders.set(currentPath, node);
                    parent.children.push(node);
                }
                parent = folders.get(currentPath);
            });
            return parent;
        };

        docNodes.forEach(doc => {
            const folder = ensureFolder(graphDocCategory(doc));
            const seen = new Set();
            const children = (entitiesByDoc.get(doc.id) || [])
                .filter(e => {
                    const name = e.name || e.label || e.id;
                    if (seen.has(name)) return false;
                    seen.add(name);
                    return true;
                })
                .slice(0, 12)
                .map(e => ({ name: e.name || e.label || e.id, value: e.freq || 1 }));
            folder.children.push({ name: doc.name || doc.id, path: doc.path, children });
        });

        const option = {
            backgroundColor: 'transparent',
            tooltip: { trigger: 'item', triggerOn: 'mousemove' },
            series: [{
                type: 'tree',
                data: [root],
                top: '4%',
                left: '8%',
                bottom: '4%',
                right: '22%',
                orient: 'LR',
                symbol: 'emptyCircle',
                symbolSize: 8,
                expandAndCollapse: true,
                initialTreeDepth: 3,
                roam: true,
                label: {
                    position: 'left',
                    verticalAlign: 'middle',
                    align: 'right',
                    color: isDark ? '#ccc' : '#333',
                    fontSize: 12
                },
                leaves: {
                    label: { position: 'right', verticalAlign: 'middle', align: 'left', color: isDark ? '#ddd' : '#333' }
                },
                emphasis: { focus: 'descendant' },
                lineStyle: { color: isDark ? '#4b5563' : '#d1d5db', width: 1.5, curveness: 0.5 }
            }]
        };
        chartInstance.hideLoading();
        chartInstance.setOption(option);
        chartInstance.on('click', (p) => {
            if (p.data && p.data.path) ctx.previewDoc(p.data.path);
        });
    }

    function renderChord(ctx, data, isDark, textColor) {
        const docNodes = data.nodes.filter(n => n.type === 'document');
        const nodeById = new Map(data.nodes.map(n => [n.id, n]));
        const categoryNodes = new Map();
        const entityNodes = new Map();
        const links = [];

        docNodes.forEach(doc => {
            const cat = graphDocCategory(doc);
            if (!categoryNodes.has(cat)) {
                categoryNodes.set(cat, { id: 'cat_' + cat, name: cat, type: 'category', symbolSize: 34, itemStyle: { color: '#8b5cf6' } });
            }
            links.push({ source: 'cat_' + cat, target: doc.id, value: 2 });
        });

        data.links.forEach(l => {
            const src = nodeById.get(l.source);
            const tgt = nodeById.get(l.target);
            const doc = src?.type === 'document' ? src : (tgt?.type === 'document' ? tgt : null);
            const ent = src?.type === 'document' ? tgt : (tgt?.type === 'document' ? src : null);
            if (!doc || !ent || ent.type === 'document') return;
            const entName = ent.name || ent.label || ent.id;
            if (!entityNodes.has(ent.id)) {
                entityNodes.set(ent.id, {
                    id: ent.id,
                    name: entName,
                    type: 'entity',
                    symbolSize: 18 + Math.min((ent.freq || 1) * 2, 18),
                    itemStyle: { color: '#10b981' }
                });
            }
            links.push({ source: doc.id, target: ent.id, value: 1 });
        });

        const nodes = [
            ...Array.from(categoryNodes.values()),
            ...docNodes.map(d => ({
                id: d.id,
                name: d.name || d.id,
                type: 'document',
                path: d.path,
                symbolSize: 26,
                itemStyle: { color: '#3b82f6' }
            })),
            ...Array.from(entityNodes.values())
        ];

        const option = {
            backgroundColor: 'transparent',
            tooltip: { trigger: 'item' },
            legend: [{ data: ['category', 'document', 'entity'], bottom: 8, textStyle: { color: textColor } }],
            series: [{
                name: '知识弦图',
                type: 'graph',
                layout: 'circular',
                circular: { rotateLabel: true },
                roam: true,
                focusNodeAdjacency: true,
                data: nodes.map(n => ({ ...n, category: n.type })),
                categories: [
                    { name: 'category' },
                    { name: 'document' },
                    { name: 'entity' }
                ],
                links: links.map(l => ({
                    source: l.source,
                    target: l.target,
                    value: l.value,
                    lineStyle: { width: Math.max(1, l.value), opacity: 0.38, curveness: 0.35 }
                })),
                lineStyle: { color: 'source', curveness: 0.35 },
                label: { show: true, position: 'right', formatter: '{b}', color: textColor, fontSize: 11 },
                emphasis: { focus: 'adjacency', lineStyle: { width: 4, opacity: 0.9 } }
            }]
        };
        chartInstance.hideLoading();
        chartInstance.setOption(option);
        chartInstance.on('click', (p) => {
            if (p.dataType === 'node' && p.data.path) ctx.previewDoc(p.data.path);
            else if (p.dataType === 'node' && p.data.type === 'entity') {
                ctx.ask(p.data.name);
                ctx.switchTab('chat');
            }
        });
    }

    function renderSankey(ctx, data, isDark) {
        const nodes = [];
        const links = [];
        const nodeSet = new Set();

        const addNode = (name, depth) => {
            if (!nodeSet.has(name)) {
                nodes.push({ name, itemStyle: { color: depth === 0 ? '#8b5cf6' : (depth === 1 ? '#3b82f6' : '#10b981') } });
                nodeSet.add(name);
            }
        };

        data.nodes.forEach(n => {
            if (n.type === 'document') {
                const cat = graphDocCategory(n);
                addNode(cat, 0);
                addNode(n.name, 1);
                links.push({ source: cat, target: n.name, value: 2 });
            }
        });

        data.links.forEach(l => {
            const src = data.nodes.find(n => n.id === l.source);
            const tgt = data.nodes.find(n => n.id === l.target);
            if (src && tgt && src.type === 'document' && tgt.type === 'entity') {
                addNode(src.name, 1);
                addNode(tgt.name, 2);
                links.push({ source: src.name, target: tgt.name, value: 1 });
            }
        });

        const option = {
            tooltip: { trigger: 'item', triggerOn: 'mousemove' },
            series: [{
                type: 'sankey',
                data: nodes,
                links,
                emphasis: { focus: 'adjacency' },
                lineStyle: { color: 'gradient', curveness: 0.5 },
                label: { color: isDark ? '#ccc' : '#333', fontSize: 12 },
                nodeAlign: 'left',
                layoutIterations: 32
            }]
        };
        chartInstance.hideLoading();
        chartInstance.setOption(option);
    }

    function resize() {
        if (chartInstance) chartInstance.resize();
    }

    function hasGraph() {
        return !!chartInstance;
    }

    function resolveContext(ctx) {
        return typeof ctx === 'function' ? ctx() : ctx;
    }

    function createActions(ctx) {
        return {
            initGraph: async () => initGraph(resolveContext(ctx))
        };
    }

    global.KBGraph = {
        createActions,
        hasGraph,
        initGraph,
        resize
    };
})(window);
