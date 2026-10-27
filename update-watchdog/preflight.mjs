import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
export async function preflight(token, request=fetch) {
 if (!token) throw new Error('dispatch-token-missing');
 const response=await request('https://api.github.com/repos/takochi92/minamoyomi/actions/workflows/update.yml',{
  headers:{Authorization:'Bearer '+token,Accept:'application/vnd.github+json','User-Agent':'Teilog-update-preflight'},
  redirect:'error',signal:AbortSignal.timeout(10_000),
 });
 if (!response.ok) throw new Error('dispatch-token-check-'+response.status);
 const expiry=Date.parse(response.headers.get('github-authentication-token-expiration') || '');
 if (Number.isFinite(expiry) && expiry<=Date.now()+86400_000) throw new Error('dispatch-token-expires-too-soon');
 return {ready:true,tokenExpiresOn:Number.isFinite(expiry) ? new Date(expiry).toISOString().slice(0,10) : 'configured-date-fallback'};
}
if (process.argv[1] && fileURLToPath(import.meta.url)===resolve(process.argv[1])) {
 preflight(process.env.UPDATE_DISPATCH_TOKEN).then(result=>console.log(JSON.stringify(result))).catch(error=>{
  console.error(/^dispatch-token-[a-z0-9-]+$/.test(error.message) ? error.message : 'dispatch-token-check-failed');process.exitCode=1;
 });
}
