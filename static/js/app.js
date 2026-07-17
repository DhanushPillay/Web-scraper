/** Sniffer — small, accessible feed interactions. */

const $ = (selector, context = document) => context.querySelector(selector);
const $$ = (selector, context = document) => [...context.querySelectorAll(selector)];

const icons = {
  saved: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>',
  bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>',
  read: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
  unread: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
};

function toast(message, type = 'success') {
  const container = $('#toastContainer');
  if (!container) return;
  const item = document.createElement('div');
  item.className = `toast toast-${type}`;
  item.setAttribute('role', 'status');
  item.textContent = message;
  container.append(item);
  window.setTimeout(() => item.remove(), 3600);
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || data.error || 'Something went wrong');
  return data;
}

function setActionState(button, active, type) {
  button.classList.toggle('is-active', active);
  button.setAttribute('aria-pressed', String(active));
  button.title = type === 'bookmark'
    ? active ? 'Remove from saved' : 'Save article'
    : active ? 'Mark unread' : 'Mark read';
  button.querySelector('svg')?.remove();
  button.insertAdjacentHTML('afterbegin', type === 'bookmark'
    ? active ? icons.saved : icons.bookmark
    : active ? icons.read : icons.unread);
}

async function toggleArticleState(button, action) {
  const card = button.closest('[data-article-id]');
  if (!card || button.disabled) return;
  button.disabled = true;
  try {
    const endpoint = action === 'bookmark' ? '/bookmark' : '/toggle_read';
    const data = await request(endpoint, {
      method: 'POST',
      body: JSON.stringify({ article_id: Number(card.dataset.articleId) })
    });
    const active = data.status === (action === 'bookmark' ? 'saved' : 'read');
    setActionState(button, active, action);
    if (action === 'read') card.classList.toggle('is-read', active);
    toast(action === 'bookmark' ? active ? 'Added to your reading list' : 'Removed from saved' : active ? 'Marked as read' : 'Marked as unread');
  } catch (error) {
    toast(error.message || 'Could not update this article', 'error');
  } finally {
    button.disabled = false;
  }
}

function openSummary() {
  const modal = $('#summaryModal');
  modal?.classList.add('show');
  modal?.setAttribute('aria-hidden', 'false');
  document.body.classList.add('has-modal');
  window.setTimeout(() => $('[data-modal-close]', modal)?.focus(), 0);
}

function closeSummary() {
  const modal = $('#summaryModal');
  modal?.classList.remove('show');
  modal?.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('has-modal');
}

async function summarizeArticle(url) {
  const body = $('#summaryBody');
  const title = $('#summaryTitle');
  const readLink = $('#summaryReadLink');
  if (!body || !title || !readLink) return;

  title.textContent = 'Article summary';
  body.innerHTML = '<div class="tp-summary-loading"><span></span><p>Preparing a short summary…</p></div>';
  readLink.hidden = true;
  openSummary();
  try {
    const data = await request('/api/summarize', { method: 'POST', body: JSON.stringify({ url }) });
    title.textContent = data.title || 'Article summary';
    const safeSummary = document.createElement('div');
    safeSummary.textContent = data.summary || 'A summary was not available for this article.';
    body.replaceChildren(safeSummary);
    readLink.href = url;
    readLink.hidden = false;
  } catch (error) {
    body.textContent = error.message || 'Unable to summarize this article right now.';
  }
}

function initScrollTop() {
  const button = $('#scrollTop');
  if (!button) return;
  const update = () => button.classList.toggle('visible', window.scrollY > 420);
  window.addEventListener('scroll', update, { passive: true });
  button.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  update();
}

function initKeyboardSearch() {
  document.addEventListener('keydown', (event) => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName);
    if (event.key === '/' && !typing) {
      event.preventDefault();
      $('#searchInput')?.focus();
    }
    if (event.key === 'Escape') closeSummary();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  $('#scrapeForm')?.addEventListener('submit', () => {
    const overlay = $('#loadingOverlay');
    const progress = $('#loadingProgress');
    overlay?.classList.add('show');
    if (!progress) return;
    const steps = [
      [3000, 'Fetching articles from sources…'],
      [8000, 'Extracting article images…'],
      [16000, 'Almost ready…'],
    ];
    const start = Date.now();
    const id = setInterval(() => {
      const elapsed = Date.now() - start;
      for (const [ms, text] of steps) {
        if (elapsed >= ms) progress.textContent = text;
      }
      if (elapsed >= 20000) clearInterval(id);
    }, 1000);
  });
  document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-action]');
    if (action) {
      const type = action.dataset.action;
      if (type === 'bookmark' || type === 'read') toggleArticleState(action, type);
      if (type === 'summary') summarizeArticle(action.dataset.url);
      return;
    }
    if (event.target.closest('[data-modal-close]')) closeSummary();
    if (event.target === $('#summaryModal')) closeSummary();
  });
  initScrollTop();
  initKeyboardSearch();
});
