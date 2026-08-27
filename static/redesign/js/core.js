
    const state = {
      activeTab: 'overview',
      userId: 'guest',
      workspaceId: 'default',
      isStreaming: true,
      token: localStorage.getItem('myagent_token') || '',
      currentUser: null,
      authMode: 'login',
      memoryCited: 0,
      memoryCorrected: 0,
    };

    /* ----------- 深色/浅色主题 ----------- */
    function currentTheme() {
      const explicit = document.documentElement.getAttribute('data-theme');
      return explicit === 'light' ? 'light' : 'dark';
    }

    function applyThemeIcon() {
      const icon = el('themeToggleIcon');
      if (!icon) return;
      icon.setAttribute('data-lucide', currentTheme() === 'dark' ? 'sun' : 'moon');
      refreshIcons();
    }

    function initTheme() {
      applyThemeIcon();
    }

    function toggleTheme() {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('remedy_theme', next); } catch (e) { /* ignore */ }
      applyThemeIcon();
    }

    /* ----------- 主界面数字流背景 ----------- */
    function initMainBgRain() {
      const canvas = document.getElementById('mainBgRain');
      if (!canvas || !canvas.getContext) return;
      const ctx = canvas.getContext('2d');
      const container = canvas.parentElement;
      const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const glyphs = '01#*<>%/'.split('');
      const fontSize = 15;
      const rowH = fontSize * 1.6;
      const trailLen = 7;
      let cols = 0;
      let drops = [];
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      let running = false;
      let rafId = null;
      let lastStep = 0;

      function resize() {
        const w = container.clientWidth;
        const h = container.clientHeight;
        if (!w || !h) return;
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        cols = Math.max(1, Math.floor(w / fontSize));
        drops = new Array(cols).fill(0).map(() => -Math.floor(Math.random() * 30));
        ctx.clearRect(0, 0, w, h);
      }

      function drawFrame() {
        const w = container.clientWidth;
        const h = container.clientHeight;
        ctx.clearRect(0, 0, w, h);
        ctx.font = fontSize + 'px "JetBrains Mono", Consolas, monospace';
        for (let i = 0; i < cols; i++) {
          const headY = drops[i];
          for (let t = 0; t < trailLen; t++) {
            const y = (headY - t) * rowH;
            if (y < 0 || y > h) continue;
            const alpha = 0.42 * (1 - t / trailLen);
            ctx.fillStyle = t === 0 ? `rgba(240, 214, 235, ${alpha + 0.15})` : `rgba(196, 130, 200, ${alpha})`;
            ctx.fillText(glyphs[(Math.random() * glyphs.length) | 0], i * fontSize, y);
          }
        }
      }

      function step(ts) {
        if (!running) return;
        if (ts - lastStep > 80) {
          lastStep = ts;
          drawFrame();
          for (let i = 0; i < cols; i++) {
            drops[i]++;
            if ((drops[i] - trailLen) * rowH > container.clientHeight && Math.random() > 0.98) {
              drops[i] = -Math.floor(Math.random() * 20);
            }
          }
        }
        rafId = requestAnimationFrame(step);
      }

      function start() {
        if (running) return;
        resize();
        if (reduceMotion) { drawFrame(); return; }
        running = true;
        lastStep = 0;
        rafId = requestAnimationFrame(step);
      }

      function stop() {
        running = false;
        if (rafId) cancelAnimationFrame(rafId);
        rafId = null;
      }

      function syncWithTheme() {
        if (currentTheme() === 'dark' && !document.hidden) start(); else stop();
      }

      window.addEventListener('resize', () => { if (currentTheme() === 'dark') resize(); });
      document.addEventListener('visibilitychange', syncWithTheme);
      new MutationObserver(syncWithTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

      syncWithTheme();
    }
    document.addEventListener('DOMContentLoaded', initMainBgRain);

    function el(id) { return document.getElementById(id); }
    function showEl(id) { const node = el(id); if (node) node.classList.remove('hidden'); }
    function hideEl(id) { const node = el(id); if (node) node.classList.add('hidden'); }

    function authHeaders(extra) {
      const headers = Object.assign({}, extra || {});
      if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
      return headers;
    }

    /* --------------------------------------------------------------
     * Sprint 0.1 — 全局 fetch 拦截器
     * -------------------------------------------------------------- */
    (function installFetchInterceptor() {
      if (window.__remedyFetchPatched) return;
      window.__remedyFetchPatched = true;
      const original = window.fetch.bind(window);
      window.fetch = async function patchedFetch(input, init) {
        let url = '';
        try {
          url = typeof input === 'string' ? input : (input && input.url) || '';
        } catch (err) {
          url = '';
        }
        // /health 与 /v1/auth/* 不参与登录态拦截，避免登录前循环
        const isAuthFree = url.startsWith('/health') || url.startsWith('/v1/auth/login') || url.startsWith('/v1/auth/register') || url.startsWith('/v1/auth/guest');
        let resp;
        try {
          resp = await original(input, init);
        } catch (err) {
          showSystemBanner('网络请求失败：' + (err && err.message ? err.message : ''), 'is-bad');
          throw err;
        }
        if (resp.status === 401) {
          // 登录态失效：清 token + 跳登录页（除登录/注册自身 401 之外）
          if (!isAuthFree && state.token) {
            const body = await resp.clone().text().catch(() => '');
            try {
              const data = body ? JSON.parse(body) : {};
              if (data.code === 'UNAUTHORIZED' || resp.status === 401) {
                handleSessionExpired();
              }
            } catch (e) {
              handleSessionExpired();
            }
          }
        } else if (resp.status === 403) {
          const isGuest = !state.userId || state.userId === 'guest';
          const isSelfProfile = /\/v1\/users\/[^/]+\/(personality|memories)/.test(url);
          if (isGuest && isSelfProfile) {
            return resp;
          }
          const body = await resp.clone().text().catch(() => '');
          let msg = '权限不足';
          try { msg = (body && JSON.parse(body).error) || msg; } catch (e) { /* ignore */ }
          toast(msg, 'error');
        } else if (resp.status >= 500) {
          showSystemBanner(`服务器异常 ${resp.status}：已记录，请稍后重试`, 'is-bad');
        }
        return resp;
      };
    })();

    function handleSessionExpired() {
      // 静默退出，避免无限刷新
      const previous = state.userId;
      clearSession();
      if (previous !== 'guest') {
        toast('登录已过期，请重新登录', 'error');
      }
      // 关闭可能打开的菜单
      hideAccountMenu();
    }

    function showSystemBanner(text, level) {
      const banner = el('systemBanner');
      if (!banner) return;
      banner.classList.remove('is-hidden', 'is-warn', 'is-bad');
      banner.classList.add(level || 'is-warn');
      el('systemBannerText').textContent = text;
      try { refreshIcons(); } catch (e) { /* ignore */ }
    }

    function dismissSystemBanner() {
      const banner = el('systemBanner');
      if (banner) banner.classList.add('is-hidden');
    }

    function refreshIcons() {
      if (window.lucide && typeof lucide.createIcons === 'function') lucide.createIcons();
    }

    function toast(message, type) {
      const host = el('toastHost');
      const node = document.createElement('div');
      node.className = 'toast' + (type ? ' ' + type : '');
      node.textContent = message;
      host.appendChild(node);
      requestAnimationFrame(() => node.classList.add('show'));
      setTimeout(() => {
        node.classList.remove('show');
        setTimeout(() => node.remove(), 240);
      }, 2800);
    }

    function askConfirm(title, message, action) {
      el('confirmTitle').textContent = title;
      el('confirmMessage').textContent = message;
      el('confirmModal').classList.remove('hidden');
      el('confirmOkBtn').onclick = async () => {
        el('confirmModal').classList.add('hidden');
        await action();
      };
      el('confirmCancelBtn').onclick = () => el('confirmModal').classList.add('hidden');
    }

    function setAuthMode(mode) {
      state.authMode = mode;
      const loginBtn = el('authTabLogin');
      const registerBtn = el('authTabRegister');
      const nick = el('authNickname');
      const submit = el('authSubmitBtn');
      if (mode === 'register') {
        loginBtn.classList.remove('active');
        registerBtn.classList.add('active');
        nick.classList.remove('hidden');
        submit.textContent = '注册并登录';
      } else {
        registerBtn.classList.remove('active');
        loginBtn.classList.add('active');
        nick.classList.add('hidden');
        submit.textContent = '登录';
      }
      el('authError').classList.add('hidden');
    }

    function fillDemoAccount(username, password) {
      setAuthMode('login');
      el('authUsername').value = username;
      el('authPassword').value = password;
    }

    function showAuthError(msg) {
      const node = el('authError');
      node.textContent = msg;
      node.classList.remove('hidden');
    }

    /* ----------- 封面统计数字 count-up ----------- */
    function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

    function animateCoverStat(node, i) {
      const target = parseFloat(node.dataset.target);
      const suffix = node.dataset.suffix || '';
      const decimals = parseInt(node.dataset.decimals, 10) || 0;
      const duration = 1500 + i * 80;
      const startDelay = 480 + i * 90;
      const start = performance.now() + startDelay;
      function tick(now) {
        const elapsed = now - start;
        if (elapsed < 0) { requestAnimationFrame(tick); return; }
        const progress = Math.min(1, elapsed / duration);
        const value = target * easeOutCubic(progress);
        node.textContent = value.toFixed(decimals) + suffix;
        if (progress < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }

    function initCoverStats() {
      const nodes = document.querySelectorAll('.cover-stat-value');
      if (!nodes.length) return;
      if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        nodes.forEach((node) => {
          const decimals = parseInt(node.dataset.decimals, 10) || 0;
          node.textContent = parseFloat(node.dataset.target).toFixed(decimals) + (node.dataset.suffix || '');
        });
        return;
      }
      let done = false;
      const observer = new IntersectionObserver((entries) => {
        if (done || !entries.some((e) => e.isIntersecting)) return;
        done = true;
        nodes.forEach((node, i) => animateCoverStat(node, i));
        observer.disconnect();
      }, { threshold: 0.25 });
      observer.observe(nodes[0].closest('.cover-stats'));
    }
    document.addEventListener('DOMContentLoaded', initCoverStats);

    async function readJson(resp) {
      const text = await resp.text();
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch (err) {
        if (resp.status === 404) throw new Error('认证接口不存在，请重启后端服务后再试');
        throw new Error(text.slice(0, 120) || '服务器返回了非 JSON 响应');
      }
    }

    async function handleAuthSubmit(e) {
      e.preventDefault();
      const username = el('authUsername').value.trim();
      const password = el('authPassword').value;
      const nickname = el('authNickname').value.trim();
      if (!username || username.length < 3) { showAuthError('用户名至少需要 3 个字符'); return; }
      if (!password || password.length < 6) { showAuthError('密码至少需要 6 位'); return; }
      try {
        if (state.authMode === 'register') {
          const reg = await fetch('/v1/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, nickname })
          });
          const regData = await readJson(reg);
          if (!reg.ok) { showAuthError(regData.error || '注册失败'); return; }
        }
        const resp = await fetch('/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        const data = await readJson(resp);
        if (!resp.ok) { showAuthError(data.error || '登录失败'); return; }
        applySession(data.token, data.user);
        toast('登录成功', 'success');
      } catch (err) {
        showAuthError(err.message);
      }
    }

    function updateMemoryUser() {
      el('currentMemoryUser').textContent = state.userId;
      el('currentMemoryUserPath').textContent = state.userId;
    }

    function applySession(token, user) {
      state.token = token;
      state.currentUser = user;
      state.userId = user.username;
      localStorage.setItem('myagent_token', token);
      hideEl('authOverlay');
      showEl('authUserBar');
      showEl('logoutBtn');
      el('authDisplayName').textContent = user.nickname || user.username;
      const badge = el('authRoleBadge');
      if (user.role === 'admin') {
        badge.textContent = '管理员';
        badge.classList.add('admin');
        showEl('adminUserSwitcher');
        showEl('adminConsoleBtn');
        showEl('adminPortraitPanel');
        showEl('tabBtn-settings');
        loadAdminUsers();
      } else {
        badge.textContent = '普通用户';
        badge.classList.remove('admin');
        hideEl('adminUserSwitcher');
        hideEl('adminConsoleBtn');
        hideEl('adminPortraitPanel');
        hideEl('tabBtn-settings');
      }
      updateMemoryUser();
      loadPersonalityProfile();
      switchTab('overview');
      if (typeof window.checkEmptyState === 'function') window.checkEmptyState();
      if (typeof window.loadCoachingCard === 'function') window.loadCoachingCard();
      if (typeof window.startTour === 'function') window.startTour();
      if (typeof window.refreshKanbanBadge === 'function') window.refreshKanbanBadge();
      if (typeof window.refreshWorkspaceList === 'function') window.refreshWorkspaceList();
    }

    function clearSession() {
      stopPersonalityPoll();
      state.token = '';
      state.currentUser = null;
      state.userId = 'guest';
      localStorage.removeItem('myagent_token');
      showEl('authOverlay');
      hideEl('authUserBar');
      hideEl('logoutBtn');
      hideEl('adminUserSwitcher');
      hideEl('adminConsoleBtn');
      hideEl('adminPortraitPanel');
      hideAccountMenu();
      dismissSystemBanner();
      updateMemoryUser();
    }

    /* ----------- 账号菜单 (Sprint 0.3 / 0.4) ----------- */
    function toggleAccountMenu() {
      const menu = el('accountMenu');
      if (!menu) return;
      if (menu.classList.contains('hidden')) {
        openAccountMenu();
      } else {
        hideAccountMenu();
      }
    }

    function openAccountMenu() {
      if (!state.currentUser) return;
      const menu = el('accountMenu');
      el('accountMenuName').textContent = state.currentUser.nickname || state.currentUser.username;
      el('accountMenuMeta').textContent =
        (state.currentUser.role === 'admin' ? '管理员 · ' : '') +
        (state.currentUser.username || '');
      menu.classList.remove('hidden');
      refreshIcons();
      // 关闭其他 popover
      const detail = el('memoryIndicatorDetail');
      if (detail) detail.classList.add('hidden');
    }

    function hideAccountMenu() {
      const menu = el('accountMenu');
      if (menu) menu.classList.add('hidden');
    }

    async function exportMyData() {
      hideAccountMenu();
      if (!state.token) { toast('请先登录后再导出', 'error'); return; }
      try {
        const resp = await fetch('/v1/me/export', { headers: authHeaders() });
        if (!resp.ok) { toast('导出失败 ' + resp.status, 'error'); return; }
        const blob = await resp.blob();
        const disposition = resp.headers.get('Content-Disposition') || '';
        const m = disposition.match(/filename="?([^"]+)"?/);
        const filename = (m && m[1]) || ('remedy_export_' + Date.now() + '.json');
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
        toast('数据已导出', 'success');
      } catch (err) {
        toast('导出失败：' + err.message, 'error');
      }
    }

    function showDeleteAccountModal() {
      hideAccountMenu();
      const input = el('deleteAccountInput');
      if (input) input.value = '';
      checkDeleteAccountInput();
      el('deleteAccountModal').classList.remove('hidden');
      setTimeout(() => { if (input) input.focus(); }, 60);
      refreshIcons();
    }

    function hideDeleteAccountModal() {
      el('deleteAccountModal').classList.add('hidden');
    }

    function checkDeleteAccountInput() {
      const input = el('deleteAccountInput');
      const btn = el('deleteAccountOkBtn');
      if (!input || !btn) return;
      btn.disabled = input.value.trim() !== '确认删除';
    }

    async function confirmDeleteAccount() {
      const btn = el('deleteAccountOkBtn');
      if (!btn || btn.disabled) return;
      btn.disabled = true;
      btn.textContent = '删除中…';
      try {
        const resp = await fetch('/v1/me', {
          method: 'DELETE',
          headers: authHeaders(),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          toast((data && data.error) || '删除失败 ' + resp.status, 'error');
          btn.disabled = false;
          btn.textContent = '永久删除';
          return;
        }
        hideDeleteAccountModal();
        toast('账号与数据已永久删除', 'success');
        clearSession();
      } catch (err) {
        toast('删除失败：' + err.message, 'error');
        btn.disabled = false;
        btn.textContent = '永久删除';
      }
    }

    // 点其他位置自动关闭账号菜单
    document.addEventListener('click', (ev) => {
      const menu = el('accountMenu');
      if (!menu || menu.classList.contains('hidden')) return;
      const target = ev.target;
      if (menu.contains(target)) return;
      if (el('authUserBar') && el('authUserBar').contains(target)) return;
      hideAccountMenu();
    });

    function getDeviceId() {
      let deviceId = localStorage.getItem('remedy_device_id');
      if (!deviceId) {
        deviceId = (crypto && crypto.randomUUID)
          ? crypto.randomUUID()
          : ('dev-' + Date.now() + '-' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2));
        localStorage.setItem('remedy_device_id', deviceId);
      }
      return deviceId;
    }

    async function enterAsGuest() {
      // 访客模式：按设备 ID 自动创建/复用独立账号，实现免注册数据隔离
      try {
        const resp = await fetch('/v1/auth/guest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ device_id: getDeviceId() })
        });
        const data = await readJson(resp);
        if (!resp.ok) { showAuthError(data.error || '访客登录失败'); return; }
        applySession(data.token, data.user);
        toast('已进入访客模式（数据按设备隔离）');
      } catch (err) {
        showAuthError(err.message);
      }
    }

    async function restoreSession() {
      if (!state.token) return;
      try {
        const resp = await fetch('/v1/auth/me', { headers: authHeaders() });
        if (!resp.ok) { clearSession(); return; }
        const data = await resp.json();
        applySession(state.token, data.user);
      } catch (err) {
        clearSession();
      }
    }

    async function handleLogout() {
      try {
        await fetch('/v1/auth/logout', { method: 'POST', headers: authHeaders() });
      } catch (err) {}
      clearSession();
      toast('已退出登录');
    }

    async function loadAdminUsers() {
      if (!state.currentUser || state.currentUser.role !== 'admin') return;
      try {
        const resp = await fetch('/v1/admin/users', { headers: authHeaders() });
        if (!resp.ok) return;
        const data = await resp.json();
        const users = data.users || [];
        el('adminUserCount').textContent = users.length + ' 名用户';
        const select = el('adminTargetSelect');
        select.innerHTML = users.map(u => `<option value="${escapeHtml(u.username)}" ${u.username === state.userId ? 'selected' : ''}>${escapeHtml(u.nickname || u.username)} (${u.role})</option>`).join('');
        el('adminUserStatsGrid').innerHTML = users.map(u => `
          <button onclick="inspectUser('${escapeHtml(u.username)}')" class="admin-user">
            <div class="admin-user-top">
              <strong>${escapeHtml(u.nickname || u.username)}</strong>
              <span>${u.role}</span>
            </div>
            <p>记忆 ${u.stats?.total_memories || 0} · 交互 ${u.stats?.total_interactions || 0}</p>
          </button>
        `).join('');
        refreshIcons();
      } catch (err) {
        console.error('Load admin users failed:', err);
      }
    }

    function onAdminTargetChange() {
      inspectUser(el('adminTargetSelect').value);
    }

    function inspectUser(username) {
      state.userId = username;
      updateMemoryUser();
      const select = el('adminTargetSelect');
      if (select) select.value = username;
      loadUserMemories();
      loadPersonalityProfile();
    }

