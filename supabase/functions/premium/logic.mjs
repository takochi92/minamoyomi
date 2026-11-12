export function paidSubscription(list, priceId, now = Date.now() / 1000) {
  return list.some(sub =>
    sub.status === "active" &&
    sub.items?.data?.some(item =>
      item.price?.id === priceId && item.current_period_end > now &&
      (!sub.cancel_at || sub.cancel_at > now)));
}

export function raceEvaluation(snapshot, date, venue, frames) {
  if (!snapshot?.through || date <= snapshot.through) return null;
  const end = Date.parse(date.replace(/^(....)(..)(..)$/, "$1-$2-$3"));
  const through = Date.parse(snapshot.through.replace(/^(....)(..)(..)$/, "$1-$2-$3"));
  if (!Number.isFinite(end) || !Number.isFinite(through) || end - through > 3 * 86400000) return null;
  const field = snapshot.venues?.[venue];
  if (!field) return null;
  return { through: snapshot.through, rows: frames.map(({ frame, motor }) => ({
    frame, motor, metrics: field.motors[String(motor)] || {}
  })) };
}
