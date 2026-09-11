const Permissions = (() => {
  const status = {
    root: 'pending',
    overlay: 'pending',
    accessibility: 'pending',
    mic: 'pending',
    storage: 'pending',
    battery: 'pending'
  };

  const plugin = () =>
    (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.PermissionPlugin) || null;

  const updateUI = (perm, state) => {
    status[perm] = state;
    const el = document.getElementById(`perm-${perm}`);
    if (el) el.innerHTML = `<span class="status-badge ${state}">${state.toUpperCase()}</span>`;
    const row = document.querySelector(`.perm-item[data-perm="${perm}"]`);
    if (row) row.classList.toggle('granted', state === 'granted');
  };

  // Generic helper: calls the real native check/request methods.
  // On web (no Capacitor native runtime), permission features simply
  // aren't available — we report that honestly instead of pretending.
  const run = async (perm, checkMethod, requestMethod, { request } = {}) => {
    const p = plugin();
    if (!p) {
      updateUI(perm, 'unavailable');
      return false;
    }
    try {
      const method = request ? requestMethod : checkMethod;
      const result = await p[method]();
      updateUI(perm, result.granted ? 'granted' : 'denied');
      return result.granted;
    } catch (e) {
      updateUI(perm, 'denied');
      return false;
    }
  };

  const checkRoot = () => run('root', 'checkRoot', 'requestRoot');
  const requestRoot = () => run('root', 'checkRoot', 'requestRoot', { request: true });

  const checkOverlay = () => run('overlay', 'checkOverlay', 'requestOverlay');
  const requestOverlay = () => run('overlay', 'checkOverlay', 'requestOverlay', { request: true });

  const checkAccessibility = () => run('accessibility', 'checkAccessibility', 'requestAccessibility');
  const requestAccessibility = () => run('accessibility', 'checkAccessibility', 'requestAccessibility', { request: true });

  const checkMic = () => run('mic', 'checkMicrophone', 'requestMicrophone');
  const requestMic = () => run('mic', 'checkMicrophone', 'requestMicrophone', { request: true });

  const checkStorage = () => run('storage', 'checkStorage', 'requestStorage');
  const requestStorage = () => run('storage', 'checkStorage', 'requestStorage', { request: true });

  const checkBattery = () => run('battery', 'checkBattery', 'requestBattery');
  const requestBattery = () => run('battery', 'checkBattery', 'requestBattery', { request: true });

  // Tapping a permission row always REQUESTS (opens the real dialog),
  // not just checks — this is what was missing before.
  const requestByName = (perm) => {
    switch (perm) {
      case 'root': return requestRoot();
      case 'overlay': return requestOverlay();
      case 'accessibility': return requestAccessibility();
      case 'mic': return requestMic();
      case 'storage': return requestStorage();
      case 'battery': return requestBattery();
      default: return Promise.resolve(false);
    }
  };

  const checkAll = async () => {
    await Promise.all([
      checkRoot(),
      checkOverlay(),
      checkAccessibility(),
      checkMic(),
      checkStorage(),
      checkBattery()
    ]);
    return Object.values(status).every((s) => s === 'granted');
  };

  const requestAll = async () => {
    // Sequential on purpose: Android can only show one system dialog
    // at a time, so firing all requests together would just drop most
    // of them.
    for (const perm of ['root', 'overlay', 'accessibility', 'mic', 'storage', 'battery']) {
      await requestByName(perm);
    }
    return Object.values(status).every((s) => s === 'granted');
  };

  // Tap ANY permission row -> fires the real request for that permission
  // (this is the click handler that was missing before; the "PENDING"
  // badge did nothing because nothing was wired to it).
  const bindRowClicks = () => {
    document.querySelectorAll('.perm-item[data-perm]').forEach((row) => {
      row.style.cursor = 'pointer';
      row.addEventListener('click', () => requestByName(row.dataset.perm));
    });
  };

  return {
    checkAll,
    requestAll,
    requestByName,
    checkRoot,
    requestRoot,
    checkOverlay,
    requestOverlay,
    checkAccessibility,
    requestAccessibility,
    checkMic,
    requestMic,
    checkStorage,
    requestStorage,
    checkBattery,
    requestBattery,
    bindRowClicks,
    getStatus: () => ({ ...status }),
    updateUI
  };
})();
