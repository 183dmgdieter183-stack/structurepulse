/** Shared UI components — imported by views */

// ── SHI Gauge (SVG arc) ──────────────────────────────────────────────────
export function SHIGauge(shi: number, status: string): string {
    const pct = Math.min(Math.max(shi, 0), 1);
    const r = 60; const cx = 80; const cy = 80;
    const startAngle = -Math.PI * 0.8;
    const endAngle = Math.PI * 0.8;
    const fillAngle = startAngle + (endAngle - startAngle) * pct;

    const color = status === 'stable' ? '#4ade80' : status === 'warning' ? '#fbbf24' : '#f87171';

    function pt(a: number) {
        return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
    }

    const trackPath = `M ${pt(startAngle)} A ${r} ${r} 0 1 1 ${pt(endAngle)}`;
    const fillPath = `M ${pt(startAngle)} A ${r} ${r} 0 ${fillAngle - startAngle > Math.PI ? 1 : 0} 1 ${pt(fillAngle)}`;

    return `
    <div class="shi-gauge-wrap">
      <svg width="160" height="130" viewBox="0 0 160 120" class="gauge-svg">
        <path d="${trackPath}" fill="none" stroke="#1e2240" stroke-width="10" stroke-linecap="round"/>
        <path d="${fillPath}" fill="none" stroke="${color}" stroke-width="10" stroke-linecap="round"
              style="filter:drop-shadow(0 0 8px ${color}88);"/>
        <text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="22" font-weight="700"
              font-family="JetBrains Mono,monospace" fill="${color}">${shi.toFixed(3)}</text>
        <text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="11" fill="#8890b0">${status.toUpperCase()}</text>
      </svg>
      <div class="gauge-label">Structural Health Index</div>
    </div>`;
}

// ── FD Bar ────────────────────────────────────────────────────────────────
export function FDBar(fd: number): string {
    const pct = Math.min(Math.max((fd - 1.0) / 1.0 * 100, 0), 100);
    const isOptimal = fd >= 1.7 && fd <= 1.9;
    return `
    <div class="fd-bar-wrap">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
        <span style="font-size:13px;color:var(--text-secondary)">Fractal Dimension</span>
        <span style="font-size:13px;font-weight:600;font-family:var(--font-mono);color:${isOptimal ? 'var(--accent-green)' : 'var(--accent-gold)'}">${fd.toFixed(4)}</span>
      </div>
      <div class="fd-bar-track">
        <div class="fd-bar-optimal"></div>
        <div class="fd-bar-fill" style="width:${pct}%"></div>
      </div>
      <div class="fd-bar-labels">
        <span>1.0 rigid</span>
        <span>optimal [1.7–1.9]</span>
        <span>chaos 2.0</span>
      </div>
    </div>`;
}

// ── Toast ─────────────────────────────────────────────────────────────────
let _toastContainer: HTMLElement | null = null;

function getToastContainer() {
    if (!_toastContainer) {
        _toastContainer = document.createElement('div');
        _toastContainer.id = 'toast-container';
        document.body.appendChild(_toastContainer);
    }
    return _toastContainer;
}

export function toast(msg: string, type: 'ok' | 'warn' | 'error' = 'ok') {
    const el = document.createElement('div');
    el.className = 'toast';
    const color = type === 'ok' ? 'var(--accent-green)' : type === 'warn' ? 'var(--accent-gold)' : 'var(--accent-red)';
    el.style.borderLeftColor = color;
    el.style.borderLeftWidth = '3px';
    el.style.borderLeftStyle = 'solid';
    el.textContent = msg;
    getToastContainer().appendChild(el);
    setTimeout(() => el.remove(), 3500);
}
