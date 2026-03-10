/** Patterns view — browse architectural patterns and instantiate them */
import { api } from '../api/client.js';
import { toast } from '../components/index.js';

const ARCH_COLORS: Record<string, string> = {
    layered: 'var(--accent-primary)',
    'event-driven': 'var(--accent-purple)',
    modular: 'var(--accent-gold)',
};

export function renderPatterns(container: HTMLElement) {
    container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Architecture Patterns</h1>
      <p class="page-subtitle">Built-in scaffolding templates — each enforces structural invariants that guarantee SHI ≥ 0.8</p>
    </div>
    <div id="patterns-grid" class="grid-2"></div>
  `;

    const grid = container.querySelector('#patterns-grid')!;
    grid.innerHTML = `<div class="loading"><div class="spinner"></div><span>Loading patterns...</span></div>`;

    api.patterns.list().then(data => {
        const patterns: any[] = data.patterns ?? [];
        if (!patterns.length) {
            grid.innerHTML = `<div class="empty-state"><div class="empty-icon">◉</div><div class="empty-text">No patterns found</div></div>`;
            return;
        }
        grid.innerHTML = patterns.map(p => patternCard(p)).join('');
        patterns.forEach((p, i) => {
            grid.querySelectorAll('.instantiate-btn')[i]?.addEventListener('click', (e) => {
                e.stopPropagation();
                doInstantiate(p);
            });
        });
    }).catch(e => {
        grid.innerHTML = `<div class="card" style="color:var(--accent-red)">Error: ${e.message}</div>`;
    });
}

function patternCard(p: any) {
    const color = ARCH_COLORS[p.architecture] ?? 'var(--accent-primary)';
    const files: string[] = p.structure ?? [];
    const invariants: string[] = p.invariants ?? [];
    return `
    <div class="pattern-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
        <div class="pattern-name" style="color:${color}">${p.name}</div>
        <span class="status-badge" style="background:${color}18;color:${color};border-color:${color}40;">${p.architecture}</span>
      </div>
      <div class="pattern-desc">${p.description}</div>

      <div style="margin-bottom:14px;">
        <div style="font-size:10.5px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">Invariants</div>
        <ul class="invariant-list">
          ${invariants.map(inv => `<li>${inv}</li>`).join('')}
        </ul>
      </div>

      <div style="margin-bottom:14px;">
        <div style="font-size:10.5px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">File Structure</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          ${files.map(f => `<span style="font-family:var(--font-mono);font-size:11.5px;background:var(--bg-elevated);border:1px solid var(--border);border-radius:4px;padding:2px 8px;color:var(--text-secondary)">${f}</span>`).join('')}
        </div>
      </div>

      <div class="pattern-footer">
        <div class="pattern-meta">FD target: ${p.fd_target} · SHI min: ${p.shi_min}</div>
        <button class="btn btn-primary instantiate-btn" style="font-size:12px;padding:7px 14px;">⬡ Instantiate</button>
      </div>
    </div>`;
}

async function doInstantiate(p: any) {
    try {
        toast(`Creating ${p.name} scaffold...`, 'ok');
        const data = await api.patterns.instantiate(p.id);
        toast(`✓ Files created in ${data.output_dir}`, 'ok');
        const files: string[] = data.files ?? [];

        // Show a quick modal-like notification
        const note = document.createElement('div');
        note.style.cssText = `
      position:fixed;bottom:80px;right:24px;z-index:9999;
      background:var(--bg-elevated);border:1px solid var(--border-accent);
      border-radius:var(--radius-md);padding:20px 24px;max-width:360px;
      box-shadow:var(--shadow-glow);animation:slide-in 0.2s ease;
    `;
        note.innerHTML = `
      <div style="font-size:13px;font-weight:600;color:var(--accent-green);margin-bottom:10px;">✓ ${p.name} instantiated</div>
      <div style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;font-family:var(--font-mono);word-break:break-all;">${data.output_dir}</div>
      <div style="display:flex;flex-direction:column;gap:4px;">
        ${files.map(f => `<span style="font-size:11.5px;font-family:var(--font-mono);color:var(--text-primary)">+ ${f}</span>`).join('')}
      </div>
      <button style="margin-top:14px;background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:12px;">dismiss</button>
    `;
        document.body.appendChild(note);
        note.querySelector('button')!.addEventListener('click', () => note.remove());
        setTimeout(() => note.remove(), 8000);
    } catch (e: any) {
        toast(`Error: ${e.message}`, 'error');
    }
}
