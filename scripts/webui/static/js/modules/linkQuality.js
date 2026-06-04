(function (global) {
    function number(value) {
        return Number(value || 0);
    }

    function summarizeLinkQuality(summary = {}) {
        const brokenLinks = number(summary.broken_links);
        const orphans = number(summary.orphans);
        const weakDocs = number(summary.weak_docs);
        const missingCrossLinks = number(summary.missing_cross_links);
        const autoLinkCandidates = number(summary.auto_link_candidates);
        const recommendationOnlyLinks = number(summary.recommendation_only_links);
        const lowConfidenceLinks = number(summary.low_confidence_links);
        const duplicateGroups = number(summary.duplicate_groups);
        const duplicateDocs = number(summary.duplicate_docs);
        const hardIssues = brokenLinks + orphans + weakDocs;
        const optimizationQueue = missingCrossLinks + autoLinkCandidates + recommendationOnlyLinks + lowConfidenceLinks;

        return {
            status: hardIssues > 0 ? 'needs_attention' : 'healthy',
            hardIssues,
            optimizationQueue,
            brokenLinks,
            orphans,
            weakDocs,
            missingCrossLinks,
            autoLinkCandidates,
            recommendationOnlyLinks,
            lowConfidenceLinks,
            duplicateGroups,
            duplicateDocs
        };
    }

    global.KBLinkQuality = {
        summarizeLinkQuality
    };
})(window);
