/** API client — only file that knows the backend URL */
const BASE = 'http://localhost:8000';

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const opts: RequestInit = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(`${BASE}${path}`, opts);
    if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
    return res.json() as Promise<T>;
}

export const api = {
    library: {
        list: (limit = 80) => request<any>('GET', `/api/library?limit=${limit}`),
        search: (q: string, language?: string) => request<any>('GET', `/api/library/search?q=${encodeURIComponent(q)}${language ? `&language=${language}` : ''}`),
        get: (id: string) => request<any>('GET', `/api/library/${id}`),
    },
    scan: {
        run: (path: string) => request<any>('POST', '/api/scan', { path }),
    },
    plan: {
        run: (problem: string, language?: string) => request<any>('POST', '/api/plan', { problem, language }),
    },
    patterns: {
        list: () => request<any>('GET', '/api/patterns'),
        get: (id: string) => request<any>('GET', `/api/patterns/${id}`),
        instantiate: (id: string) => request<any>('POST', `/api/patterns/${id}/instantiate`, {}),
    },
};
