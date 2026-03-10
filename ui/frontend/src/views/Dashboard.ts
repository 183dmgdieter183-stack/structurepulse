/** Dashboard view — scan a path and display structural health */
import { api } from '../api/client.js';
import { SHIGauge, FDBar, toast } from '../components/index.js';

const DEFAULT_PATH = '/Users/annabellabohn/Desktop/sstructurepulse/code/structurepulse';

export function renderDashboard(container: HTMLElement) {
  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Dashboard</h1>
      <p class="page-subtitle">Scan any directory or file for structural health metrics</p>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="card-title">Target Path</div>
      <div class="path-input-wrap">
        <input type="text" id="scan-path" class="path-input" placeholder="/path/to/your/project" value="${DEFAULT_PATH}" />
        <button id="browse-btn" class="btn btn-ghost">📁 Browse</button>
        <button id="scan-btn" class="btn btn-primary">⬡ Scan</button>
      </div>
    </div>

    <div id="scan-results"></div>
  `;

  const btn = container.querySelector('#scan-btn') as HTMLButtonElement;
  const browseBtn = container.querySelector('#browse-btn') as HTMLButtonElement;
  const pathInput = container.querySelector('#scan-path') as HTMLInputElement;

  btn.addEventListener('click', () => runScan(pathInput.value.trim(), container));

  browseBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('http://localhost:8000/api/scan/browse');
      const data = await res.json();
      if (data.path) {
        pathInput.value = data.path;
        runScan(data.path, container);
      }
    } catch (e) {
      toast('Could not open folder picker', 'error');
    }
  });

  // Auto-scan on load
  runScan(DEFAULT_PATH, container);
}

async function runScan(path: string, container: HTMLElement) {
  if (!path) return;
  const results = container.querySelector('#scan-results')!;
  results.innerHTML = `<div class="loading"><div class="spinner"></div><span>Scanning...</span></div>`;

  try {
    const data = await api.scan.run(path);
    const m = data.metrics;
    const fp = data.fingerprint ?? {};
    const status = m.status as string;

    results.innerHTML = `
      <div class="grid-4" style="margin-bottom:20px;">
        ${metricCard('SHI Score', m.shi?.toFixed(3), statusBadge(status), '--accent-green')}
        ${metricCard('Fractal Dim.', m.fd?.toFixed(4), `<span style="color:var(--text-secondary);font-size:12px">${m.fd_status ?? ''}</span>`, '--accent-primary')}
        ${metricCard('Dep. Cycles', m.cycle_count ?? 0, m.cycle_count === 0 ? '<span class="status-badge status-stable">Clean</span>' : '<span class="status-badge status-critical">Has Cycles</span>', '--accent-purple')}
        ${metricCard('Coupling', (m.coupling_density ?? 0).toFixed(3), `<span style="color:var(--text-secondary);font-size:12px">${fp.modules ?? '?'} modules</span>`, '--accent-gold')}
      </div>

      <div class="grid-2" style="margin-bottom:20px;">
        <div class="card">
          <div class="card-title">SHI Gauge</div>
          ${SHIGauge(m.shi ?? 0, status)}
        </div>
        <div class="card">
          <div class="card-title">Fractal Dimension Band</div>
          ${FDBar(m.fd ?? 1.0)}
          <div style="margin-top:20px; display:flex; flex-direction:column; gap:8px;">
            ${infoRow('Architecture', fp.architecture_style ?? '?')}
            ${infoRow('Total Nodes', fp.total_nodes ?? '?')}
            ${infoRow('Avg LOC/mod', fp.avg_module_loc ?? '?')}
            ${infoRow('Entropy', m.graph_entropy?.toFixed(3) ?? '?')}
            ${infoRow('Complexity', m.avg_complexity?.toFixed(2) ?? '?')}
          </div>
        </div>
      </div>

      ${data.explanation?.length ? `
      <div class="card" style="margin-bottom:20px;">
        <div class="card-title">Root Cause Analysis</div>
        <div style="display:flex; flex-direction:column; gap:6px;">
          ${data.explanation.map((line: string) => {
      const isSub = line.startsWith('  ');
      const color = line.includes('✓') ? 'var(--accent-green)' : (line.includes('warning') || line.includes('moderate') ? 'var(--accent-gold)' : (line.includes('critical') || line.includes('chaos') || line.includes('cycle') ? 'var(--accent-red)' : 'var(--text-secondary)'));
      return `
              <div style="font-size:${isSub ? '12px' : '13px'}; color:${color}; ${isSub ? 'padding-left:14px; opacity:0.8;' : 'font-weight:500;'}">
                ${line.trim()}
              </div>
            `;
    }).join('')}
        </div>
      </div>` : ''}

      ${data.inconsistencies?.length ? `
      <div class="card" style="margin-bottom:20px; border-color:var(--accent-gold);">
        <div class="card-title" style="color:var(--accent-gold)">[!] Role Inconsistencies</div>
        <div style="display:flex; flex-direction:column; gap:12px;">
          ${data.inconsistencies.map((w: any) => `
            <div style="padding:10px; background:rgba(251,191,36,0.05); border-radius:var(--radius-sm); border:1px solid rgba(251,191,36,0.2)">
              <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                <span style="font-weight:600; font-size:13px; color:var(--accent-gold)">${w.kind}</span>
                <span style="font-family:var(--font-mono); font-size:11px; color:var(--text-secondary)">${w.module_path.split('/').pop()}</span>
              </div>
              <div style="font-size:12px; color:var(--text-primary); margin-bottom:4px;">${w.message}</div>
              <div style="font-size:11px; color:var(--text-dim); font-style:italic;">${w.detail}</div>
            </div>
          `).join('')}
        </div>
      </div>` : ''}

      ${data.dependency_cycles?.length ? `
      <div class="card" style="margin-bottom:20px;">
        <div class="card-title">Dependency Cycles</div>
        <div style="display:flex; flex-direction:column; gap:8px;">
          ${data.dependency_cycles.map((cycle: string[]) => {
      const parts = cycle.map((mod, i) => {
        const nextMod = cycle[(i + 1) % cycle.length];
        const line = data.import_lines[`${mod}->${nextMod}`];
        const name = mod.split('/').pop();
        return line ? `${name}<span style="color:var(--accent-primary)">:${line}</span>` : name;
      });
      return `
              <div style="font-family:var(--font-mono); font-size:12px; padding:8px; background:var(--bg-elevated); border-radius:var(--radius-sm); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                <span style="color:var(--accent-red)">↻</span> ${parts.join(' <span style="color:var(--text-dim)">→</span> ')}
              </div>
            `;
    }).join('')}
        </div>
      </div>` : ''}
    `;
  } catch (e: any) {
    results.innerHTML = `<div class="card"><p style="color:var(--accent-red)">Error: ${e.message}</p></div>`;
    toast(e.message, 'error');
  }
}

function metricCard(label: string, value: any, sub: string, color: string) {
  return `
    <div class="metric-card">
      <div class="metric-label">${label}</div>
      <div class="metric-value" style="color:var(${color})">${value ?? '—'}</div>
      <div class="metric-sub">${sub}</div>
    </div>`;
}

function infoRow(label: string, value: any) {
  return `<div style="display:flex;justify-content:space-between;font-size:13px;">
    <span style="color:var(--text-secondary)">${label}</span>
    <span style="font-family:var(--font-mono);color:var(--text-primary)">${value}</span>
  </div>`;
}

function statusBadge(status: string) {
  const cls = status === 'stable' ? 'status-stable' : status === 'warning' ? 'status-warning' : 'status-critical';
  return `<span class="status-badge ${cls}">${status}</span>`;
}
