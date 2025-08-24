// client.js
(() => {
  const canvas = document.getElementById('game');
  const ctx = canvas.getContext('2d');
  const sl = document.getElementById('sl');
  const sr = document.getElementById('sr');
  const toast = document.getElementById('toast');

  const adminModal = document.getElementById('admin');
  const adminAuthBlock = document.getElementById('adminAuthBlock');
  const adminControls = document.getElementById('adminControls');
  const adminCodeInput = document.getElementById('adminCode');
  const adminAuthBtn = document.getElementById('adminAuthBtn');
  const closeAdmin = document.getElementById('closeAdmin');
  const broadcastMsg = document.getElementById('broadcastMsg');
  const broadcastBtn = document.getElementById('broadcastBtn');
  const pauseToggle = document.getElementById('pauseToggle');
  const resetScores = document.getElementById('resetScores');
  const chips = document.querySelectorAll('.chips button');

  let isAdmin = false;
  let side = 'spectator';
  let state = {
    left_y: 245, right_y: 245, ball_x: 443, ball_y: 293,
    score_l: 0, score_r: 0, paused: false, event: null, w: 900, h: 600
  };

  // WebSocket
  const host = window.location.hostname || 'localhost';
  const port = window.PONG_WS_PORT || 8765;
  const ws = new WebSocket(`ws://${host}:${port}`);

  ws.addEventListener('open', () => {
    showToast('Connected to server ✅');
  });

  ws.addEventListener('message', (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.type === 'role') {
        side = data.side;
        showToast(`You are: ${side.toUpperCase()}`);
      } else if (data.type === 'state') {
        state = data;
        sl.textContent = state.score_l;
        sr.textContent = state.score_r;
      } else if (data.type === 'broadcast') {
        showToast(data.message || '');
      } else if (data.type === 'admin_result') {
        if (data.ok) {
          isAdmin = true;
          adminAuthBlock.classList.add('hidden');
          adminControls.classList.remove('hidden');
          showToast('Admin unlocked 🔓');
        } else {
          showToast('Wrong admin code ❌');
        }
      } else if (data.type === 'event') {
        state.event = data.event;
        showToast(state.event ? `Event: ${state.event}` : 'Events cleared');
      }
    } catch {}
  });

  ws.addEventListener('close', () => {
    showToast('Disconnected from server ❌');
  });

  // Input handling
  const keys = new Set();
  window.addEventListener('keydown', (e) => {
    if (e.code === 'Tab') {
      e.preventDefault();
      toggleAdmin(true);
      return;
    }
    keys.add(e.code);

    if (e.code === 'KeyP') {
      ws.send(JSON.stringify({ type: 'pause' }));
    }

    sendInput();
  });

  window.addEventListener('keyup', (e) => {
    keys.delete(e.code);
    sendInput();
  });

  function sendInput() {
    let up = false, down = false;
    if (side === 'left' || side === 'right' || true) { // allow spectators to move nothing
      if (state.event === 'invert') {
        up = keys.has('ArrowDown') || keys.has('KeyS');
        down = keys.has('ArrowUp') || keys.has('KeyW');
        if (side === 'left') { up = keys.has('KeyS'); down = keys.has('KeyW'); }
        if (side === 'right') { up = keys.has('ArrowDown'); down = keys.has('ArrowUp'); }
      } else {
        up = keys.has('ArrowUp') || keys.has('KeyW');
        down = keys.has('ArrowDown') || keys.has('KeyS');
        if (side === 'left') { up = keys.has('KeyW'); down = keys.has('KeyS'); }
        if (side === 'right') { up = keys.has('ArrowUp'); down = keys.has('ArrowDown'); }
      }
    }
    ws.send(JSON.stringify({ type: 'input', up, down }));
  }

  // Admin UI
  function toggleAdmin(show) {
    adminModal.classList.toggle('hidden', show === false);
  }
  closeAdmin.addEventListener('click', () => toggleAdmin(false));

  adminAuthBtn.addEventListener('click', () => {
    const code = adminCodeInput.value.trim();
    ws.send(JSON.stringify({ type: 'admin_auth', code }));
  });

  broadcastBtn.addEventListener('click', () => {
    const message = broadcastMsg.value.trim();
    if (!message) return;
    if (!isAdmin) return showToast('Unlock admin first.');
    ws.send(JSON.stringify({ type: 'admin', action: 'broadcast', message }));
    broadcastMsg.value = '';
  });

  chips.forEach(btn => {
    btn.addEventListener('click', () => {
      const ev = btn.getAttribute('data-ev');
      if (!isAdmin) return showToast('Unlock admin first.');
      ws.send(JSON.stringify({ type: 'admin', action: 'event', event: ev }));
    });
  });

  pauseToggle.addEventListener('click', () => {
    if (!isAdmin) return showToast('Unlock admin first.');
    ws.send(JSON.stringify({ type: 'admin', action: 'pause_toggle' }));
  });

  resetScores.addEventListener('click', () => {
    if (!isAdmin) return showToast('Unlock admin first.');
    ws.send(JSON.stringify({ type: 'admin', action: 'reset_scores' }));
  });

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2000);
  }

  // Render
  function draw() {
    const w = canvas.width, h = canvas.height;
    // Disco event background pulse
    if (state.event === 'disco') {
      const t = performance.now() * 0.004;
      const a = Math.abs(Math.sin(t));
      ctx.fillStyle = `hsl(${(t*60)%360},70%,${30 + a*20}%)`;
      ctx.fillRect(0,0,w,h);
    } else {
      ctx.clearRect(0,0,w,h);
    }

    // center line
    ctx.globalAlpha = 0.7;
    ctx.fillStyle = '#72809b';
    for (let y=0;y<h;y+=32){
      ctx.fillRect(w/2 - 2, y, 4, 18);
    }
    ctx.globalAlpha = 1;

    // paddles & ball
    ctx.fillStyle = '#e9eef8';
    ctx.fillRect(30, state.left_y, 14, 110);
    ctx.fillRect(w - 30 - 14, state.right_y, 14, 110);
    ctx.fillRect(state.ball_x, state.ball_y, 14, 14);

    // paused overlay
    if (state.paused) {
      ctx.fillStyle = 'rgba(0,0,0,0.45)';
      ctx.fillRect(0,0,w,h);
      ctx.fillStyle = '#a7d3ff';
      ctx.font = 'bold 48px Inter, Arial';
      ctx.textAlign = 'center';
      ctx.fillText('PAUSED', w/2, h/2);
    }

    requestAnimationFrame(draw);
  }
  draw();
})();
