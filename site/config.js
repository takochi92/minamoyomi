// サイト設定。広告・アフィリエイトのタグはここに貼るだけで各ページの枠に表示されます。
// 空文字の枠は表示されません。
window.SITE_CONFIG = {
  // Public client settings only. Never put service_role or secret keys here.
  // Live Google login, RLS, cloud round-trip and logout checks passed.
  account: { url: "https://xkibgkdniwlfocwpmuzy.supabase.co", publishableKey: "sb_publishable_g3Xf_bVA_fLJfzfZ2lQpIw_J0v4yaDS", verificationOnly: false },
  // ライブオッズの Worker のURL（例 "https://teilog-live.あなた.workers.dev"）。空ならライブ欄は出ません
  liveApi: "",
  ads: {
    home_mid: "",   // トップ「まもなく締切」の下
    race_mid: "",   // レースページ「見立て」の下
    race_side: "",  // レースページ 水面気象の下
  },
};
