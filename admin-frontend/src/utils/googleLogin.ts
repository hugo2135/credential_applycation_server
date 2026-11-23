// Google 登入完成後，後端把結果放在 URL fragment 導回登入頁（/login#google_token=...）。
// 用 fragment 而不是 query string：fragment 不會送到伺服器，token 不會出現在任何 log。
export interface GoogleLoginResult {
  token?: string
  email?: string
  linked: boolean
  error?: string
}

export function consumeGoogleFragment(): GoogleLoginResult | null {
  const params = new URLSearchParams(window.location.hash.slice(1))
  if (!params.has('google_token') && !params.has('google_error')) return null
  // 讀完立刻從網址列清掉，避免 token 留在瀏覽紀錄或被重新整理時重複處理
  history.replaceState(null, '', window.location.pathname + window.location.search)
  return {
    token: params.get('google_token') ?? undefined,
    email: params.get('email') ?? undefined,
    linked: params.get('google_linked') === '1',
    error: params.get('google_error') ?? undefined,
  }
}
