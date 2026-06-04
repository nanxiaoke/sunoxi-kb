const { createApp, ref, reactive, onMounted, computed, watch, nextTick } = Vue;

createApp({
    setup() {
        const activeTab = ref('chat');
        const theme = ref(localStorage.getItem('theme') || 'dark');
        const mobileMenuOpen = ref(false);
        const graphLayout = ref('sankey');
        const graphSearchText = ref('');
        const associationReport = ref(null);
        const loadingAssociations = ref(false);
        const uiLang = ref(localStorage.getItem('kb_ui_lang') || 'zh');
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
        const webuiConfig = ref({
            app: { name: 'Sunoxi KB', title: 'Sunoxi 知识库', subtitle: 'Personal Knowledge Base', logo: '/static/favicon.svg?v=4' },
            features: { chat: true, graph: true, documents: true, upload: true, url_import: true, candidates: true, rss: true, wechat: true, llm_settings: true, llm_audit: true },
            translation_policy: defaultTranslationPolicy()
        });
        const loadingWebuiConfig = ref(false);
        const savingWebuiConfig = ref(false);
        const webuiApp = computed(() => webuiConfig.value.app || {});
        const webuiFeatures = computed(() => webuiConfig.value.features || {});
        const featureEnabled = (name) => webuiFeatures.value[name] !== false;
        const linkQualityHealth = computed(() => KBLinkQuality.summarizeLinkQuality(associationReport.value?.summary || {}));
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
        const t = (key) => key.split('.').reduce((obj, part) => obj && obj[part], i18n[uiLang.value]) || key;
        watch(uiLang, (v) => {
            localStorage.setItem('kb_ui_lang', v);
            document.documentElement.lang = v === 'en' ? 'en' : 'zh';
        }, { immediate: true });
        watch(webuiApp, (app) => {
            if(app?.title) document.title = app.title;
        }, { immediate: true, deep: true });

        const loadWebuiConfig = async () => {
            await KBSettings.loadWebuiConfig(settingsContext);
        };

        const saveWebuiConfig = async () => {
            await KBSettings.saveWebuiConfig(settingsContext);
        };

        const saveAllSettings = async () => {
            await saveWebuiConfig();
            if(featureEnabled('llm_settings')) await saveLlmConfig();
        };

        const refreshAllSettings = async () => {
            await loadWebuiConfig();
            if(featureEnabled('llm_settings')) await loadLlmConfig();
            if(featureEnabled('llm_audit')) await loadLlmAudit();
        };
        
        // Switch Tab Logic
        const switchTab = (tab) => {
            if(tab !== 'settings' && !featureEnabled(tab === 'docs' ? 'documents' : tab)) {
                showToast('该功能已在系统设置中关闭', 'warning');
                return;
            }
            activeTab.value = tab;
            mobileMenuOpen.value = false;
            if(previewOpen.value) closePreview();
            if(tab === 'graph') {
                loadAssociations(false).catch(()=>{});
                nextTick(() => initGraph());
            } else if(tab === 'docs') {
                loadDocs();
            } else if(tab === 'candidates') {
                loadCandidates();
            } else if(tab === 'wechat') {
                loadWechatSources();
            } else if(tab === 'rss') {
                loadRssFeeds();
            } else if(tab === 'settings') {
                loadWebuiConfig();
                loadLlmConfig();
                loadLlmAudit();
            }
        };

        // Theme
        const toggleTheme = () => {
            theme.value = theme.value === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', theme.value);
            localStorage.setItem('theme', theme.value);
            if(activeTab.value === 'graph' && chartInstance) {
                setTimeout(initGraph, 100); // Re-render graph with new theme colors
            }
        };
        document.documentElement.setAttribute('data-theme', theme.value);

        // --- Toasts ---
        const toasts = ref([]);
        let toastId = 0;
        const showToast = (msg, type='info', duration=3000) => {
            const id = toastId++;
            toasts.value.push({id, msg, type});
            setTimeout(() => { toasts.value = toasts.value.filter(t => t.id !== id); }, duration);
        };

        // --- Markdown Setup ---
        const renderMarkdown = (() => {
            try {
                if (typeof marked === 'undefined') throw new Error('marked not loaded');
                marked.setOptions({
                    highlight: function(code, lang) {
                        try {
                            if (lang && hljs.getLanguage(lang)) {
                                return hljs.highlight(code, { language: lang }).value;
                            }
                            return hljs.highlightAuto(code).value;
                        } catch(e) { return code; }
                    },
                    breaks: true
                });
                return (text) => {
                    try {
                        const html = marked.parse(text || '');
                        return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
                    } catch(e) { return '<pre>' + (text || '') + '</pre>'; }
                };
            } catch(e) {
                console.warn('Markdown init failed:', e);
                return (text) => '<pre>' + (text || '') + '</pre>';
            }
        })();

        // --- Chat System ---
        const chatInput = ref('');
        const chatHistory = ref([]);
        const isWaiting = ref(false);
        const chatAnswerMode = ref(localStorage.getItem('kb_chat_answer_mode') || 'extractive');
        watch(chatAnswerMode, (v) => localStorage.setItem('kb_chat_answer_mode', v));
        
        const scrollToBottom = () => {
            nextTick(() => {
                const container = document.getElementById('chat-container');
                if (container) container.scrollTop = container.scrollHeight;
            });
        };

        const ask = (text) => { chatInput.value = text; submitChat(); };
        
        const submitChat = async () => {
            const q = chatInput.value.trim();
            if(!q) return;
            
            chatHistory.value.push({ role: 'user', content: q, time: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) });
            chatInput.value = '';
            isWaiting.value = true;
            scrollToBottom();
            
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&qa=true&answer_mode=${encodeURIComponent(chatAnswerMode.value)}`);
                const data = await res.json();
                
                chatHistory.value.push({
                    role: 'ai',
                    content: data.answer || "未能生成答案。",
                    sources: data.documents || [],
                    citations: data.citations || [],
                    latency: data.latency,
                    cache_hit: data.cache_hit,
                    context_preview: data.context_preview,
                    diagnostics: data.diagnostics || {},
                    answer_mode: data.answer_mode,
                    llm: data.llm,
                    time: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                });
            } catch (e) {
                showToast("问答请求失败", "error");
                chatHistory.value.push({ role: 'ai', content: "系统内部错误，无法连接到模型。" });
            } finally {
                isWaiting.value = false;
                scrollToBottom();
            }
        };

        // --- Document Preview Drawer ---
        const previewOpen = ref(false);
        const previewLoading = ref(false);
        const previewContent = ref('');
        const previewDocName = ref('');
        const previewDocPath = ref('');
        const previewRelated = ref([]);
        const previewAssociation = ref(null);
        const previewMeta = ref({});
        const previewAuditItem = ref(null);
        const previewMode = ref('document');
        const candidateWorkbenchItem = ref(null);
        const isEditingDoc = ref(false);
        const translationModels = ref([]);
        const translationProvider = ref('local_gemma4');
        const isRetranslating = ref(false);
        const llmProviders = ref([]);
        const llmFlows = ref([]);
        const llmBackups = ref([]);
        const llmSecretSetup = ref(null);
        const llmMode = ref('hybrid');
        const llmModeOptions = ref([]);
        const settingLlmMode = ref('');
        const llmAudit = ref(null);
        const llmAuditFilters = reactive({ flow: '', provider: '', model: '', status: '', missing: false, fallback: false, retranslated: false });
        const loadingLlmAudit = ref(false);
        const translationBackfillAudit = ref(null);
        const translationBackfillDryRun = ref(null);
        const loadingTranslationBackfill = ref(false);
        const loadingLlmConfig = ref(false);
        const savingLlmConfig = ref(false);
        const restoringLlmBackup = ref('');
        const objectEntries = (obj) => Object.entries(obj || {});
        const selectedTranslationModel = computed(() => translationModels.value.find(m => m.provider === translationProvider.value || m.provider_name === translationProvider.value || m.id === translationProvider.value) || null);
        const translationProviderLabel = (model) => {
            if(!model) return translationProvider.value || '-';
            const kind = model.kind === 'online' ? '在线' : '本地';
            return `${model.label || model.provider_name || model.provider || kind} · ${model.model || '-'}`;
        };
        const retranslateContext = {
            selectedTranslationModel,
            isRetranslating,
            isEditingDoc,
            previewDocPath,
            translationProvider,
            t,
            translationProviderLabel,
            showToast,
            previewDoc: (...args) => previewDoc(...args),
            loadDocs: (...args) => loadDocs(...args)
        };
        const retranslateAction = computed(() => KBRetranslate.buildRetranslateAction(retranslateContext));
        const retranslateButtonTitle = computed(() => retranslateAction.value.title);
        const llmModeLabel = computed(() => (llmModeOptions.value.find(m => m.id === llmMode.value)?.label) || llmMode.value || 'custom');
        const llmModeDescription = computed(() => (llmModeOptions.value.find(m => m.id === llmMode.value)?.description) || '');
        const fileImportFlow = computed(() => llmFlows.value.find(f => f.name === 'file_import_structure') || null);
        const fileImportProviderChain = computed(() => (fileImportFlow.value?.providers || []).map(name => {
            const p = llmProviders.value.find(item => item.name === name);
            return p ? `${name} / ${p.model}` : name;
        }).join(' -> '));
        const qaFlow = computed(() => llmFlows.value.find(f => f.name === 'qa') || null);
        const qaProviderChain = computed(() => (qaFlow.value?.providers || []).map(name => {
            const p = llmProviders.value.find(item => item.name === name);
            return p ? `${name} / ${p.model}` : name;
        }).join(' -> '));

        const normalizeLlmProviders = (items) => (items || []).map(p => ({
            ...p,
            name: String(p.name || '').trim(),
            _original_name: String(p.name || '').trim()
        }));

        const normalizeLlmFlows = (items) => (items || []).map(f => ({
            ...f,
            providers: Array.isArray(f.providers) ? f.providers.filter(Boolean) : [],
            new_provider: ''
        }));
        const settingsContext = {
            webuiConfig,
            loadingWebuiConfig,
            savingWebuiConfig,
            mergeTranslationPolicy,
            llmProviders,
            llmFlows,
            llmSecretSetup,
            llmMode,
            llmModeOptions,
            settingLlmMode,
            llmAudit,
            llmAuditFilters,
            loadingLlmAudit,
            translationBackfillAudit,
            translationBackfillDryRun,
            loadingTranslationBackfill,
            loadingLlmConfig,
            savingLlmConfig,
            restoringLlmBackup,
            llmBackups,
            llmModeLabel,
            normalizeLlmProviders,
            normalizeLlmFlows,
            showToast,
            loadTranslationModels: (...args) => loadTranslationModels(...args)
        };

        const providerLabel = (name) => {
            const p = llmProviders.value.find(item => item.name === name);
            if(!p) return t('settings.missingProvider') || 'Missing provider';
            return [p.label, p.model].filter(Boolean).join(' · ');
        };
        const providerTimeout = (name) => {
            const p = llmProviders.value.find(item => item.name === name);
            return Number(p?.timeout_sec || 60);
        };

        const nextProviderName = () => {
            const used = new Set(llmProviders.value.map(p => p.name));
            let idx = 1;
            let name = 'new_provider';
            while(used.has(name)) {
                idx += 1;
                name = `new_provider_${idx}`;
            }
            return name;
        };

        const addLlmProvider = () => {
            const name = nextProviderName();
            llmProviders.value.push({
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
            showToast(`已新增 Provider：${name}`, 'info', 4000);
        };

        const syncProviderName = (provider) => {
            const oldName = provider._original_name || '';
            const newName = String(provider.name || '').trim();
            if(!/^[A-Za-z0-9_-]+$/.test(newName)) {
                provider.name = oldName;
                showToast('Provider ID 只能包含字母、数字、下划线和短横线', 'error', 6000);
                return;
            }
            const duplicate = llmProviders.value.some(p => p !== provider && p.name === newName);
            if(duplicate) {
                provider.name = oldName;
                showToast(`Provider ID 已存在：${newName}`, 'error', 6000);
                return;
            }
            if(oldName && oldName !== newName) {
                llmFlows.value.forEach(flow => {
                    flow.providers = (flow.providers || []).map(name => name === oldName ? newName : name);
                });
            }
            provider._original_name = newName;
        };

        const deleteLlmProvider = (provider) => {
            if(!provider?.name) return;
            const refs = llmFlows.value.filter(flow => (flow.providers || []).includes(provider.name)).map(flow => flow.name);
            const message = refs.length
                ? `确认删除 Provider ${provider.name}？它会同时从这些业务流移除：${refs.join(', ')}`
                : `确认删除 Provider ${provider.name}？`;
            if(!confirm(message)) return;
            llmProviders.value = llmProviders.value.filter(p => p !== provider);
            const fallback = llmProviders.value[0]?.name || '';
            llmFlows.value.forEach(flow => {
                flow.providers = (flow.providers || []).filter(name => name !== provider.name);
                if(!flow.providers.length && fallback) flow.providers = [fallback];
            });
            showToast(`已删除 Provider：${provider.name}`, 'info', 4000);
        };

        const availableProvidersForFlow = (flow) => {
            const selected = new Set(flow.providers || []);
            return llmProviders.value.filter(provider => !selected.has(provider.name));
        };

        const addProviderToFlow = (flow) => {
            if(!flow.new_provider) return;
            flow.providers = flow.providers || [];
            if(!flow.providers.includes(flow.new_provider)) {
                flow.providers.push(flow.new_provider);
            }
            flow.new_provider = '';
        };

        const removeFlowProvider = (flow, idx) => {
            if(!flow.providers || flow.providers.length <= 1) return;
            flow.providers.splice(idx, 1);
        };

        const moveFlowProvider = (flow, idx, delta) => {
            const providers = flow.providers || [];
            const target = idx + delta;
            if(target < 0 || target >= providers.length) return;
            const [item] = providers.splice(idx, 1);
            providers.splice(target, 0, item);
        };

        const closePreview = () => {
            previewOpen.value = false;
            isEditingDoc.value = false;
            previewRelated.value = [];
            previewAssociation.value = null;
            previewMeta.value = {};
            previewAuditItem.value = null;
            previewMode.value = 'document';
            candidateWorkbenchItem.value = null;
        };

        const previewDoc = async (path, options = {}) => {
            previewDocPath.value = path;
            previewDocName.value = path.split('/').pop();
            previewOpen.value = true;
            previewLoading.value = true;
            isEditingDoc.value = false;
            previewContent.value = '';
            previewRelated.value = [];
            previewAssociation.value = null;
            previewMeta.value = {};
            previewAuditItem.value = options.auditItem || null;
            previewMode.value = 'document';
            candidateWorkbenchItem.value = null;
            
            try {
                const res = await fetch(`/api/documents/${encodeURIComponent(path)}`);
                if(res.ok) {
                    const data = await res.json();
                    previewContent.value = data.content || '';
                    previewRelated.value = data.related || [];
                    previewAssociation.value = data.association || null;
                    previewMeta.value = data.meta || {};
                } else {
                    previewContent.value = "无法加载文档内容。";
                }
            } catch(e) {
                showToast("加载失败", "error");
            } finally {
                previewLoading.value = false;
            }
        };

        const focusDocInList = async (path) => {
            if(!path) return;
            activeTab.value = 'docs';
            const parts = path.split('/');
            selectedDocFolder.value = parts.length > 1 ? parts.slice(0, -1).join('/') : '';
            docSearchText.value = parts[parts.length - 1] || path;
            docsPage.value = 1;
            await nextTick();
            previewDoc(path);
        };

        const openAuditDoc = async (item) => {
            if(!item?.path) return;
            await previewDoc(item.path, { auditItem: item });
        };

        const openDocAudit = async (path) => {
            if(!path) return;
            activeTab.value = 'settings';
            if(!llmAudit.value && !loadingLlmAudit.value) await loadLlmAudit();
            const item = (llmAudit.value?.items || []).find(x => x.path === path);
            if(item) {
                await previewDoc(path, { auditItem: item });
            } else {
                await previewDoc(path);
                showToast('已打开文档；当前审计筛选中未找到对应条目', 'info', 5000);
            }
        };

        const saveDocContent = async () => {
            try {
                const res = await fetch(`/api/documents/${encodeURIComponent(previewDocPath.value)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: previewContent.value })
                });
                if(res.ok) {
                    showToast("保存成功", "success");
                    isEditingDoc.value = false;
                } else {
                    throw new Error("保存失败");
                }
            } catch(e) {
                showToast("保存出错: " + e.message, "error");
            }
        };

        const loadTranslationModels = async () => {
            try {
                const res = await fetch('/api/translation/models');
                const data = await res.json();
                translationModels.value = data.models || [];
                const current = selectedTranslationModel.value;
                if(!current || current.available === false) {
                    const firstAvailable = translationModels.value.find(m => m.available);
                    translationProvider.value = firstAvailable?.provider || translationModels.value[0]?.provider || 'local_gemma4';
                }
            } catch(e) {
                translationModels.value = [
                    { id: 'deepseek_pro', provider: 'deepseek_pro', provider_name: 'deepseek_pro', kind: 'online', label: 'DeepSeek Pro', model: 'deepseek-v4-pro', available: false, key_env: 'DEEPSEEK_API_KEY', timeout_sec: 90 },
                    { id: 'local_gemma4', provider: 'local_gemma4', provider_name: 'local_gemma4', kind: 'local', label: 'Local Gemma4', model: 'gemma4:e4b', available: true, timeout_sec: 120 }
                ];
                translationProvider.value = 'local_gemma4';
            }
        };

        const retranslateDoc = async () => KBRetranslate.runRetranslate(retranslateContext);

        const loadLlmConfig = async () => {
            await KBSettings.loadLlmConfig(settingsContext);
        };

        const saveLlmConfig = async () => {
            await KBSettings.saveLlmConfig(settingsContext);
        };

        const applyLlmConfigPayload = async (data) => {
            await KBSettings.applyLlmConfigPayload(settingsContext, data);
        };

        const setLlmMode = async (mode) => {
            await KBSettings.setLlmMode(settingsContext, mode);
        };

        const loadLlmBackups = async () => {
            await KBSettings.loadLlmBackups(settingsContext);
        };

        const loadLlmAudit = async () => {
            await KBSettings.loadLlmAudit(settingsContext);
        };

        const resetLlmAuditFilters = async () => {
            Object.assign(llmAuditFilters, { flow: '', provider: '', model: '', status: '', missing: false, fallback: false, retranslated: false });
            await loadLlmAudit();
        };

        const llmAuditExportUrl = (format) => {
            return KBSettings.llmAuditExportUrl(settingsContext, format);
        };

        const exportLlmAudit = (format) => {
            window.open(llmAuditExportUrl(format), '_blank');
        };

        const loadTranslationBackfillAudit = async () => {
            await KBSettings.loadTranslationBackfillAudit(settingsContext);
        };

        const previewTranslationBackfillDryRun = async () => {
            await KBSettings.previewTranslationBackfillDryRun(settingsContext);
        };

        const restoreLlmBackup = async (name) => {
            await KBSettings.restoreLlmBackup(settingsContext, name);
        };

        const testLlmProvider = async (provider) => {
            if(!provider?.name) return;
            provider.testing = true;
            provider.test_result = null;
            try {
                const res = await fetch(`/api/llm/providers/${encodeURIComponent(provider.name)}/test`, { method: 'POST' });
                const data = await res.json();
                provider.test_result = data;
                if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                showToast(`${provider.name} 测试通过`, 'success', 4000);
            } catch(e) {
                provider.test_result = provider.test_result || { ok: false, error: e.message };
                showToast(`${provider.name} 测试失败: ${e.message}`, 'error', 7000);
            } finally {
                provider.testing = false;
            }
        };

        // --- Document Management ---
        const docs = ref([]);
        const loadingDocs = ref(false);
        const docSearchText = ref('');
        const selectedDocFolder = ref('');
        const docsPage = ref(1);
        const docsPageSize = ref(80);
        const isMaintaining = ref(false);
        const maintenanceReport = ref(null);
        const repairingQuality = ref(false);
        const candidates = ref([]);
        const candidateSummary = ref(null);
        const candidateTierFilter = ref('');
        const candidateTypeFilter = ref('');
        const candidateIncludeSkipped = ref(false);
        const loadingCandidates = ref(false);
        const importingCandidateId = ref('');
        const translatingCandidateId = ref('');
        const batchTranslatingPreview = ref(false);
        const batchSkippingCandidates = ref(false);
        const batchImportingA = ref(false);
        const batchImportLimit = ref(20);
        const batchImportRetries = ref(2);
        const batchImportJob = ref(null);
        const candidateEditOpen = ref(false);
        const savingCandidateEdit = ref(false);
        const candidateEditItem = ref(null);
        const candidateEditOriginalTitle = ref('');
        const candidateEditForm = reactive({ id: '', title: '', category: '技术', tagsText: '', notes: '' });
        const lastImportResult = ref(null);
        const tierMeta = {
            A: { title: 'A · 优先导入', badgeClass: 'badge-success', borderClass: 'border-success/40', order: 0 },
            B: { title: 'B · 值得审核', badgeClass: 'badge-info', borderClass: 'border-info/40', order: 1 },
            C: { title: 'C · 低优先级', badgeClass: 'badge-warning', borderClass: 'border-warning/40', order: 2 },
            D: { title: 'D · 建议跳过', badgeClass: 'badge-ghost', borderClass: 'border-base-300', order: 3 },
            '?': { title: '未评级', badgeClass: 'badge-ghost', borderClass: 'border-base-300', order: 4 },
        };
        const candidateTime = (item) => {
            const raw = item.publish_time || item.modified || '';
            const t = Date.parse(raw);
            return Number.isFinite(t) ? t : 0;
        };
        const candidateGroups = computed(() => {
            const map = {};
            for(const item of candidates.value || []) {
                const tier = item.quality_tier || '?';
                if(!map[tier]) map[tier] = [];
                map[tier].push(item);
            }
            return Object.entries(map)
                .map(([tier, items]) => {
                    items.sort((a,b) => candidateTime(b) - candidateTime(a));
                    const meta = tierMeta[tier] || tierMeta['?'];
                    return { tier, items, ...meta };
                })
                .sort((a,b) => (a.order ?? 9) - (b.order ?? 9));
        });
        const tierBadgeClass = (tier) => (tierMeta[tier] || tierMeta['?']).badgeClass;
        const tierLabel = (tier) => (tierMeta[tier] || tierMeta['?']).title.replace(/^. · /, '');
        const tierCardClass = (tier) => {
            if(tier === 'A') return 'bg-success/5 border-success/30';
            if(tier === 'B') return 'bg-info/5 border-info/30';
            if(tier === 'C') return 'bg-warning/5 border-warning/30';
            return 'bg-base-200 border-base-300';
        };
        const formatCandidateDate = (item) => {
            const raw = item.publish_time || item.modified || '';
            const d = new Date(raw);
            if(Number.isNaN(d.getTime())) return raw || '无日期';
            return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
        };
        const candidateContext = {
            candidates,
            candidateSummary,
            candidateTierFilter,
            candidateTypeFilter,
            candidateIncludeSkipped,
            loadingCandidates,
            importingCandidateId,
            translatingCandidateId,
            batchTranslatingPreview,
            batchSkippingCandidates,
            batchImportingA,
            batchImportLimit,
            batchImportRetries,
            batchImportJob,
            candidateEditOpen,
            savingCandidateEdit,
            candidateEditItem,
            candidateEditOriginalTitle,
            candidateEditForm,
            lastImportResult,
            stats,
            previewMode,
            showToast,
            closePreview,
            loadDocs: (...args) => loadDocs(...args),
            previewCandidate: (...args) => previewCandidate(...args)
        };
        const wechatSources = ref([]);
        const loadingWechatSources = ref(false);
        const savingWechatSource = ref(false);
        const discoveringWechat = ref(false);
        const wechatDiscoveryResult = ref(null);
        const newWechatSource = ref({ name: '', sample_url: '', tags: '', priority: 'normal' });
        const discoverForm = ref({ source: '', since: '', limit: 10, url: '' });
        const rssFeeds = ref([]);
        const loadingRssFeeds = ref(false);
        const syncingRss = ref(false);
        const rssSyncResult = ref(null);
        const rssNewForm = ref({ url: '', name: '', category: 'articles', priority: 'medium', tags: '', notes: '', language: 'en', interval_minutes: 360, max_articles: 10, enabled: true });
        const dragOver = ref(false);
        const stats = ref({});
        const showUrlInput = ref(false);
        const fetchUrlInput = ref('');
        const isFetchingUrl = ref(false);
        const fetchUrlError = ref('');
        const fetchUrlSuccess = ref(false);
        const failedImports = ref([]);
        const qualityOnly = ref(false);
        const qualityIssueLabels = {
            summary_placeholder: '摘要缺失',
            keypoints_placeholder: '关键点缺失',
            entities_placeholder: '实体缺失',
            quality_scan_failed: '扫描失败',
        };
        const issueLabel = (issue) => qualityIssueLabels[issue] || issue;
        const issueText = (issues) => (issues || []).map(issueLabel).join(' / ');
        const maintenanceContext = {
            activeTab,
            associationReport,
            isMaintaining,
            loadingAssociations,
            maintenanceReport,
            previewDocPath,
            qualityBadCount,
            repairingQuality,
            issueText,
            nextTick,
            showToast,
            initGraph: (...args) => initGraph(...args),
            loadDocs: (...args) => loadDocs(...args),
            previewDoc: (...args) => previewDoc(...args)
        };
        const documentsContext = {
            docs,
            failedImports,
            fetchUrlError,
            fetchUrlInput,
            fetchUrlSuccess,
            isFetchingUrl,
            loadingDocs,
            stats,
            showToast
        };

        const loadDocs = async () => {
            await KBDocuments.loadDocs(documentsContext);
        };

        const filteredDocs = computed(() => {
            const q = docSearchText.value.trim().toLowerCase();
            let list = docs.value.slice().sort((a, b) => b.mtime - a.mtime);
            if(qualityOnly.value) list = list.filter(d => d.quality && !d.quality.ok);
            if(!q) return list;
            return list.filter(d => d.name.toLowerCase().includes(q) || d.relpath.toLowerCase().includes(q) || (d.type || '').toLowerCase().includes(q));
        });

        watch([docSearchText, selectedDocFolder, qualityOnly], () => { docsPage.value = 1; });

        const folderRows = computed(() => {
            const dirs = new Map();
            const addDir = (path) => {
                if(!dirs.has(path)) dirs.set(path, { path, label: path ? path.split('/').pop() : '全部文档', depth: path ? path.split('/').length - 1 : 0, count: 0 });
            };
            addDir('');
            docs.value.forEach(doc => {
                const parts = doc.relpath.split('/');
                if(parts.length > 1) {
                    for(let i = 1; i < parts.length; i++) addDir(parts.slice(0, i).join('/'));
                }
            });
            dirs.forEach(folder => {
                folder.count = folder.path === ''
                    ? docs.value.length
                    : docs.value.filter(d => d.relpath.startsWith(folder.path + '/')).length;
            });
            return Array.from(dirs.values()).sort((a, b) => {
                if(a.path === '') return -1;
                if(b.path === '') return 1;
                return a.path.localeCompare(b.path, 'zh-Hans-CN');
            });
        });

        const visibleDocs = computed(() => {
            const folder = selectedDocFolder.value;
            const list = !folder ? filteredDocs.value : filteredDocs.value.filter(d => d.relpath.startsWith(folder + '/'));
            return list;
        });
        const docsTotalPages = computed(() => Math.max(1, Math.ceil(visibleDocs.value.length / docsPageSize.value)));
        const pagedVisibleDocs = computed(() => {
            const start = (docsPage.value - 1) * docsPageSize.value;
            return visibleDocs.value.slice(start, start + docsPageSize.value);
        });

        const qualityBadCount = computed(() => docs.value.filter(d => d.quality && !d.quality.ok).length);
        const qualityIssueSummary = computed(() => {
            const counts = {};
            docs.value.forEach(d => (d.quality?.issues || []).forEach(i => { counts[i] = (counts[i] || 0) + 1; }));
            return Object.entries(counts)
                .sort((a, b) => b[1] - a[1])
                .map(([issue, count]) => `${issueLabel(issue)} ${count}`)
                .join('，');
        });

        const repairDocQuality = async (path) => {
            await KBMaintenance.repairDocQuality(maintenanceContext, path);
        };

        const repairAllQuality = async () => {
            await KBMaintenance.repairAllQuality(maintenanceContext);
        };

        const loadRssFeeds = async () => {
            loadingRssFeeds.value = true;
            try {
                const res = await fetch('/api/rss/feeds');
                const data = await res.json();
                rssFeeds.value = data.feeds || [];
            } catch(e) { showToast('加载RSS订阅失败', 'error'); }
            finally { loadingRssFeeds.value = false; }
        };

        const saveRssFeed = async () => {
            const payload = { ...rssNewForm.value };
            if(typeof payload.tags === 'string') payload.tags = payload.tags.split(',').map(t=>t.trim()).filter(Boolean);
            try {
                const res = await fetch('/api/rss/feeds', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if(!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
                showToast('RSS订阅已保存', 'success');
                rssNewForm.value = { url: '', name: '', category: 'articles', priority: 'medium', tags: '', notes: '', language: 'en', interval_minutes: 360, max_articles: 10, enabled: true };
                await loadRssFeeds();
            } catch(e) { showToast(`保存失败: ${e.message}`, 'error'); }
        };

        const deleteRssFeed = async (key) => {
            if(!confirm(`确认删除订阅源 "${key}"？`)) return;
            try {
                const res = await fetch(`/api/rss/feeds/${encodeURIComponent(key)}`, { method: 'DELETE' });
                if(!res.ok) throw new Error(`HTTP ${res.status}`);
                showToast('已删除', 'success');
                await loadRssFeeds();
            } catch(e) { showToast(`删除失败: ${e.message}`, 'error'); }
        };

        const toggleRssFeed = async (key) => {
            try {
                const feed = rssFeeds.value.find(f => f.key === key);
                if(!feed) return;
                const res = await fetch(`/api/rss/feeds/${encodeURIComponent(key)}`, {
                    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: !feed.enabled })
                });
                if(!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
                feed.enabled = !feed.enabled;
                showToast(`已${feed.enabled ? '启用' : '禁用'} ${feed.name || key}`, 'success');
            } catch(e) { showToast(`操作失败: ${e.message}`, 'error'); }
        };

        const syncRss = async (feedKey=null) => {
            if(typeof feedKey !== 'string') feedKey = null;
            syncingRss.value = true;
            rssSyncResult.value = null;
            try {
                const payload = { limit: 5 };
                if(feedKey) payload.feed_key = feedKey;
                const res = await fetch('/api/rss/sync', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                rssSyncResult.value = data;
                if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                showToast(`RSS同步完成: ${data.new} 新, ${data.skipped} 跳过, ${data.errors} 错误`, data.new > 0 ? 'success' : 'info', 6000);
                await loadRssFeeds();
                await loadCandidates();
            } catch(e) { showToast(`RSS同步失败: ${e.message}`, 'error', 8000); }
            finally { syncingRss.value = false; }
        };

        const loadWechatSources = async () => {
            loadingWechatSources.value = true;
            try {
                const res = await fetch('/api/wechat/sources');
                const data = await res.json();
                wechatSources.value = data.sources || [];
            } catch(e) { showToast('加载公众号订阅失败', 'error'); }
            finally { loadingWechatSources.value = false; }
        };

        const saveWechatSource = async () => {
            savingWechatSource.value = true;
            try {
                const res = await fetch('/api/wechat/sources', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newWechatSource.value)
                });
                const data = await res.json();
                if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                showToast('公众号订阅已保存', 'success');
                newWechatSource.value = { name: '', sample_url: '', tags: '', priority: 'normal' };
                await loadWechatSources();
            } catch(e) { showToast(`保存失败: ${e.message}`, 'error'); }
            finally { savingWechatSource.value = false; }
        };

        const discoverWechat = async (sourceName=null) => {
            if(sourceName && typeof sourceName !== 'string') sourceName = null;
            discoveringWechat.value = true;
            wechatDiscoveryResult.value = null;
            try {
                const payload = { ...discoverForm.value };
                if(sourceName) payload.source = sourceName;
                const res = await fetch('/api/wechat/discover', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                wechatDiscoveryResult.value = data;
                if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                showToast('搜索发现完成，候选已进入候选池', 'success', 6000);
                await loadWechatSources();
                await loadCandidates();
            } catch(e) { showToast(`发现失败: ${e.message}`, 'error', 8000); }
            finally { discoveringWechat.value = false; }
        };

        const loadCandidates = async () => {
            await KBCandidates.loadCandidates(candidateContext);
        };

        const previewCandidate = async (id) => {
            previewLoading.value = true;
            previewOpen.value = true;
            isEditingDoc.value = false;
            previewRelated.value = [];
            previewAssociation.value = null;
            previewMeta.value = {};
            previewAuditItem.value = null;
            try {
                const res = await fetch(`/api/candidates/${encodeURIComponent(id)}`);
                const data = await res.json();
                previewMode.value = 'candidate';
                candidateWorkbenchItem.value = data;
                KBCandidates.setCandidateEditForm(candidateContext, data);
                previewDocName.value = data.translated_title || data.title || '候选文章';
                const trans = data.translation || {};
                const zhTitle = data.translated_title || trans.translated_title || '';
                const zhSummary = data.translated_summary || trans.translated_summary || '';
                const zhContent = data.translated_content || trans.translated_content || '';
                const topics = data.translated_topics || trans.topics || [];
                const keyTerms = data.key_terms || trans.key_terms || [];
                const quality = data.quality || {};
                const parts = [];
                if(zhTitle || zhSummary || zhContent) {
                    parts.push(`# ${zhTitle || data.title || '候选文章'}`);
                    parts.push(`> 质量等级：${data.quality_tier || '?'} · ${data.quality_score ?? 0}分 · ${quality.recommendation || ''}`);
                    if(data.title && zhTitle && data.title !== zhTitle) parts.push(`> 原文标题：${data.title}`);
                    if(data.source_name) parts.push(`> 来源：${data.source_name}`);
                    if(data.publish_time) parts.push(`> 发布时间：${data.publish_time}`);
                    if(data.url) parts.push(`> 链接：${data.url}`);
                    if(topics.length) parts.push(`> 中文主题：${topics.join(' / ')}`);
                    if(keyTerms.length) parts.push(`> 关键术语：${keyTerms.join(' / ')}`);
                    parts.push('');
                    parts.push('## 中文预览');
                    parts.push(zhContent || zhSummary || '（暂无中文正文，仅有标题翻译）');
                    if(quality.reasons?.length || quality.penalties?.length) {
                        parts.push('');
                        parts.push('## 质量判断理由');
                        for(const r of (quality.reasons || [])) parts.push(`- + ${r}`);
                        for(const p of (quality.penalties || [])) parts.push(`- - ${p}`);
                    }
                    parts.push('');
                    parts.push('---');
                    parts.push('');
                    parts.push('## 英文原文');
                    parts.push(data.content || '');
                    previewContent.value = parts.join('\n');
                } else {
                    previewContent.value = data.content || '';
                }
                previewDocPath.value = '';
            } catch(e) {
                showToast('加载候选预览失败', 'error');
            } finally {
                previewLoading.value = false;
            }
        };

        const translateCandidate = async (id, options={}) => {
            await KBCandidates.translateCandidate(candidateContext, id, options);
        };

        const batchTranslatePreview = async () => {
            await KBCandidates.batchTranslatePreview(candidateContext);
        };

        const editCandidate = (item) => {
            KBCandidates.editCandidate(candidateContext, item);
        };

        const closeCandidateEdit = () => {
            KBCandidates.closeCandidateEdit(candidateContext);
        };

        const saveCandidateEdit = async () => {
            await KBCandidates.saveCandidateEdit(candidateContext);
        };

        const saveCandidateReviewInline = async () => {
            await KBCandidates.saveCandidateReviewInline(candidateContext);
        };

        const loadBatchImportStatus = async () => {
            return KBCandidates.loadBatchImportStatus(candidateContext);
        };

        const startBatchImportPolling = () => {
            KBCandidates.startBatchImportPolling(candidateContext);
        };

        const batchImportA = async () => {
            await KBCandidates.batchImportA(candidateContext);
        };

        const batchSkipLowQuality = async () => {
            await KBCandidates.batchSkipLowQuality(candidateContext);
        };

        const importCandidate = async (id) => {
            await KBCandidates.importCandidate(candidateContext, id);
        };

        const skipCandidate = async (id) => {
            await KBCandidates.skipCandidate(candidateContext, id);
        };

        const restoreCandidate = async (id) => {
            await KBCandidates.restoreCandidate(candidateContext, id);
        };

        const openLastImportedDoc = async () => {
            if(!lastImportResult.value?.wiki_path) return;
            switchTab('docs');
            await nextTick();
            previewDoc(lastImportResult.value.wiki_path);
        };

        const searchLastImported = async () => {
            const q = lastImportResult.value?.search_query || lastImportResult.value?.wiki_path || '';
            if(!q) return;
            docSearchText.value = q;
            switchTab('docs');
            await loadDocs();
            showToast(`已按导入内容过滤文档：${q}`, 'info', 5000);
        };

        const runMaintenance = async () => {
            await KBMaintenance.runMaintenance(maintenanceContext);
        };

        const deleteDoc = async (path) => {
            await KBDocuments.deleteDoc(documentsContext, path);
        };

        const fetchUrl = async () => {
            await KBDocuments.fetchUrl(documentsContext);
        };

        const handleFileUpload = async (e) => {
            const files = e.target.files;
            if(!files.length) return;
            await uploadFiles(files);
        };
        const handleDrop = async (e) => {
            dragOver.value = false;
            const files = e.dataTransfer.files;
            if(!files.length) return;
            await uploadFiles(files);
        };
        const uploadFiles = async (files) => {
            await KBDocuments.uploadFiles(documentsContext, files);
        };

        const retryFailedImport = async (item) => {
            await KBDocuments.retryFailedImport(documentsContext, item);
        };

        const formatBytes = (bytes) => {
            if(bytes === 0) return '0 B';
            const k = 1024, sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        };
        const formatDate = (ts) => new Date(ts*1000).toLocaleDateString();


        const loadAssociations = async (rebuild=false) => {
            await KBMaintenance.loadAssociations(maintenanceContext, rebuild);
        };

        // --- Knowledge Graph (ECharts) ---
        let chartInstance = null;
        const initGraph = async () => {
            const container = document.getElementById('graph-container');
            if(!container) return;
            
            if(chartInstance) { chartInstance.dispose(); }
            
            chartInstance = echarts.init(container, theme.value === 'dark' ? 'dark' : null);
            chartInstance.showLoading({ color: '#3b82f6', maskColor: theme.value==='dark'?'rgba(29,35,42,0.8)':'rgba(255,255,255,0.8)'});

            try {
                let apiUrl = '/api/graph?limit=50';
                const q = graphSearchText.value.trim();
                if (q) apiUrl += '&entity=' + encodeURIComponent(q) + '&mode=neighbors';
                const res = await fetch(apiUrl);
                const data = await res.json();
                
                if(!data.nodes || data.nodes.length === 0) {
                    chartInstance.hideLoading();
                    return;
                }

                const isDark = theme.value === 'dark';
                const textColor = isDark ? '#a6adbb' : '#1f2937';
                const lineColor = isDark ? '#4b5563' : '#d1d5db';

                if (graphLayout.value === 'sankey') {
                    renderSankey(data, isDark);
                } else if (graphLayout.value === 'tree') {
                    renderTree(data, isDark);
                } else if (graphLayout.value === 'chord') {
                    renderChord(data, isDark, textColor);
                } else {
                    renderForceOrCircular(data, isDark, textColor, lineColor);
                }
            } catch(e) {
                console.error("Graph error:", e);
                chartInstance.hideLoading();
                showToast("加载图谱失败", "error");
            }
        };

        const renderForceOrCircular = (data, isDark, textColor, lineColor) => {
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
                        shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)'
                    },
                    label: {
                        show: graphLayout.value === 'circular' || totalNodes < 60,
                        position: graphLayout.value === 'circular' ? 'right' : 'bottom',
                        rotate: graphLayout.value === 'circular' ? 0 : 0,
                        formatter: '{b}',
                        color: textColor,
                        fontSize: 12,
                        backgroundColor: isDark ? 'rgba(0,0,0,0.5)' : 'rgba(255,255,255,0.7)',
                        padding: [2, 4], borderRadius: 4
                    },
                    type: n.type, categories: n.categories || [n.category || '其他'], path: n.path
                };
            });

            const option = {
                backgroundColor: 'transparent',
                tooltip: { trigger: 'item' },
                series: [{
                    type: 'graph',
                    layout: graphLayout.value,
                    data: nodes,
                    links: data.links.map(l => ({
                        source: l.source, target: l.target,
                        lineStyle: { width: 1.5, opacity: 0.4, curveness: 0.1 }
                    })),
                    roam: true,
                    focusNodeAdjacency: true,
                    force: {
                        repulsion: 1000, gravity: 0.05, edgeLength: [80, 200], friction: 0.8
                    },
                    circular: { rotateLabel: true },
                    lineStyle: { color: lineColor, curveness: 0.3 },
                    emphasis: { lineStyle: { width: 4, opacity: 1 }, label: { show: true } }
                }]
            };
            chartInstance.hideLoading();
            chartInstance.setOption(option);
            
            chartInstance.on('click', (p) => {
                if(p.dataType === 'node' && p.data.path) previewDoc(p.data.path);
                else if (p.dataType === 'node') { ask(p.data.name); switchTab('chat'); }
            });
        };

        const graphDocCategory = (docNode) => {
            if(docNode.path && docNode.path.includes('/')) return docNode.path.split('/').slice(0, -1).join('/');
            const cats = Array.isArray(docNode.categories) ? docNode.categories : (docNode.category ? [docNode.category] : []);
            return (cats[0] && cats[0] !== '文档') ? cats[0] : 'root';
        };

        const renderTree = (data, isDark) => {
            const docNodes = data.nodes.filter(n => n.type === 'document');
            const nodeById = new Map(data.nodes.map(n => [n.id, n]));
            const entitiesByDoc = new Map();
            data.links.forEach(l => {
                const src = nodeById.get(l.source);
                const tgt = nodeById.get(l.target);
                if(src && tgt && src.type === 'document' && tgt.type !== 'document') {
                    if(!entitiesByDoc.has(src.id)) entitiesByDoc.set(src.id, []);
                    entitiesByDoc.get(src.id).push(tgt);
                } else if(src && tgt && tgt.type === 'document' && src.type !== 'document') {
                    if(!entitiesByDoc.has(tgt.id)) entitiesByDoc.set(tgt.id, []);
                    entitiesByDoc.get(tgt.id).push(src);
                }
            });

            const root = { name: webuiApp.value.name || 'Knowledge Base', children: [] };
            const folders = new Map();
            const ensureFolder = (path) => {
                if(!path || path === 'root') {
                    if(!folders.has('root')) {
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
                    if(!folders.has(currentPath)) {
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
                    .filter(e => { const name = e.name || e.label || e.id; if(seen.has(name)) return false; seen.add(name); return true; })
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
                    top: '4%', left: '8%', bottom: '4%', right: '22%',
                    orient: 'LR',
                    symbol: 'emptyCircle',
                    symbolSize: 8,
                    expandAndCollapse: true,
                    initialTreeDepth: 3,
                    roam: true,
                    label: {
                        position: 'left', verticalAlign: 'middle', align: 'right',
                        color: isDark ? '#ccc' : '#333', fontSize: 12
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
                if(p.data && p.data.path) previewDoc(p.data.path);
            });
        };

        const renderChord = (data, isDark, textColor) => {
            const docNodes = data.nodes.filter(n => n.type === 'document');
            const nodeById = new Map(data.nodes.map(n => [n.id, n]));
            const categoryNodes = new Map();
            const entityNodes = new Map();
            const links = [];

            docNodes.forEach(doc => {
                const cat = graphDocCategory(doc);
                if(!categoryNodes.has(cat)) {
                    categoryNodes.set(cat, { id: 'cat_' + cat, name: cat, type: 'category', symbolSize: 34, itemStyle: { color: '#8b5cf6' } });
                }
                links.push({ source: 'cat_' + cat, target: doc.id, value: 2 });
            });

            data.links.forEach(l => {
                const src = nodeById.get(l.source);
                const tgt = nodeById.get(l.target);
                const doc = src?.type === 'document' ? src : (tgt?.type === 'document' ? tgt : null);
                const ent = src?.type === 'document' ? tgt : (tgt?.type === 'document' ? src : null);
                if(!doc || !ent || ent.type === 'document') return;
                const entName = ent.name || ent.label || ent.id;
                if(!entityNodes.has(ent.id)) {
                    entityNodes.set(ent.id, { id: ent.id, name: entName, type: 'entity', symbolSize: 18 + Math.min((ent.freq || 1) * 2, 18), itemStyle: { color: '#10b981' } });
                }
                links.push({ source: doc.id, target: ent.id, value: 1 });
            });

            const nodes = [
                ...Array.from(categoryNodes.values()),
                ...docNodes.map(d => ({
                    id: d.id, name: d.name || d.id, type: 'document', path: d.path, symbolSize: 26,
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
                    data: nodes.map(n => ({...n, category: n.type})),
                    categories: [
                        { name: 'category' },
                        { name: 'document' },
                        { name: 'entity' }
                    ],
                    links: links.map(l => ({
                        source: l.source, target: l.target, value: l.value,
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
                if(p.dataType === 'node' && p.data.path) previewDoc(p.data.path);
                else if(p.dataType === 'node' && p.data.type === 'entity') { ask(p.data.name); switchTab('chat'); }
            });
        };

        const renderSankey = (data, isDark) => {
            // Transform Graph to Sankey: Category -> Doc -> Entity
            const nodes = [];
            const links = [];
            const nodeSet = new Set();

            const addNode = (name, depth) => {
                if(!nodeSet.has(name)) {
                    nodes.push({ name: name, itemStyle: { color: depth === 0 ? '#8b5cf6' : (depth === 1 ? '#3b82f6' : '#10b981') } });
                    nodeSet.add(name);
                }
            };

            data.nodes.forEach(n => {
                if(n.type === 'document') {
                    const cats = Array.isArray(n.categories) ? n.categories : (n.category ? [n.category] : ['未分类']);
                    const cat = graphDocCategory(n);
                    addNode(cat, 0);
                    addNode(n.name, 1);
                    links.push({ source: cat, target: n.name, value: 2 });
                }
            });

            data.links.forEach(l => {
                const src = data.nodes.find(n => n.id === l.source);
                const tgt = data.nodes.find(n => n.id === l.target);
                if(src && tgt && src.type === 'document' && tgt.type === 'entity') {
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
                    links: links,
                    emphasis: { focus: 'adjacency' },
                    lineStyle: { color: 'gradient', curveness: 0.5 },
                    label: { color: isDark ? '#ccc' : '#333', fontSize: 12 },
                    nodeAlign: 'left',
                    layoutIterations: 32
                }]
            };
            chartInstance.hideLoading();
            chartInstance.setOption(option);
        };

        // Resize observer for graph
        onMounted(async () => {
            window.addEventListener('resize', () => {
                if(activeTab.value === 'graph' && chartInstance) chartInstance.resize();
            });
            
            // Initial load stats & sidebar counts
            await loadWebuiConfig().catch(()=>{});
            fetch('/api/stats').then(r=>r.json()).then(s => stats.value = s).catch(()=>{});
            if(featureEnabled('candidates')) {
                loadCandidates().catch(()=>{});
                loadBatchImportStatus().then(job => { if(job.running) startBatchImportPolling(); }).catch(()=>{});
            }
            if(featureEnabled('wechat')) loadWechatSources().catch(()=>{});
            if(featureEnabled('rss')) loadRssFeeds().catch(()=>{});
            loadTranslationModels().catch(()=>{});
            if(featureEnabled('llm_settings')) {
                loadLlmConfig().catch(()=>{});
                loadLlmBackups().catch(()=>{});
            }
            if(featureEnabled('llm_audit')) {
                loadLlmAudit().catch(()=>{});
                loadTranslationBackfillAudit().catch(()=>{});
            }
        });

        return {
            activeTab, switchTab, theme, toggleTheme, uiLang, t, mobileMenuOpen, graphLayout, graphSearchText, associationReport, linkQualityHealth, loadingAssociations, loadAssociations,
            webuiConfig, webuiApp, webuiFeatures, featureEnabled, loadingWebuiConfig, savingWebuiConfig, loadWebuiConfig, saveWebuiConfig, saveAllSettings, refreshAllSettings,
            toasts, 
            chatInput, chatHistory, isWaiting, submitChat, chatAnswerMode, renderMarkdown, ask,
            qaProviderChain,
            docs, filteredDocs, folderRows, visibleDocs, pagedVisibleDocs, docsPage, docsPageSize, docsTotalPages, selectedDocFolder, loadingDocs, docSearchText, loadDocs, qualityBadCount, qualityIssueSummary, qualityOnly, issueLabel, issueText, repairingQuality, repairDocQuality, repairAllQuality, deleteDoc,
            isMaintaining, maintenanceReport, runMaintenance,
            candidates, candidateGroups, candidateSummary, candidateTierFilter, candidateTypeFilter, candidateIncludeSkipped, loadingCandidates, importingCandidateId, translatingCandidateId, batchTranslatingPreview, batchImportingA, batchImportLimit, batchImportRetries, batchImportJob, loadBatchImportStatus, batchSkippingCandidates, candidateEditOpen, savingCandidateEdit, candidateEditItem, candidateEditOriginalTitle, candidateEditForm, lastImportResult, openLastImportedDoc, searchLastImported, tierBadgeClass, tierLabel, tierCardClass, formatCandidateDate, loadCandidates, previewCandidate, translateCandidate, batchTranslatePreview, batchImportA, editCandidate, closeCandidateEdit, saveCandidateEdit, batchSkipLowQuality, importCandidate, skipCandidate, restoreCandidate,
            wechatSources, loadingWechatSources, savingWechatSource, discoveringWechat, wechatDiscoveryResult, newWechatSource, discoverForm, loadWechatSources, saveWechatSource, discoverWechat,
            rssFeeds, loadingRssFeeds, syncingRss, rssSyncResult, rssNewForm, loadRssFeeds, saveRssFeed, deleteRssFeed, syncRss, toggleRssFeed,
            dragOver, handleDrop, handleFileUpload, formatBytes, formatDate, stats,
            initGraph,
            previewOpen, previewLoading, previewContent, previewDocName, previewDocPath, previewRelated, previewAssociation, previewMeta, previewAuditItem, previewMode, candidateWorkbenchItem, previewDoc, focusDocInList, openAuditDoc, openDocAudit, closePreview, isEditingDoc, saveDocContent, saveCandidateReviewInline,
            translationModels, translationProvider, selectedTranslationModel, retranslateAction, retranslateButtonTitle, isRetranslating, retranslateDoc,
            llmProviders, llmFlows, llmBackups, llmSecretSetup, llmMode, llmModeOptions, llmModeLabel, llmModeDescription, settingLlmMode,
            fileImportFlow, fileImportProviderChain,
            llmAudit, llmAuditFilters, loadingLlmAudit, translationBackfillAudit, translationBackfillDryRun, loadingTranslationBackfill, loadingLlmConfig, savingLlmConfig, restoringLlmBackup,
            loadLlmConfig, saveLlmConfig, setLlmMode, loadLlmBackups, loadLlmAudit, resetLlmAuditFilters, exportLlmAudit, loadTranslationBackfillAudit, previewTranslationBackfillDryRun, restoreLlmBackup, testLlmProvider, objectEntries,
            addLlmProvider, deleteLlmProvider, syncProviderName, providerLabel, providerTimeout,
            availableProvidersForFlow, addProviderToFlow, removeFlowProvider, moveFlowProvider,
            showUrlInput, fetchUrlInput, isFetchingUrl, fetchUrlError, fetchUrlSuccess, fetchUrl, failedImports, retryFailedImport
        };
    }
}).mount('#app');
