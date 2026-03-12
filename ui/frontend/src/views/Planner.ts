/** Planner view — "I want to build X" → architectural blueprint */
import { api } from '../api/client.js';
import { toast } from '../components/index.js';

const EXAMPLES = [
    'A secure FastAPI SaaS backend with Stripe payments and JWT auth',
    'A RAG chatbot that answers questions from company documents',
    'A gRPC microservice for real-time video processing',
    'A CLI tool for managing AWS S3 backups',
    'An async task queue with Celery and Redis for email processing',
];

export function renderPlanner(container: HTMLElement) {
    container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Architecture Planner</h1>
      <p class="page-subtitle">Describe what you want to build — StructurePulse finds the best-matching elite blueprints</p>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div class="card-title">What do you want to build?</div>
      <textarea id="problem-input" class="problem-input" placeholder="Describe your architectural challenge..."></textarea>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px;gap:12px;flex-wrap:wrap;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;" id="example-chips"></div>
        <button id="plan-btn" class="btn btn-primary">✦ Generate Plan</button>
      </div>
    </div>

    <div id="plan-result"></div>
  `;

    const chips = container.querySelector('#example-chips')!;
    const input = container.querySelector('#problem-input') as HTMLTextAreaElement;
    const btn = container.querySelector('#plan-btn') as HTMLButtonElement;
    const result = container.querySelector('#plan-result')!;

    EXAMPLES.forEach(ex => {
        const chip = document.createElement('button');
        chip.className = 'btn btn-ghost';
        chip.style.cssText = 'font-size:11.5px;padding:5px 12px;';
        chip.textContent = ex.split(' ').slice(0, 5).join(' ') + '…';
        chip.title = ex;
        chip.addEventListener('click', () => { input.value = ex; });
        chips.appendChild(chip);
    });

    btn.addEventListener('click', async () => {
        const problem = input.value.trim();
        if (!problem) { toast('Enter a problem description', 'warn'); return; }

        result.innerHTML = `<div class="loading"><div class="spinner"></div><span>Analysing your problem against 69 elite blueprints...</span></div>`;
        btn.disabled = true;

        try {
            const data = await api.plan.run(problem);
            renderPlanResult(result, data, problem);
        } catch (e: any) {
            result.innerHTML = `<div class="card" style="color:var(--accent-red)">Error: ${e.message}</div>`;
            toast(e.message, 'error');
        } finally {
            btn.disabled = false;
        }
    });
}

function renderPlanResult(el: Element, data: any, problem: string) {
    const matches: any[] = data.library_matches ?? [];
    el.innerHTML = `
    <div class="grid-2" style="margin-bottom:20px;">
      <div class="card">
        <div class="card-title">Recommendation</div>
        <p style="font-size:13.5px;color:var(--text-primary);line-height:1.6;">${data.recommendation ?? '—'}</p>
      </div>
      <div class="card">
        <div class="card-title">Library Matches</div>
        ${matches.length ? matches.map(m => matchRow(m)).join('') : '<p style="color:var(--text-secondary);font-size:13px">No direct match — new territory! Generate & validate.</p>'}
      </div>
    </div>

    ${data.agent_prompt ? `
    <div class="card">
      <div class="card-title">Agent Prompt — Ready for Claude / Cursor</div>
      <pre class="code-block">${escapeHtml(data.agent_prompt)}</pre>
      <div style="margin-top:12px;">
        <button id="copy-prompt" class="btn btn-ghost" style="font-size:12.5px;">⎘ Copy to clipboard</button>
      </div>
    </div>` : ''}
  `;

    el.querySelector('#copy-prompt')?.addEventListener('click', () => {
        navigator.clipboard.writeText(data.agent_prompt ?? '').then(() => toast('Copied!', 'ok'));
    });
}

function matchRow(m: any) {
    const shi = (m.shi ?? 0).toFixed(2);
    return `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border);">
      <div>
        <div style="font-size:13px;font-weight:500;">${m.name ?? m.id}</div>
        <div style="font-size:11.5px;color:var(--text-secondary);font-family:var(--font-mono)">${m.id} · ${m.language}</div>
      </div>
      <div style="font-size:13px;font-weight:700;font-family:var(--font-mono);color:var(--accent-green)">${shi}</div>
    </div>`;
}

function escapeHtml(s: string) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
