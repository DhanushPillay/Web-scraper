/** Sniffer — drawer + SSE scrape + interactions (single source, XSS-safe) */
const $ = (s, c = document) => c.querySelector(s);

const summaryCache = new Map();
let lastFocus = null;

function toast(msg, type = 'success') {
  const c = $('#toastContainer');
  if (!c) return;
  const el = document.createElement('div');
  el.className = `toast${type === 'error' ? ' toast-error' : ''}`;
  el.textContent = msg;
  c.append(el);
  setTimeout(() => el.remove(), 3200);
}
window.toast = toast;

async function request(url, opts = {}, timeoutMs = 12000) {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, {
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', ...(opts.headers || {}) },
      ...opts,
      signal: ctrl.signal,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.message || d.error || 'Something went wrong');
    return d;
  } finally {
    clearTimeout(id);
  }
}

function openDrawer() {
  const d = $('#summaryDrawer'), o = $('#drawerOverlay');
  if (!d) return;
  lastFocus = document.activeElement;
  d.classList.add('is-open');
  o?.classList.add('is-open');
  d.setAttribute('aria-hidden', 'false');
  o?.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  setTimeout(() => $('[data-drawer-close]', d)?.focus(), 20);
}

function closeDrawer() {
  const d = $('#summaryDrawer'), o = $('#drawerOverlay');
  d?.classList.remove('is-open');
  o?.classList.remove('is-open');
  d?.setAttribute('aria-hidden', 'true');
  o?.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  if (lastFocus?.focus) lastFocus.focus();
}

async function summarizeArticle(url, titleHint) {
  const body = $('#drawerBody'), title = $('#drawerTitle'), meta = $('#drawerMeta'), link = $('#drawerLink');
  if (!body || !title) return;
  title.textContent = titleHint || 'Quick read';
  if (meta) meta.textContent = 'Fetching…';
  body.replaceChildren(Object.assign(document.createElement('div'), { className: 'sn-loader', textContent: 'Extracting summary…' }));
  if (link) { link.hidden = true; link.href = url; }
  openDrawer();
  try {
    let d = summaryCache.get(url);
    if (!d) {
      d = await request('/api/summarize', { method: 'POST', body: JSON.stringify({ url }) }, 15000);
      summaryCache.set(url, d);
    }
    title.textContent = d.title || titleHint || 'Quick read';
    if (meta) meta.textContent = `${d.read_time || 3}-min quick read`;
    const frag = document.createDocumentFragment();
    if (d.dek) {
      const p = document.createElement('p');
      p.className = 'sn-drawer-dek';
      p.textContent = d.dek;
      frag.append(p);
    } else if (d.summary) {
      const p = document.createElement('p');
      p.className = 'sn-drawer-dek';
      p.textContent = d.summary;
      frag.append(p);
    }
    const pts = (d.bullets || []).filter((b) => b && b !== d.dek).slice(0, 3);
    if (pts.length) {
      const label = document.createElement('div');
      label.className = 'sn-drawer-label';
      label.textContent = 'Key points';
      frag.append(label);
      const ul = document.createElement('ul');
      ul.className = 'sn-drawer-bullets';
      pts.slice(0, 2).forEach((b) => {
        const li = document.createElement('li');
        li.textContent = b;
        ul.append(li);
      });
      frag.append(ul);
      if (pts[2]) {
        const why = document.createElement('div');
        why.className = 'sn-why';
        const wl = document.createElement('div');
        wl.className = 'sn-drawer-label';
        wl.textContent = 'Why it matters';
        const wp = document.createElement('p');
        wp.textContent = pts[2];
        why.append(wl, wp);
        frag.append(why);
      }
    }
    if (!frag.childNodes.length) frag.append(Object.assign(document.createElement('p'), { textContent: 'Could not extract a summary.' }));
    body.replaceChildren(frag);
    if (link) { link.href = url; link.hidden = false; }
  } catch (e) {
    body.replaceChildren(Object.assign(document.createElement('p'), { textContent: e.message || 'Unable to summarize — try opening the article directly.' }));
  }
}

function initScrapeSSE() {
  const form = $('#scrapeForm');
  const overlay = $('#scrapeOverlay');
  const stage = $('#scrapeStage');
  const fill = $('#scrapeProgressFill');
  const pct = $('#scrapePct');
  if (!form || !overlay) return;
  let target = 0;
  let raf = 0;
  const paint = () => {
    if (!fill) return;
    const cur = parseFloat(fill.style.width) || 0;
    const next = cur + (target - cur) * 0.2;
    fill.style.width = `${Math.abs(target - next) < 0.5 ? target : next}%`;
    if (pct) pct.textContent = `${Math.round(parseFloat(fill.style.width) || 0)}%`;
    if (Math.abs(target - cur) > 0.5) raf = requestAnimationFrame(paint);
  };
  const setProgress = (p) => {
    target = p;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(paint);
  };
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    overlay.classList.add('show');
    if (stage) stage.textContent = 'Connecting to sources...';
    setProgress(0);
    try {
      const res = await fetch('/api/scrape', { method: 'POST' });
      const ctype = res.headers.get('content-type') || '';
      if (!res.ok || !ctype.includes('text/event-stream')) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.message || d.error || `Scrape failed (${res.status})`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.stage && stage) stage.textContent = evt.stage === 'Done' ? `Done — ${evt.total || ''} stories loaded` : evt.stage;
            if (evt.progress !== undefined) setProgress(evt.progress);
            if (evt.error) throw new Error(evt.stage || 'Scrape failed');
          } catch (_) { /* keep streaming */ }
        }
      }
      setProgress(100);
      setTimeout(() => { window.location.href = '/'; }, 400);
    } catch (err) {
      if (stage) stage.textContent = `Scrape failed: ${err.message || 'unknown error'}`;
      setTimeout(() => { window.location.href = '/'; }, 2500);
    }
  });
}

function initReveal() {
  const els = document.querySelectorAll('.reveal');
  if (!els.length) return;
  if (!('IntersectionObserver' in window)) { els.forEach((el) => el.classList.add('is-in')); return; }
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en, i) => {
      if (en.isIntersecting) {
        en.target.style.transitionDelay = `${Math.min(i * 60, 180)}ms`;
        en.target.classList.add('is-in');
        io.unobserve(en.target);
      }
    });
  }, { threshold: 0.08 });
  els.forEach((el) => io.observe(el));
}

function initScrollTop() {
  const b = $('#scrollTop');
  if (!b) return;
  let ticking = false;
  const upd = () => {
    b.classList.toggle('visible', window.scrollY > 350);
    ticking = false;
  };
  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; requestAnimationFrame(upd); }
  }, { passive: true });
  b.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  upd();
}

function initKeys() {
  document.addEventListener('keydown', (e) => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); $('#searchInput')?.focus(); }
    if (e.key === 'Escape') closeDrawer();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  document.addEventListener('click', async (e) => {
    const closer = e.target.closest('[data-drawer-close]');
    if (closer) { closeDrawer(); return; }
    if (e.target.id === 'drawerOverlay') { closeDrawer(); return; }
    const a = e.target.closest('[data-action]');
    if (!a) return;
    const t = a.dataset.action;
    if (t === 'summary') {
      e.preventDefault();
      const card = a.closest('[data-article-id]');
      const fallback = card?.querySelector('.sn-article-title')?.textContent?.trim();
      summarizeArticle(a.dataset.url, a.dataset.title || fallback);
    } else if (t === 'bookmark') {
      e.preventDefault();
      const id = Number(a.dataset.id || a.closest('[data-article-id]')?.dataset.articleId);
      if (!id || a.disabled) return;
      a.disabled = true;
      try {
        const d = await request('/bookmark', { method: 'POST', body: JSON.stringify({ article_id: id }) });
        const saved = d.status === 'saved';
        a.setAttribute('aria-pressed', String(saved));
        a.textContent = saved ? 'Saved' : 'Save';
        toast(saved ? 'Saved' : 'Removed');
      } catch (err) { toast(err.message || 'Could not update', 'error'); }
      finally { a.disabled = false; }
    }
  });
  initScrapeSSE();
  initReveal();
  initScrollTop();
  initKeys();
});
