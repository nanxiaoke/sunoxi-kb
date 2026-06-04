(function (global) {
    function scrollToBottom(ctx) {
        ctx.nextTick(() => {
            const container = document.getElementById('chat-container');
            if (container) container.scrollTop = container.scrollHeight;
        });
    }

    function ask(ctx, text) {
        ctx.chatInput.value = text;
        return submitChat(ctx);
    }

    async function submitChat(ctx) {
        const q = ctx.chatInput.value.trim();
        if (!q) return;

        ctx.chatHistory.value.push({
            role: 'user',
            content: q,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        });
        ctx.chatInput.value = '';
        ctx.isWaiting.value = true;
        scrollToBottom(ctx);

        try {
            const data = await KBApi.getJson(
                `/api/search?q=${encodeURIComponent(q)}&qa=true&answer_mode=${encodeURIComponent(ctx.chatAnswerMode.value)}`
            );
            ctx.chatHistory.value.push({
                role: 'ai',
                content: data.answer || '未能生成答案。',
                sources: data.documents || [],
                citations: data.citations || [],
                latency: data.latency,
                cache_hit: data.cache_hit,
                context_preview: data.context_preview,
                diagnostics: data.diagnostics || {},
                answer_mode: data.answer_mode,
                llm: data.llm,
                time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            });
        } catch (e) {
            ctx.showToast('问答请求失败', 'error');
            ctx.chatHistory.value.push({ role: 'ai', content: '系统内部错误，无法连接到模型。' });
        } finally {
            ctx.isWaiting.value = false;
            scrollToBottom(ctx);
        }
    }

    global.KBChat = {
        ask,
        scrollToBottom,
        submitChat
    };
})(window);
