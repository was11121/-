let memoryGraphInstance = null;

const MEMORY_CATEGORY_COLOR = {
  preference_like: '#5fbf5a',
  preference_dislike: '#c2542a',
  need: '#4a8fd6',
  identity: '#a86bea',
  boundary: '#e0a83a',
  instruction: '#3ad0c8',
  correction: '#e05a9a',
};

const MEMORY_CATEGORY_STYLE = {
  preference_like: 'marble',
  preference_dislike: 'rocky',
  need: 'bands',
  identity: 'rocky',
  boundary: 'bands',
  instruction: 'marble',
  correction: 'rocky',
};

async function loadMemoryGraph() {
  try {
    const resp = await fetch(`/v1/users/${encodeURIComponent(state.userId)}/memory/graph`, { headers: authHeaders() });
    if (resp.status === 401) { clearSession(); return; }
    const data = await resp.json();
    if (resp.status === 403) {
      const container = el('memoryGraphContainer');
      container.classList.add('hidden');
      const emptyEl = el('memoryGraphEmpty');
      emptyEl.classList.remove('hidden');
      emptyEl.innerHTML = `<p style="color:var(--terra)">${escapeHtml(data.error || '无权查看其他用户的记忆图谱')}</p>`;
      return;
    }
    renderMemoryGraph(data.nodes || [], data.links || []);
  } catch (err) {
    console.error('Load memory graph failed:', err);
  }
}

// ---- 宇宙背景（AI 生成的深空实拍风格素材） ----

function applySpaceBackground(THREE, scene, container) {
  const img = new Image();
  img.onload = () => {
    // 以 70% 不透明度把实拍图叠加在纯黑底上，压暗背景以突出前景的记忆行星
    const canvas = document.createElement('canvas');
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#020208';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.globalAlpha = 0.7;
    ctx.drawImage(img, 0, 0);

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const fitCover = () => {
      const canvasAspect = container.clientWidth / container.clientHeight;
      const imgAspect = img.width / img.height;
      if (canvasAspect > imgAspect) {
        texture.repeat.set(1, imgAspect / canvasAspect);
        texture.offset.set(0, (1 - imgAspect / canvasAspect) / 2);
      } else {
        texture.repeat.set(canvasAspect / imgAspect, 1);
        texture.offset.set((1 - canvasAspect / imgAspect) / 2, 0);
      }
    };
    fitCover();
    scene.background = texture;
    window.addEventListener('resize', fitCover);
  };
  img.src = '/static/redesign/vendor/space-bg.jpg';
}

// ---- 记忆行星 ----

function planetRadius(node) {
  const occ = node.occurrence_count || 1;
  const conf = node.confidence || 0.5;
  return 6 + Math.min(occ, 8) * 1.8 + conf * 3;
}

function makePlanetTexture(THREE, colorHex, style, seed) {
  const w = 256, h = 128;
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d');
  let rnd = seed;
  const rand = () => { rnd = (rnd * 9301 + 49297) % 233280; return rnd / 233280; };

  ctx.fillStyle = colorHex;
  ctx.fillRect(0, 0, w, h);

  const shade = (hex, amt) => {
    const c = parseInt(hex.slice(1), 16);
    let r = (c >> 16) + amt, g = ((c >> 8) & 0xff) + amt, b = (c & 0xff) + amt;
    r = Math.max(0, Math.min(255, r)); g = Math.max(0, Math.min(255, g)); b = Math.max(0, Math.min(255, b));
    return `rgb(${r},${g},${b})`;
  };

  if (style === 'bands') {
    const bandCount = 10 + Math.floor(rand() * 4);
    for (let i = 0; i < bandCount; i++) {
      const y = (i / bandCount) * h;
      const bh = h / bandCount;
      ctx.fillStyle = shade(colorHex, (rand() - 0.5) * 60);
      ctx.globalAlpha = 0.55 + rand() * 0.3;
      ctx.fillRect(0, y, w, bh * (0.6 + rand() * 0.6));
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = shade(colorHex, -70);
    ctx.beginPath();
    ctx.ellipse(w * 0.6, h * 0.5, w * 0.09, h * 0.06, 0, 0, Math.PI * 2);
    ctx.fill();
  } else if (style === 'rocky') {
    ctx.fillStyle = shade(colorHex, -25);
    ctx.fillRect(0, 0, w, h);
    const craters = 40;
    for (let i = 0; i < craters; i++) {
      const x = rand() * w, y = rand() * h, r = 2 + rand() * 7;
      ctx.fillStyle = shade(colorHex, -40 - rand() * 30);
      ctx.globalAlpha = 0.5;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = shade(colorHex, 30);
      ctx.globalAlpha = 0.3;
      ctx.beginPath(); ctx.arc(x - r * 0.3, y - r * 0.3, r * 0.5, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
  } else {
    for (let i = 0; i < 26; i++) {
      const x = rand() * w, y = rand() * h, rw = 12 + rand() * 34, rh = 4 + rand() * 8;
      ctx.fillStyle = shade(colorHex, rand() > 0.5 ? 40 + rand() * 30 : -30 - rand() * 30);
      ctx.globalAlpha = 0.25 + rand() * 0.25;
      ctx.beginPath();
      ctx.ellipse(x, y, rw, rh, rand() * Math.PI, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

function buildPlanetObject(THREE, node) {
  const color = MEMORY_CATEGORY_COLOR[node.category] || '#9aa0a8';
  const style = MEMORY_CATEGORY_STYLE[node.category] || 'rocky';
  const radius = planetRadius(node);
  const seed = Math.abs(hashString(node.id)) % 100000 || 1;
  const group = new THREE.Group();

  const texture = makePlanetTexture(THREE, color, style, seed);
  const core = new THREE.Mesh(
    new THREE.SphereGeometry(radius, 40, 40),
    new THREE.MeshStandardMaterial({
      map: texture, roughness: 0.75, metalness: 0.08,
      emissive: color, emissiveIntensity: 0.12,
    })
  );
  core.rotation.y = seed % Math.PI;
  group.add(core);

  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.3, 24, 24),
    new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: 0.22, side: THREE.BackSide,
      blending: THREE.AdditiveBlending, depthWrite: false,
    })
  );
  group.add(glow);

  if ((node.occurrence_count || 0) >= 3) {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(radius * 1.7, radius * 2.3, 56),
      new THREE.MeshBasicMaterial({
        color, transparent: true, opacity: 0.4, side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending, depthWrite: false,
      })
    );
    ring.rotation.x = Math.PI / 2.3;
    ring.rotation.z = (seed % 628) / 100;
    group.add(ring);
  }

  return group;
}

function hashString(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) { h = (h << 5) - h + str.charCodeAt(i); h |= 0; }
  return h;
}

function renderMemoryGraph(nodes, links) {
  const container = el('memoryGraphContainer');
  const emptyEl = el('memoryGraphEmpty');
  const infoPanel = el('memoryGraphInfoPanel');
  if (!nodes.length) {
    container.classList.add('hidden');
    infoPanel.classList.add('hidden');
    emptyEl.classList.remove('hidden');
    emptyEl.innerHTML = `<p>还没有可视化的记忆，先在对话中沉淀一些记忆吧</p><button class="btn btn-sm" onclick="switchTab('chat')"><i data-lucide="messages-square"></i>去对话</button>`;
    refreshIcons();
    return;
  }
  container.classList.remove('hidden');
  emptyEl.classList.add('hidden');

  const LINK_STYLE = {
    evidence: { color: '#f0b25a', width: 2.4, particles: 3 },
    category: { color: '#7fa7d6', width: 1.1, particles: 0 },
    related: { color: '#4a4f6a', width: 0.5, particles: 0 },
  };

  if (!memoryGraphInstance) {
    memoryGraphInstance = ForceGraph3D()(container)
      .width(container.clientWidth)
      .height(container.clientHeight)
      .backgroundColor('#020208')
      .nodeLabel(n => escapeHtml(n.label || ''))
      .nodeThreeObject(n => buildPlanetObject(THREE, n))
      .nodeThreeObjectExtend(false)
      .nodeVal(n => planetRadius(n))
      .linkColor(l => (LINK_STYLE[l.type] || LINK_STYLE.related).color)
      .linkWidth(l => (LINK_STYLE[l.type] || LINK_STYLE.related).width)
      .linkOpacity(0.65)
      .linkCurvature(0.2)
      .linkDirectionalParticles(l => (LINK_STYLE[l.type] || LINK_STYLE.related).particles)
      .linkDirectionalParticleWidth(1.8)
      .linkDirectionalParticleSpeed(0.006)
      .onNodeClick(showMemoryGraphInfo);

    memoryGraphInstance.d3Force('charge').strength(-200);

    const scene = memoryGraphInstance.scene();
    scene.add(new THREE.AmbientLight(0x252a4a, 0.55));
    const keyLight = new THREE.PointLight(0xfff2d0, 2.0, 6000, 1.2);
    keyLight.position.set(1400, 900, -1200);
    scene.add(keyLight);
    const rimLight = new THREE.PointLight(0x5a6fd8, 0.5, 4000);
    rimLight.position.set(-500, -300, 400);
    scene.add(rimLight);

    applySpaceBackground(THREE, scene, container);

    const controls = memoryGraphInstance.controls();
    if (controls) {
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.35;
    }

    window.addEventListener('resize', () => {
      if (memoryGraphInstance && state.activeTab === 'graph') {
        memoryGraphInstance.width(container.clientWidth).height(container.clientHeight);
      }
    });
  } else {
    memoryGraphInstance.width(container.clientWidth).height(container.clientHeight);
  }
  memoryGraphInstance.graphData({ nodes, links });
}

function showMemoryGraphInfo(node) {
  const panel = el('memoryGraphInfoPanel');
  panel.classList.remove('hidden');
  const contentEscaped = escapeHtml(node.label || '');
  panel.innerHTML = `
    <span class="tag tag-sage">${escapeHtml(node.category || '')}</span>
    <p>${contentEscaped}</p>
    <div class="confidence-bar" style="--pct:${Math.round((node.confidence || 0) * 100)}%"></div>
    <small class="muted-note">出现 ${node.occurrence_count || 0} 次</small>
    <div class="actions">
      <button class="btn btn-sm" onclick="applyFeedback('${node.id}', 'confirm')">确认</button>
      <button class="btn btn-sm" onclick="editMemory('${node.id}', '${contentEscaped.replace(/'/g, "&#39;")}')">编辑</button>
      <button class="btn btn-sm" onclick="forgetMemory('${node.id}')">遗忘</button>
    </div>`;
}
