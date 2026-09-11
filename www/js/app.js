const App = (() => {
  let agentRunning = false;
  let uptimeStart = null;
  let uptimeTimer = null;
  let commandCount = 0;
  let avatarSrc = 'assets/avatar-default.png';

  const $ = (id) => document.getElementById(id);

  const showToast = (msg, type = 'info') => {
    const container = $('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 3000);
  };

  const updateConnectionStatus = (state) => {
    const dot = $('connectionDot');
    const text = $('connectionText');
    const badge = $('agentBadge');
    const ring = $('agentRing');
    const core = $('agentCore');
    const pulse = document.querySelector('.core-pulse');

    if (state === 'connected') {
      if (dot) dot.className = 'status-dot connected';
      if (text) text.textContent = 'Connected';
      if (badge) { badge.textContent = 'ONLINE'; badge.className = 'card-badge online'; }
      if (ring) ring.classList.add('active');
      if (core) core.classList.add('active');
      if (pulse) pulse.classList.add('active');
    } else if (state === 'connecting') {
      if (dot) dot.className = 'status-dot connecting';
      if (text) text.textContent = 'Connecting...';
      if (badge) { badge.textContent = 'CONNECTING'; badge.className = 'card-badge connecting'; }
      if (ring) ring.classList.remove('active');
      if (core) core.classList.remove('active');
      if (pulse) pulse.classList.remove('active');
    } else {
      if (dot) dot.className = 'status-dot';
      if (text) text.textContent = 'Disconnected';
      if (badge) { badge.textContent = 'OFFLINE'; badge.className = 'card-badge'; }
      if (ring) ring.classList.remove('active');
      if (core) core.classList.remove('active');
      if (pulse) pulse.classList.remove('active');
    }
  };

  const formatUptime = (ms) => {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600).toString().padStart(2, '0');
    const m = Math.floor((s % 3600) / 60).toString().padStart(2, '0');
    const sec = (s % 60).toString().padStart(2, '0');
    return `${h}:${m}:${sec}`;
  };

  const startUptime = () => {
    uptimeStart = Date.now();
    if (uptimeTimer) clearInterval(uptimeTimer);
    uptimeTimer = setInterval(() => {
      const el = $('uptimeValue');
      if (el && uptimeStart) el.textContent = formatUptime(Date.now() - uptimeStart);
    }, 1000);
  };

  const stopUptime = () => {
    if (uptimeTimer) clearInterval(uptimeTimer);
    uptimeTimer = null;
    const el = $('uptimeValue');
    if (el) el.textContent = '00:00:00';
  };

  const updateBattery = async () => {
    try {
      if (navigator.getBattery) {
        const battery = await navigator.getBattery();
        const level = Math.round(battery.level * 100);
        const charging = battery.charging;
        const icon = $('batteryIcon');
        const text = $('batteryText');
        if (icon) icon.textContent = charging ? '⚡' : '🔋';
        if (text) text.textContent = `${level}%`;
      }
    } catch (e) {}
  };

  const startAgent = async () => {
    if (agentRunning) return;
    agentRunning = true;
    commandCount = 0;

    $('startBtn').classList.add('disabled');
    $('startBtn').disabled = true;
    $('stopBtn').classList.remove('disabled');
    $('stopBtn').disabled = false;

    updateConnectionStatus('connecting');
    Bridge.log('Starting agent service...', 'info');

    try {
      const status = await Bridge.checkStatus();
      if (status) {
        updateConnectionStatus('connected');
        Bridge.log('Agent connected successfully', 'success');
        showToast('Agent started successfully', 'success');
        startUptime();
        await maybeShowOverlay();
      } else {
        throw new Error('Termux server not responding');
      }
    } catch (err) {
      updateConnectionStatus('disconnected');
      Bridge.log(`Failed: ${err.message}`, 'error');
      showToast('Failed to connect to Termux', 'error');
      agentRunning = false;
      $('startBtn').classList.remove('disabled');
      $('startBtn').disabled = false;
      $('stopBtn').classList.add('disabled');
      $('stopBtn').disabled = true;
    }
  };

  const stopAgent = async () => {
    if (!agentRunning) return;
    agentRunning = false;

    $('startBtn').classList.remove('disabled');
    $('startBtn').disabled = false;
    $('stopBtn').classList.add('disabled');
    $('stopBtn').disabled = true;

    updateConnectionStatus('disconnected');
    await hideOverlay();
    stopUptime();
    Bridge.log('Agent stopped', 'warn');
    showToast('Agent stopped', 'warn');
  };

  const loadAvatar = async () => {
    const saved = await Storage.get('avatar');
    if (saved) {
      avatarSrc = saved;
      const img = $('avatarImage');
      if (img) img.src = saved;
      Overlay.updateAvatar(saved);
    }
  };

  const saveAvatar = async () => {
    await Storage.set('avatar', avatarSrc);
    Overlay.updateAvatar(avatarSrc);
  };

  const deleteAvatar = async () => {
    avatarSrc = 'assets/avatar-default.png';
    const img = $('avatarImage');
    if (img) img.src = avatarSrc;
    await Storage.remove('avatar');
    Overlay.updateAvatar(avatarSrc);
    showToast('Avatar reset to default', 'info');
  };

  const handleAvatarUpload = (file) => {
    if (!file) return;
    const validTypes = ['image/png', 'image/gif', 'image/jpeg', 'image/webp'];
    if (!validTypes.includes(file.type)) {
      showToast('Only PNG, JPG, WEBP or GIF allowed', 'error');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      showToast('File too large (max 5MB)', 'error');
      return;
    }
    const reader = new FileReader();
    reader.onload = async (e) => {
      avatarSrc = e.target.result;
      const img = $('avatarImage');
      if (img) img.src = avatarSrc;
      await saveAvatar();
      if (agentRunning) await syncNativeOverlay(); // live-update if already floating
      showToast('Avatar updated', 'success');
    };
    reader.readAsDataURL(file);
  };

  // --- Real system-wide overlay (native, survives app close) ---------

  const isNative = () => !!(window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.OverlayPlugin);
  const hasRealAvatar = () => !!avatarSrc && !avatarSrc.endsWith('avatar-default.png');

  const getAvatarSizeDp = async () => {
    const saved = await Storage.get('avatarSize');
    return saved ? parseInt(saved, 10) : 80;
  };

  const syncNativeOverlay = async () => {
    if (!isNative() || !hasRealAvatar()) return;
    try {
      const size = await getAvatarSizeDp();
      await window.Capacitor.Plugins.OverlayPlugin.start({ avatar: avatarSrc, size });
    } catch (e) {
      Bridge.log(`Overlay failed: ${e.message}`, 'error');
    }
  };

  // Shows the floating avatar ONLY if the user actually picked one and
  // the overlay setting is on. No avatar selected -> nothing appears on
  // screen at all when the agent starts; just the background service +
  // its silent notification.
  const maybeShowOverlay = async () => {
    if (!Settings.get().enableOverlay || !hasRealAvatar()) return;
    if (isNative()) {
      await syncNativeOverlay();
    } else if (Overlay.isVisible() === false) {
      Overlay.show(); // web-preview fallback (in-page div, not a real system overlay)
    }
  };

  const hideOverlay = async () => {
    if (isNative()) {
      try {
        await window.Capacitor.Plugins.OverlayPlugin.stop();
      } catch (e) { /* already stopped */ }
    } else {
      Overlay.hide();
    }
  };

  const setupEventListeners = () => {
    $('startBtn').addEventListener('click', startAgent);
    $('stopBtn').addEventListener('click', stopAgent);

    $('uploadAvatarBtn').addEventListener('click', () => {
      $('avatarFileInput').click();
    });

    $('avatarFileInput').addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) handleAvatarUpload(file);
      e.target.value = '';
    });

    $('deleteAvatarBtn').addEventListener('click', () => {
      if (confirm('Reset avatar to default?')) deleteAvatar();
    });

    Permissions.bindRowClicks();
    $('checkAllBtn').addEventListener('click', async () => {
      showToast('Checking permissions...', 'info');
      await Permissions.requestAll();
      const allGranted = Object.values(Permissions.getStatus()).every(s => s === 'granted');
      if (allGranted) {
        showToast('All permissions granted', 'success');
      } else {
        showToast('Some permissions denied', 'warn');
      }
    });

    $('settingsBtn').addEventListener('click', () => {
      $('settingsModal').classList.add('active');
    });

    $('closeSettingsBtn').addEventListener('click', () => {
      $('settingsModal').classList.remove('active');
    });

    document.querySelector('.modal-backdrop').addEventListener('click', () => {
      $('settingsModal').classList.remove('active');
    });

    $('saveSettingsBtn').addEventListener('click', async () => {
      await Settings.save();
      await syncBackgroundListener();
      showToast('Settings saved', 'success');
      $('settingsModal').classList.remove('active');
    });

    $('resetSettingsBtn').addEventListener('click', async () => {
      if (confirm('Reset all data? This cannot be undone.')) {
        await Storage.clear();
        await Settings.reset();
        showToast('All data reset', 'warn');
        $('settingsModal').classList.remove('active');
      }
    });

    $('agentNameInput').addEventListener('change', async (e) => {
      await Storage.set('agentName', e.target.value);
      showToast('Agent name saved', 'success');
      await syncBackgroundListener();
    });

    $('modeSelect').addEventListener('change', async (e) => {
      await Storage.set('mode', e.target.value);
      showToast(`Mode: ${e.target.value}`, 'info');
    });

    $('avatarSizeRange').addEventListener('input', async (e) => {
      await Storage.set('avatarSize', e.target.value);
      if (agentRunning) await syncNativeOverlay();
    });

    // Talk to Jarvis: text send + mic (Web Speech API where available).
    const sendFromInput = async () => {
      const input = $('chatInput');
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      appendChatBubble('user', text);
      const pendingEl = appendChatBubble('agent', '…', 'pending');
      const data = await sendPrompt(text);
      const reply = data && (data.reply || (data.action_result && data.action_result.message)) || "(no reply)";
      pendingEl.textContent = reply;
      pendingEl.classList.remove('pending');
    };

    $('chatSendBtn').addEventListener('click', sendFromInput);
    $('chatInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sendFromInput();
    });

    setupMic();
  };

  // Renders a chat bubble and returns the element (so callers can update
  // it later, e.g. swapping a "…" placeholder for the real reply).
  const appendChatBubble = (role, text, extraClass = '') => {
    const log = $('chatLog');
    if (!log) return document.createElement('div');
    const el = document.createElement('div');
    el.className = `chat-bubble ${role}${extraClass ? ' ' + extraClass : ''}`;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  };

  // Voice input via the browser's Web Speech API. This works in Chrome-based
  // WebViews with Google app / internet available, but isn't guaranteed on
  // every Android build — the text box above always works regardless, so
  // voice is a progressive enhancement, not a requirement.
  let recognition = null;
  let isListening = false;

  // Starts/stops the native background wake-word listening service to
  // match the "Always Listen (Background)" setting. Uses whatever name
  // the user set in the Agent Name field as the wake word.
  const syncBackgroundListener = async () => {
    const isNative = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
    if (!isNative || !window.Capacitor.Plugins.BackgroundListenerPlugin) return;
    const settings = Settings.get();
    const agentName = (await Storage.get('agentName')) || 'Jarvis';
    try {
      if (settings.backgroundListen) {
        await window.Capacitor.Plugins.BackgroundListenerPlugin.start({
          agentName,
          endpoint: settings.apiEndpoint
        });
      } else {
        await window.Capacitor.Plugins.BackgroundListenerPlugin.stop();
      }
    } catch (e) {
      Bridge.log(`Background listener error: ${e.message}`, 'error');
    }
  };

  const setupMic = () => {
    const micBtn = $('micBtn');
    if (!micBtn) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      micBtn.title = 'Voice input not supported on this device — use the text box';
      micBtn.style.opacity = '0.4';
      micBtn.addEventListener('click', () => {
        showToast('Voice input not supported here — type your command instead', 'warn');
      });
      return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      isListening = true;
      micBtn.classList.add('listening');
    };
    recognition.onend = () => {
      isListening = false;
      micBtn.classList.remove('listening');
    };
    recognition.onerror = (e) => {
      isListening = false;
      micBtn.classList.remove('listening');
      showToast('Mic error: ' + e.error, 'error');
    };
    recognition.onresult = (e) => {
      const text = e.results[0][0].transcript;
      $('chatInput').value = text;
      $('chatSendBtn').click();
    };

    micBtn.addEventListener('click', () => {
      if (isListening) {
        recognition.stop();
      } else {
        try { recognition.start(); } catch (e) { /* already started */ }
      }
    });
  };

  const loadSettings = async () => {
    const agentName = await Storage.get('agentName');
    if (agentName) {
      const el = $('agentNameInput');
      if (el) el.value = agentName;
    }
    const mode = await Storage.get('mode');
    if (mode) {
      const el = $('modeSelect');
      if (el) el.value = mode;
    }
    const avatarSize = await Storage.get('avatarSize');
    if (avatarSize) {
      const el = $('avatarSizeRange');
      if (el) el.value = avatarSize;
    }
    await Settings.load();
  };

  // Poll http://127.0.0.1:5000/status every 5s to keep the connection
  // indicator accurate even if the WebSocket drops or the agent hasn't
  // been explicitly started yet.
  let statusPollTimer = null;
  const pollStatus = async () => {
    const status = await Bridge.checkStatus();
    if (status) {
      if (!agentRunning) {
        // Backend is reachable even though the UI hadn't marked it running.
        updateConnectionStatus('connected');
      }
    } else if (!agentRunning) {
      updateConnectionStatus('disconnected');
    }
  };
  const startStatusPolling = () => {
    if (statusPollTimer) return;
    pollStatus();
    statusPollTimer = setInterval(pollStatus, 5000);
  };

  // Send a user command/prompt to the local backend at /process.
  // Includes the agent's saved name + mode + recent chat history so the
  // backend can build a persona-aware, multi-turn conversation instead
  // of treating every message as a stateless one-off.
  const MAX_HISTORY = 20;

  const sendPrompt = async (text) => {
    if (!text || !text.trim()) return null;
    try {
      const agentName = (await Storage.get('agentName')) || 'Jarvis';
      const mode = (await Storage.get('mode')) || 'responsive';
      const history = (await Storage.get('chatHistory')) || [];

      Bridge.log(`→ /process (${agentName}): ${text}`, 'info');
      const data = await Bridge.request('POST', '/process', {
        prompt: text,
        agent_name: agentName,
        mode,
        history
      });

      commandCount++;
      const el = $('commandCount');
      if (el) el.textContent = commandCount;

      if (data && data.reply) {
        showToast(data.reply, 'success');
        const updated = [
          ...history,
          { role: 'user', content: text },
          { role: 'assistant', content: data.reply }
        ].slice(-MAX_HISTORY);
        await Storage.set('chatHistory', updated);
      }
      return data;
    } catch (err) {
      showToast('Command failed: ' + err.message, 'error');
      return null;
    }
  };

  const init = async () => {
    setupEventListeners();
    await loadSettings();
    await loadAvatar();
    await updateBattery();
    setInterval(updateBattery, 30000);
    startStatusPolling();

    const history = (await Storage.get('chatHistory')) || [];
    history.forEach((m) => appendChatBubble(m.role === 'user' ? 'user' : 'agent', m.content));

    // Auto-start if enabled
    const settings = Settings.get();
    if (settings.autoStart) {
      setTimeout(startAgent, 1500);
    }

    // Initial permission check
    setTimeout(() => Permissions.checkAll(), 1000);

    Bridge.log('Dashboard ready', 'success');
    showToast('AI Voice Agent ready', 'success');
    await syncBackgroundListener();
  };

  const onWSMessage = (data) => {
    if (data.command) {
      commandCount++;
      const el = $('commandCount');
      if (el) el.textContent = commandCount;
    }
  };

  return { init, onWSMessage, sendPrompt };
})();

window.App = App;

document.addEventListener('DOMContentLoaded', () => {
  App.init();
});

// Capacitor native bridge
if (window.Capacitor) {
  window.Capacitor.Plugins = window.Capacitor.Plugins || {};
}
