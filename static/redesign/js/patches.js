/* Sprint 2：补丁体验 — Toast / 红点 / 影响预览 diff / 批量操作 / Workspace 切换 */
(function () {
  'use strict';

  function el(id) { return document.getElementById(id); }
  function refreshIcons() { if (window.lucide) lucide.createIcons(); }
  function t(msg, kind) { if (typeof window.toast === 'function') window.toast(msg, kind); }

  /* ============================== 2.1 / 2.2 Toast + 侧栏红点 ============================== */

  let _draftPatchesCache = [];   // 当前已知的 draft patches（用于 badge 持续显示）
  let _blockedTasksCache = [];   // 当前已知的受阻任务（用于全局通知铃铛）

  /** 监听 secretary_events 中的 reality_patch，做即时反馈。 */
  function notifyPatchesCreated(count, patches) {
    t(`已生成 ${count} 个待确认的"现实补丁"，请到「秘书看板」查看`, 'success');
    const normalized = (patches || [])
      .map(p => (p && p.data) ? p.data : p)
      .filter(p => p && p.id);
    const byId = {};
    _draftPatchesCache.concat(normalized).forEach(p => { byId[p.id] = p; });
    _draftPatchesCache = Object.keys(byId).map(k => byId[k]);
    if (!_allPatchesCache.length) _allPatchesCache = _draftPatchesCache.slice();
    else {
      normalized.forEach(p => {
        const i = _allPatchesCache.findIndex(x => x.id === p.id);
        if (i >= 0) _allPatchesCache[i] = Object.assign({}, _allPatchesCache[i], p);
        else _allPatchesCache.push(p);
      });
    }
    updateKanbanBadge();
  }

  /** 拉取当前 workspace 的 draft patches 数量，更新侧栏 Tab 红色徽章。 */
  async function refreshKanbanBadge() {
    const username = (window.state && window.state.userId) || '';
    if (!username) return;
    const ws = (window.state && window.state.workspaceId) || 'default';
    try {
      const resp = await fetch('/v1/workspaces/' + encodeURIComponent(ws) + '/dashboard', { headers: authHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();
      const drafts = (data.patches || []).filter(p => p.status === 'draft');
      _draftPatchesCache = drafts;
      _blockedTasksCache = (data.tasks || []).filter(tk => tk.status === 'blocked');
      updateKanbanBadge();
    } catch (err) { /* ignore */ }
  }

  function authHeaders() {
    const h = {};
    const t = (window.localStorage || {}).getItem('myagent_token');
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  function updateKanbanBadge() {
    const badge = el('kanbanBadge');
    const count = _draftPatchesCache.length;
    if (badge) {
      if (count > 0) {
        badge.textContent = count > 99 ? '99+' : String(count);
        badge.classList.remove('hidden');
      } else {
        badge.textContent = '';
        badge.classList.add('hidden');
      }
    }
    updateNotificationBell();
  }

  /* ============================== 全局通知铃铛（跨 Tab 聚合待处理事项） ============================== */

  function updateNotificationBell() {
    const badge = el('notifBellBadge');
    if (!badge) return;
    const count = _draftPatchesCache.length + _blockedTasksCache.length;
    if (count > 0) {
      badge.textContent = count > 99 ? '99+' : String(count);
      badge.classList.remove('hidden');
    } else {
      badge.textContent = '';
      badge.classList.add('hidden');
    }
  }

  function setBlockedTasksCache(arr) {
    _blockedTasksCache = arr || [];
    updateNotificationBell();
  }

  function renderNotificationList() {
    const list = el('notifList');
    if (!list) return;
    const items = [];
    _draftPatchesCache.forEach(p => {
      const change = typeof p.proposed_change === 'string' ? p.proposed_change : JSON.stringify(p.proposed_change || '');
      const label = `${p.target_type || ''} ${p.operation || ''} → ${change}`.trim();
      items.push(`<button class="notif-item" onclick="window.switchTab && switchTab('kanban'); window.hideNotificationPopover && hideNotificationPopover();">
        <span class="tag tag-gold">待确认补丁</span><span>${escapeNotifHtml(label || p.id || '')}</span>
      </button>`);
    });
    _blockedTasksCache.forEach(task => {
      items.push(`<button class="notif-item" onclick="window.switchTab && switchTab('kanban'); window.hideNotificationPopover && hideNotificationPopover();">
        <span class="tag tag-terra">受阻任务</span><span>${escapeNotifHtml(task.title || task.id || '')}</span>
      </button>`);
    });
    list.innerHTML = items.length ? items.join('') : '<p class="empty">暂无待处理事项</p>';
    refreshIcons();
  }

  function escapeNotifHtml(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').slice(0, 60);
  }

  function toggleNotificationPopover() {
    const panel = el('notifPanel');
    if (!panel) return;
    if (panel.classList.contains('hidden')) {
      renderNotificationList();
      panel.classList.remove('hidden');
    } else {
      panel.classList.add('hidden');
    }
  }

  function hideNotificationPopover() {
    const panel = el('notifPanel');
    if (panel) panel.classList.add('hidden');
  }

  /* ============================== 2.3 影响预览 diff 弹窗 ============================== */

  /**
   * 打开补丁影响预览。要求 patch 已经在看板渲染过（即已经在 dashboard data 中）。
   * 我们直接拉取单条 patch 的 detail：
   * - 后端目前还没有 GET /v1/patches/<id>，所以从看板 dashboard 的 patches 缓存中查找。
   */
  async function openPatchDiff(patchId) {
    let patch = (_allPatchesCache || []).find(p => p.id === patchId)
      || (_draftPatchesCache || []).find(p => p.id === patchId);
    if (!patch) {
      const ws = (window.state && window.state.workspaceId) || 'default';
      try {
        const resp = await fetch('/v1/workspaces/' + encodeURIComponent(ws) + '/dashboard', { headers: authHeaders() });
        if (resp.ok) {
          const data = await resp.json();
          _allPatchesCache = data.patches || [];
          _draftPatchesCache = _allPatchesCache.filter(p => p.status === 'draft');
          updateKanbanBadge();
          patch = _allPatchesCache.find(p => p.id === patchId);
        }
      } catch (err) { /* ignore */ }
    }
    if (!patch) {
      t('补丁已不可用，请刷新看板再试', 'error');
      return;
    }
    const rollback = parseRollback(patch);
    showPatchDiffModal(patch, rollback);
  }

  function parseRollback(patch) {
    if (!patch.rollback_data) return null;
    try { return JSON.parse(patch.rollback_data); } catch (e) { return null; }
  }

  function showPatchDiffModal(patch, rollback) {
    const modal = el('patchDiffModal');
    if (!modal) return;
    el('patchDiffId').textContent = patch.id;
    el('patchDiffOp').textContent = (patch.operation || '') + ' · ' + (patch.target_type || '');
    el('patchDiffRisk').textContent = patch.risk || 'medium';
    el('patchDiffRisk').className = 'risk-pill risk-' + (patch.risk || 'medium');
    el('patchDiffEvidence').textContent = patch.evidence || '（无引证）';
    el('patchDiffProposed').textContent = patch.proposed_change || '';
    el('patchDiffCreatedBy').textContent = (patch.created_by || '—') + ' · ' + (patch.created_at || '');
    const targetIdEl = el('patchDiffTargetId');
    if (targetIdEl) targetIdEl.textContent = patch.target_id || '—';

    // diff 双列
    const diffBody = el('patchDiffBody');
    if (diffBody) {
      const before = rollback && rollback.previous_task ? rollback.previous_task : (rollback && rollback.created_task_id ? { status: '(新建任务)' } : { status: '(无法对比)' });
      diffBody.innerHTML = `
        <div class="diff-col">
          <div class="diff-label">变更前</div>
          <pre class="diff-box diff-before">${escapeHtml(JSON.stringify(before, null, 2))}</pre>
        </div>
        <div class="diff-col">
          <div class="diff-label">变更后（将应用）</div>
          <pre class="diff-box diff-after">${escapeHtml(JSON.stringify({
            operation: patch.operation,
            target_type: patch.target_type,
            target_id: patch.target_id,
            proposed_change: patch.proposed_change,
            risk: patch.risk,
          }, null, 2))}</pre>
        </div>
      `;
    }

    // 按钮态
    const confirmBtn = el('patchDiffConfirmBtn');
    const rollbackBtn = el('patchDiffRollbackBtn');
    const cancelBtn = el('patchDiffCancelBtn');
    if (confirmBtn) {
      confirmBtn.style.display = patch.status === 'draft' ? '' : 'none';
      confirmBtn.onclick = async () => {
        confirmBtn.disabled = true;
        confirmBtn.textContent = '应用中…';
        try {
          const r = await fetch('/v1/patches/' + encodeURIComponent(patch.id) + '/confirm', {
            method: 'POST', headers: authHeaders(),
          });
          if (!r.ok) {
            const data = await r.json().catch(() => ({}));
            t('应用失败：' + (data.error || r.status), 'error');
            return;
          }
          t('补丁已应用', 'success');
          modal.classList.add('hidden');
          refreshKanbanBadge();
          if (typeof loadDashboard === 'function') loadDashboard();
        } finally {
          confirmBtn.disabled = false;
          confirmBtn.textContent = '确认应用';
        }
      };
    }
    if (rollbackBtn) {
      rollbackBtn.style.display = patch.status === 'applied' ? '' : 'none';
      rollbackBtn.onclick = async () => {
        rollbackBtn.disabled = true;
        rollbackBtn.textContent = '回滚中…';
        try {
          const r = await fetch('/v1/patches/' + encodeURIComponent(patch.id) + '/rollback', {
            method: 'POST', headers: authHeaders(),
          });
          if (!r.ok) {
            const data = await r.json().catch(() => ({}));
            t('回滚失败：' + (data.error || r.status), 'error');
            return;
          }
          t('补丁已回滚', 'success');
          modal.classList.add('hidden');
          refreshKanbanBadge();
          if (typeof loadDashboard === 'function') loadDashboard();
        } finally {
          rollbackBtn.disabled = false;
          rollbackBtn.textContent = '回滚此补丁';
        }
      };
    }
    if (cancelBtn) {
      cancelBtn.onclick = () => modal.classList.add('hidden');
    }

    modal.classList.remove('hidden');
    refreshIcons();
  }

  let _allPatchesCache = [];

  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  /* ============================== 2.4 Workspace 切换 ============================== */

  async function refreshWorkspaceList() {
    try {
      const resp = await fetch('/v1/workspaces', { headers: authHeaders() });
      if (!resp.ok) {
        t('工作区列表加载失败：' + resp.status, 'error');
        renderWorkspaceDropdown([]);
        return;
      }
      const data = await resp.json();
      renderWorkspaceDropdown(data.workspaces || []);
    } catch (err) {
      t('工作区列表加载失败', 'error');
      renderWorkspaceDropdown([]);
    }
  }

  function renderWorkspaceDropdown(workspaces) {
    const host = el('workspaceSelector');
    const wsName = el('workspaceName');
    if (!host) return;
    const current = (window.state && window.state.workspaceId) || 'default';
    if (wsName) wsName.textContent = (workspaces.find(w => w.id === current) || {}).name || current;
    host.innerHTML = workspaces.map(w => `
      <button class="workspace-item ${w.id === current ? 'is-current' : ''}" data-id="${escapeHtml(w.id)}">
        <i data-lucide="${w.id === current ? 'check' : 'folder'}"></i>
        <span>${escapeHtml(w.name)}</span>
      </button>
    `).join('') + `
      <div class="workspace-divider"></div>
      <button class="workspace-item workspace-new" onclick="window.showCreateWorkspaceModal && window.showCreateWorkspaceModal()">
        <i data-lucide="plus"></i><span>新建工作区</span>
      </button>
    `;
    Array.from(host.querySelectorAll('.workspace-item[data-id]')).forEach(btn => {
      btn.onclick = () => switchWorkspace(btn.dataset.id);
    });
    refreshIcons();
  }

  async function switchWorkspace(wsId) {
    if (!wsId) return;
    if ((window.state.workspaceId || '') === wsId) {
      el('workspaceDropdown')?.classList.add('hidden');
      return;
    }
    window.state.workspaceId = wsId;
    const wsInput = el('workspaceIdInput');
    if (wsInput) wsInput.value = wsId;
    el('workspaceDropdown')?.classList.add('hidden');
    t('已切换到 ' + wsId, 'success');
    // 触发看板 / 总览重载
    if (typeof loadDashboard === 'function') loadDashboard();
    if (typeof loadOverview === 'function') loadOverview();
    refreshKanbanBadge();
  }

  function toggleWorkspaceDropdown() {
    const d = el('workspaceDropdown');
    if (!d) return;
    d.classList.toggle('hidden');
    if (!d.classList.contains('hidden')) {
      refreshWorkspaceList();
    }
  }

  function showCreateWorkspaceModal() {
    const m = el('createWorkspaceModal');
    if (m) m.classList.remove('hidden');
    const input = el('newWorkspaceName');
    if (input) { input.value = ''; setTimeout(() => input.focus(), 60); }
    refreshIcons();
  }

  function hideCreateWorkspaceModal() {
    el('createWorkspaceModal')?.classList.add('hidden');
  }

  async function submitCreateWorkspace() {
    const input = el('newWorkspaceName');
    const btn = el('createWorkspaceOkBtn');
    const name = (input && input.value || '').trim();
    if (!name) { t('工作区名称不能为空', 'error'); return; }
    if (btn) { btn.disabled = true; btn.textContent = '创建中…'; }
    try {
      const resp = await fetch('/v1/workspaces', {
        method: 'POST',
        headers: Object.assign(authHeaders(), { 'Content-Type': 'application/json' }),
        body: JSON.stringify({ name }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.success) {
        t((data && data.error) || '创建失败', 'error');
        return;
      }
      t('已创建：' + (data.workspace && data.workspace.name), 'success');
      hideCreateWorkspaceModal();
      await switchWorkspace(data.workspace.id);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '创建并切换'; }
    }
  }

  /* ============================== 2.6 批量操作 ============================== */

  let _selectedPatchIds = new Set();

  function togglePatchSelection(patchId, checkbox) {
    if (checkbox.checked) _selectedPatchIds.add(patchId);
    else _selectedPatchIds.delete(patchId);
    updateBatchBar();
  }

  function updateBatchBar() {
    const bar = el('patchBatchBar');
    const count = el('patchBatchCount');
    if (!bar) return;
    if (_selectedPatchIds.size > 0) {
      bar.classList.remove('hidden');
      if (count) count.textContent = _selectedPatchIds.size;
    } else {
      bar.classList.add('hidden');
    }
  }

  function clearSelection() {
    _selectedPatchIds.clear();
    document.querySelectorAll('.patch-select-input').forEach(cb => { cb.checked = false; });
    updateBatchBar();
  }

  async function batchConfirm() {
    const ids = Array.from(_selectedPatchIds);
    if (ids.length === 0) return;
    let ok = 0, skip = 0, fail = 0;
    for (const id of ids) {
      try {
        const r = await fetch('/v1/patches/' + encodeURIComponent(id) + '/confirm', {
          method: 'POST', headers: authHeaders(),
        });
        if (r.ok) ok++;
        else if (r.status === 409) skip++;
        else fail++;
      } catch (e) { fail++; }
    }
    t(`批量应用：成功 ${ok} 跳过 ${skip} 失败 ${fail}`, ok > 0 ? 'success' : 'error');
    clearSelection();
    if (typeof loadDashboard === 'function') loadDashboard();
    refreshKanbanBadge();
  }

  async function batchRollback() {
    const ids = Array.from(_selectedPatchIds);
    if (ids.length === 0) return;
    let ok = 0, skip = 0, fail = 0;
    for (const id of ids) {
      try {
        const r = await fetch('/v1/patches/' + encodeURIComponent(id) + '/rollback', {
          method: 'POST', headers: authHeaders(),
        });
        if (r.ok) ok++;
        else if (r.status === 409) skip++;
        else fail++;
      } catch (e) { fail++; }
    }
    t(`批量回滚：成功 ${ok} 跳过 ${skip} 失败 ${fail}`, ok > 0 ? 'success' : 'error');
    clearSelection();
    if (typeof loadDashboard === 'function') loadDashboard();
    refreshKanbanBadge();
  }

  /* ============================== 暴露给 frontend ============================== */

  window.notifyPatchesCreated = notifyPatchesCreated;
  window.refreshKanbanBadge = refreshKanbanBadge;
  window.updateKanbanBadge = updateKanbanBadge;
  window.setBlockedTasksCache = setBlockedTasksCache;
  window.toggleNotificationPopover = toggleNotificationPopover;
  window.hideNotificationPopover = hideNotificationPopover;
  window.openPatchDiff = openPatchDiff;
  window.toggleWorkspaceDropdown = toggleWorkspaceDropdown;
  window.switchWorkspace = switchWorkspace;
  window.showCreateWorkspaceModal = showCreateWorkspaceModal;
  window.hideCreateWorkspaceModal = hideCreateWorkspaceModal;
  window.submitCreateWorkspace = submitCreateWorkspace;
  window.togglePatchSelection = togglePatchSelection;
  window.batchConfirm = batchConfirm;
  window.batchRollback = batchRollback;
  window.clearPatchSelection = clearSelection;
  window.setPatchesCache = function (arr) {
    _allPatchesCache = arr || [];
    _draftPatchesCache = _allPatchesCache.filter(p => p.status === 'draft');
  };

  document.addEventListener('DOMContentLoaded', () => {
    refreshKanbanBadge();
    document.addEventListener('click', (ev) => {
      const panel = el('notifPanel');
      const bell = el('notifBell');
      if (!panel || panel.classList.contains('hidden')) return;
      if (panel.contains(ev.target) || (bell && bell.contains(ev.target))) return;
      panel.classList.add('hidden');
    });
  });
})();
