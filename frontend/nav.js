(function () {
  // Apply saved/system theme before first paint to avoid flash
  const savedTheme = localStorage.getItem('fpl_theme');
  if (savedTheme === 'dark' || savedTheme === 'light') {
    document.documentElement.setAttribute('data-theme', savedTheme);
  }
  // System preference handled by CSS @media (prefers-color-scheme: dark)

  const path = location.pathname;

  const links = [
    { href: '/',                  label: 'Home' },
    { href: '/optimize.html',     label: 'Best Squad' },
    { href: '/rate-squad.html',   label: 'Squad Rating' },
    { href: '/transfers.html',    label: 'Transfers' },
    { href: '/lineup.html',       label: 'Pick Team' },
    { href: '/fixture-plan.html', label: 'Fixture Plan' },
  ];

  const nav = document.createElement('nav');

  // Brand mark + wordmark
  const brand = document.createElement('a');
  brand.className = 'brand';
  brand.href = '/';
  brand.setAttribute('aria-label', 'FPL Tool home');
  brand.innerHTML = `
    <span class="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="1,9 4.5,5 7,7.5 12,2"/>
        <polyline points="9,2 12,2 12,5"/>
      </svg>
    </span>
    FPL Tool`;
  nav.appendChild(brand);

  for (const { href, label } of links) {
    const a = document.createElement('a');
    a.href = href;
    a.textContent = label;
    const isHome = href === '/' && (path === '/' || path === '/index.html');
    const isPage = href !== '/' && path.endsWith(href.replace('/', ''));
    if (isHome || isPage) a.classList.add('active');
    if (isHome || isPage) a.setAttribute('aria-current', 'page');
    nav.appendChild(a);
  }

  // Theme toggle button
  const themeBtn = document.createElement('button');
  themeBtn.className = 'theme-btn';
  themeBtn.setAttribute('aria-label', 'Toggle dark mode');
  themeBtn.setAttribute('title', 'Toggle dark/light mode');
  updateThemeIcon();
  themeBtn.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme');
    // If no explicit theme, check system preference
    const effectiveDark = current === 'dark' ||
      (!current && window.matchMedia('(prefers-color-scheme: dark)').matches);
    const next = effectiveDark ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('fpl_theme', next);
    updateThemeIcon();
  });
  nav.appendChild(themeBtn);

  const keyBtn = document.createElement('button');
  keyBtn.className = 'key-btn';
  keyBtn.title = 'Click to set or update your API key';
  refreshKeyBtn();
  keyBtn.addEventListener('click', () => {
    const current = localStorage.getItem('fpl_api_key') || '';
    const input = prompt('Enter your API key (leave blank to clear):', current);
    if (input === null) return;
    if (input.trim()) {
      localStorage.setItem('fpl_api_key', input.trim());
    } else {
      localStorage.removeItem('fpl_api_key');
    }
    refreshKeyBtn();
  });
  nav.appendChild(keyBtn);

  document.body.insertBefore(nav, document.body.firstChild);

  function updateThemeIcon() {
    const current = document.documentElement.getAttribute('data-theme');
    const effectiveDark = current === 'dark' ||
      (!current && window.matchMedia('(prefers-color-scheme: dark)').matches);
    // Sun icon for dark mode (click to go light), Moon for light mode (click to go dark)
    themeBtn.innerHTML = effectiveDark
      ? `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
           <circle cx="12" cy="12" r="5"/>
           <line x1="12" y1="1" x2="12" y2="3"/>
           <line x1="12" y1="21" x2="12" y2="23"/>
           <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
           <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
           <line x1="1" y1="12" x2="3" y2="12"/>
           <line x1="21" y1="12" x2="23" y2="12"/>
           <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
           <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
         </svg>`
      : `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
           <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
         </svg>`;
    themeBtn.setAttribute('aria-label', effectiveDark ? 'Switch to light mode' : 'Switch to dark mode');
  }

  function refreshKeyBtn() {
    const key = localStorage.getItem('fpl_api_key');
    keyBtn.textContent = key ? 'API key: set' : 'API key: not set';
    keyBtn.className = 'key-btn ' + (key ? 'set' : 'unset');
  }

  // Shared helpers available to all pages via window.FPL
  window.FPL = {
    getApiKey() { return localStorage.getItem('fpl_api_key') || ''; },
    getEntryId() { return localStorage.getItem('fpl_entry_id') || ''; },
    setEntryId(id) { if (id) localStorage.setItem('fpl_entry_id', String(id)); },

    posBadge(pos) {
      return `<span class="badge pos-${pos}">${pos}</span>`;
    },

    badge(cls, label) {
      return `<span class="badge badge-${cls}">${label}</span>`;
    },

    async apiFetch(url) {
      const key = this.getApiKey();
      if (!key) throw new Error('API key not set — click "API key: not set" in the nav bar to add it.');
      const r = await fetch(url, { headers: { 'X-API-Key': key } });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${r.status})`);
      }
      return r.json();
    },

    setLoading(show, btnEl) {
      const el = document.getElementById('loading');
      if (el) el.classList.toggle('visible', show);
      if (btnEl) btnEl.disabled = show;
    },

    showError(msg) {
      const el = document.getElementById('error');
      if (el) { el.textContent = msg; el.className = 'msg msg-error'; }
    },

    clearError() {
      const el = document.getElementById('error');
      if (el) { el.textContent = ''; }
    },
  };
})();
