// A topic may be saved as its name or its ntfy.sh subscription URL.
// Never follow a supplied host, path or query to another destination.
export function notificationTopic(value) {
 let topic=typeof value==='string' ? value.trim() : '';
 if(topic.startsWith('https://')) {
  try {
   const url=new URL(topic);
   if(url.origin!=='https://ntfy.sh' || url.username || url.password || url.search || url.hash) return null;
   topic=decodeURIComponent(url.pathname.replace(/^\//,'').replace(/\/$/,''));
  } catch (_) {return null;}
 }
 return /^[-_A-Za-z0-9]{1,64}$/.test(topic) ? topic : null;
}
