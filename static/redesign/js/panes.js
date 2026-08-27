
    function switchTab(tabId) {
      state.activeTab = tabId;
      document.querySelectorAll('.pane').forEach(node => node.classList.remove('active'));
      el('tab-' + tabId).classList.add('active');
      document.querySelectorAll('.nav-btn').forEach(node => node.classList.remove('active'));
      el('tabBtn-' + tabId).classList.add('active');
      if (tabId === 'kanban') loadDashboard();
      if (tabId === 'library') loadLibrary();
      if (tabId === 'overview') loadOverview();
      if (tabId === 'memory') {
        if (state.currentUser && state.currentUser.role === 'admin') loadAdminUsers();
        loadUserMemories();
        loadPersonalityProfile();
      }
      if (tabId === 'web') refreshIcons();
      if (tabId === 'settings') loadAdminSettings();
      // 对话页实时同步人格画像：进入对话 Tab 时开启轮询，离开时停止
      if (tabId === 'chat') startPersonalityPoll();
      else stopPersonalityPoll();
    }

    // ---- 人格画像实时轮询（对话页自动同步后端计算好的画像） ----
    let personalityPollTimer = null;
    function startPersonalityPoll() {
      if (personalityPollTimer) return;
      loadPersonalityProfile();
      personalityPollTimer = setInterval(() => {
        if (state.activeTab === 'chat' && state.token) loadPersonalityProfile();
      }, 10000);
    }
    function stopPersonalityPoll() {
      if (personalityPollTimer) {
        clearInterval(personalityPollTimer);
        personalityPollTimer = null;
      }
    }

    async function checkHealth() {
      try {
        const res = await fetch('/health');
        const data = await res.json();
        if (data.status === 'ok') {
          el('healthBadge').classList.add('is-ok');
          el('healthBadge').classList.remove('is-bad');
          el('healthText').textContent = '系统正常';
          el('cogEngineName').textContent = data.cognitive_engine || 'PythonEngine';
          if (el('ovHealth')) el('ovHealth').textContent = '正常';
          // LLM 状态 → banner
          const llm = data.llm || {};
          if (llm.configured === false) {
            showSystemBanner(
              `当前未连接 LLM（${llm.model || 'deepseek-v4-flash'}），对话将使用本地规则引擎回答。管理员可在「服务配置」中补全 MODEL_API_KEY。`,
              'is-warn'
            );
          } else if (llm.error) {
            showSystemBanner('LLM 状态检测异常：' + llm.error, 'is-warn');
          } else {
            dismissSystemBanner();
          }
        }
      } catch (err) {
        el('healthBadge').classList.remove('is-bad');
        el('healthBadge').classList.add('is-bad');
        el('healthText').textContent = '服务离线';
        if (el('ovHealth')) el('ovHealth').textContent = '离线';
        showSystemBanner('后端服务不可达，部分功能可能受限。', 'is-bad');
      }
    }

    function fillChatInput(text) {
      const input = el('chatInput');
      input.value = text;
      input.focus();
    }

    function goQuickChat() {
      switchTab('chat');
      el('chatInput').focus();
    }

    function goQuickPatch() {
      switchTab('chat');
      fillChatInput('创建一个任务：完成系统前后端联调测试');
    }

    function goQuickLibrary() {
      switchTab('library');
    }

    async function loadOverview() {
      el('ovUser').textContent = state.currentUser ? (state.currentUser.nickname || state.currentUser.username) : (state.userId === 'guest' ? '访客' : state.userId);
      el('ovWorkspace').textContent = state.workspaceId;
      el('ovEngine').textContent = (el('cogEngineName').textContent || 'PythonEngine').trim();
      el('ovHealth').textContent = el('healthBadge').classList.contains('is-bad') ? '离线' : '正常';
      // 冷启动辅助视图（Sprint 1）
      if (typeof window.checkEmptyState === 'function') window.checkEmptyState();
      if (typeof window.loadCoachingCard === 'function') window.loadCoachingCard();
      try {
        const resp = await fetch(`/v1/workspaces/${encodeURIComponent(state.workspaceId)}/dashboard`, { headers: authHeaders() });
        const data = await resp.json();
        const counts = data.counts || {};
        el('ovTaskTodo').textContent = counts.todo || 0;
        el('ovTaskProgress').textContent = counts.in_progress || 0;
        const patches = data.patches || [];
        const list = el('ovPatchList');
        if (patches.length === 0) {
          list.innerHTML = '<div class="empty-state"><p>暂无补丁，可在对话中下达任务生成草稿</p><button class="btn btn-sm" onclick="goQuickPatch()"><i data-lucide="square-pen"></i>下达任务</button></div>';
        } else {
          list.innerHTML = patches.slice(0, 4).map(p => {
            let badge = '<span class="badge badge-draft">草稿</span>';
            if (p.status === 'applied') badge = '<span class="badge badge-applied">已应用</span>';
            else if (p.status === 'rolled_back') badge = '<span class="badge badge-rolled">已回滚</span>';
            return `<div class="patch-mini"><span class="patch-id">${escapeHtml(p.id)}</span><span class="patch-change" title="${escapeHtml(p.proposed_change)}">${escapeHtml(p.proposed_change)}</span>${badge}</div>`;
          }).join('');
        }
        refreshIcons();
      } catch (err) {
        el('ovPatchList').innerHTML = '<p class="empty">看板数据加载失败</p>';
      }
      try {
        const resp = await fetch('/v1/library/documents', { headers: authHeaders() });
        const data = await resp.json();
        el('ovDocs').textContent = (data.documents || []).length;
      } catch (err) {}
      try {
        const resp = await fetch(`/v1/users/${encodeURIComponent(state.userId)}/memory?q=&limit=100`, { headers: authHeaders() });
        const data = await resp.json();
        el('ovMemories').textContent = (data.memories || []).length;
      } catch (err) {}
    }

    function updateMemoryIndicator() {
      el('memoryCitedText').textContent = state.memoryCited;
      el('memoryCorrectedText').textContent = state.memoryCorrected;
    }

    async function handleChatSubmit(e) {
      e.preventDefault();
      const input = el('chatInput');
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      appendUserMessage(text);
      const msgId = 'msg-' + Date.now();
      appendAgentPlaceholder(msgId);
      const payload = {
        user_id: state.userId,
        workspace_id: state.workspaceId,
        message: text,
        channel: 'web'
      };
      if (state.isStreaming) {
        try {
          const resp = await fetch('/v1/interactions/stream', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(payload)
          });
          const reader = resp.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop();
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                const jsonStr = line.replace('data: ', '').trim();
                try {
                  const eventData = JSON.parse(jsonStr);
                  if (eventData.type === 'response') renderAgentResponse(msgId, eventData.data);
                } catch (pe) {
                  console.error('Parse SSE json failed:', pe);
                }
              }
            }
          }
        } catch (err) {
          renderAgentError(msgId, err.message);
        }
      } else {
        try {
          const resp = await fetch('/v1/interactions', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(payload)
          });
          const data = await resp.json();
          if (resp.ok) renderAgentResponse(msgId, data);
          else renderAgentError(msgId, data.error || '请求失败');
        } catch (err) {
          renderAgentError(msgId, err.message);
        }
      }
    }

    function appendUserMessage(text) {
      const container = el('chatMessages');
      const column = container.querySelector('.chat-column');
      const wrap = document.createElement('div');
      wrap.className = 'chat-column';
      const div = document.createElement('div');
      div.className = 'msg user';
      div.innerHTML = `
        <div class="msg-body">
          <div class="bubble bubble-user prose">${escapeHtml(text)}</div>
          <div class="msg-meta">${escapeHtml(state.userId)} · 刚刚</div>
        </div>
        <div class="avatar avatar-user"><i data-lucide="user"></i></div>
      `;
      wrap.appendChild(div);
      container.appendChild(wrap);
      refreshIcons();
      container.scrollTop = container.scrollHeight;
    }

    function appendAgentPlaceholder(msgId) {
      const container = el('chatMessages');
      const wrap = document.createElement('div');
      wrap.className = 'chat-column';
      const div = document.createElement('div');
      div.id = msgId;
      div.className = 'msg agent';
      div.innerHTML = `
        <div class="avatar avatar-agent"><i data-lucide="bot"></i></div>
        <div class="msg-body">
          <div class="bubble bubble-agent agent-content prose">
            <span class="thinking"><i data-lucide="loader"></i> 正在思考与处理...</span>
          </div>
          <div class="agent-extras"></div>
          <div class="msg-meta">Agent · 处理中</div>
        </div>
      `;
      wrap.appendChild(div);
      container.appendChild(wrap);
      refreshIcons();
      container.scrollTop = container.scrollHeight;
    }

    function renderAgentResponse(msgId, data) {
      const node = el(msgId);
      if (!node) return;
      const contentBox = node.querySelector('.agent-content');
      const extrasBox = node.querySelector('.agent-extras');
      const meta = node.querySelector('.msg-meta');
      contentBox.innerHTML = marked.parse(data.content || '（无响应内容）');
      extrasBox.innerHTML = '';
      if (meta) meta.textContent = 'Agent · 已完成';

      if (data.secretary_events && data.secretary_events.length > 0) {
        let _patchCountInBatch = 0;
        data.secretary_events.forEach(secEvent => {
          if (secEvent.type === 'reality_patch') {
            const patch = secEvent.data;
            _patchCountInBatch++;
            const card = document.createElement('div');
            card.className = 'extra-panel patch-extra';
            card.innerHTML = `
              <div class="extra-head">
                <i data-lucide="shield"></i>
                <span>待确认现实补丁</span>
                <span class="badge badge-draft">${escapeHtml(patch.operation)} ${escapeHtml(patch.target_type)}</span>
              </div>
              <p class="extra-text">${escapeHtml(patch.proposed_change)}</p>
              <div class="extra-actions">
                <button class="btn btn-sm btn-primary" onclick="confirmPatch('${patch.id}')"><i data-lucide="check"></i>确认并应用</button>
                <button class="btn btn-sm" onclick="openPatchDiff('${patch.id}')"><i data-lucide="eye"></i>查看影响</button>
              </div>
            `;
            extrasBox.appendChild(card);
          } else if (secEvent.type === 'sync_draft') {
            const draft = secEvent.data;
            const card = document.createElement('div');
            card.className = 'extra-panel sync-extra';
            card.innerHTML = `
              <div class="extra-head">
                <i data-lucide="list-checks"></i>
                <span>同步草稿已生成</span>
                <span class="badge badge-mist">${escapeHtml(draft.session_id)}</span>
              </div>
              <p class="extra-text">${draft.draft.tasks.length} 项任务提议待确认</p>
              <div class="extra-actions">
                <button class="btn btn-sm" onclick="confirmSync('${draft.session_id}')"><i data-lucide="check"></i>确认同步</button>
              </div>
            `;
            extrasBox.appendChild(card);
          }
        });
        // 批量补丁 Toast + 侧栏红点（Sprint 2.1）
        if (_patchCountInBatch > 0 && typeof window.notifyPatchesCreated === 'function') {
          window.notifyPatchesCreated(_patchCountInBatch, data.secretary_events.filter(e => e.type === 'reality_patch'));
        }
      }

      if (data.citations && data.citations.length > 0) {
        const citeBox = document.createElement('div');
        citeBox.className = 'extra-panel cite-panel';
        citeBox.innerHTML = `<div class="extra-head"><i data-lucide="bookmark"></i><span>知识库引用 (${data.citations.length})</span></div>`;
        data.citations.forEach(c => {
          citeBox.innerHTML += `
            <div class="cite-item">
              <strong>[${escapeHtml(c.title)}]</strong> <span>(${escapeHtml(c.source)})</span>
              <p class="extra-text">${escapeHtml(c.snippet)}</p>
            </div>
          `;
        });
        extrasBox.appendChild(citeBox);
      }

      if (data.tips && data.tips.length > 0) {
        data.tips.forEach(tip => {
          const tipCard = document.createElement('div');
          tipCard.className = 'extra-panel tip-item';
          tipCard.innerHTML = `
            <div class="extra-head"><i data-lucide="lightbulb"></i><span>启发式提示</span></div>
            <div class="tip-title">${escapeHtml(tip.title)}</div>
            <p class="extra-text">${escapeHtml(tip.message)}</p>
            ${tip.alternative_angle ? `<p class="extra-text">建议角度：${escapeHtml(tip.alternative_angle)}</p>` : ''}
          `;
          extrasBox.appendChild(tipCard);
        });
      }

      if (data.memory_events && data.memory_events.length > 0) {
        state.memoryCited += data.memory_events.length;
        updateMemoryIndicator();
        const memEventDiv = document.createElement('div');
        memEventDiv.className = 'mem-event';
        memEventDiv.innerHTML = `
          <i data-lucide="sparkles"></i>
          <span>萃取长期记忆：${data.memory_events.map(m => `[${escapeHtml(m.category)}] ${escapeHtml(m.content)}`).join('；')}</span>
        `;
        extrasBox.appendChild(memEventDiv);
      }

      // 对话响应携带最新人格画像时，实时刷新大五面板（后端 observe 已更新）
      if (data.metadata && data.metadata.personality) {
        renderPersonality(data.metadata.personality);
      }

      const container = el('chatMessages');
      refreshIcons();
      container.scrollTop = container.scrollHeight;
    }

    function renderAgentError(msgId, errMsg) {
      const node = el(msgId);
      if (!node) return;
      const contentBox = node.querySelector('.agent-content');
      const meta = node.querySelector('.msg-meta');
      contentBox.innerHTML = `<span style="color:var(--terra)"><i data-lucide="triangle-alert"></i> 处理失败：${escapeHtml(errMsg)}</span>`;
      if (meta) meta.textContent = 'Agent · 失败';
      refreshIcons();
    }

    async function loadDashboard() {
      try {
        const resp = await fetch(`/v1/workspaces/${encodeURIComponent(state.workspaceId)}/dashboard`, { headers: authHeaders() });
        const data = await resp.json();
        // 同步给 patches.js 缓存与红点（Sprint 2.1/2.2/2.4/2.6）
        if (typeof window.setPatchesCache === 'function') window.setPatchesCache(data.patches || []);
        if (typeof window.setBlockedTasksCache === 'function') window.setBlockedTasksCache((data.tasks || []).filter(tk => tk.status === 'blocked'));
        if (typeof window.updateKanbanBadge === 'function') {
          window.updateKanbanBadge();
        }
        // 看板 onboarding 解释卡（Sprint 2.4）
        const explainer = el('kanbanExplainer');
        const draftCount = (data.patches || []).filter(p => p.status === 'draft').length;
        if (explainer && (data.patches || []).length === 0) {
          explainer.classList.remove('hidden');
        } else if (explainer) {
          explainer.classList.add('hidden');
        }
        if (typeof window.clearPatchSelection === 'function') window.clearPatchSelection();
        const counts = data.counts || { todo: 0, in_progress: 0, blocked: 0, done: 0 };
        el('countTodo').textContent = counts.todo || 0;
        el('countInProgress').textContent = counts.in_progress || 0;
        el('countBlocked').textContent = counts.blocked || 0;
        el('countDone').textContent = counts.done || 0;
        el('badgeTodo').textContent = counts.todo || 0;
        el('badgeInProgress').textContent = counts.in_progress || 0;
        el('badgeBlocked').textContent = counts.blocked || 0;
        el('badgeDone').textContent = counts.done || 0;

        const lanes = {
          todo: el('laneTodo'),
          in_progress: el('laneInProgress'),
          blocked: el('laneBlocked'),
          done: el('laneDone'),
        };
        Object.values(lanes).forEach(lane => lane.innerHTML = '');
        const tasks = data.tasks || [];
        if (tasks.length === 0) {
          Object.values(lanes).forEach(lane => lane.innerHTML = '<p class="empty">无任务</p>');
        } else {
          tasks.forEach(task => {
            const lane = lanes[task.status] || lanes.todo;
            const card = document.createElement('div');
            card.className = 'task-card';
            card.innerHTML = `
              <div class="task-meta">
                <span class="mono">${escapeHtml(task.id)}</span>
                <span>${escapeHtml(task.owner || '未指派')}</span>
              </div>
              <div class="task-title">${escapeHtml(task.title)}</div>
              <div class="task-foot">
                <span>${task.updated_at ? escapeHtml(String(task.updated_at).substring(5, 16)) : ''}</span>
              </div>
            `;
            lane.appendChild(card);
          });
        }

        const patchTable = el('patchTableBody');
        const patches = data.patches || [];
        if (patches.length === 0) {
          patchTable.innerHTML = '<tr><td colspan="8" class="empty">暂无补丁，可在对话中下达任务生成草稿</td></tr>';
        } else {
          patchTable.innerHTML = patches.map(p => {
            let statusBadge = '<span class="badge badge-draft">Draft (草稿)</span>';
            if (p.status === 'applied') statusBadge = '<span class="badge badge-applied">Applied (已应用)</span>';
            else if (p.status === 'rolled_back') statusBadge = '<span class="badge badge-rolled">Rolled Back (已回滚)</span>';
            let actionBtns = '';
            if (p.status === 'draft') {
              actionBtns += `<button class="btn btn-sm btn-primary" onclick="confirmPatch('${p.id}')"><i data-lucide="check"></i>应用</button>`;
            } else if (p.status === 'applied') {
              actionBtns += `<button class="btn btn-sm btn-danger" onclick="rollbackPatch('${p.id}')"><i data-lucide="rotate-ccw"></i>回滚</button>`;
            }
            actionBtns += ` <button class="btn btn-sm" onclick="openPatchDiff('${p.id}')"><i data-lucide="eye"></i>影响</button>`;
            return `
              <tr>
                <td class="ta-c"><input class="patch-select-input" type="checkbox" onchange="window.togglePatchSelection && window.togglePatchSelection('${p.id}', this)" ${p.status === 'draft' || p.status === 'applied' ? '' : 'disabled'} /></td>
                <td class="cell-mono">${escapeHtml(p.id)}</td>
                <td>${escapeHtml(p.target_type)}</td>
                <td class="cell-mono">${escapeHtml(p.operation)}</td>
                <td class="cell-change" title="${escapeHtml(p.proposed_change)}">${escapeHtml(p.proposed_change)}</td>
                <td>${statusBadge}</td>
                <td class="cell-muted">${escapeHtml(p.created_by)}<span class="cell-sub">${p.created_at ? escapeHtml(String(p.created_at).substring(5, 16)) : ''}</span></td>
                <td class="ta-r">${actionBtns}</td>
              </tr>
            `;
          }).join('');
        }
        refreshIcons();
      } catch (err) {
        console.error('Load dashboard failed:', err);
      }
    }

    function confirmPatch(patchId) {
      askConfirm('确认应用补丁', `补丁 ${patchId} 将写入实体表并立即生效。`, async () => {
        try {
          const resp = await fetch(`/v1/patches/${encodeURIComponent(patchId)}/confirm`, {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ actor: state.userId })
          });
          const data = await resp.json();
          if (resp.ok) {
            toast(`补丁 ${patchId} 已成功应用`, 'success');
            loadDashboard();
            if (typeof window.refreshKanbanBadge === 'function') window.refreshKanbanBadge();
          } else {
            toast('确认失败：' + (data.error || '未知错误'), 'error');
          }
        } catch (err) {
          toast('网络异常：' + err.message, 'error');
        }
      });
    }

    function rollbackPatch(patchId) {
      askConfirm('回滚补丁', `补丁 ${patchId} 将被回滚并恢复原始状态。`, async () => {
        try {
          const resp = await fetch(`/v1/patches/${encodeURIComponent(patchId)}/rollback`, {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ actor: state.userId })
          });
          const data = await resp.json();
          if (resp.ok) {
            toast(`补丁 ${patchId} 已回滚`, 'success');
            loadDashboard();
            if (typeof window.refreshKanbanBadge === 'function') window.refreshKanbanBadge();
          } else {
            toast('回滚失败：' + (data.error || '未知错误'), 'error');
          }
        } catch (err) {
          toast('网络异常：' + err.message, 'error');
        }
      });
    }

    function confirmSync(sessionId) {
      askConfirm('确认同步草稿', `同步会话 ${sessionId} 中的任务提议将被确认并写入看板。`, async () => {
        try {
          const resp = await fetch(`/v1/sync/${encodeURIComponent(sessionId)}/confirm`, {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ actor: state.userId })
          });
          const data = await resp.json();
          if (resp.ok) {
            toast(`同步会话 ${sessionId} 已确认，新增 ${data.tasks.length} 项任务`, 'success');
            loadDashboard();
          } else {
            toast('确认失败：' + (data.error || '未知错误'), 'error');
          }
        } catch (err) {
          toast('网络异常：' + err.message, 'error');
        }
      });
    }

    async function loadLibrary() {
      try {
        const resp = await fetch('/v1/library/documents', { headers: authHeaders() });
        const data = await resp.json();
        const docs = data.documents || [];
        el('docCountBadge').textContent = `共 ${docs.length} 篇`;
        const listEl = el('documentList');
        if (docs.length === 0) {
          listEl.innerHTML = '<div class="empty-state"><p>知识库还是空的，先上传一份文档开始建立索引</p><button class="btn btn-sm" onclick="document.getElementById(\'fileUploadInput\').click()"><i data-lucide="cloud-upload"></i>上传文档</button></div>';
          refreshIcons();
          return;
        }
        listEl.innerHTML = docs.map(doc => `
          <div class="doc-row">
            <div class="doc-icon"><i data-lucide="file-text"></i></div>
            <div class="doc-main">
              <div class="doc-title">${escapeHtml(doc.title)}<span class="tag tag-neutral">${escapeHtml(doc.source || 'upload')}</span></div>
              <p class="doc-snippet">${escapeHtml(doc.content || '')}</p>
              <div class="doc-meta">
                <span>SHA256: ${escapeHtml(doc.content_hash || '').substring(0, 16)}...</span>
                <span>字数: ${doc.char_count || 0}</span>
              </div>
            </div>
          </div>
        `).join('');
        refreshIcons();
      } catch (err) {
        console.error('Load library failed:', err);
      }
    }

    async function uploadFile(file) {
      if (!file) return;
      const formData = new FormData();
      formData.append('file', file);
      formData.append('source', 'upload');
      try {
        const resp = await fetch('/v1/library/documents', {
          method: 'POST',
          headers: authHeaders(),
          body: formData
        });
        const data = await resp.json();
        if (resp.ok) {
          toast(`文件「${file.name}」录入成功`, 'success');
          loadLibrary();
        } else {
          toast('上传失败：' + (data.error || '未知错误'), 'error');
        }
      } catch (err) {
        toast('上传网络异常：' + err.message, 'error');
      }
    }

    function handleFileUpload(e) {
      uploadFile(e.target.files[0]);
      e.target.value = '';
    }

    async function handleTextDocumentIngest() {
      const title = el('docTitleInput').value.trim() || 'note.txt';
      const content = el('docContentInput').value.trim();
      if (!content) {
        toast('请输入文档内容', 'error');
        return;
      }
      try {
        const resp = await fetch('/v1/library/documents', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ filename: title, content, source: 'manual' })
        });
        const data = await resp.json();
        if (resp.ok) {
          toast(`文档「${title}」已录入知识库`, 'success');
          el('docTitleInput').value = '';
          el('docContentInput').value = '';
          loadLibrary();
        } else {
          toast('录入失败：' + (data.error || '未知错误'), 'error');
        }
      } catch (err) {
        toast('网络异常：' + err.message, 'error');
      }
    }

    async function searchLibrary() {
      const query = el('librarySearchInput').value.trim();
      if (!query) { loadLibrary(); return; }
      try {
        const resp = await fetch(`/v1/library/search?q=${encodeURIComponent(query)}&limit=10`, { headers: authHeaders() });
        const data = await resp.json();
        const results = data.results || [];
        const listEl = el('documentList');
        if (results.length === 0) {
          listEl.innerHTML = `<p class="empty">未找到匹配「${escapeHtml(query)}」的知识库片段</p>`;
          return;
        }
        listEl.innerHTML = `
          <div class="doc-row search-hit" style="border-bottom:1px solid var(--line);background:var(--accent-soft)">
            <div class="doc-main"><div class="doc-title">命中检索结果 (${results.length} 条)</div></div>
          </div>
          ${results.map(r => `
            <div class="doc-row search-hit">
              <div class="doc-icon"><i data-lucide="search"></i></div>
              <div class="doc-main">
                <div class="doc-title">[${escapeHtml(r.title)}]<span class="tag tag-mist">得分 ${r.score || 0}</span></div>
                <p class="doc-snippet">${escapeHtml(r.snippet)}</p>
              </div>
            </div>
          `).join('')}
        `;
        refreshIcons();
      } catch (err) {
        console.error('Search library failed:', err);
      }
    }

    async function loadUserMemories() {
      const q = el('memoryQueryInput').value.trim();
      try {
        const resp = await fetch(`/v1/users/${encodeURIComponent(state.userId)}/memory?q=${encodeURIComponent(q)}&limit=50`, { headers: authHeaders() });
        const data = await resp.json();
        if (resp.status === 401) { clearSession(); return; }
        const grid = el('memoryCardGrid');
        if (resp.status === 403) {
          grid.innerHTML = `<p class="empty" style="color:var(--terra)">${escapeHtml(data.error || '无权查看其他用户的记忆画像')}</p>`;
          return;
        }
        const memories = data.memories || [];
        if (memories.length === 0) {
          grid.innerHTML = q
            ? `<p class="empty">没有匹配「${escapeHtml(q)}」的记忆</p>`
            : `<div class="empty-state"><p>还没有长期记忆，先告诉 Agent 你的偏好，它会自动沉淀在这里</p><button class="btn btn-sm" onclick="switchTab('chat')"><i data-lucide="messages-square"></i>去对话</button></div>`;
          refreshIcons();
          return;
        }
        grid.innerHTML = memories.map(mem => `
          <div class="mem-row">
            <div class="mem-top">
              <span class="tag tag-sage">${escapeHtml(mem.category)}</span>
              <span class="mem-conf">
                <span class="conf-track"><span class="conf-fill" style="width:${Math.round((mem.confidence || 0) * 100)}%"></span></span>
                <strong>${(mem.confidence * 100).toFixed(0)}%</strong>
              </span>
            </div>
            <div class="mem-content">${escapeHtml(mem.content)}</div>
            <p class="mem-evidence">证据：&quot;${escapeHtml(mem.evidence || '')}&quot;</p>
            <div class="mem-foot">
              <span class="meta">出现次数 ${mem.occurrence_count} 次</span>
              <div class="mem-actions">
                <button class="btn btn-sm btn-icon" title="确认增强置信度" onclick="applyFeedback('${mem.id}', 'confirm')"><i data-lucide="thumbs-up"></i></button>
                <button class="btn btn-sm btn-icon" title="拒绝标记为无效" onclick="applyFeedback('${mem.id}', 'reject')"><i data-lucide="thumbs-down"></i></button>
                <button class="btn btn-sm btn-icon" title="编辑/纠正这条记忆" onclick="editMemory('${mem.id}', '${escapeHtml(mem.content).replace(/'/g, "&#39;")}')"><i data-lucide="pencil"></i></button>
                <button class="btn btn-sm btn-icon" title="彻底遗忘并抹除证据链" onclick="forgetMemory('${mem.id}')"><i data-lucide="trash-2"></i></button>
              </div>
            </div>
          </div>
        `).join('');
        refreshIcons();
      } catch (err) {
        console.error('Load memories failed:', err);
      }
    }

    async function applyFeedback(memoryId, feedbackType) {
      try {
        const resp = await fetch('/v1/feedback', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ user_id: state.userId, memory_id: memoryId, feedback_type: feedbackType })
        });
        const data = await resp.json();
        if (resp.ok) {
          if (feedbackType === 'confirm') state.memoryCited += 1;
          if (feedbackType === 'reject') state.memoryCorrected += 1;
          updateMemoryIndicator();
          toast('反馈已记录', 'success');
          loadUserMemories();
        } else {
          toast('反馈提交失败：' + (data.error || '未知错误'), 'error');
        }
      } catch (err) {
        toast('网络异常：' + err.message, 'error');
      }
    }

    async function editMemory(memoryId, currentContent) {
      const next = window.prompt('编辑这条记忆的内容：', currentContent || '');
      if (next === null) return;
      const trimmed = next.trim();
      if (!trimmed || trimmed === currentContent) return;
      try {
        const resp = await fetch(`/v1/users/${encodeURIComponent(state.userId)}/memory/${encodeURIComponent(memoryId)}`, {
          method: 'PATCH',
          headers: { ...authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: trimmed })
        });
        const data = await resp.json();
        if (resp.ok) {
          toast('记忆已更新', 'success');
          loadUserMemories();
        } else {
          toast('更新失败：' + (data.error || '未知错误'), 'error');
        }
      } catch (err) {
        toast('网络异常：' + err.message, 'error');
      }
    }

    function forgetMemory(memoryId) {
      askConfirm('彻底遗忘记忆', '此条记忆及相关证据链将被永久抹除，且不可恢复。', async () => {
        try {
          const resp = await fetch(`/v1/users/${encodeURIComponent(state.userId)}/memory/${encodeURIComponent(memoryId)}/forget`, {
            method: 'POST',
            headers: authHeaders()
          });
          const data = await resp.json();
          if (resp.ok && data.success) {
            toast('记忆已遗忘', 'success');
            loadUserMemories();
          } else {
            toast('遗忘操作未成功', 'error');
          }
        } catch (err) {
          toast('网络异常：' + err.message, 'error');
        }
      });
    }



    function secretHint(nodeId, meta) {
      const node = el(nodeId);
      if (!node) return;
      if (meta && meta.configured) node.textContent = `(已配置 ${meta.hint || ''})`;
      else node.textContent = '(未配置)';
    }

    function setVal(id, val) { const n = el(id); if (n) n.value = val; }
    async function loadAdminSettings() {
      if (!state.currentUser || state.currentUser.role !== 'admin') return;
      try {
        const resp = await fetch('/v1/admin/settings', { headers: authHeaders() });
        const data = await resp.json();
        if (!resp.ok) {
          const st = el('settingsStatus'); if (st) st.textContent = data.error || '读取配置失败';
          return;
        }
        const s = data.settings || {};
        setVal('cfgMemoryBackend', s.MEMORY_BACKEND || 'local');
        setVal('cfgMemoryMcpUrl', s.MEMORY_MCP_URL || '');
        setVal('cfgWebBackend', s.WEB_BACKEND || 'local');
        setVal('cfgWebMcpUrl', s.WEB_MCP_URL || '');
        setVal('cfgBaseUrl', s.BASE_URL || '');
        setVal('cfgCurrentModel', s.CURRENT_MODEL || '');
        setVal('cfgWebTimeout', s.WEB_SEARCH_TIMEOUT || '20');
        // secrets stay blank on purpose
        setVal('cfgMcpApiKey', '');
        setVal('cfgModelApiKey', '');
        secretHint('hintMcpKey', s.MCP_API_KEY);
        secretHint('hintModelKey', s.MODEL_API_KEY);
        const rt = data.runtime || {};
        const st2 = el('settingsStatus'); if (st2) st2.textContent = `当前生效：memory=${rt.memory_backend || '-'} / web=${rt.web_backend || '-'}；密钥留空表示不修改。`;
        refreshIcons();
      } catch (err) {
        const st3 = el('settingsStatus'); if (st3) st3.textContent = '读取配置异常：' + err.message;
      }
    }

    function collectSettingsPayload() {
      const payload = {
        MEMORY_BACKEND: el('cfgMemoryBackend').value,
        MEMORY_MCP_URL: el('cfgMemoryMcpUrl').value.trim(),
        WEB_BACKEND: el('cfgWebBackend').value,
        WEB_MCP_URL: el('cfgWebMcpUrl').value.trim(),
        BASE_URL: el('cfgBaseUrl').value.trim(),
        CURRENT_MODEL: el('cfgCurrentModel').value.trim(),
        WEB_SEARCH_TIMEOUT: el('cfgWebTimeout').value.trim(),
      };
      const mcpKey = el('cfgMcpApiKey').value.trim();
      const modelKey = el('cfgModelApiKey').value.trim();
      if (mcpKey) payload.MCP_API_KEY = mcpKey;
      if (modelKey) payload.MODEL_API_KEY = modelKey;
      return payload;
    }

    async function saveAdminSettings() {
      if (!state.currentUser || state.currentUser.role !== 'admin') return;
      const payload = collectSettingsPayload();
      try {
        const resp = await fetch('/v1/admin/settings', {
          method: 'PUT',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (!resp.ok) {
          toast(data.error || '保存失败', 'error');
          return;
        }
        toast('配置已保存并热更新', 'success');
        el('settingsTestOut').textContent = JSON.stringify(data, null, 2);
        await loadAdminSettings();
      } catch (err) {
        toast('保存异常：' + err.message, 'error');
      }
    }

    async function testSetting(target) {
      if (!state.currentUser || state.currentUser.role !== 'admin') return;
      el('settingsTestOut').textContent = `正在测试 ${target} ...`;
      try {
        const resp = await fetch('/v1/admin/settings/test', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ target, overrides: collectSettingsPayload() })
        });
        const data = await resp.json();
        el('settingsTestOut').textContent = JSON.stringify(data, null, 2);
        if (data.ok) toast(`${target} 测试通过`, 'success');
        else toast(`${target} 测试失败`, 'error');
      } catch (err) {
        el('settingsTestOut').textContent = String(err);
        toast('测试异常：' + err.message, 'error');
      }
    }

    async function loadPersonalityProfile() {
      const grid = el('personalityTraitGrid');
      if (!grid) return;
      try {
        const resp = await fetch(`/v1/users/${encodeURIComponent(state.userId)}/personality`, { headers: authHeaders() });
        const data = await resp.json();
        if (resp.status === 401) { clearSession(); return; }
        if (resp.status === 403) {
          el('personalityDisclaimer').textContent = data.error || '无权查看';
          grid.innerHTML = '';
          return;
        }
        renderPersonality(data);
        refreshIcons();
      } catch (err) {
        console.error('Load personality failed:', err);
        el('personalityDisclaimer').textContent = '画像加载失败：' + (err.message || 'unknown');
      }
    }

    // 从后端画像数据（/v1/users/{id}/personality 或对话响应 metadata.personality）渲染大五面板
    function renderPersonality(data) {
      const grid = el('personalityTraitGrid');
      if (!grid) return;
      const model = data.model || {};
      const samples = data.samples !== undefined ? data.samples : (data.scores ? Object.keys(data.scores).length : 0);
      const experimentalTag = model.experimental ? '（实验性）' : '';
      el('personalityBackend').textContent = (model.backend || 'heuristic') + (samples !== null ? ` · ${samples} 条样本` : '') + experimentalTag;
      el('personalityDisclaimer').textContent = model.disclaimer || '对话积累后生成估计，不是心理诊断。';
      // 解锁进度环（Sprint 1.4）
      if (typeof window.renderPersonalityUnlock === 'function') {
        window.renderPersonalityUnlock(samples || 0, model.backend || 'heuristic');
      }
      let traits = data.traits || [];
      // 对话响应只带 scores（无 traits 时按固定英文名渲染条形图）
      const scores = data.scores || {};
      const scoreKeys = Object.keys(scores);
      if (traits.length === 0 && scoreKeys.length > 0) {
        traits = scoreKeys.map(key => ({ zh: key, en: key, score: scores[key] }));
      }
      grid.innerHTML = traits.length ? traits.map(trait => {
        const pct = Math.round((trait.score || 0) * 100);
        return `
          <div class="trait">
            <div class="trait-name">${escapeHtml(trait.zh || trait.en || 'trait')}</div>
            <div class="bar"><div style="width:${pct}%"></div></div>
            <div class="trait-meta">
              <span>${escapeHtml(trait.en || '')}</span>
              <span class="mono">${pct}%</span>
            </div>
          </div>`;
      }).join('') : '<p class="muted-note">暂无足够样本生成画像</p>';
      const work = data.work_style || {};
      el('personalityThinking').textContent = work.thinking_label || '样本不足';
      el('personalityThinkingNote').textContent = work.thinking_note || '';
      el('personalityExecution').textContent = work.execution_label || '样本不足';
      el('personalityExecutionNote').textContent = work.execution_note || '';
      const play = data.playbook || {};
      el('personalityHeadline').textContent = play.headline || '今日秘书重点';
      el('personalityStrengths').innerHTML = (play.strengths || ['对话后再评估长处']).map(item => `<li>${escapeHtml(item)}</li>`).join('');
      el('personalityGaps').innerHTML = (play.gaps || ['对话后再评估短板']).map(item => `<li>${escapeHtml(item)}</li>`).join('');
      el('personalityFocus').innerHTML = (play.today_focus || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    }

    async function webSearch() {
      const query = el('webQueryInput').value.trim();
      if (!query) { toast('请输入搜索关键词', 'error'); return; }
      const listEl = el('webResultList');
      listEl.innerHTML = `<div class="empty-state"><p>正在联网检索「${escapeHtml(query)}」...</p></div>`;
      try {
        const resp = await fetch('/v1/web/search', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ query, limit: 8 })
        });
        const data = await resp.json();
        el('webEngineBadge').textContent = `通道: ${data.channel || 'none'}`;
        const results = data.results || [];
        if (data.error && results.length === 0) {
          listEl.innerHTML = `<div class="empty-state"><p style="color:var(--terra)">检索失败：${escapeHtml(data.error)}</p></div>`;
          return;
        }
        if (results.length === 0) {
          listEl.innerHTML = `<div class="empty-state"><p>未找到关于「${escapeHtml(query)}」的结果，换个说法试试？</p></div>`;
          return;
        }
        listEl.innerHTML = `
          ${data.answer ? `<div class="web-answer"><strong>AI 综合摘要</strong><div class="web-snippet">${escapeHtml(data.answer)}</div></div>` : ''}
          ${results.map((r, i) => `
            <div class="web-item">
              <div class="web-item-top">
                <a href="${escapeHtml(r.url || '#')}" target="_blank" rel="noopener">${escapeHtml(r.title || r.url || '未命名结果')}</a>
                <span class="tag tag-mist mono">${i + 1}. ${escapeHtml(r.source || 'web')}</span>
              </div>
              <div class="web-snippet">${escapeHtml(r.snippet || r.content || '')}</div>
              <div class="web-item-foot">
                <span class="url">${escapeHtml(r.url || '')}</span>
                <button class="btn btn-sm" onclick="webFetchUrl('${escapeHtml(r.url || '')}')"><i data-lucide="file-text"></i>读正文</button>
              </div>
            </div>
          `).join('')}
        `;
        refreshIcons();
      } catch (err) {
        listEl.innerHTML = `<div class="empty-state"><p style="color:var(--terra)">联网请求异常：${escapeHtml(err.message)}</p></div>`;
      }
    }

    async function webFetch() {
      const url = el('webUrlInput').value.trim();
      await webFetchUrl(url);
    }

    async function webFetchUrl(url) {
      if (!url) { toast('请输入网页链接', 'error'); return; }
      const listEl = el('webResultList');
      listEl.innerHTML = `<div class="empty-state"><p>正在读取 ${escapeHtml(url)} ...</p></div>`;
      try {
        const resp = await fetch('/v1/web/fetch', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ url })
        });
        const data = await resp.json();
        const content = data.content || '';
        if (data.error && !content) {
          listEl.innerHTML = `<div class="empty-state"><p style="color:var(--terra)">读取失败：${escapeHtml(data.error || 'unknown')}</p></div>`;
          return;
        }
        el('webEngineBadge').textContent = data.via ? `解析: ${data.via}` : '网页解析';
        el('webUrlInput').value = url;
        listEl.innerHTML = `
          <div class="web-item">
            <div class="web-item-top">
              <a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(url)}</a>
              <span class="tag tag-sage mono">正文 ${content.length} 字</span>
            </div>
            <pre class="web-content">${escapeHtml(content)}</pre>
          </div>
        `;
        refreshIcons();
      } catch (err) {
        listEl.innerHTML = `<div class="empty-state"><p style="color:var(--terra)">读取异常：${escapeHtml(err.message)}</p></div>`;
      }
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    document.addEventListener('DOMContentLoaded', () => {
      const wsEl = el('workspaceIdInput');
      wsEl.addEventListener('change', () => {
        state.workspaceId = wsEl.value.trim() || 'default';
        if (state.activeTab === 'kanban') loadDashboard();
        if (state.activeTab === 'overview') loadOverview();
      });
      el('streamToggle').addEventListener('change', () => {
        state.isStreaming = el('streamToggle').checked;
      });
      el('memoryIndicator').addEventListener('click', () => {
        el('memoryIndicatorPanel').classList.toggle('hidden');
      });
      document.addEventListener('click', (e) => {
        const panel = el('memoryIndicatorPanel');
        if (!panel.classList.contains('hidden') && !panel.contains(e.target) && !el('memoryIndicator').contains(e.target)) {
          panel.classList.add('hidden');
        }
      });

      const dropZone = el('dropZone');
      dropZone.addEventListener('click', () => el('fileUploadInput').click());
      dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('is-dragover'); });
      dropZone.addEventListener('dragleave', () => dropZone.classList.remove('is-dragover'));
      dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('is-dragover');
        const file = e.dataTransfer.files[0];
        if (file) uploadFile(file);
      });

      checkHealth();
      restoreSession();
      updateMemoryIndicator();
      initTheme();
      refreshIcons();
    });
  


