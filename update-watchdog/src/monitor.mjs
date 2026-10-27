import {tick} from './index.mjs';
import {notificationTopic} from '../topic.mjs';

export function safeFailure(error) {
  return /^(github-status-\d{3}|freshness-status-\d{3}|invalid-[a-z-]+|missing-dispatch-token)$/.test(error?.message)
    ? error.message : 'request-failed';
}

export async function monitorCheck(storage, env, now = new Date(), request = fetch, check = tick) {
  const previous = await storage.get('state') || {};
  const day = new Date(now.getTime()+9*3600_000).toISOString().slice(0,10);
  let result, failure;
  try {result = await check(env,now,request);} catch(error) {failure=safeFailure(error);result=error.health || {};}
  const configuredChanged=previous.configuredExpiresOn!==env.DISPATCH_TOKEN_EXPIRES_ON;
  const expiry = result.tokenExpiresOn || (!configuredChanged && previous.tokenExpiresOn) || env.DISPATCH_TOKEN_EXPIRES_ON;
  const expiresAt = /^\d{4}-\d{2}-\d{2}$/.test(expiry || '') ? Date.parse(expiry+'T00:00:00Z') : NaN;
  const daysLeft = Number.isFinite(expiresAt) && new Date(expiresAt).toISOString().slice(0,10)===expiry
    ? Math.floor((expiresAt-Date.parse(day+'T00:00:00Z'))/86400_000) : null;
  const consecutiveFailures = failure ? Math.min(100,(previous.consecutiveFailures || 0)+1) : 0;
  const state = {
    checkedAt:now.toISOString(), state:failure || result.state,
    updatedAt:result.updated_at || null, ageMinutes:result.ageMinutes ?? null,
    consecutiveFailures, tokenExpiresOn:daysLeft===null ? null : expiry,
    configuredExpiresOn:env.DISPATCH_TOKEN_EXPIRES_ON,
    alerts:previous.tokenExpiresOn===expiry ? {...previous.alerts} : {},
    lastTestId:previous.lastTestId || null,
    alertDelivery:previous.alertDelivery || null,
    alertHttpStatus:previous.alertHttpStatus || null,
    alertErrorCode:previous.alertErrorCode || null,
  };
  let category, message;
  if (/^(github-status-(401|403)|missing-dispatch-token)$/.test(failure || '')) {
    category='outage'; message='自動更新のGitHub認証または権限が失敗しています（'+failure+'）。管理画面で起動鍵を確認してください。';
  } else if (daysLeft===null) {
    category='outage'; message='起動鍵の有効期限設定が不正です。監視Workerの設定を確認してください。';
  } else if (result.state==='update-stuck' || result.ageMinutes>=20) {
    category='outage'; message='レースの公開更新が遅れています。公開データの経過 '+result.ageMinutes+'分。GitHub Actionsの状態を確認してください。';
  } else if (consecutiveFailures>=2) {
    category='outage'; message='更新監視が連続して失敗しました（'+failure+'）。';
  } else if (daysLeft!==null && daysLeft<=14 && result.state!=='outside-hours') {
    category=daysLeft<=1 ? 'expiry1' : daysLeft<=7 ? 'expiry7' : 'expiry14';
    message='自動更新の起動鍵は'+expiry+'が有効期限です（残り'+Math.max(0,daysLeft)+'日）。期限前に鍵を交換し、監視Workerを再配備してください。';
  }
  const alreadyClaimed = category==='outage' ? state.alerts.outage===day : !!state.alerts[category];
  if (category && alreadyClaimed) category=undefined;
  const testId = /^\d{1,20}$/.test(env.ADMIN_ALERT_TEST_ID || '') ? env.ADMIN_ALERT_TEST_ID : null;
  if (!category && testId && testId!==state.lastTestId) {
    category='test'; message='艇ろぐの更新停止・鍵期限の管理者通知テストです。一般利用者への通知ではありません。';
  }
  const enabled=env.ADMIN_ALERTS_ENABLED==='true';
  state.alertsEnabled=enabled;
  const topic=notificationTopic(env.ADMIN_ALERT_TOPIC);
  if (enabled && !topic) {state.alertDelivery='channel-invalid';}
  const send=category && enabled && !!topic;
  if (send) {
    if (category==='test') state.lastTestId=testId;
    else state.alerts[category]=category==='outage' ? day : expiry;
    state.alertDelivery='claimed';
  }
  // Claim before transport: an ambiguous HTTP response must not cause repeated notifications.
  // This single bounded record contains no credentials, notification topic, notes, or subscriptions.
  await storage.put('state',state);
  if (send) {
    try {
      const response=await request('https://ntfy.sh/',{
        method:'POST',headers:{'Content-Type':'application/json'},redirect:'manual',signal:AbortSignal.timeout(10_000),
        body:JSON.stringify({topic,title:category==='test' ? '艇ろぐ：更新監視のテスト' : '艇ろぐ：自動更新の確認が必要です',
          message,click:'https://github.com/takochi92/minamoyomi/actions/workflows/update.yml',tags:['warning']}),
      });
      state.alertDelivery=response.ok ? 'sent' : 'failed';
      state.alertHttpStatus=response.status;
      state.alertErrorCode=null;
      if (!response.ok) {
        try {const body=await response.json();if(Number.isInteger(body.code))state.alertErrorCode=body.code;}catch(_){}
      }
    } catch (_) {state.alertDelivery='unknown';state.alertHttpStatus=null;}
    await storage.put('state',state);
  }
  const unhealthy=!!failure || daysLeft===null || (enabled && !topic) ||
    (enabled && ['failed','unknown'].includes(state.alertDelivery)) || result.state==='update-stuck' || result.ageMinutes>=20;
  return {state,unhealthy};
}

export class UpdateMonitor {
  constructor(ctx,env) {this.ctx=ctx;this.env=env;this.running=null;}
  async fetch(request) {
    if (request.method==='GET' && new URL(request.url).pathname==='/status') {
      const state=await this.ctx.storage.get('state');
      return Response.json(state ? {checkedAt:state.checkedAt,state:state.state,updatedAt:state.updatedAt,
        ageMinutes:state.ageMinutes,tokenExpiresOn:state.tokenExpiresOn,alertsEnabled:state.alertsEnabled,alertDelivery:state.alertDelivery,alertHttpStatus:state.alertHttpStatus,alertErrorCode:state.alertErrorCode,
        testClaimed:!!state.lastTestId,testCurrent:state.lastTestId===this.env.ADMIN_ALERT_TEST_ID} : {state:'not-checked'});
    }
    if (request.method!=='POST' || new URL(request.url).pathname!=='/check') return new Response('Not found',{status:404});
    // One global instance serializes concurrent Cron deliveries, avoiding duplicate dispatches and alerts.
    if (!this.running) this.running=monitorCheck(this.ctx.storage,this.env).finally(()=>{this.running=null;});
    const result=await this.running;
    return Response.json({state:result.state.state},{status:result.unhealthy ? 503 : 200});
  }
}
