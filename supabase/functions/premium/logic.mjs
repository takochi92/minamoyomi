export function calendarDay(value) {
  if (typeof value !== "string" || !/^20\d{6}$/.test(value)) return null;
  const iso = value.replace(/^(....)(..)(..)$/, "$1-$2-$3");
  const stamp = Date.parse(iso);
  return Number.isFinite(stamp) && new Date(stamp).toISOString().startsWith(iso + "T") ? stamp : null;
}

export function paidSubscription(list, priceIds, now = Date.now() / 1000) {
  return list.some(sub =>
    sub.status === "active" &&
    sub.items?.data?.some(item =>
      priceIds.includes(item.price?.id) && item.current_period_end > now &&
      (!sub.cancel_at || sub.cancel_at > now)));
}

export function validSnapshot(snapshot, today) {
  const cutoff = calendarDay(snapshot?.through);
  const yesterday = calendarDay(today) - 86400000;
  if (snapshot?.version !== 1 || cutoff === null || cutoff > yesterday || cutoff < yesterday - 2 * 86400000) return false;
  const entries = Object.entries(snapshot.venues || {});
  return entries.length > 0 && entries.every(([venue, field]) => {
    const period = calendarDay(field?.period);
    if (!/^(0[1-9]|1[0-9]|2[0-4])$/.test(venue) || period === null || period > cutoff) return false;
    const motors = Object.entries(field.motors || {});
    return motors.length > 0 && motors.every(([motor, data]) => {
      if (!/^[1-9]\d{0,2}$/.test(motor)) return false;
      const metrics = Object.entries(data || {});
      return metrics.length > 0 && metrics.every(([key, m]) => {
        const observed = calendarDay(m?.through);
        return ["exhibition", "straight"].includes(key) && /^[SABCD]$/.test(m?.grade) &&
          observed !== null && observed >= period && observed <= cutoff &&
          Number.isFinite(m.venue_delta) && Number.isFinite(m.delta) &&
          Number.isInteger(m.runs) && m.runs >= 6 &&
          Number.isInteger(m.field) && m.field >= 12 &&
          Number.isInteger(m.meetings) && m.meetings >= 1 && m.meetings <= 3;
      });
    });
  });
}

export function raceEvaluation(snapshot, date, venue, frames) {
  const raceDay = calendarDay(date);
  const cutoff = calendarDay(snapshot?.through);
  if (raceDay === null || cutoff === null || raceDay <= cutoff || raceDay - cutoff > 3 * 86400000) return null;
  const field = snapshot.venues?.[venue];
  if (!field?.motors) return null;
  return { through: snapshot.through, rows: frames.map(({ frame, motor }) => ({
    frame, motor, metrics: field.motors[String(motor)] || {}
  })) };
}
