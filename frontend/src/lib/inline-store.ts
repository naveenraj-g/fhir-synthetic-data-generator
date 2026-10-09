/**
 * Inline results come back once, in the POST response, and are never stored by the server (by design: the database
 * keeps metadata only). Hold them here so the job page can show them right after generating. They are gone on a
 * full page reload, and the UI says so.
 */
const store = new Map<string, Record<string, unknown>[]>();

export const saveInline = (id: string, bundles: Record<string, unknown>[]) => void store.set(id, bundles);
export const getInline = (id: string) => store.get(id);
