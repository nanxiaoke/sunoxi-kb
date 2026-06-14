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

        let navigationContext = null;
        const { switchTab, toggleTheme } = KBUI.createActions(() => navigationContext);
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
        const { scrollToBottom, ask, submitChat } = KBChat.createActions(chatContext);
        let graphContext = null;
        const { initGraph } = KBGraph.createActions(() => graphContext);

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
        retranslateContext.retranslateAction = retranslateAction;
        const retranslateButtonTitle = computed(() => retranslateAction.value.title);
        const llmModeLabel = computed(() => KBSettings.llmModeLabel(llmModeOptions.value, llmMode.value));
        const llmModeDescription = computed(() => KBSettings.llmModeDescription(llmModeOptions.value, llmMode.value));
        const fileImportFlow = computed(() => KBSettings.flowByName(llmFlows.value, 'file_import_structure'));
        const fileImportProviderChain = computed(() => KBSettings.flowProviderChain(llmFlows.value, llmProviders.value, 'file_import_structure'));
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
            featureEnabled,
            normalizeLlmProviders,
            normalizeLlmFlows,
            t,
            showToast,
            loadTranslationModels: (...args) => loadTranslationModels(...args)
        };

        const {
            addLlmProvider,
            syncProviderName,
            deleteLlmProvider,
            availableProvidersForFlow,
            addProviderToFlow,
            removeFlowProvider,
            moveFlowProvider,
            providerLabel,
            providerTimeout,
            loadWebuiConfig,
            saveWebuiConfig,
            saveAllSettings,
            refreshAllSettings,
            loadLlmConfig,
            saveLlmConfig,
            setLlmMode,
            loadLlmBackups,
            loadLlmAudit,
            resetLlmAuditFilters,
            exportLlmAudit,
            loadTranslationBackfillAudit,
            previewTranslationBackfillDryRun,
            restoreLlmBackup,
            testLlmProvider
        } = KBSettings.createActions(settingsContext);

        let previewContext = null;
        const {
            closePreview,
            previewDoc,
            focusDocInList,
            openAuditDoc,
            openDocAudit,
            saveDocContent
        } = KBPreview.createActions(() => previewContext);

        // --- Document Management ---
        const docs = ref([]);
        const loadingDocs = ref(false);
        const docSearchText = ref('');
        const selectedDocFolder = ref('');
        const docsPage = ref(1);
        const docsPageSize = ref(80);
        const isMaintaining = ref(false);
        const maintenanceReport = ref(null);
        const stats = ref({});
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
        const showUrlInput = ref(false);
        const fetchUrlInput = ref('');
        const isFetchingUrl = ref(false);
        const fetchUrlError = ref('');
        const fetchUrlSuccess = ref(false);
        const failedImports = ref([]);
        const qualityOnly = ref(false);
        const qualityBadCount = computed(() => KBDocuments.qualityBadCount(docs.value));
        const qualityIssueSummary = computed(() => KBDocuments.qualityIssueSummary(docs.value));
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
        const {
            loadTranslationModels,
            retranslateDoc
        } = KBRetranslate.createActions(retranslateContext);
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
        navigationContext = {
            activeTab,
            mobileMenuOpen,
            previewOpen,
            theme,
            nextTick,
            showToast,
            featureEnabled,
            hasGraph: () => KBGraph.hasGraph(),
            closePreview: (...args) => closePreview(...args),
            initGraph: (...args) => initGraph(...args),
            loadAssociations: (...args) => loadAssociations(...args),
            loadCandidates: (...args) => loadCandidates(...args),
            loadDocs: (...args) => loadDocs(...args),
            loadLlmAudit: (...args) => loadLlmAudit(...args),
            loadLlmConfig: (...args) => loadLlmConfig(...args),
            loadRssFeeds: (...args) => loadRssFeeds(...args),
            loadWebuiConfig: (...args) => loadWebuiConfig(...args),
            loadWechatSources: (...args) => loadWechatSources(...args)
        };
        graphContext = {
            graphLayout,
            graphSearchText,
            theme,
            webuiApp,
            ask,
            previewDoc,
            showToast,
            switchTab
        };

        const {
            loadDocs,
            deleteDoc,
            fetchUrl,
            handleFileUpload,
            handleDrop,
            uploadFiles,
            retryFailedImport
        } = KBDocuments.createActions(documentsContext);

        const filteredDocs = computed(() => KBDocuments.filterDocs(docs.value, {
            query: docSearchText.value,
            qualityOnly: qualityOnly.value
        }));

        watch([docSearchText, selectedDocFolder, qualityOnly], () => { docsPage.value = 1; });

        const folderRows = computed(() => KBDocuments.buildFolderRows(docs.value));

        const visibleDocs = computed(() => KBDocuments.visibleDocs(filteredDocs.value, selectedDocFolder.value));
        const docsTotalPages = computed(() => KBDocuments.totalPages(visibleDocs.value, docsPageSize.value));
        const pagedVisibleDocs = computed(() => KBDocuments.pageItems(visibleDocs.value, docsPage.value, docsPageSize.value));

        const {
            repairDocQuality,
            repairAllQuality,
            runMaintenance,
            loadAssociations
        } = KBMaintenance.createActions(maintenanceContext);

        const {
            loadRssFeeds,
            saveRssFeed,
            deleteRssFeed,
            toggleRssFeed,
            syncRss,
            loadWechatSources,
            saveWechatSource,
            discoverWechat
        } = KBSources.createActions(sourcesContext);

        const {
            loadCandidates,
            previewCandidate,
            translateCandidate,
            batchTranslatePreview,
            editCandidate,
            closeCandidateEdit,
            saveCandidateEdit,
            saveCandidateReviewInline,
            loadBatchImportStatus,
            startBatchImportPolling,
            batchImportA,
            batchSkipLowQuality,
            importCandidate,
            skipCandidate,
            restoreCandidate,
            openLastImportedDoc,
            searchLastImported
        } = KBCandidates.createActions(candidateContext);

        const formatBytes = KBUI.formatBytes;
        const formatDate = KBUI.formatDate;
        // Resize observer for graph
        onMounted(async () => {
            await KBUI.mountApp({
                activeTab,
                stats,
                featureEnabled,
                hasGraph: () => KBGraph.hasGraph(),
                resizeGraph: () => KBGraph.resize(),
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
