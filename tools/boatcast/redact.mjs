// ログ・manifest・報告に出す文字列から、配信まわりのセッショントークンなどを落とす共通関数。
//
// ルール
//   ・URL は「スキーム＋ドメイン＋パス」までだけを残す。クエリ文字列・ハッシュ・認証情報（user:pass@）は必ず落とす
//   ・Cookie / Authorization 系のヘッダ風の行、token= / session= / sig= などの値も伏せる
//   ・data: / blob: / javascript: は中身を出さない
// すべての出力経路（コンソール、manifest.json、エラーメッセージ）は、必ずこのファイルの関数を通すこと。

const URL_RE = /\b(?:https?|wss?):\/\/[^\s"'<>\\]+/gi;
const TRAILING_PUNCT_RE = /[)\]},.;:!?]+$/;
const HEADER_RE = /\b(set-cookie|cookie|authorization|proxy-authorization|x-[a-z0-9-]*token[a-z0-9-]*)\b\s*[:=]\s*[^\n]*/gi;
const KV_RE = /\b(token|access_token|session|sessionid|sid|sig|signature|key|auth|jwt|hdnts|hdntl)=[^&\s"'<>]+/gi;

/** 1つの URL を「スキーム＋ドメイン＋パス」だけにする。URL として読めないものは ? や # から先を落とす */
export function redactUrl(input) {
  if (typeof input !== 'string') return input;
  const s = input.trim();
  if (s === '' || s === 'about:blank') return s;
  const lower = s.toLowerCase();
  for (const p of ['data:', 'blob:', 'javascript:', 'file:']) {
    if (lower.startsWith(p)) return `${p}[omitted]`;
  }
  try {
    const u = new URL(s);
    if (u.protocol === 'http:' || u.protocol === 'https:' || u.protocol === 'ws:' || u.protocol === 'wss:') {
      return `${u.protocol}//${u.host}${u.pathname}`;
    }
    return `${u.protocol}[omitted]`;
  } catch {
    return s.split(/[?#]/)[0];
  }
}

/** 文章の中にある URL をすべて redactUrl に通し、ヘッダ風・token= 風の値も伏せる */
export function redactText(text) {
  if (typeof text !== 'string') return text;
  let out = text.replace(URL_RE, (m) => {
    const tail = (m.match(TRAILING_PUNCT_RE) || [''])[0];
    const body = tail ? m.slice(0, m.length - tail.length) : m;
    return redactUrl(body) + tail;
  });
  out = out.replace(HEADER_RE, (_m, name) => `${name}: [REDACTED]`);
  out = out.replace(KV_RE, (_m, name) => `${name}=[REDACTED]`);
  return out;
}

/** オブジェクト・配列の中の文字列をすべて redactText に通した「新しい」値を返す（元は変えない） */
export function redactDeep(value) {
  if (typeof value === 'string') return redactText(value);
  if (Array.isArray(value)) return value.map(redactDeep);
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = redactDeep(v);
    return out;
  }
  return value;
}

/** console に出すときの口。引数はすべて伏せ字処理を通す */
export function makeLogger(prefix = '', sink = console.log) {
  return (...args) => {
    const parts = args.map((a) => {
      if (typeof a === 'string') return redactText(a);
      if (a instanceof Error) return redactText(`${a.name}: ${a.message}`);
      try { return redactText(JSON.stringify(redactDeep(a))); } catch { return '[unprintable]'; }
    });
    sink(prefix ? `${prefix} ${parts.join(' ')}` : parts.join(' '));
  };
}
