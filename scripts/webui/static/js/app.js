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
        const defaultTranslationPolicy = KBUI.defaultTranslationPolicy;
        const mergeTranslationPolicy = KBUI.mergeTranslationPolicy;
        const webuiConfig = ref({
            app: { name: 'Sunoxi KB', title: 'Sunoxi 知识库', subtitle: 'Personal Knowledge Base', logo: '/static/favicon.svg?v=4' },
            features: { chat: true, graph: true, documents: true, upload: true, url_import: true, candidates: true, rss: true, wechat: true, llm_settings: true, llm_audit: true },
            translation_policy: defaultTranslationPolicy()
        });
        const loadingWebuiConfig = ref(false);
        const savingWebuiConfig = ref(false);
        const webuiApp = computed(() => webuiConfig.value.app || {});
        const webuiFeatures = computed(() => webuiConfig.value.features || {});
        const featureEnabled = (name) => KBUI.featureEnabled(webuiFeatures.value, name);
        const linkQualityHealth = computed(() => KBLinkQuality.summarizeLinkQuality(associationReport.value?.summary || {}));
        const t = (key) => KBUI.translate(uiLang.value, key);
        KBUI.bindLanguage(watch, uiLang);
        KBUI.bindDocumentTitle(watch, webuiApp);

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
            KBUI.toggleTheme({
                theme,
                activeTab,
                hasGraph: () => !!chartInstance,
                initGraph
            });
        };
        KBUI.applyTheme(theme.value);

        // --- Toasts ---
        const { toasts, showToast } = KBUI.createToasts(ref);

        // --- Markdown Setup ---
        const renderMarkdown = KBUI.createMarkdownRenderer();

        // --- Chat System ---
        const chatInput = ref('');
        const chatHistory = ref([]);
        const isWaiting = ref(false);
        const chatAnswerMode = ref(localStorage.getItem('kb_chat_answer_mode') || 'extractive');
        KBChat.bindAnswerMode(watch, chatAnswerMode);
        const chatContext = {
            chatAnswerMode,
            chatHistory,
            chatInput,
            isWaiting,
            nextTick,
            showToast
        };
        const scrollToBottom = () => KBChat.scrollToBottom(chatContext);
        const ask = (text) => KBChat.ask(chatContext, text);
        const submitChat = async () => {
            await KBChat.submitChat(chatContext);
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
        const selectedTranslationModel = computed(() => KBRetranslate.selectedTranslationModel(translationModels.value, translationProvider.value));
        const translationProviderLabel = (model) => KBRetranslate.translationProviderLabel(model, translationProvider.value);
        const translationModelContext = {
            selectedTranslationModel,
            translationModels,
            translationProvider
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
        const llmModeLabel = computed(() => KBSettings.llmModeLabel(llmModeOptions.value, llmMode.value));
        const llmModeDescription = computed(() => KBSettings.llmModeDescription(llmModeOptions.value, llmMode.value));
        const fileImportFlow = computed(() => llmFlows.value.find(f => f.name === 'file_import_structure') || null);
        const fileImportProviderChain = computed(() => KBSettings.flowProviderChain(llmFlows.value, llmProviders.value, 'file_import_structure'));
        const qaFlow = computed(() => llmFlows.value.find(f => f.name === 'qa') || null);
        const qaProviderChain = computed(() => KBSettings.flowProviderChain(llmFlows.value, llmProviders.value, 'qa'));

        const normalizeLlmProviders = KBSettings.normalizeLlmProviders;
        const normalizeLlmFlows = KBSettings.normalizeLlmFlows;
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
            t,
            showToast,
            loadTranslationModels: (...args) => loadTranslationModels(...args)
        };

        const addLlmProvider = () => {
            KBSettings.addLlmProvider(settingsContext);
        };

        const syncProviderName = (provider) => {
            KBSettings.syncProviderName(settingsContext, provider);
        };

        const deleteLlmProvider = (provider) => {
            KBSettings.deleteLlmProvider(settingsContext, provider);
        };

        const availableProvidersForFlow = (flow) => {
            return KBSettings.availableProvidersForFlow(settingsContext, flow);
        };

        const addProviderToFlow = (flow) => {
            KBSettings.addProviderToFlow(flow);
        };

        const removeFlowProvider = (flow, idx) => {
            KBSettings.removeFlowProvider(flow, idx);
        };

        const moveFlowProvider = (flow, idx, delta) => {
            KBSettings.moveFlowProvider(flow, idx, delta);
        };

        const providerLabel = (name) => KBSettings.providerLabel(settingsContext, name);
        const providerTimeout = (name) => KBSettings.providerTimeout(settingsContext, name);

        let previewContext = null;
        const closePreview = () => {
            KBPreview.closePreview(previewContext);
        };

        const previewDoc = async (path, options = {}) => {
            await KBPreview.previewDoc(previewContext, path, options);
        };

        const focusDocInList = async (path) => {
            await KBPreview.focusDocInList(previewContext, path);
        };

        const openAuditDoc = async (item) => {
            await KBPreview.openAuditDoc(previewContext, item);
        };

        const openDocAudit = async (path) => {
            await KBPreview.openDocAudit(previewContext, path);
        };

        const saveDocContent = async () => {
            await KBPreview.saveDocContent(previewContext);
        };

        const loadTranslationModels = async () => {
            await KBRetranslate.loadTranslationModels(translationModelContext);
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
            await KBSettings.resetLlmAuditFilters(settingsContext);
        };

        const llmAuditExportUrl = (format) => {
            return KBSettings.llmAuditExportUrl(settingsContext, format);
        };

        const exportLlmAudit = (format) => {
            KBSettings.exportLlmAudit(settingsContext, format);
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
            await KBSettings.testLlmProvider(settingsContext, provider);
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
        const candidateGroups = computed(() => KBCandidates.buildCandidateGroups(candidates.value));
        const tierBadgeClass = (tier) => KBCandidates.tierBadgeClass(tier);
        const tierLabel = (tier) => KBCandidates.tierLabel(tier);
        const tierCardClass = (tier) => KBCandidates.tierCardClass(tier);
        const formatCandidateDate = (item) => KBCandidates.formatCandidateDate(item);
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
            candidateWorkbenchItem,
            docSearchText,
            isEditingDoc,
            previewAssociation,
            previewAuditItem,
            previewContent,
            previewDocName,
            previewDocPath,
            previewLoading,
            previewMeta,
            previewOpen,
            previewRelated,
            stats,
            previewMode,
            nextTick,
            showToast,
            closePreview,
            switchTab,
            loadDocs: (...args) => loadDocs(...args),
            previewDoc: (...args) => previewDoc(...args),
            previewCandidate: (...args) => previewCandidate(...args)
        };
        const wechatSources = ref([]);
        const loadingWechatSources = ref(false);
        const savingWechatSource = ref(false);
        const discoveringWechat = ref(false);
        const wechatDiscoveryResult = ref(null);
        const newWechatSource = ref(KBSources.defaultWechatSource());
        const discoverForm = ref({ source: '', since: '', limit: 10, url: '' });
        const rssFeeds = ref([]);
        const loadingRssFeeds = ref(false);
        const syncingRss = ref(false);
        const rssSyncResult = ref(null);
        const rssNewForm = ref(KBSources.defaultRssForm());
        const dragOver = ref(false);
        const stats = ref({});
        const showUrlInput = ref(false);
        const fetchUrlInput = ref('');
        const isFetchingUrl = ref(false);
        const fetchUrlError = ref('');
        const fetchUrlSuccess = ref(false);
        const failedImports = ref([]);
        const qualityOnly = ref(false);
        const issueLabel = (issue) => KBDocuments.issueLabel(issue);
        const issueText = (issues) => KBDocuments.issueText(issues);
        previewContext = {
            activeTab,
            candidateWorkbenchItem,
            docSearchText,
            docsPage,
            isEditingDoc,
            llmAudit,
            loadingLlmAudit,
            previewAssociation,
            previewAuditItem,
            previewContent,
            previewDocName,
            previewDocPath,
            previewLoading,
            previewMeta,
            previewMode,
            previewOpen,
            previewRelated,
            selectedDocFolder,
            nextTick,
            showToast,
            loadLlmAudit: (...args) => loadLlmAudit(...args)
        };
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
            dragOver,
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
        const sourcesContext = {
            discoveringWechat,
            discoverForm,
            loadingRssFeeds,
            loadingWechatSources,
            newWechatSource,
            rssFeeds,
            rssNewForm,
            rssSyncResult,
            savingWechatSource,
            syncingRss,
            wechatDiscoveryResult,
            wechatSources,
            showToast,
            loadCandidates: (...args) => loadCandidates(...args)
        };

        const loadDocs = async () => {
            await KBDocuments.loadDocs(documentsContext);
        };

        const filteredDocs = computed(() => KBDocuments.filterDocs(docs.value, {
            query: docSearchText.value,
            qualityOnly: qualityOnly.value
        }));

        watch([docSearchText, selectedDocFolder, qualityOnly], () => { docsPage.value = 1; });

        const folderRows = computed(() => KBDocuments.buildFolderRows(docs.value));

        const visibleDocs = computed(() => KBDocuments.visibleDocs(filteredDocs.value, selectedDocFolder.value));
        const docsTotalPages = computed(() => KBDocuments.totalPages(visibleDocs.value, docsPageSize.value));
        const pagedVisibleDocs = computed(() => KBDocuments.pageItems(visibleDocs.value, docsPage.value, docsPageSize.value));

        const qualityBadCount = computed(() => KBDocuments.qualityBadCount(docs.value));
        const qualityIssueSummary = computed(() => KBDocuments.qualityIssueSummary(docs.value));

        const repairDocQuality = async (path) => {
            await KBMaintenance.repairDocQuality(maintenanceContext, path);
        };

        const repairAllQuality = async () => {
            await KBMaintenance.repairAllQuality(maintenanceContext);
        };

        const loadRssFeeds = async () => {
            await KBSources.loadRssFeeds(sourcesContext);
        };

        const saveRssFeed = async () => {
            await KBSources.saveRssFeed(sourcesContext);
        };

        const deleteRssFeed = async (key) => {
            await KBSources.deleteRssFeed(sourcesContext, key);
        };

        const toggleRssFeed = async (key) => {
            await KBSources.toggleRssFeed(sourcesContext, key);
        };

        const syncRss = async (feedKey=null) => {
            await KBSources.syncRss(sourcesContext, feedKey);
        };

        const loadWechatSources = async () => {
            await KBSources.loadWechatSources(sourcesContext);
        };

        const saveWechatSource = async () => {
            await KBSources.saveWechatSource(sourcesContext);
        };

        const discoverWechat = async (sourceName=null) => {
            await KBSources.discoverWechat(sourcesContext, sourceName);
        };

        const loadCandidates = async () => {
            await KBCandidates.loadCandidates(candidateContext);
        };

        const previewCandidate = async (id) => {
            await KBCandidates.previewCandidate(candidateContext, id);
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
            await KBCandidates.openLastImportedDoc(candidateContext);
        };

        const searchLastImported = async () => {
            await KBCandidates.searchLastImported(candidateContext);
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
            await KBDocuments.handleFileUpload(documentsContext, e);
        };
        const handleDrop = async (e) => {
            await KBDocuments.handleDrop(documentsContext, e);
        };
        const uploadFiles = async (files) => {
            await KBDocuments.uploadFiles(documentsContext, files);
        };

        const retryFailedImport = async (item) => {
            await KBDocuments.retryFailedImport(documentsContext, item);
        };

        const formatBytes = KBUI.formatBytes;
        const formatDate = KBUI.formatDate;


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
            await KBUI.mountApp({
                activeTab,
                stats,
                featureEnabled,
                hasGraph: () => !!chartInstance,
                resizeGraph: () => chartInstance.resize(),
                loadWebuiConfig,
                loadCandidates,
                loadBatchImportStatus,
                startBatchImportPolling,
                loadWechatSources,
                loadRssFeeds,
                loadTranslationModels,
                loadLlmConfig,
                loadLlmBackups,
                loadLlmAudit,
                loadTranslationBackfillAudit
            });
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
