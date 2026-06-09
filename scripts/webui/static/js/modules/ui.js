(function (global) {
    const defaultTranslationPolicy = () => ({
        enabled: true,
        mode: 'bilingual_on_import',
        targets: 'auto_opposite',
        fallback_on_failure: 'preview_only',
        candidate_tiers: ['A', 'B'],
        preserve_original_full: true,
        max_chunk_chars: 3500,
        full_translate: {
            url_import: true,
            file_upload: true,
            candidate_import: true,
            rss_candidate_preview: false,
            wechat_candidate_import: true
        },
        chinese_source: { translate_to_english: true },
        english_source: { translate_to_chinese: true }
    });

    const mergeTranslationPolicy = (policy = {}) => {
        const defaults = defaultTranslationPolicy();
        const incoming = policy || {};
        return {
            ...defaults,
            ...incoming,
            candidate_tiers: Array.isArray(incoming.candidate_tiers) ? incoming.candidate_tiers : defaults.candidate_tiers,
            full_translate: { ...defaults.full_translate, ...(incoming.full_translate || {}) },
            chinese_source: { ...defaults.chinese_source, ...(incoming.chinese_source || {}) },
            english_source: { ...defaults.english_source, ...(incoming.english_source || {}) }
        };
    };

    const i18n = {
        zh: {
            nav: { chat: '智能问答', graph: '知识图谱', docs: '文档管理', candidates: '候选池', wechat: '公众号订阅', rss: 'RSS订阅', settings: '系统设置' },
            chat: { emptyTitle: '今天想研究点什么？', emptyBody: '可以直接向我提问，或者输入关键词进行语义搜索。' },
            docs: {
                title: '文档管理', subtitle: '支持拖拽文件上传，自动分析摘要与实体', filter: '过滤文档...',
                maintenance: '维护知识库', maintaining: '维护中...', fetchUrl: '从网址抓取', upload: '上传文件',
                dropTitle: '将文件拖拽到此处', dropBody: '支持 Markdown, TXT, Python, PDF 等格式',
                fetchTitle: '从网址抓取文章', fetchPlaceholder: '输入文章网址，例如 https://example.com/article',
                fetching: '抓取中...', fetchImport: '抓取并导入', fetchSuccess: '抓取成功！文档已导入知识库。',
                folders: '目录结构', items: '个文档', sorted: '按修改时间排序', viewAll: '查看全部',
                empty: '当前目录没有匹配文档', page: '第', total: '共', prev: '上一页', next: '下一页'
            },
            settings: {
                title: '系统设置', subtitle: '管理知识库名称、环境功能开关、模型策略与审计信息',
                basic: '基础设置', features: '功能开关', appName: '知识库名称', appTitle: '页面标题', appSubtitle: '副标题', appLogo: 'Logo 路径',
                featureHint: '关闭功能会隐藏菜单，并让对应 API 返回 403。',
                refresh: '刷新', save: '保存配置', secretNote: '这里不会显示或保存 API Key，只显示环境变量名和是否已配置。',
                deploymentMode: '部署模式', deploymentModeHint: '一键切换全局策略；保存前会自动备份 llm_runtime.yaml。',
                secretFile: '密钥文件', systemdDropin: 'systemd 配置', setupCommand: '一键配置命令',
                configured: '已配置', notConfigured: '未配置', permissionMode: '权限',
                audit: 'LLM 审计', auditRefresh: '刷新审计', auditCoverage: '覆盖率', auditMissing: '缺少元数据',
                auditFallback: 'Fallback', auditRetranslated: '已重翻译', auditLegacyTranslation: '历史翻译', recentLlmDocs: '最近模型产物',
                providers: 'Providers', flows: '业务流策略', label: '显示名', type: '类型', model: '模型', baseUrl: 'Base URL',
                keyEnv: 'Key 环境变量', timeout: '超时秒数', callTimeout: '模型调用超时（秒）', callTimeoutHint: '单次模型 HTTP 请求超时；全文翻译每个分片单独计时。',
                secretReady: '密钥已配置', secretMissing: '缺少密钥', noSecret: '无需密钥',
                intent: '策略意图', providersOrder: 'Provider 顺序', notes: '备注', chunkChars: '分片字符数',
                fallbackNotice: 'Fallback 记录', allowFallback: '允许 fallback', allowOnline: '允许在线模型', test: '测试',
                backups: '配置备份', restore: '恢复', addProvider: '新增', deleteProvider: '删除',
                selectProvider: '选择 Provider', add: '添加', remove: '移除', up: '上移', down: '下移',
                missingProvider: 'Provider 不存在'
            },
            doc: { retranslate: '重新翻译', retranslateDisabledEdit: '保存或取消编辑后才能重翻译', retranslateDisabledNoDoc: '请先选择文档', retranslateDisabledNoModel: '模型未加载' },
            common: { edit: '编辑', save: '保存' }
        },
        en: {
            nav: { chat: 'Chat', graph: 'Knowledge Graph', docs: 'Documents', candidates: 'Candidates', wechat: 'WeChat Sources', rss: 'RSS Feeds', settings: 'System Settings' },
            chat: { emptyTitle: 'What do you want to research today?', emptyBody: 'Ask a question directly, or enter keywords for semantic search.' },
            docs: {
                title: 'Documents', subtitle: 'Drag files here, analyze summaries and entities automatically', filter: 'Filter documents...',
                maintenance: 'Maintain KB', maintaining: 'Maintaining...', fetchUrl: 'Fetch URL', upload: 'Upload',
                dropTitle: 'Drop files here', dropBody: 'Supports Markdown, TXT, Python, PDF and more',
                fetchTitle: 'Fetch Article From URL', fetchPlaceholder: 'Enter article URL, e.g. https://example.com/article',
                fetching: 'Fetching...', fetchImport: 'Fetch and Import', fetchSuccess: 'Fetched successfully. Document imported.',
                folders: 'Folders', items: 'documents', sorted: 'sorted by modified time', viewAll: 'View all',
                empty: 'No matching documents in this folder', page: 'Page', total: 'Total', prev: 'Prev', next: 'Next'
            },
            settings: {
                title: 'System Settings', subtitle: 'Manage branding, environment feature switches, model policies, and audit data.',
                basic: 'Basic Settings', features: 'Feature Switches', appName: 'Knowledge Base Name', appTitle: 'Page Title', appSubtitle: 'Subtitle', appLogo: 'Logo Path',
                featureHint: 'Disabled features are hidden from navigation and blocked by API gates.',
                refresh: 'Refresh', save: 'Save Config', secretNote: 'API keys are never shown or saved here. Only env var names and configured status are displayed.',
                deploymentMode: 'Deployment Mode', deploymentModeHint: 'Switch global policy presets. llm_runtime.yaml is backed up before changes.',
                secretFile: 'Secret file', systemdDropin: 'systemd drop-in', setupCommand: 'One-shot setup command',
                configured: 'Configured', notConfigured: 'Not configured', permissionMode: 'Mode',
                audit: 'LLM Audit', auditRefresh: 'Refresh Audit', auditCoverage: 'Coverage', auditMissing: 'Missing metadata',
                auditFallback: 'Fallback', auditRetranslated: 'Retranslated', auditLegacyTranslation: 'Legacy translation', recentLlmDocs: 'Recent LLM outputs',
                providers: 'Providers', flows: 'Flow Policies', label: 'Label', type: 'Type', model: 'Model', baseUrl: 'Base URL',
                keyEnv: 'Key Env Var', timeout: 'Timeout Sec', callTimeout: 'Model call timeout (sec)', callTimeoutHint: 'Timeout for one model HTTP request; full translation applies it per chunk.',
                secretReady: 'Secret ready', secretMissing: 'Secret missing', noSecret: 'No secret',
                intent: 'Intent', providersOrder: 'Provider order', notes: 'Notes', chunkChars: 'Chunk chars',
                fallbackNotice: 'Fallback notice', allowFallback: 'Allow fallback', allowOnline: 'Allow online', test: 'Test',
                backups: 'Config Backups', restore: 'Restore', addProvider: 'Add', deleteProvider: 'Delete',
                selectProvider: 'Select provider', add: 'Add', remove: 'Remove', up: 'Up', down: 'Down',
                missingProvider: 'Missing provider'
            },
            doc: { retranslate: 'Retranslate', retranslateDisabledEdit: 'Save or cancel edit first', retranslateDisabledNoDoc: 'Select a document first', retranslateDisabledNoModel: 'Model not loaded' },
            common: { edit: 'Edit', save: 'Save' }
        }
    };

    function translate(lang, key) {
        return key.split('.').reduce((obj, part) => obj && obj[part], i18n[lang]) || key;
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
    }

    function createToasts(ref) {
        const toasts = ref([]);
        let toastId = 0;
        const showToast = (msg, type = 'info', duration = 3000) => {
            const id = toastId++;
            toasts.value.push({ id, msg, type });
            setTimeout(() => {
                toasts.value = toasts.value.filter(t => t.id !== id);
            }, duration);
        };
        return { toasts, showToast };
    }

    function createMarkdownRenderer() {
        try {
            if (typeof marked === 'undefined') throw new Error('marked not loaded');
            marked.setOptions({
                highlight: function (code, lang) {
                    try {
                        if (lang && hljs.getLanguage(lang)) {
                            return hljs.highlight(code, { language: lang }).value;
                        }
                        return hljs.highlightAuto(code).value;
                    } catch (e) {
                        return code;
                    }
                },
                breaks: true
            });
            return (text) => {
                try {
                    const html = marked.parse(text || '');
                    return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
                } catch (e) {
                    return '<pre>' + (text || '') + '</pre>';
                }
            };
        } catch (e) {
            console.warn('Markdown init failed:', e);
            return (text) => '<pre>' + (text || '') + '</pre>';
        }
    }

    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function formatDate(ts) {
        return new Date(ts * 1000).toLocaleDateString();
    }

    global.KBUI = {
        applyTheme,
        createMarkdownRenderer,
        createToasts,
        defaultTranslationPolicy,
        formatBytes,
        formatDate,
        mergeTranslationPolicy,
        translate
    };
})(window);
