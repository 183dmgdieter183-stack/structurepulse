/** Library view — browse and search the 69 elite modules */
import { api } from '../api/client.js';
import { toast } from '../components/index.js';

export function renderLibrary(container: HTMLElement) {
    container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Elite Architecture Library</h1>
      <p class="page-subtitle">69 gold-standard blueprints — each passing SHI ≥ 0.8</p>
    </div>

    <div style="display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap;">
      <div class="search-wrap" style="flex:1;min-width:220px;">
        <span class="search-icon">⬡</span>
        <input type="text" id="lib-search" class="search-input" placeholder="Search blueprints (stripe, auth, gRPC, RAG...)" />
      </div>
      <select id="lib-lang" style="background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:0 14px;color:var(--text-primary);font-size:13.5px;cursor:pointer;">
        <option value="">All Languages</option>
        <option value="python">Python</option>
        <option value="typescript">TypeScript</option>
      </select>
      <div id="lib-count" style="display:flex;align-items:center;color:var(--text-secondary);font-size:13px;white-space:nowrap;min-width:80px;"></div>
    </div>

    <div id="lib-grid" class="module-grid"></div>
    <div id="lib-detail" style="display:none;"></div>
  `;

    let debounce: ReturnType<typeof setTimeout>;
    const grid = container.querySelector('#lib-grid')!;
    const detail = container.querySelector('#lib-detail')!;
    const countEl = container.querySelector('#lib-count')!;

    async function load(q = '', lang = '') {
        grid.innerHTML = `<div class="loading"><div class="spinner"></div><span>Loading library...</span></div>`;
        try {
            const data = await (q || lang ? api.library.search(q, lang || undefined) : api.library.list());
            const items: any[] = data.matches ?? [];
            countEl.textContent = `${items.length} modules`;
            if (!items.length) {
                grid.innerHTML = `<div class="empty-state"><div class="empty-icon">⬡</div><div class="empty-text">No modules found for "${q}"</div></div>`;
                return;
            }
            grid.innerHTML = items.map(m => moduleCard(m)).join('');
            grid.querySelectorAll('.module-card').forEach((el, i) => {
                el.addEventListener('click', () => showDetail(items[i], grid, detail));
            });
        } catch (e: any) {
            grid.innerHTML = `<div class="card" style="color:var(--accent-red)">Could not load library: ${e.message}</div>`;
        }
    }

    const searchEl = container.querySelector('#lib-search') as HTMLInputElement;
    const langEl = container.querySelector('#lib-lang') as HTMLSelectElement;

    searchEl.addEventListener('input', () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => load(searchEl.value.trim(), langEl.value), 300);
    });
    langEl.addEventListener('change', () => load(searchEl.value.trim(), langEl.value));

    load();
}

function moduleCard(m: any) {
    const shi = typeof m.shi === 'number' ? m.shi.toFixed(2) : '?';
    const shiColor = m.shi >= 0.9 ? 'var(--accent-green)' : m.shi >= 0.8 ? 'var(--accent-primary)' : 'var(--accent-gold)';
    const arch = m.fingerprint?.architecture ?? m.language ?? '';
    return `
    <div class="module-card" style="cursor:pointer;">
      <div class="module-card-header">
        <div class="module-name">${m.name ?? m.id}</div>
        <div class="module-shi" style="color:${shiColor};background:${shiColor}18">${shi}</div>
      </div>
      <div class="module-desc">${m.description ?? ''}</div>
      <div class="module-tags">
        ${arch ? `<span class="tag">${arch}</span>` : ''}
        <span class="tag">${m.language ?? 'py'}</span>
        ${(m.tags ?? []).slice(0, 2).filter((t: string) => !['github', 'python', 'typescript'].includes(t)).map((t: string) => `<span class="tag">${t}</span>`).join('')}
      </div>
    </div>`;
}

function showDetail(m: any, grid: Element, detail: Element) {
    (grid as HTMLElement).style.display = 'none';
    (detail as HTMLElement).style.display = 'block';
    const ghUrl = (m.tags ?? []).find((t: string) => t.startsWith('url:'))?.replace('url:', '') ?? '';
    detail.innerHTML = `
    <button id="back-btn" class="btn btn-ghost" style="margin-bottom:20px;">← Back to Library</button>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:20px;">
        <div>
          <h2 style="font-size:18px;font-weight:700;margin-bottom:6px;">${m.name}</h2>
          <p style="font-size:13px;color:var(--text-secondary);">${m.description ?? ''}</p>
        </div>
        <div style="text-align:right;flex-shrink:0;">
          <div style="font-size:28px;font-weight:700;font-family:var(--font-mono);color:var(--accent-green)">${m.shi?.toFixed(3)}</div>
          <div style="font-size:11px;color:var(--text-secondary)">SHI Score</div>
        </div>
      </div>
      <div class="grid-3" style="margin-bottom:20px;">
        ${detailMetric('FD', m.fd?.toFixed(4))}
        ${detailMetric('Status', m.status)}
        ${detailMetric('Language', m.language)}
        ${detailMetric('Architecture', m.fingerprint?.architecture ?? '?')}
        ${detailMetric('Nodes', m.fingerprint?.node_count ?? '?')}
        ${detailMetric('LOC', m.fingerprint?.loc ?? '?')}
      </div>
      ${ghUrl ? `<a href="${ghUrl}" target="_blank" class="btn btn-ghost">→ View on GitHub</a>` : ''}
    </div>`;

    detail.querySelector('#back-btn')!.addEventListener('click', () => {
        (detail as HTMLElement).style.display = 'none';
        (grid as HTMLElement).style.display = 'grid';
    });
}

function detailMetric(label: string, value: any) {
    return `<div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px;">
    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px;">${label}</div>
    <div style="font-size:15px;font-weight:600;font-family:var(--font-mono);color:var(--text-primary)">${value ?? '?'}</div>
  </div>`;
}
