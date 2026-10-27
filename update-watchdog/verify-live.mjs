const token=process.env.UPDATE_DISPATCH_TOKEN;
if(!token)throw new Error('missing-verification-token');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const end=Date.now()+180_000;
while(Date.now()<end) {
 const response=await fetch('https://teilog-update-watchdog.site-kanri19.workers.dev/health',{
  headers:{Authorization:'Bearer '+token},redirect:'error',signal:AbortSignal.timeout(10_000),
 });
 if(response.status===401)throw new Error('verification-auth-failed');
 if(!response.ok){console.log('verification-pending',response.status);await wait(15_000);continue;}
 const state=await response.json();
 // Fixed fields only; no credentials, notification topic or user data in output.
 console.log(JSON.stringify({checkedAt:state.checkedAt,state:state.state,updatedAt:state.updatedAt,
  tokenExpiresOn:state.tokenExpiresOn,alertDelivery:state.alertDelivery,alertHttpStatus:state.alertHttpStatus,testClaimed:state.testClaimed,testCurrent:state.testCurrent}));
 const fresh=state.checkedAt && Date.now()-Date.parse(state.checkedAt)<180_000;
 if(fresh && ['fresh','update-running','backoff','dispatched','outside-hours'].includes(state.state) &&
    (process.env.EXPECT_TEST_ALERT!=='true' || (state.testCurrent && state.alertDelivery==='sent')))process.exit(0);
 if(state.testCurrent && ['failed','unknown'].includes(state.alertDelivery))throw new Error('test-alert-not-confirmed');
 await wait(15_000);
}
throw new Error('verification-not-complete');
