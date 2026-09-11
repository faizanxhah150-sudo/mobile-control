const Overlay = (() => {
  let overlayEl = null;
  let visible = false;
  let dragging = false;
  let dragOffset = { x: 0, y: 0 };
  let currentPos = { x: 20, y: 200 };
  let currentSize = 80;
  let resizing = false;
  let resizeStart = { x: 0, y: 0, size: 80 };

  const createOverlay = () => {
    if (overlayEl) return;
    overlayEl = document.createElement('div');
    overlayEl.className = 'agent-overlay';
    overlayEl.innerHTML = `
      <div class="overlay-avatar">
        <img src="assets/avatar-default.png" alt="Agent" />
      </div>
      <div class="overlay-resize"></div>
    `;
    overlayEl.style.cssText = `
      position: fixed;
      left: ${currentPos.x}px;
      top: ${currentPos.y}px;
      width: ${currentSize}px;
      height: ${currentSize}px;
      z-index: 9999;
      cursor: move;
      user-select: none;
      touch-action: none;
    `;
    document.body.appendChild(overlayEl);

    const avatar = overlayEl.querySelector('.overlay-avatar');
    const resize = overlayEl.querySelector('.overlay-resize');

    // Drag handlers
    const onStart = (e) => {
      if (e.target === resize) return;
      dragging = true;
      const point = e.touches ? e.touches[0] : e;
      const rect = overlayEl.getBoundingClientRect();
      dragOffset.x = point.clientX - rect.left;
      dragOffset.y = point.clientY - rect.top;
      e.preventDefault();
    };

    const onMove = (e) => {
      if (!dragging) return;
      const point = e.touches ? e.touches[0] : e;
      const x = point.clientX - dragOffset.x;
      const y = point.clientY - dragOffset.y;
      overlayEl.style.left = `${x}px`;
      overlayEl.style.top = `${y}px`;
      currentPos = { x, y };
      e.preventDefault();
    };

    const onEnd = () => {
      dragging = false;
    };

    overlayEl.addEventListener('mousedown', onStart);
    overlayEl.addEventListener('touchstart', onStart, { passive: false });
    document.addEventListener('mousemove', onMove);
    document.addEventListener('touchmove', onMove, { passive: false });
    document.addEventListener('mouseup', onEnd);
    document.addEventListener('touchend', onEnd);

    // Resize handlers
    const onResizeStart = (e) => {
      resizing = true;
      const point = e.touches ? e.touches[0] : e;
      resizeStart = { x: point.clientX, y: point.clientY, size: currentSize };
      e.preventDefault();
      e.stopPropagation();
    };

    const onResizeMove = (e) => {
      if (!resizing) return;
      const point = e.touches ? e.touches[0] : e;
      const dx = point.clientX - resizeStart.x;
      const dy = point.clientY - resizeStart.y;
      const delta = Math.max(dx, dy);
      const newSize = Math.max(50, Math.min(200, resizeStart.size + delta));
      currentSize = newSize;
      overlayEl.style.width = `${newSize}px`;
      overlayEl.style.height = `${newSize}px`;
      e.preventDefault();
    };

    const onResizeEnd = () => {
      resizing = false;
    };

    resize.addEventListener('mousedown', onResizeStart);
    resize.addEventListener('touchstart', onResizeStart, { passive: false });
    document.addEventListener('mousemove', onResizeMove);
    document.addEventListener('touchmove', onResizeMove, { passive: false });
    document.addEventListener('mouseup', onResizeEnd);
    document.addEventListener('touchend', onResizeEnd);
  };

  const show = () => {
    createOverlay();
    if (overlayEl) {
      overlayEl.style.display = 'block';
      visible = true;
    }
  };

  const hide = () => {
    if (overlayEl) {
      overlayEl.style.display = 'none';
      visible = false;
    }
  };

  const destroy = () => {
    if (overlayEl) {
      overlayEl.remove();
      overlayEl = null;
      visible = false;
    }
  };

  const updateAvatar = (src) => {
    if (!overlayEl) return;
    const img = overlayEl.querySelector('.overlay-avatar img');
    if (img) img.src = src;
  };

  const isVisible = () => visible;

  return { show, hide, destroy, updateAvatar, isVisible, getPosition: () => ({ ...currentPos }), getSize: () => currentSize };
})();
