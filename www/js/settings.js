const Settings = (() => {
  const DEFAULTS = {
    apiEndpoint: 'http://127.0.0.1:5000',
    autoStart: false,
    enableOverlay: true,
    backgroundListen: false,
    language: 'en-US',
    speed: 5
  };

  let current = { ...DEFAULTS };

  const load = async () => {
    const saved = await Storage.get('settings');
    if (saved) {
      current = { ...DEFAULTS, ...saved };
    }
    applyToUI();
  };

  const applyToUI = () => {
    const apiEl = document.getElementById('apiEndpoint');
    const autoEl = document.getElementById('autoStartToggle');
    const overlayEl = document.getElementById('overlayToggle');
    const bgListenEl = document.getElementById('backgroundListenToggle');
    const langEl = document.getElementById('languageSelect');
    const speedEl = document.getElementById('speedRange');
    if (apiEl) apiEl.value = current.apiEndpoint;
    if (autoEl) autoEl.checked = current.autoStart;
    if (overlayEl) overlayEl.checked = current.enableOverlay;
    if (bgListenEl) bgListenEl.checked = current.backgroundListen;
    if (langEl) langEl.value = current.language;
    if (speedEl) speedEl.value = current.speed;
  };

  const save = async () => {
    const apiEl = document.getElementById('apiEndpoint');
    const autoEl = document.getElementById('autoStartToggle');
    const overlayEl = document.getElementById('overlayToggle');
    const bgListenEl = document.getElementById('backgroundListenToggle');
    const langEl = document.getElementById('languageSelect');
    const speedEl = document.getElementById('speedRange');
    current = {
      apiEndpoint: apiEl ? apiEl.value : DEFAULTS.apiEndpoint,
      autoStart: autoEl ? autoEl.checked : DEFAULTS.autoStart,
      enableOverlay: overlayEl ? overlayEl.checked : DEFAULTS.enableOverlay,
      backgroundListen: bgListenEl ? bgListenEl.checked : DEFAULTS.backgroundListen,
      language: langEl ? langEl.value : DEFAULTS.language,
      speed: speedEl ? parseInt(speedEl.value) : DEFAULTS.speed
    };
    await Storage.set('settings', current);
    Bridge.setEndpoint(current.apiEndpoint);
    return current;
  };

  const reset = async () => {
    current = { ...DEFAULTS };
    await Storage.set('settings', current);
    applyToUI();
  };

  const get = () => ({ ...current });

  return { load, save, reset, get };
})();
