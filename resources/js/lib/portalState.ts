import { reactive } from 'vue';
import { fetchPortalIdentity } from '@/lib/portalApi';
import { readIdentity } from '@/lib/portalData';
import type { PortalIdentity } from '@/types/portal';

export const portalState = reactive<{
    identity: PortalIdentity | null;
    loading: boolean;
    error: string | null;
}>({ identity: null, loading: true, error: null });

let activeRead: AbortController | undefined;

export function clearIdentity() {
    activeRead?.abort();
    activeRead = undefined;
    portalState.identity = null;
    portalState.loading = false;
    portalState.error = null;
}

export async function refreshIdentity(background = false) {
    activeRead?.abort();
    const read = new AbortController();
    activeRead = read;

    if (!background) {
        portalState.loading = true;
    }

    portalState.error = null;

    try {
        const identity = readIdentity(await fetchPortalIdentity(read.signal));

        if (!read.signal.aborted) {
            portalState.identity = identity;
        }
    } catch (error) {
        if (read.signal.aborted) {
            return;
        }

        portalState.identity = null;

        if (
            error instanceof Error &&
            !('status' in error && error.status === 401)
        ) {
            portalState.error =
                'We could not load your portal account. Please try again.';
        }
    } finally {
        if (activeRead === read) {
            activeRead = undefined;
            portalState.loading = false;
        }
    }
}
