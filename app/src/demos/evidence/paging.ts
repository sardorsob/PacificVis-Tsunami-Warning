export const EVIDENCE_PAGE_SIZE = 50;

export function evidencePage<T>(rows: readonly T[], requestedPage: number, previousIdentity: string, identity: string) {
  const pageCount = Math.max(1, Math.ceil(rows.length / EVIDENCE_PAGE_SIZE));
  const requested = previousIdentity === identity && Number.isFinite(requestedPage) ? Math.trunc(requestedPage) : 1;
  const page = Math.max(1, Math.min(pageCount, requested));
  const start = (page - 1) * EVIDENCE_PAGE_SIZE;
  const end = Math.min(rows.length, start + EVIDENCE_PAGE_SIZE);
  return { page, pageCount, start, end, rows: rows.slice(start, end) };
}
