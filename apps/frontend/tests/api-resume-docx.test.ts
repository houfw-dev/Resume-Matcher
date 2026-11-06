import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { downloadResumeDocx, getResumeDocxUrl } from '@/lib/api/resume';

describe('resume DOCX API', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('builds the docx URL without a lang query by default', () => {
    const url = getResumeDocxUrl('abc 123');
    expect(url).toBe('/api/v1/resumes/abc%20123/docx');
  });

  it('encodes the locale into the lang query param', () => {
    const url = getResumeDocxUrl('res-1', 'zh');
    expect(url).toBe('/api/v1/resumes/res-1/docx?lang=zh');
  });

  it('downloads the blob through apiFetch', async () => {
    const body = new Blob(['PK']);
    fetchMock.mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: {
          'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      })
    );

    const result = await downloadResumeDocx('res-1');
    expect(result).toBeInstanceOf(Blob);

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes/res-1/docx');
  });

  it('throws when the docx endpoint fails', async () => {
    fetchMock.mockResolvedValue(new Response('boom', { status: 500 }));

    await expect(downloadResumeDocx('res-1')).rejects.toThrow(/Failed to download resume document/);
  });
});
