import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiRequest, readCsrfCookie } from '../src/api/client';

describe('API request security contract', () => {
  beforeEach(() => {
    document.cookie = 'smartattend_csrf=; Max-Age=0; path=/';
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends session cookies and a CSRF header for authenticated mutations', async () => {
    document.cookie = 'smartattend_csrf=csrf%2Bvalue; path=/';
    const fetchMock = vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }));

    await apiRequest('/teacher/example', { method: 'POST', body: { state: 'ok' }, classId: 'class-7' });

    const [, init] = fetchMock.mock.calls[0]!;
    const headers = new Headers(init?.headers);
    expect(init?.credentials).toBe('include');
    expect(headers.get('X-CSRF-Token')).toBe('csrf+value');
    expect(headers.get('X-Class-ID')).toBe('class-7');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(init?.body).toBe(JSON.stringify({ state: 'ok' }));
  });

  it('does not add a stale CSRF cookie to explicitly public mutations', async () => {
    document.cookie = 'smartattend_csrf=stale-token; path=/';
    const fetchMock = vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }));

    await apiRequest('/teacher-requests', { method: 'POST', body: { full_name: 'Teacher' }, csrf: false });

    const [, init] = fetchMock.mock.calls[0]!;
    expect(new Headers(init?.headers).has('X-CSRF-Token')).toBe(false);
  });

  it('does not add a CSRF header to ordinary public GET requests', async () => {
    const fetchMock = vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ name: 'School' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }));

    await apiRequest('/public/school-branding');

    const [, init] = fetchMock.mock.calls[0]!;
    expect(init?.credentials).toBe('include');
    expect(new Headers(init?.headers).has('X-CSRF-Token')).toBe(false);
  });

  it('leaves multipart content type to the browser boundary implementation', async () => {
    const form = new FormData();
    form.append('files', new Blob(['test'], { type: 'image/jpeg' }), 'capture.jpg');
    const fetchMock = vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }));

    await apiRequest('/teacher/students/1/face-enrollment', { method: 'POST', body: form });

    const [, init] = fetchMock.mock.calls[0]!;
    expect(init?.body).toBe(form);
    expect(new Headers(init?.headers).has('Content-Type')).toBe(false);
  });

  it('normalizes API errors and retains request identifiers', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'SESSION_EXPIRED', message: 'Please sign in again.', request_id: 'req-123' },
    }), { status: 401, headers: { 'content-type': 'application/json' } }));

    await expect(apiRequest('/admin/me')).rejects.toMatchObject({
      name: 'ApiError', status: 401, code: 'SESSION_EXPIRED', requestId: 'req-123',
    });
  });

  it('reads the CSRF cookie only, never the HttpOnly session cookie', () => {
    document.cookie = 'smartattend_csrf=public-csrf; path=/';
    expect(readCsrfCookie()).toBe('public-csrf');
  });
});
