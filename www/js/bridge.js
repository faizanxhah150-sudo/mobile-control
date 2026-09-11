const Bridge = (() => {
  let endpoint = 'http://127.0.0.1:5000';
  let stats = { requests: 0, errors: 0, latency: 0 };
  let connected = false;
  let ws = null;
  let wsRetryTimer = null;

  const log = (msg, type = 'info') => {
    const logEl = document.getElementById('bridgeLog');
    if (!logEl) return;
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    const time = new Date().toLocaleTimeString();
    entry.textContent = `[${time}] ${msg}`;
    logEl.appendChild(entry);
    logEl.scrollTop = logEl.scrollHeight;
    // Keep max 50 entries
    while (logEl.children.length > 50) {
      logEl.removeChild(logEl.firstChild);
    }
  };

  const updateStats = () => {
    const reqEl = document.getElementById('statRequests');
    const errEl = document.getElementById('statErrors');
    const latEl = document.getElementById('statLatency');
    if (reqEl) reqEl.textContent = stats.requests;
    if (errEl) errEl.textContent = stats.errors;
    if (latEl) latEl.textContent = `${stats.latency}ms`;
  };

  const setEndpoint = (url) => {
    endpoint = url.replace(/\/$/, '');
  };

  const request = async (method, path, body = null) => {
    const url = `${endpoint}${path}`;
    const start = performance.now();
    stats.requests++;
    try {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const res = await fetch(url, opts);
      const elapsed = Math.round(performance.now() - start);
      stats.latency = elapsed;
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      log(`${method} ${path} → ${res.status} (${elapsed}ms)`, 'success');
      updateStats();
      return data;
    } catch (err) {
      stats.errors++;
      log(`${method} ${path} → ERROR: ${err.message}`, 'error');
      updateStats();
      throw err;
    }
  };

  const checkStatus = async () => {
    try {
      const data = await request('GET', '/status');
      connected = true;
      return data;
    } catch (e) {
      connected = false;
      return null;
    }
  };

  // Sends a natural-language prompt/command to the local backend's
  // /process endpoint, per the Jarvis local REST bridge spec.
  const sendCommand = async (cmd, params = {}) => {
    return request('POST', '/process', { prompt: cmd, ...params });
  };

  const connectWS = () => {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const wsUrl = endpoint.replace('http', 'ws');
    try {
      ws = new WebSocket(`${wsUrl}/ws`);
      ws.onopen = () => {
        log('WebSocket connected', 'success');
        connected = true;
      };
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          log(`WS: ${data.type || 'message'}`, 'info');
          if (window.App && window.App.onWSMessage) {
            window.App.onWSMessage(data);
          }
        } catch (err) {
          log(`WS raw: ${e.data}`, 'info');
        }
      };
      ws.onerror = (e) => {
        log('WebSocket error', 'error');
      };
      ws.onclose = () => {
        log('WebSocket disconnected', 'warn');
        connected = false;
        // Retry after 5s
        wsRetryTimer = setTimeout(connectWS, 5000);
      };
    } catch (err) {
      log(`WS connect failed: ${err.message}`, 'error');
    }
  };

  const disconnectWS = () => {
    if (wsRetryTimer) clearTimeout(wsRetryTimer);
    if (ws) {
      ws.close();
      ws = null;
    }
    connected = false;
  };

  const isConnected = () => connected;

  return {
    setEndpoint,
    request,
    checkStatus,
    sendCommand,
    connectWS,
    disconnectWS,
    isConnected,
    getStats: () => ({ ...stats }),
    log
  };
})();
