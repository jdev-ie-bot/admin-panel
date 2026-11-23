import { afterEach, expect, it, vi } from 'vitest';
import { fetchPortalIdentity } from '@/lib/portalApi';
import { clearIdentity, portalState, refreshIdentity } from '@/lib/portalState';
import { identity } from './portalFixtures';

vi.mock('@/lib/portalApi', async (original) => ({
    ...(await original<Record<string, unknown>>()),
    fetchPortalIdentity: vi.fn(),
}));

afterEach(() => {
    clearIdentity();
    vi.resetAllMocks();
});

it('does not restore private identity from a read that outlives sign-out', async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(fetchPortalIdentity).mockReturnValue(
        new Promise((resolve) => {
            finish = resolve;
        }),
    );
    const read = refreshIdentity();
    const signal = vi.mocked(fetchPortalIdentity).mock.calls[0][0];
    clearIdentity();
    expect(signal?.aborted).toBe(true);
    finish(identity());
    await read;
    expect(portalState.identity).toBeNull();
    expect(portalState.loading).toBe(false);
});
