/* Sprint 1：冷启动 — Demo Workspace、空状态、首登 Tour、人格解锁进度 */
(function () {
  'use strict';

  /* ============================== 工具 ============================== */
  function el(id) { return document.getElementById(id); }
  function refreshIcons() { if (window.lucide) lucide.createIcons(); }

  /* ============================== 1.2 总览空状态 + Demo 注入 ============================== */

  /** 检测是否需要展示"是否体验示例"二选一卡 */
  async function checkEmptyState() {
    const stats = el('onboardingStats');
    const welcome = el('onboardingWelcome');
    const demoBtn = el('seedDemoBtn');
    const skipBtn = el('skipDemoBtn');
    const clearBtn = el('clearDemoBtn');

    if (!stats || !welcome || !demoBtn || !skipBtn) return;

    // 没有 token 不展示
    const token = (window.localStorage || {}).getItem('myagent_token');
    if (!token) { welcome.classList.add('hidden'); return; }

    try {
      const resp = await fetch('/v1/me/onboarding', { headers: { Authorization: 'Bearer ' + token } });
      if (!resp.ok) return;
      const data = await resp.json();
      const seeded = !!data.demo_seeded;

      // 看一眼真实数据：memories + tasks + docs 是否全 0
      const dashResp = await fetch('/v1/workspaces/default/dashboard', { headers: { Authorization: 'Bearer ' + token } });
      const dash = dashResp.ok ? await dashResp.json() : {};
      const tasksCount = (dash.tasks || []).length;
      const patchesCount = (dash.patches || []).length;

      if (seeded) {
        // 已 demo：显示「清空示例」+ 顶部 banner 提示
        welcome.classList.add('hidden');
        if (clearBtn) clearBtn.classList.remove('hidden');
        return;
      }

      // 未 demo：仅在真实数据全 0 时才弹（避免覆盖用户已有数据）
      const memResp = await fetch('/v1/users/' + encodeURIComponent(data.user.username) + '/memory?q=&limit=1', { headers: { Authorization: 'Bearer ' + token } });
      const mem = memResp.ok ? await memResp.json() : {};
      const memCount = (mem.memories || []).length;

      const isEmpty = memCount === 0 && tasksCount === 0 && patchesCount === 0;
      const skipped = localStorage.getItem('onboard_skip_demo') === '1';

      if (isEmpty && !skipped) {
        welcome.classList.remove('hidden');
      } else {
        welcome.classList.add('hidden');
      }
      if (clearBtn) clearBtn.classList.add('hidden');
    } catch (err) {
      console.warn('checkEmptyState failed:', err);
    }
  }

  async function seedDemo() {
    const token = (window.localStorage || {}).getItem('myagent_token');
    if (!token) return;
    const btn = el('seedDemoBtn');
    if (btn) { btn.disabled = true; btn.textContent = '注入中…'; }
    try {
      const resp = await fetch('/v1/me/onboarding/seed-demo', { method: 'POST', headers: { Authorization: 'Bearer ' + token } });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.success) {
        (window.toast || alert)((data && data.error) || '示例注入失败', 'error');
        return;
      }
      const s = data.summary || {};
      (window.toast || alert)('已注入示例：' + (s.memories || 0) + ' 记忆 · ' + (s.tasks || 0) + ' 任务 · ' + (s.patches || 0) + ' 补丁 · 1 文档', 'success');
      // 重载所有受影响 Tab
      if (typeof loadOverview === 'function') loadOverview();
      if (typeof loadLibrary === 'function') loadLibrary();
      if (typeof loadUserMemories === 'function') loadUserMemories();
      checkEmptyState();
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '开始体验'; }
    }
  }

  async function skipDemo() {
    localStorage.setItem('onboard_skip_demo', '1');
    const welcome = el('onboardingWelcome');
    if (welcome) welcome.classList.add('hidden');
  }

  async function clearDemo() {
    (window.askConfirm || function (t, m, a) { if (confirm(t + '\n' + m)) a(); })(
      '清空示例数据',
      '将删除为你注入的 3 条记忆、1 份文档、3 个示例任务与 1 个补丁（你的真实数据不受影响）。',
      async () => {
        const token = (window.localStorage || {}).getItem('myagent_token');
        if (!token) return;
        try {
          const resp = await fetch('/v1/me/onboarding/clear-demo', { method: 'POST', headers: { Authorization: 'Bearer ' + token } });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok || !data.success) {
            (window.toast || alert)((data && data.error) || '清空失败', 'error');
            return;
          }
          (window.toast || alert)('示例数据已清空', 'success');
          if (typeof loadOverview === 'function') loadOverview();
          if (typeof loadLibrary === 'function') loadLibrary();
          if (typeof loadUserMemories === 'function') loadUserMemories();
          checkEmptyState();
        } catch (err) {
          (window.toast || alert)('清空失败：' + err.message, 'error');
        }
      }
    );
  }

  /* ============================== 1.3 首登 Tour ============================== */

  const TOUR_STEPS = [
    { tab: 'overview', title: '总览', desc: '今天最该做什么、最近的补丁与人格建议，都在这里。' },
    { tab: 'chat',     title: '交互工作台', desc: '对话产生记忆、任务、补丁。可以 `!search` 联网，`@@文档` 引用知识库。' },
    { tab: 'kanban',   title: '秘书看板', desc: 'AI 生成的"现实补丁"在这里等你确认或回滚。' },
    { tab: 'library',  title: '文档知识库', desc: '上传的文件会成为对话的"权威依据"，被自动引用。' },
    { tab: 'memory',   title: '记忆与画像', desc: '查看你沉淀的所有偏好、需求、身份；以及大五人格画像。' },
    { tab: 'web',      title: '联网检索', desc: '也可以在对话里直接 `!search 关键词` 或粘贴链接。' },
  ];

  let tourIndex = 0;
  let tourMask = null;

  function ensureTourUI() {
    if (tourMask) return;
    const css = document.createElement('style');
    css.textContent = `
      .tour-mask { position: fixed; inset: 0; background: rgba(20,18,12,0.55); z-index: 999; display: flex; align-items: center; justify-content: center; }
      .tour-card { background: var(--surface-3, #fffdf8); border: 1px solid var(--line, #dcd5c9); border-radius: 14px; padding: 22px 24px; max-width: 460px; width: calc(100% - 40px); box-shadow: 0 24px 60px rgba(0,0,0,0.18); color: var(--ink, #181c21); font-family: inherit; }
      .tour-card h4 { margin: 0 0 6px; font-size: 18px; }
      .tour-card p  { margin: 0; color: var(--muted, #746e63); line-height: 1.7; font-size: 14px; }
      .tour-actions { display: flex; gap: 8px; margin-top: 18px; align-items: center; justify-content: flex-end; }
      .tour-progress { font-size: 11px; color: var(--faint, #999184); margin-right: auto; }
      .tour-btn { height: 36px; padding: 0 14px; border: 1px solid var(--line-strong, #c6bdad); background: var(--surface, #fbfaf6); color: var(--ink, #181c21); border-radius: 8px; cursor: pointer; font-size: 13px; font-family: inherit; }
      .tour-btn.primary { background: var(--accent, #2c6b5d); color: #fffdf8; border-color: var(--accent, #2c6b5d); }
      .tour-btn:hover { border-color: var(--accent, #2c6b5d); }
    `;
    document.head.appendChild(css);

    tourMask = document.createElement('div');
    tourMask.className = 'tour-mask hidden';
    tourMask.innerHTML = `
      <div class="tour-card">
        <h4 id="tourTitle"></h4>
        <p id="tourDesc"></p>
        <div class="tour-actions">
          <span class="tour-progress" id="tourProgress"></span>
          <button class="tour-btn" id="tourSkip">跳过</button>
          <button class="tour-btn primary" id="tourNext">下一步 →</button>
        </div>
      </div>
    `;
    document.body.appendChild(tourMask);

    el('tourSkip').onclick = () => endTour();
    el('tourNext').onclick = () => advanceTour();
  }

  function tourStorageKey() {
    const u = (window.state && window.state.userId) || '';
    if (!u || u === 'guest') return '';
    return 'tour_done:' + u;
  }

  function startTour() {
    const key = tourStorageKey();
    if (!key) return;
    if (localStorage.getItem(key) === '1') return;
    ensureTourUI();
    tourIndex = 0;
    showTourStep();
    tourMask.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function showTourStep() {
    const step = TOUR_STEPS[tourIndex];
    if (!step) return endTour();
    // 切到目标 Tab（不阻塞用户后续操作）
    if (typeof switchTab === 'function') switchTab(step.tab);
    el('tourTitle').textContent = step.title + '（' + (tourIndex + 1) + '/' + TOUR_STEPS.length + '）';
    el('tourDesc').textContent = step.desc;
    el('tourProgress').textContent = '首登引导';
    if (tourIndex === TOUR_STEPS.length - 1) {
      el('tourNext').textContent = '完成 ✓';
    } else {
      el('tourNext').textContent = '下一步 →';
    }
  }

  function advanceTour() {
    tourIndex++;
    if (tourIndex >= TOUR_STEPS.length) {
      endTour();
    } else {
      showTourStep();
    }
  }

  function endTour() {
    if (tourMask) tourMask.classList.add('hidden');
    document.body.style.overflow = '';
    const key = tourStorageKey();
    if (key) localStorage.setItem(key, '1');
  }

  /* ============================== 1.4 人格解锁进度环 ============================== */

  function renderPersonalityUnlock(samples, backend) {
    const wrap = el('personalityUnlock');
    const full = el('personalityFull');
    if (!wrap || !full) return;
    const target = 10;
    if ((samples || 0) >= target) {
      wrap.classList.add('hidden');
      full.classList.remove('hidden');
      return;
    }
    wrap.classList.remove('hidden');
    full.classList.add('hidden');
    const pct = Math.min(100, Math.round(((samples || 0) / target) * 100));
    const ring = el('unlockRingFill');
    const text = el('unlockText');
    const c = 2 * Math.PI * 26;
    if (ring) ring.style.strokeDasharray = `${(pct / 100) * c} ${c}`;
    if (text) text.textContent = `${samples || 0}/${target}`;
  }

  /* ============================== 1.5 总览"今天先做这件事" 卡 ============================== */

  async function loadCoachingCard() {
    const host = el('coachingCard');
    if (!host) return;
    const token = (window.localStorage || {}).getItem('myagent_token');
    if (!token) { host.classList.add('hidden'); return; }

    try {
      const username = (window.state && window.state.userId) || '';
      if (!username) { host.classList.add('hidden'); return; }
      const resp = await fetch('/v1/users/' + encodeURIComponent(username) + '/personality', { headers: { Authorization: 'Bearer ' + token } });
      if (!resp.ok) { host.classList.add('hidden'); return; }
      const profile = await resp.json();
      const samples = profile.samples || 0;
      if (samples < 3) {
        // samples 太少：给引导占位
        host.classList.remove('hidden');
        el('coachingCardBody').innerHTML = `
          <div class="coaching-low">
            <i data-lucide="sparkles"></i>
            <p>再聊 <b>${Math.max(0, 3 - samples)}</b> 句，我就会根据你的人格给你针对性建议。</p>
            <button class="btn btn-sm" onclick="window.switchTab && switchTab('chat')"><i data-lucide="messages-square"></i>开始对话</button>
          </div>
        `;
        refreshIcons();
        return;
      }

      // 后端 coaching_playbook 已存在；前端直接渲染 3 条（来自 work_style.thinking_label / execution_label 派生）
      host.classList.remove('hidden');
      const work = profile.work_style || {};
      const tips = coachingTemplate(samples, work);
      el('coachingCardBody').innerHTML = tips.map(t => `
        <div class="coaching-item">
          <i data-lucide="${t.icon}"></i>
          <div class="coaching-text">
            <strong>${escapeHtml(t.title)}</strong>
            <span>${escapeHtml(t.desc)}</span>
          </div>
          <button class="btn btn-sm" onclick="${t.onclick}">${escapeHtml(t.cta)}</button>
        </div>
      `).join('');
      refreshIcons();
    } catch (err) {
      host.classList.add('hidden');
    }
  }

  function coachingTemplate(samples, work) {
    const thinking = work.thinking_label || '理性';
    const execution = work.execution_label || '执行均衡';
    const executionStyle = work.execution_style || 'balanced';

    const tips = [];
    if (executionStyle === 'procrastinator') {
      tips.push({
        icon: 'timer',
        title: '今天先做 25 分钟',
        desc: '基于你的拖延倾向，建议把第一件事压缩到 25 分钟番茄钟，直接开始。',
        cta: '去开聊',
        onclick: "window.goQuickChat && goQuickChat()",
      });
    } else {
      tips.push({
        icon: 'zap',
        title: '把今天最关键的事排上',
        desc: `你倾向「${execution}」，先用一句话写下今天最想完成的一件事。`,
        cta: '创建任务',
        onclick: "window.goQuickPatch && goQuickPatch()",
      });
    }

    tips.push({
      icon: 'book-open',
      title: '把今天会聊的事提前告诉我',
      desc: '告诉我你今天在忙什么、想做什么，我会主动跟进并每周回顾。',
      cta: '记住一条',
      onclick: "window.switchTab && (switchTab('chat'), window.fillChatInput && fillChatInput('记住：'))",
    });

    if (samples < 8) {
      tips.push({
        icon: 'brain',
        title: `人格画像 ${samples}/10`,
        desc: '你的大五人格画像正在生成中。聊得越多，建议就越准。',
        cta: '查看画像',
        onclick: "window.switchTab && switchTab('memory')",
      });
    } else {
      tips.push({
        icon: 'brain',
        title: '基于' + thinking + '的本周方向',
        desc: '你本周的最佳状态是「' + thinking + '思维」。把大块时间留给需要思考的事。',
        cta: '看人格',
        onclick: "window.switchTab && switchTab('memory')",
      });
    }
    return tips.slice(0, 3);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  /* ============================== 自启动 ============================== */

  // 暴露到 window 以便内联 onclick 调用
  window.seedDemo = seedDemo;
  window.skipDemo = skipDemo;
  window.clearDemo = clearDemo;
  window.startTour = startTour;
  window.endTour = endTour;
  window.checkEmptyState = checkEmptyState;
  window.renderPersonalityUnlock = renderPersonalityUnlock;
  window.loadCoachingCard = loadCoachingCard;

  document.addEventListener('DOMContentLoaded', () => {
    checkEmptyState();
    loadCoachingCard();
  });
})();
