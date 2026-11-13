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
    function validScore(m, minimumRuns) {
      const observed = calendarDay(m?.through);
      return observed !== null && observed >= period && observed <= cutoff &&
        Number.isFinite(m.venue_delta) && Number.isFinite(m.delta) &&
        Number.isInteger(m.runs) && m.runs >= minimumRuns &&
        Number.isInteger(m.field) && m.field >= 12;
    }
    const motors = Object.entries(field.motors || {});
    const baseValid = motors.every(([motor, data]) =>
      /^[1-9]\d{0,2}$/.test(motor) && Object.keys(data || {}).length > 0 &&
      Object.entries(data).every(([key, m]) =>
        ["exhibition", "straight"].includes(key) && /^[SABCD]$/.test(m?.grade) &&
        validScore(m, 6) && Number.isInteger(m.meetings) && m.meetings >= 1 && m.meetings <= 3));
    const pairings = Object.entries(field.pairings || {});
    const pairsValid = pairings.every(([motor, riders]) =>
      /^[1-9]\d{0,2}$/.test(motor) && Object.entries(riders || {}).every(([rider, scores]) =>
        /^\d{4}$/.test(rider) && Object.entries(scores || {}).every(([key, m]) => {
          const start = calendarDay(m?.start);
          return (key === "turn" ||
            ((key === "overall" || (key === "acceleration" && ["04", "22"].includes(venue))) && Number.isInteger(m?.index))) &&
            /^[ABCD]$/.test(m?.grade) && validScore(m, 3) && m.meetings === 1 &&
            start !== null && start >= period && start <= calendarDay(m.through) &&
            typeof m.title === "string" && m.title.length > 0 && m.title.length <= 200;
        })));
    return (motors.length > 0 || pairings.length > 0) && baseValid && pairsValid;
  });
}

export function raceEvaluation(snapshot, date, venue, frames, title = "") {
  const raceDay = calendarDay(date);
  const cutoff = calendarDay(snapshot?.through);
  if (raceDay === null || cutoff === null || raceDay <= cutoff || raceDay - cutoff > 3 * 86400000) return null;
  const field = snapshot.venues?.[venue];
  if (!field?.motors) return null;
  return { through: snapshot.through, rows: frames.map(({ frame, motor, rider }) => {
    const metrics = { ...field.motors[String(motor)] };
    const pair = /^\d{4}$/.test(rider || "") ? field.pairings?.[motor]?.[rider] : undefined;
    for (const [key, score] of Object.entries(pair || {})) {
      const observed = calendarDay(score.through);
      if (title && title === score.title && observed !== null && raceDay - observed <= 3 * 86400000) {
        metrics[key] = score;
      }
    }
    return { frame, motor, metrics };
  }) };
}
