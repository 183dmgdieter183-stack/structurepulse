/** Client-side router — maps hash routes to view modules */
import { renderDashboard } from './views/Dashboard.js';
import { renderLibrary } from './views/Library.js';
import { renderPlanner } from './views/Planner.js';
import { renderPatterns } from './views/Patterns.js';

type ViewFn = (container: HTMLElement) => void;

const ROUTES: Record<string, ViewFn> = {
    dashboard: renderDashboard,
    library: renderLibrary,
    planner: renderPlanner,
    patterns: renderPatterns,
};

function getView(): string {
    const hash = location.hash.replace('#', '');
    return ROUTES[hash] ? hash : 'dashboard';
}

function setActive(view: string) {
    document.querySelectorAll('.nav-item').forEach(el => {
        el.classList.toggle('active', (el as HTMLElement).dataset.view === view);
    });
}

export function initRouter(container: HTMLElement) {
    function navigate() {
        const view = getView();
        setActive(view);
        container.innerHTML = '';
        ROUTES[view](container);
    }

    window.addEventListener('hashchange', navigate);

    // nav clicks
    document.querySelectorAll('.nav-item').forEach(el => {
        el.addEventListener('click', (e) => {
            e.preventDefault();
            const view = (el as HTMLElement).dataset.view ?? 'dashboard';
            location.hash = view;
        });
    });

    navigate();
}
