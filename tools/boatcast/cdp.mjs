// Chrome DevTools Protocol の最小ドライバ。Node v22 の標準機能（fetch / WebSocket）だけで動く。外部npm依存なし。
//
//   const cdp = await CdpClient.connect({ port: 9454 });
//   await cdp.navigate(url);
//   const v = await cdp.evaluate('document.title');
//   const png = await cdp.screenshot();     // Buffer
//   await cdp.click(640, 450);
//   await cdp.close();
//
// 対象ページは http://127.0.0.1:<port>/json/list の type=page から取る。
// 注意：場ページ経由だとプレイヤーは別ドメインの iframe になり、iframe 側のターゲットではスクリーンショットが撮れない。
//       単体プレイヤーURLを直接開く方式を正とする。

import { StageError } from './failures.mjs';
import { redactText } from './redact.mjs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getJson(url, init, timeoutMs = 5000) {
  const res = await fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${redactText(url)}`);
  return res.json();
}

export class CdpClient {
  constructor(ws, target, port) {
    this.ws = ws;
    this.target = target;
    this.port = port;
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = new Map();
    this.closed = false;
    ws.addEventListener('message', (ev) => this.#onMessage(ev));
    ws.addEventListener('close', () => this.#onClose());
    ws.addEventListener('error', () => this.#onClose());
  }

  /** /json/version（Chrome のバージョン確認） */
  static async version({ host = '127.0.0.1', port }) {
    return getJson(`http://${host}:${port}/json/version`);
  }

  /** 先頭のページターゲットに繋ぐ。無ければ about:blank を1つ作る */
  static async connect({ host = '127.0.0.1', port, urlIncludes = null, timeoutMs = 15000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    let lastErr = null;
    while (Date.now() < deadline) {
      try {
        let list = await getJson(`http://${host}:${port}/json/list`);
        let pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
        if (urlIncludes) pages = pages.filter((t) => (t.url || '').includes(urlIncludes));
        if (!pages.length && !urlIncludes) {
          const created = await getJson(`http://${host}:${port}/json/new?about:blank`, { method: 'PUT' });
          pages = [created];
        }
        if (pages.length) {
          const target = pages[0];
          const ws = new WebSocket(target.webSocketDebuggerUrl);
          await new Promise((resolve, reject) => {
            ws.addEventListener('open', resolve, { once: true });
            ws.addEventListener('error', () => reject(new Error('WebSocket を開けませんでした')), { once: true });
          });
          return new CdpClient(ws, target, port);
        }
      } catch (e) {
        lastErr = e;
      }
      await sleep(400);
    }
    throw new StageError('cdp', `デバッグポート ${port} の対象ページが取れませんでした（${redactText(lastErr?.message || '対象なし')}）`);
  }

  #onMessage(ev) {
    let msg;
    try { msg = JSON.parse(typeof ev.data === 'string' ? ev.data : Buffer.from(ev.data).toString('utf8')); } catch { return; }
    if (msg.id !== undefined) {
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(`${p.method}: ${msg.error.message}`));
      else p.resolve(msg.result);
    } else if (msg.method) {
      for (const h of this.handlers.get(msg.method) || []) {
        try { h(msg.params); } catch { /* ハンドラの例外で接続を落とさない */ }
      }
    }
  }

  #onClose() {
    this.closed = true;
    for (const [, p] of this.pending) p.reject(new Error(`${p.method}: 接続が閉じました`));
    this.pending.clear();
  }

  send(method, params = {}, timeoutMs = 30000) {
    if (this.closed) return Promise.reject(new Error(`${method}: 接続が閉じています`));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method}: ${timeoutMs}ms でタイムアウト`));
      }, timeoutMs);
      this.pending.set(id, {
        method,
        resolve: (r) => { clearTimeout(timer); resolve(r); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  on(method, handler) {
    if (!this.handlers.has(method)) this.handlers.set(method, []);
    this.handlers.get(method).push(handler);
  }

  async enable(domains = ['Page', 'Runtime', 'Network']) {
    for (const d of domains) await this.send(`${d}.enable`);
  }

  /** Runtime.evaluate。式の値（JSON にできるもの）を返す。例外は Error にする */
  async evaluate(expression, { awaitPromise = true, timeoutMs = 30000 } = {}) {
    const r = await this.send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true, userGesture: true }, timeoutMs);
    if (r.exceptionDetails) {
      const d = r.exceptionDetails;
      throw new Error(`evaluate: ${d.exception?.description || d.text || '例外'}`);
    }
    return r.result?.value;
  }

  /** Page.navigate。読み込み完了（load）まで待つ。待ちきれなくても進める（動画は後で個別に待つ） */
  async navigate(url, { waitLoadMs = 20000 } = {}) {
    let loaded = false;
    const onLoad = () => { loaded = true; };
    this.on('Page.loadEventFired', onLoad);
    const r = await this.send('Page.navigate', { url });
    if (r.errorText) throw new Error(`navigate: ${r.errorText}`);
    const end = Date.now() + waitLoadMs;
    while (!loaded && Date.now() < end) await sleep(100);
    const arr = this.handlers.get('Page.loadEventFired') || [];
    this.handlers.set('Page.loadEventFired', arr.filter((h) => h !== onLoad));
    return loaded;
  }

  /** Page.captureScreenshot。表示中のビューポートを PNG の Buffer で返す */
  async screenshot({ format = 'png' } = {}) {
    const r = await this.send('Page.captureScreenshot', { format, fromSurface: true });
    return Buffer.from(r.data, 'base64');
  }

  /** Input.dispatchMouseEvent で左クリック（ユーザー操作扱いにして再生を始めたいとき用） */
  async click(x, y) {
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    try { this.ws.close(); } catch { /* 閉じ済み */ }
  }
}
