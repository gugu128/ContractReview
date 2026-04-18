export function buildMarkedHtml(fullText, ranges = []) {
  if (!fullText) return ''

  const normalized = [...ranges]
    .filter((range) => Number.isFinite(range?.start) && Number.isFinite(range?.end) && range.end > range.start)
    .sort((a, b) => a.start - b.start)

  const safeRanges = []
  let lastEnd = 0
  for (const range of normalized) {
    const start = Math.max(0, Math.min(fullText.length, range.start))
    const end = Math.max(start, Math.min(fullText.length, range.end))
    if (start < lastEnd) continue
    safeRanges.push({ ...range, start, end })
    lastEnd = end
  }

  let cursor = 0
  const html = safeRanges
    .map((range, index) => {
      const before = escapeHtml(fullText.slice(cursor, range.start))
      const marked = escapeHtml(fullText.slice(range.start, range.end))
      cursor = range.end
      const markId = range.id || `highlight-${index}`
      return `${before}<mark id="${markId}" data-start="${range.start}" data-end="${range.end}" class="rounded-md bg-amber-300/80 px-1 text-slate-950 shadow-sm shadow-amber-400/20">${marked}</mark>`
    })
    .join('')

  return `${html}${escapeHtml(fullText.slice(cursor))}`
}

export function escapeHtml(text) {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}
