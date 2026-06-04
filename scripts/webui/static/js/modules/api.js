(function (global) {
    async function requestJson(url, options = {}) {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        return data;
    }

    async function getJson(url) {
        return requestJson(url);
    }

    async function sendJson(url, payload = {}, options = {}) {
        const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
        return requestJson(url, {
            ...options,
            headers,
            body: JSON.stringify(payload)
        });
    }

    global.KBApi = {
        getJson,
        requestJson,
        sendJson
    };
})(window);
