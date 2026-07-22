/**
 * 後端回傳的時間字串是 naive UTC（沒有 'Z' 或 +00:00 時區標記），瀏覽器的 Date
 * 建構子在缺少時區資訊時會當成「本機時間」解析，導致畫面顯示的時間少了 UTC+8
 * 的時差（看起來像沒有轉換到台北時間）。統一在這裡補上 'Z' 再解析，避免每個
 * 畫面各自處理、漏改。
 */
function parseUtcDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const hasTimezone = /[zZ]|[+-]\d{2}:\d{2}$/.test(value)
  return new Date(hasTimezone ? value : `${value}Z`)
}

export function formatDate(value: string | null | undefined, fallback = '—'): string {
  const d = parseUtcDate(value)
  return d ? d.toLocaleString() : fallback
}

export { parseUtcDate }
