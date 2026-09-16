/* 向量空間與知識圖譜的畫法。
 *
 * 抽成獨立檔案是因為主畫面的抽屜和 /inspect 那一頁都要用 ——
 * 同一套邏輯複製兩份，改一邊忘另一邊是遲早的事。
 *
 * 依賴：頁面要先定義 $(id) 和 esc(text)，以及對應的 DOM 元素。
 * 沒有那些元素的頁面（例如只放圖譜的那一頁）會自己跳過。
 */

/* ══════════ 向量空間 ══════════ */

/* 為什麼要畫這張圖：學生以為「向量檢索會找到意思相近的」，
   直到看見中文教材和英文論文是兩團完全分開的東西 ——
   用中文問論文裡才有的概念，向量會把你拉去中文那一團。
   那不是 query 寫壞了，是空間本來就長這樣。 */

const VEC = { data: null, hot: new Set(), sel: null };
const VEC_COLORS = ['#F2B441', '#6FD3A8', '#8FA8FF', '#FF7A6B', '#C9A0FF', '#57C7D4',
                    '#E8905A', '#9BD45F', '#FF9FC4', '#7FD8B0', '#BFA76A', '#6FA8FF'];

function vecLoad() {
  $('vecStat').textContent = '載入中…';
  return fetch('/api/vecmap').then(r => r.json()).then(d => {
    VEC.data = d;
    vecPaint();
    vecStats();
  });
}

function vecStats() {
  const o = VEC.data.overview, m = VEC.data.map;
  $('vecStat').innerHTML =
    '<div>片段 <b>' + o.chunks + '</b></div>' +
    '<div>檔案 <b>' + o.files + '</b></div>' +
    '<div>維度 <b>' + (o.dims || '—') + '</b></div>' +
    '<div>store <b>' + esc(o.store) + '</b></div>' +
    '<div>字數中位數 <b>' + o.chars.p50 + '</b></div>' +
    '<div>補過脈絡 <b>' + o.with_context + '</b></div>';

  $('vecLegend').innerHTML = (m.files || []).map((f, i) =>
    '<span><i style="background:' + VEC_COLORS[i % VEC_COLORS.length] + '"></i>' +
    esc(f.split('/').pop()) + '</span>').join('');

  const parts = [];
  if (m.ok) parts.push('這兩個軸只解釋了 <b>' + (m.explained * 100).toFixed(1) +
    '%</b> 的變異 —— <b>這是一張 384 維的影子，不是真相。</b>圖上很近不代表檢索一定撈得到。');
  if (o.mean_similarity != null) parts.push('隨機兩塊的平均相似度是 <b>' + o.mean_similarity +
    '</b>。所以「相似度 0.85」本身沒有意義 —— 要比的是**相對排名**，不是絕對數字。');
  $('vecWarn').innerHTML = parts.join('<br><br>') || '';
}

function vecXY(pt, W, H, pad) {
  return [pad + (pt.x + 1) / 2 * (W - pad * 2), pad + (1 - (pt.y + 1) / 2) * (H - pad * 2)];
}

function vecPaint() {
  const cv = $('vecmap'), g = cv.getContext('2d');
  const W = cv.width, H = cv.height, pad = 18;
  g.clearRect(0, 0, W, H);

  // 底線：讓人看得出原點在哪，不然散點沒有參考系
  g.strokeStyle = 'rgba(139,150,179,.14)';
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(pad, H / 2); g.lineTo(W - pad, H / 2);
  g.moveTo(W / 2, pad); g.lineTo(W / 2, H - pad);
  g.stroke();

  const m = VEC.data && VEC.data.map;
  if (!m || !m.ok) {
    g.fillStyle = '#8B96B3';
    g.font = '14px system-ui';
    g.fillText(m ? m.why : '沒有資料', pad, H / 2);
    return;
  }

  m.points.forEach(pt => {
    const [x, y] = vecXY(pt, W, H, pad);
    const hot = VEC.hot.has(pt.id), sel = VEC.sel === pt.id;
    g.beginPath();
    g.arc(x, y, sel ? 6 : hot ? 5 : 2.6, 0, Math.PI * 2);
    g.fillStyle = VEC_COLORS[pt.f % VEC_COLORS.length];
    g.globalAlpha = (VEC.hot.size && !hot && !sel) ? 0.18 : 0.85;
    g.fill();
    if (hot || sel) {
      g.globalAlpha = 1;
      g.strokeStyle = sel ? '#EEF1F8' : '#F2B441';
      g.lineWidth = sel ? 2 : 1.5;
      g.stroke();
    }
  });
  g.globalAlpha = 1;
}

/** 找滑鼠底下最近的點。canvas 沒有 DOM，只能自己算距離。 */
function vecHit(ev) {
  const m = VEC.data && VEC.data.map;
  if (!m || !m.ok) return null;
  const cv = $('vecmap'), r = cv.getBoundingClientRect();
  const sx = cv.width / r.width, sy = cv.height / r.height;
  const mx = (ev.clientX - r.left) * sx, my = (ev.clientY - r.top) * sy;
  let best = null, bd = 14 * sx;
  m.points.forEach(pt => {
    const [x, y] = vecXY(pt, cv.width, cv.height, 18);
    const d = Math.hypot(x - mx, y - my);
    if (d < bd) { bd = d; best = pt; }
  });
  return best;
}

$('vecmap').onmousemove = ev => {
  const pt = vecHit(ev);
  let tip = document.querySelector('.vectip');
  if (!pt) { if (tip) tip.remove(); return; }
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'vectip';
    $('vecmap').parentNode.appendChild(tip);
  }
  const f = VEC.data.map.files[pt.f] || '';
  tip.innerHTML = '<div>' + esc(pt.h) + '</div><div class="p">' + esc(f) +
                  (pt.page ? ' · 第 ' + pt.page + ' 頁' : '') + '</div>';
  const r = $('vecmap').getBoundingClientRect();
  tip.style.left = Math.min(ev.clientX - r.left + 12, r.width - 170) + 'px';
  tip.style.top = (ev.clientY - r.top + 12) + 'px';
};
$('vecmap').onmouseleave = () => {
  const tip = document.querySelector('.vectip');
  if (tip) tip.remove();
};

$('vecmap').onclick = ev => {
  const pt = vecHit(ev);
  if (!pt) return;
  VEC.sel = pt.id;
  vecPaint();
  $('vecNb').textContent = '查鄰居中…';
  fetch('/api/neighbors?id=' + encodeURIComponent(pt.id) + '&k=6')
    .then(r => r.json())
    .then(d => {
      if (!d.ok) { $('vecNb').textContent = d.why; return; }
      $('vecNb').innerHTML = '<b>' + esc(pt.id) + '</b> 的鄰居：<br>' +
        d.neighbors.map(n => '　' + n.sim.toFixed(3) + '　' + esc(n.path) + '　' +
          esc(n.heading)).join('<br>') +
        '<br><br>鄰居如果來自完全不相干的檔案，那就是它把不該撈的東西拉進來的原因。';
    });
};

/* 上一題的答案引用了哪些片段 —— 把它們在空間裡點亮，
   一眼就看得出「這一題的證據是散在各處還是擠在一團」 */
$('vecCites').onclick = () => {
  const ids = [...document.querySelectorAll('#answer .cite')].map(c => c.dataset.id);
  if (!ids.length) {
    $('vecNb').textContent = '上一題還沒有答案，或答案裡沒有可點的出處。';
    return;
  }
  VEC.hot = new Set(ids);
  $('vecCites').classList.add('on');
  vecPaint();
  $('vecNb').innerHTML = '標了 <b>' + VEC.hot.size + '</b> 個引用到的片段。' +
    '擠成一團 = 證據都來自同一區；散開 = 這題真的需要跨文件。再按一次取消。';
  $('vecCites').onclick = () => {
    VEC.hot.clear(); VEC.sel = null;
    $('vecCites').classList.remove('on');
    $('vecNb').textContent = '';
    vecPaint();
    location.reload();     // 還原按鈕行為最省事的作法
  };
};

$('vecReload').onclick = () => { VEC.hot.clear(); VEC.sel = null; $('vecNb').textContent = ''; vecLoad(); };

/* ══════════ 知識圖譜 ══════════ */

/* 力導向布局自己寫 —— 不到 40 行，而且教室離線時 CDN 抓不到函式庫。
   彈簧把有邊的節點拉近、斥力把所有節點推開，跑個幾百步就會自己排開。 */

const GR = { data: null, pos: [], screen: [], timer: null, sel: null };

function gLoad() {
  $('gStat').textContent = '載入中…';
  return fetch('/api/graph').then(r => r.json()).then(d => {
    GR.data = d;
    gStats();
    if (d.subgraph && d.subgraph.ok) gLayout();
    else gBlank(d.describe.ok ? '圖裡還沒有跨檔關聯' : d.describe.why);
  });
}

function gBlank(why) {
  const g = $('graphmap').getContext('2d');
  g.clearRect(0, 0, $('graphmap').width, $('graphmap').height);
  g.fillStyle = '#8B96B3';
  g.font = '13px system-ui';
  g.fillText(why || '沒有圖', 20, 40);
  $('gTip').innerHTML =
    '沒有接圖也完全不影響其他功能。要接的話：<br>' +
    '<code>docker run -d --name neo4j-teach -p 7474:7474 -p 7687:7687 ' +
    '-e NEO4J_AUTH=neo4j/你的密碼 neo4j:5</code><br>' +
    '在 <code>.env</code> 設 <code>NEO4J_URI</code> / <code>NEO4J_PASSWORD</code>，' +
    '然後 <code>uv run python scripts/seed_neo4j.py</code>。';
}

function gStats() {
  const de = GR.data.describe, sg = GR.data.subgraph;
  if (!de.ok) { $('gStat').textContent = ''; $('gSchema').textContent = ''; return; }
  $('gStat').innerHTML =
    '<div>節點 <b>' + de.nodes + '</b></div><div>關係 <b>' + de.edges + '</b></div>' +
    '<div>畫出來 <b>' + (sg.ok ? sg.nodes.length : 0) + '</b></div>' +
    '<div>資料庫 <b>' + esc(de.database) + '</b></div>';
  $('gSchema').innerHTML =
    de.labels.map(l => '(<b>:' + esc(l.label) + '</b>) × ' + l.n).join('　') + '<br>' +
    de.relationships.map(r => '-[<b>:' + esc(r.type) + '</b>]-> × ' + r.n).join('　');
  if (sg.ok) {
    $('gLegend').innerHTML = sg.files.map((f, i) =>
      '<span><i style="background:' + VEC_COLORS[i % VEC_COLORS.length] + '"></i>' +
      esc(f.split('/').pop()) + '</span>').join('');
  }
}

/** 力導向（Fruchterman-Reingold）。

   第一版的斥力寫死 900/d²，121 個節點互推的總和遠大於彈簧和向心力，
   結果所有點都被推到邊界夾住，畫出來是一個空心矩形。
   FR 的重點是**斥力強度要隨節點密度縮放**：k = sqrt(面積 / 節點數)。 */
function gLayout(steps) {
  const sg = GR.data.subgraph;
  // 尺寸跟著畫布走 —— 抽屜裡是小張的，/inspect 那頁是大張的，同一套程式碼要都對
  const cvv = $('graphmap');
  const N = sg.nodes.length, W = cvv.width, H = cvv.height;
  if (!N) return;
  const k = Math.sqrt((W * H) / N) * 0.62;     // 理想間距
  const idx = {};
  sg.nodes.forEach((n, i) => { idx[n.id] = i; });

  // 起始位置照檔案分角度散開 —— 從隨機開始的話每次排出來差很多，講解會對不上
  GR.pos = sg.nodes.map((n, i) => {
    const a = (n.f / Math.max(1, sg.files.length)) * Math.PI * 2 + (i % 7) * 0.13;
    const r = 60 + (i % 11) * 7;
    return { x: W / 2 + Math.cos(a) * r, y: H / 2 + Math.sin(a) * r };
  });

  const E = sg.edges.map(e => [idx[e.a], idx[e.b]]).filter(([a, b]) => a != null && b != null);
  clearTimeout(GR.timer);
  let step = 0;
  const total = steps || 220;

  const tick = () => {
    for (let pass = 0; pass < 4 && step < total; pass++, step++) {
      const temp = (W / 12) * (1 - step / total);     // 降溫：一開始大步走，最後微調
      const dsp = GR.pos.map(() => ({ x: 0, y: 0 }));

      for (let a = 0; a < N; a++) {
        for (let b = a + 1; b < N; b++) {
          let dx = GR.pos[a].x - GR.pos[b].x, dy = GR.pos[a].y - GR.pos[b].y;
          let d = Math.hypot(dx, dy);
          if (d < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d = 0.01; }
          const f = (k * k) / d;                       // 斥力 ∝ k²/d
          dsp[a].x += dx / d * f; dsp[a].y += dy / d * f;
          dsp[b].x -= dx / d * f; dsp[b].y -= dy / d * f;
        }
      }
      E.forEach(([a, b]) => {
        const dx = GR.pos[a].x - GR.pos[b].x, dy = GR.pos[a].y - GR.pos[b].y;
        const d = Math.hypot(dx, dy) || 0.01;
        const f = (d * d) / k;                         // 引力 ∝ d²/k
        dsp[a].x -= dx / d * f; dsp[a].y -= dy / d * f;
        dsp[b].x += dx / d * f; dsp[b].y += dy / d * f;
      });

      for (let i = 0; i < N; i++) {
        const d = Math.hypot(dsp[i].x, dsp[i].y) || 0.01;
        const m = Math.min(d, temp);                   // 一步最多走 temp
        GR.pos[i].x += dsp[i].x / d * m;
        GR.pos[i].y += dsp[i].y / d * m;
        GR.pos[i].x += (W / 2 - GR.pos[i].x) * 0.012;  // 輕微向心，避免整團飄走
        GR.pos[i].y += (H / 2 - GR.pos[i].y) * 0.012;
        // 這裡**不夾邊界**。夾了的話密的地方會整排貼在邊上，畫出來是一個空心矩形 ——
        // 讓它自由排開，畫的時候再整團縮放進畫布（見 gFit）。
      }
    }
    gPaint();
    if (step < total) GR.timer = setTimeout(tick, 16);
  };
  tick();
}

/** 把整團座標縮放進畫布。模擬時不管邊界，畫的時候才對齊 —— 這樣才不會貼邊。 */
function gFit(cv, pad) {
  // 用 2%–98% 分位而不是最大最小：兩三個離群點就會把整團擠成一小坨，
  // 那是「縮放到極值」最典型的災情。離群的畫在邊上就好。
  const q = (a, t) => { const b = [...a].sort((u, v) => u - v);
    return b[Math.max(0, Math.min(b.length - 1, Math.round((b.length - 1) * t)))]; };
  const xs = GR.pos.map(p => p.x), ys = GR.pos.map(p => p.y);
  const x0 = q(xs, 0.02), x1 = q(xs, 0.98);
  const y0 = q(ys, 0.02), y1 = q(ys, 0.98);
  const sx = (cv.width - pad * 2) / Math.max(1, x1 - x0);
  const sy = (cv.height - pad * 2) / Math.max(1, y1 - y0);
  const sc = Math.min(sx, sy);
  const ox = pad + ((cv.width - pad * 2) - (x1 - x0) * sc) / 2;
  const oy = pad + ((cv.height - pad * 2) - (y1 - y0) * sc) / 2;
  const cl = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  return p => [cl(ox + (p.x - x0) * sc, 8, cv.width - 8),
               cl(oy + (p.y - y0) * sc, 8, cv.height - 8)];
}

function gPaint() {
  const sg = GR.data && GR.data.subgraph;
  if (!sg || !sg.ok || !GR.pos.length) return;
  const cv = $('graphmap'), g = cv.getContext('2d');
  g.clearRect(0, 0, cv.width, cv.height);
  const idx = {};
  sg.nodes.forEach((n, i) => { idx[n.id] = i; });
  const fit = gFit(cv, 16);
  GR.screen = GR.pos.map(fit);

  sg.edges.forEach(e => {
    const a = GR.screen[idx[e.a]], b = GR.screen[idx[e.b]];
    if (!a || !b) return;
    const hot = GR.sel && (e.a === GR.sel || e.b === GR.sel);
    g.strokeStyle = hot ? 'rgba(242,180,65,.85)' : 'rgba(111,211,168,.16)';
    g.lineWidth = hot ? 1.6 : 0.7;
    g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
  });

  sg.nodes.forEach((n, i) => {
    const p = GR.screen[i];
    g.beginPath();
    g.arc(p[0], p[1], GR.sel === n.id ? 6.5 : 3.4, 0, Math.PI * 2);
    g.fillStyle = VEC_COLORS[n.f % VEC_COLORS.length];
    g.fill();
    if (GR.sel === n.id) { g.strokeStyle = '#EEF1F8'; g.lineWidth = 2; g.stroke(); }
  });
}

function gHit(ev) {
  const sg = GR.data && GR.data.subgraph;
  if (!sg || !sg.ok || !GR.pos.length) return null;
  const cv = $('graphmap'), r = cv.getBoundingClientRect();
  const mx = (ev.clientX - r.left) * cv.width / r.width;
  const my = (ev.clientY - r.top) * cv.height / r.height;
  let best = null, bd = 12;
  (GR.screen || []).forEach((p, i) => {
    const d = Math.hypot(p[0] - mx, p[1] - my);
    if (d < bd) { bd = d; best = sg.nodes[i]; }
  });
  return best;
}

$('graphmap').onclick = ev => {
  const n = gHit(ev);
  if (!n) { GR.sel = null; gPaint(); $('gTip').textContent = ''; return; }
  GR.sel = n.id;
  gPaint();
  const sg = GR.data.subgraph;
  const links = sg.edges.filter(e => e.a === n.id || e.b === n.id);
  const others = links.map(e => {
    const o = sg.nodes.find(x => x.id === (e.a === n.id ? e.b : e.a));
    return '　' + e.score.toFixed(3) + '　' + esc(o ? o.path : '?') + '　' + esc(o ? o.heading : '');
  });
  $('gTip').innerHTML = '<b>' + esc(n.id) + '</b>　' + esc(n.heading) + '<br>' +
    '跨檔連到 <b>' + links.length + '</b> 塊：<br>' + others.join('<br>');
};
$('graphmap').onmousemove = ev => { $('graphmap').style.cursor = gHit(ev) ? 'pointer' : 'default'; };

$('gReheat').onclick = () => gLayout();
$('gReload').onclick = () => { GR.sel = null; $('gTip').textContent = ''; gLoad(); };
