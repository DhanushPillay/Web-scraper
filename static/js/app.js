/**
 * Sniffer — Client-side Interactions
 * Vanilla JS, no frameworks, progressive enhancement
 */

// ============================================================================
// Utility Functions
// ============================================================================

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

const createToast = (message, type = 'success') => {
  const container = $('#toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', 'alert');
  toast.setAttribute('aria-live', 'polite');

  const icons = {
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
  };

  toast.innerHTML = `${icons[type]}<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'slideIn 0.3s ease reverse';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
};

const showLoading = (btn, originalHTML) => {
  btn.dataset.originalHTML = originalHTML || btn.innerHTML;
  btn.innerHTML = '<span class="spinner" style="width:18px;height:18px;border:2px solid var(--border-muted);border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite"></span>';
  btn.disabled = true;
};

const hideLoading = (btn) => {
  btn.innerHTML = btn.dataset.originalHTML || '';
  btn.disabled = false;
  delete btn.dataset.originalHTML;
};

const debounce = (fn, delay) => {
  let id;
  return (...args) => {
    clearTimeout(id);
    id = setTimeout(() => fn(...args), delay);
  };
};

// ============================================================================
// API Calls
// ============================================================================

const api = {
  async request(url, options = {}) {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  },

  bookmark(id) {
    return this.request('/bookmark', { method: 'POST', body: JSON.stringify({ article_id: id }) });
  },

  toggleRead(id) {
    return this.request('/toggle_read', { method: 'POST', body: JSON.stringify({ article_id: id }) });
  },

  summarize(url) {
    return this.request('/api/summarize', { method: 'POST', body: JSON.stringify({ url }) });
  },

  personalized() {
    return this.request('/api/personalized');
  },

  subscribe(email) {
    return this.request('/subscribe', { method: 'POST', body: JSON.stringify({ email }) });
  },

  loadMore(params) {
    const qs = new URLSearchParams(params).toString();
    return this.request(`/?${qs}`, { headers: { 'X-Requested-With': 'fetch' } });
  }
};

// ============================================================================
// Article Interactions
// ============================================================================

async function toggleBookmark(articleId, btn) {
  const originalHTML = btn.innerHTML;
  showLoading(btn, originalHTML);

  try {
    const data = await api.bookmark(articleId);
    const isSaved = data.status === 'saved';

    btn.classList.toggle('active', isSaved);
    btn.setAttribute('aria-label', isSaved ? 'Remove bookmark' : 'Bookmark');
    btn.title = isSaved ? 'Remove bookmark' : 'Bookmark';

    // Update icon
    btn.innerHTML = isSaved
      ? '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';

    createToast(isSaved ? 'Article saved' : 'Bookmark removed', 'success');
  } catch (err) {
    console.error(err);
    btn.innerHTML = originalHTML;
    btn.disabled = false;
    createToast('Failed to update bookmark', 'error');
  }
}

async function toggleRead(articleId, btn) {
  const originalHTML = btn.innerHTML;
  showLoading(btn, originalHTML);

  try {
    const data = await api.toggleRead(articleId);
    const isRead = data.status === 'read';

    const card = btn.closest('.article-card');
    card.classList.toggle('is-read', isRead);
    btn.classList.toggle('read-active', isRead);
    btn.setAttribute('aria-label', isRead ? 'Mark as unread' : 'Mark as read');
    btn.title = isRead ? 'Mark as unread' : 'Mark as read';

    btn.innerHTML = isRead
      ? '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';

    createToast(isRead ? 'Marked as read' : 'Marked as unread', 'success');
  } catch (err) {
    console.error(err);
    btn.innerHTML = originalHTML;
    btn.disabled = false;
    createToast('Failed to update read status', 'error');
  }
}

async function summarizeArticle(url) {
  const modal = $('#summaryModal');
  const body = $('#summaryBody');
  const titleEl = $('#summaryTitle');
  const readLink = $('#summaryReadLink');

  if (!modal || !body) return;

  // Reset modal content
  body.innerHTML = `
    <div style="text-align: center; padding: var(--space-6);">
      <div class="skeleton-title" style="width: 60px; height: 60px; border-radius: 50%; margin: 0 auto var(--space-4);"></div>
      <p style="color: var(--text-secondary); margin: 0;">Generating AI summary…</p>
    </div>
  `;
  readLink.style.display = 'none';

  openModal(modal);

  try {
    const data = await api.summarize(url);

    if (data.error) {
      body.innerHTML = `<div style="padding: var(--space-4); background: var(--danger-bg); border: 1px solid var(--danger); border-radius: 8px; color: var(--danger);">${data.error}</div>`;
      return;
    }

    titleEl.textContent = data.title || 'Summary';

    let html = '';
    if (data.top_image) {
      html += `<img src="${data.top_image}" alt="" style="max-width:100%;height:auto;border-radius:8px;margin-bottom:var(--space-4);">`;
    }
    html += `<div style="line-height: var(--leading-relaxed);">${data.summary}</div>`;
    body.innerHTML = html;

    readLink.href = url;
    readLink.style.display = 'inline-flex';
  } catch (err) {
    console.error(err);
    body.innerHTML = `<div style="padding: var(--space-4); background: var(--danger-bg); border: 1px solid var(--danger); border-radius: 8px; color: var(--danger);">Failed to generate summary. Please try again.</div>`;
  }
}

// ============================================================================
// Modal Management
// ============================================================================

function openModal(modal) {
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';
  // Focus first focusable element
  setTimeout(() => {
    const focusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    focusable?.focus();
  }, 100);
}

function closeModal(modal) {
  modal.classList.remove('open');
  document.body.style.overflow = '';
}

function closeSummaryModal() {
  closeModal($('#summaryModal'));
}

function closeShortcutsHelp() {
  closeModal($('#shortcutsHelp'));
}

// Close modal on overlay click
$$('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeModal(overlay);
  });
});

// Close modal on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    $$('.modal-overlay.open').forEach(closeModal);
  }
});

// ============================================================================
// Load More Articles (Infinite Scroll Alternative)
// ============================================================================

async function loadMoreArticles() {
  const btn = $('#loadMoreBtn');
  if (!btn || btn.disabled) return;

  const params = {
    page: btn.dataset.nextPage,
    sort: btn.dataset.sort,
    source: btn.dataset.source,
    keyword: btn.dataset.keyword,
    category: btn.dataset.category,
    saved_only: btn.dataset.savedOnly
  };

  const btnText = btn.querySelector('.btn-text');
  const spinner = btn.querySelector('.spinner');
  const originalText = btnText.textContent;

  btn.disabled = true;
  btnText.textContent = 'Loading…';
  spinner.style.display = 'block';

  try {
    const data = await api.loadMore(params);

    if (data.articles && data.articles.length > 0) {
      const list = $('.articles-list');
      data.articles.forEach(article => {
        const card = renderArticleCard(article);
        list.appendChild(card);
      });

      // Update button for next page
      btn.dataset.nextPage = parseInt(btn.dataset.nextPage) + 1;
      btnText.textContent = originalText;
      spinner.style.display = 'none';
      btn.disabled = false;

      // Hide button if no more pages
      if (data.articles.length < 30) {
        btn.style.display = 'none';
      }
    } else {
      btn.style.display = 'none';
    }
  } catch (err) {
    console.error(err);
    btnText.textContent = 'Retry';
    spinner.style.display = 'none';
    btn.disabled = false;
    createToast('Failed to load more articles', 'error');
  }
}

function renderArticleCard(article) {
  const template = document.createElement('template');
  const sourceColors = {
    'Hacker News': '#ff6600',
    'TechCrunch': '#00a3e0',
    'Reddit': '#ff4500',
    'The Verge': '#e01e5a',
    'Ars Technica': '#00b4d8'
  };
  const sourceColor = sourceColors[article.source] || '#52525b';

  template.innerHTML = `
    <article class="article-card ${article.is_read ? 'is-read' : ''} ${article.excerpt ? 'has-excerpt' : ''}"
             id="article-${article.id}"
             style="--source-color: ${sourceColor}"
             data-article-id="${article.id}"
             data-source="${article.source}">

      <div class="article-content">
        <h2 class="article-title">
          <a href="${article.link}" target="_blank" rel="noopener noreferrer">${escapeHtml(article.title)}</a>
        </h2>

        ${article.excerpt ? `<p class="article-excerpt">${escapeHtml(article.excerpt)}</p>` : ''}

        <div class="article-meta">
          <span class="source-badge">
            <span style="width: 8px; height: 8px; border-radius: 50%; background: ${sourceColor}; flex-shrink: 0;"></span>
            ${escapeHtml(article.source)}
          </span>

          <span class="meta-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
            <span class="tabular-nums">${article.score || 0}</span>
          </span>

          <span class="meta-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span class="tabular-nums">${article.comments || '0'}</span>
          </span>

          ${article.category && article.category !== 'general' && article.category !== 'General'
            ? `<span class="category-badge">${escapeHtml(article.category)}</span>`
            : ''}

          ${article.sentiment && article.sentiment !== 'neutral'
            ? `<span class="sentiment-badge sentiment-${article.sentiment}">${article.sentiment === 'positive' ? 'Positive' : 'Negative'}</span>`
            : ''}

          ${article.read_time
            ? `<span class="read-time">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                ${article.read_time} min
              </span>`
            : ''}
        </div>
      </div>

      <div class="article-actions">
        <button class="icon-btn ${article.is_saved ? 'active' : ''}"
                onclick="toggleBookmark(${article.id}, this)"
                aria-label="${article.is_saved ? 'Remove bookmark' : 'Bookmark'}"
                title="${article.is_saved ? 'Remove bookmark' : 'Bookmark'}">
          <svg viewBox="0 0 24 24" fill="${article.is_saved ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
        </button>

        <button class="icon-btn ${article.is_read ? 'read-active' : ''}"
                onclick="toggleRead(${article.id}, this)"
                aria-label="${article.is_read ? 'Mark as unread' : 'Mark as read'}"
                title="${article.is_read ? 'Mark as unread' : 'Mark as read'}">
          <svg viewBox="0 0 24 24" fill="${article.is_read ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        </button>

        <button class="icon-btn"
                onclick="summarizeArticle('${escapeHtml(article.link)}')"
                aria-label="AI Summary"
                title="AI Summary">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
        </button>
      </div>
    </article>
  `;

  return template.content.firstElementChild;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============================================================================
// Personalized Feed
// ============================================================================

async function fetchPersonalized() {
  const btn = $('#personalizedBtn');
  if (!btn) return;

  const originalHTML = btn.innerHTML;
  showLoading(btn, originalHTML);

  try {
    const data = await api.personalized();
    if (data.articles && data.articles.length > 0) {
      createToast(`Found ${data.articles.length} personalized recommendations`, 'success');
      // Could replace the article list here, for now just notify
    } else {
      createToast('Bookmark some articles first to get personalized recommendations', 'success');
    }
  } catch (err) {
    console.error(err);
    createToast('Failed to load personalized feed', 'error');
  } finally {
    btn.innerHTML = originalHTML;
    btn.disabled = false;
  }
}

// ============================================================================
// Subscribe Form
// ============================================================================

function initSubscribeForm() {
  const form = $('#subscribeForm');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = $('#subscribeEmail');
    const msg = $('#subscribeMessage');
    const email = input.value.trim();

    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      msg.textContent = 'Please enter a valid email address';
      msg.style.color = 'var(--danger)';
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = 'Subscribing…';

    try {
      await api.subscribe(email);
      msg.textContent = 'Subscribed successfully!';
      msg.style.color = 'var(--success)';
      form.reset();
    } catch (err) {
      msg.textContent = err.message || 'Subscription failed';
      msg.style.color = 'var(--danger)';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = originalText;
    }
  });
}

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

function initKeyboardShortcuts() {
  const helpModal = $('#shortcutsHelp');
  let focusedCardIndex = -1;
  const cards = () => $$('.article-card:not(.skeleton)');

  document.addEventListener('keydown', (e) => {
    // Don't trigger shortcuts when typing in inputs
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.target.isContentEditable) {
      if (e.key !== 'Escape') return;
    }

    switch (e.key) {
      case '?':
        if (e.shiftKey) {
          e.preventDefault();
          openModal(helpModal);
        }
        break;

      case '/':
        e.preventDefault();
        const searchInput = $('#scrapeForm input[name="keyword"], .search-input');
        searchInput?.focus();
        break;

      case 'j':
      case 'ArrowDown':
        e.preventDefault();
        navigateCards(1);
        break;

      case 'k':
      case 'ArrowUp':
        e.preventDefault();
        navigateCards(-1);
        break;

      case 'o':
      case 'Enter':
        if (focusedCardIndex >= 0) {
          e.preventDefault();
          const card = cards()[focusedCardIndex];
          const link = card?.querySelector('.article-title a');
          link?.click();
        }
        break;

      case 'b':
        if (focusedCardIndex >= 0) {
          e.preventDefault();
          const card = cards()[focusedCardIndex];
          const btn = card?.querySelector('.icon-btn.active, .icon-btn:not(.read-active):first-of-type');
          btn?.click();
        }
        break;

      case 'r':
        if (focusedCardIndex >= 0) {
          e.preventDefault();
          const card = cards()[focusedCardIndex];
          const btn = card?.querySelector('.icon-btn.read-active, .icon-btn:not(.active):nth-of-type(2)');
          btn?.click();
        }
        break;

      case 'Escape':
        closeModal(helpModal);
        closeModal($('#summaryModal'));
        closeModal($('#commandPalette'));
        break;

      case 't':
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        e.preventDefault();
        $('#themeToggle')?.click();
        break;
    }
  });

  function navigateCards(direction) {
    const allCards = cards();
    if (!allCards.length) return;

    // Remove previous focus
    allCards.forEach(c => c.classList.remove('focused'));

    focusedCardIndex = Math.max(0, Math.min(allCards.length - 1, focusedCardIndex + direction));
    const card = allCards[focusedCardIndex];
    card.classList.add('focused');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Track focus on card click/hover
  document.addEventListener('mouseover', (e) => {
    const card = e.target.closest('.article-card');
    if (card) {
      const allCards = cards();
      focusedCardIndex = allCards.indexOf(card);
      allCards.forEach(c => c.classList.remove('focused'));
      card.classList.add('focused');
    }
  });
}

// ============================================================================
// Scroll to Top
// ============================================================================

function initScrollTop() {
  const btn = $('#scrollTop');
  if (!btn) return;

  const toggle = () => {
    btn.classList.toggle('visible', window.scrollY > 400);
  };

  window.addEventListener('scroll', debounce(toggle, 100), { passive: true });
  toggle();
}

// ============================================================================
// Theme Toggle
// ============================================================================

function initThemeToggle() {
  const toggle = document.createElement('button');
  toggle.className = 'theme-toggle';
  toggle.setAttribute('aria-label', 'Toggle dark/light mode');
  toggle.innerHTML = `
    <svg class="moon-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
    <svg class="sun-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <circle cx="12" cy="12" r="5"/>
      <line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
      <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
    </svg>
  `;

  toggle.addEventListener('click', () => {
    const html = document.documentElement;
    const isDark = html.getAttribute('data-theme') !== 'light';
    html.setAttribute('data-theme', isDark ? 'light' : 'dark');
    localStorage.setItem('theme', isDark ? 'light' : 'dark');
  });

  // Load saved theme
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const initialTheme = savedTheme || (prefersDark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', initialTheme);

  // Add to navbar
  const navbarActions = $('.nav-actions');
  if (navbarActions) {
    navbarActions.insertBefore(toggle, navbarActions.firstChild);
  }
}

// ============================================================================
// Search Form Enhancement
// ============================================================================

function initSearchForm() {
  const form = $('#scrapeForm');
  if (!form) return;

  // Sync URL with form state
  const urlParams = new URLSearchParams(window.location.search);
  const keywordInput = form.querySelector('input[name="keyword"]');
  const sourceSelect = form.querySelector('select[name="source"]');
  const sortSelect = form.querySelector('select[name="sort"]');

  if (keywordInput && urlParams.get('keyword')) {
    keywordInput.value = urlParams.get('keyword');
  }
  if (sourceSelect && urlParams.get('source')) {
    sourceSelect.value = urlParams.get('source');
  }
  if (sortSelect && urlParams.get('sort')) {
    sortSelect.value = urlParams.get('sort');
  }

  // Show loading overlay on submit
  form.addEventListener('submit', () => {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.classList.add('show');
  });
}

// ============================================================================
// Loading Overlay Cleanup
// ============================================================================

function hideLoadingOverlay() {
  const overlay = document.getElementById('loadingOverlay');
  if (overlay) {
    overlay.classList.remove('show');
  }
}

// ============================================================================
// Filter Toggle — Progressive Disclosure
// ============================================================================

function initFilterToggle() {
  const toggle = $('#filterToggle');
  const advanced = $('#advancedFilters');
  if (!toggle || !advanced) return;

  // Check if any advanced filter is active
  const urlParams = new URLSearchParams(window.location.search);
  const hasAdvanced = urlParams.get('category') || urlParams.get('sort') || urlParams.get('saved_only');
  if (hasAdvanced) {
    toggle.setAttribute('aria-expanded', 'true');
    advanced.setAttribute('aria-hidden', 'false');
    advanced.classList.add('open');
  }

  toggle.addEventListener('click', () => {
    const isExpanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', !isExpanded);
    advanced.setAttribute('aria-hidden', isExpanded);
    advanced.classList.toggle('open');
  });
}

// ============================================================================
// Density Toggle — Compact / Comfortable / Spacious
// ============================================================================

function initDensityToggle() {
  const toggle = $('.density-toggle');
  if (!toggle) return;

  const savedDensity = localStorage.getItem('density') || 'comfortable';
  document.body.classList.add(`density-${savedDensity}`);
  toggle.querySelectorAll('.density-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.density === savedDensity);
  });

  toggle.addEventListener('click', (e) => {
    const btn = e.target.closest('.density-btn');
    if (!btn) return;

    const density = btn.dataset.density;
    document.body.classList.remove('density-compact', 'density-comfortable', 'density-spacious');
    document.body.classList.add(`density-${density}`);
    localStorage.setItem('density', density);

    toggle.querySelectorAll('.density-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
}

// ============================================================================
// Source Health Badges — Dropdown Content
// ============================================================================

function renderSourceHealth(sources) {
  if (!sources || !sources.length) return '';

  return sources.map(s => {
    const statusClass = s.status === 'ok' ? 'ok' : s.status === 'error' ? 'error' : 'idle';
    const lastScrape = s.last_scrape
      ? new Date(s.last_scrape * 1000).toLocaleTimeString()
      : 'Never';
    return `
      <div class="source-health-item">
        <span class="source-health-dot ${statusClass}"></span>
        <span class="source-health-name">${escapeHtml(s.source)}</span>
        <span class="source-health-time">${lastScrape}</span>
      </div>
    `;
  }).join('');
}

async function loadSourceHealth() {
  try {
    const data = await api.request('/api/health');
    const container = $('#sourceHealthList');
    if (container && data.sources) {
      container.innerHTML = renderSourceHealth(data.sources);
    }
  } catch (err) {
    console.error('Failed to load source health:', err);
  }
}

// ============================================================================
// Command Palette — Cmd+K / Ctrl+K
// ============================================================================

function initCommandPalette() {
  const overlay = $('#commandPalette');
  const input = $('#commandInput');
  const list = $('#commandList');
  if (!overlay || !input || !list) return;

  const openPalette = () => {
    overlay.classList.add('open');
    input.value = '';
    filterCommands('');
    setTimeout(() => input.focus(), 50);
    document.body.style.overflow = 'hidden';
  };

  const closePalette = () => {
    overlay.classList.remove('open');
    document.body.style.overflow = '';
  };

  // Open with Cmd+K / Ctrl+K
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      openPalette();
    }
    if (e.key === 'Escape' && overlay.classList.contains('open')) {
      closePalette();
    }
  });

  // Close on overlay click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closePalette();
  });

  // Filter commands as user types
  input.addEventListener('input', () => {
    filterCommands(input.value.toLowerCase());
  });

  // Handle command clicks
  list.addEventListener('click', (e) => {
    const item = e.target.closest('.command-item');
    if (!item) return;
    executeCommand(item.dataset.action);
    closePalette();
  });

  // Keyboard navigation in list
  input.addEventListener('keydown', (e) => {
    const items = [...list.querySelectorAll('.command-item')];
    const active = list.querySelector('.command-item:hover');
    const idx = items.indexOf(active);

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = items[idx + 1] || items[0];
      next?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = items[idx - 1] || items[items.length - 1];
      prev?.focus();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (active) {
        executeCommand(active.dataset.action);
        closePalette();
      }
    }
  });

  function filterCommands(query) {
    const items = list.querySelectorAll('.command-item');
    const groups = list.querySelectorAll('.command-group');

    items.forEach(item => {
      const text = item.textContent.toLowerCase();
      item.style.display = text.includes(query) ? '' : 'none';
    });

    // Hide empty groups
    groups.forEach(group => {
      const visibleItems = group.querySelectorAll('.command-item:not([style*="display: none"])');
      group.style.display = visibleItems.length ? '' : 'none';
    });
  }

  function executeCommand(action) {
    switch (action) {
      case 'go-feed':
        window.location.href = '/';
        break;
      case 'go-saved':
        window.location.href = '/saved';
        break;
      case 'refresh':
        document.getElementById('scrapeForm')?.submit();
        break;
      case 'search':
        document.getElementById('searchInput')?.focus();
        break;
      case 'toggle-theme':
        $('#themeToggle')?.click();
        break;
      case 'export-csv':
        window.location.href = '/download';
        break;
      case 'export-json':
        window.location.href = '/export/json';
        break;
    }
  }
}

// ============================================================================
// Focus Mode — Hide chrome, highlight current article
// ============================================================================

function initFocusMode() {
  let focusActive = false;

  document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

    if (e.key === 'f' && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      focusActive = !focusActive;
      document.body.classList.toggle('focus-mode', focusActive);
      createToast(focusActive ? 'Focus mode on' : 'Focus mode off', 'success');
    }
  });
}

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
  // Hide loading overlay
  hideLoadingOverlay();

  // Initialize all modules
  initThemeToggle();
  initSubscribeForm();
  initKeyboardShortcuts();
  initScrollTop();
  initSearchForm();
  initFilterToggle();
  initDensityToggle();
  initCommandPalette();
  initFocusMode();

  // Load source health
  loadSourceHealth();

  // Load more button
  const loadMoreBtn = $('#loadMoreBtn');
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', loadMoreArticles);
  }

  // Personalized feed button
  const personalizedBtn = $('#personalizedBtn');
  if (personalizedBtn) {
    personalizedBtn.addEventListener('click', fetchPersonalized);
  }

  // Close modal buttons
  $$('[data-modal-close]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.closest('.modal-overlay')));
  });

  // Focus first article card for keyboard nav
  const firstCard = $('.article-card');
  if (firstCard) firstCard.classList.add('focused');

  console.log('Sniffer initialized');
});

// Handle page visibility change (refresh on return)
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    // Optionally refresh data
  }
});

// Service Worker registration
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js')
      .then(reg => console.log('SW registered:', reg.scope))
      .catch(err => console.log('SW registration failed:', err));
  });
}