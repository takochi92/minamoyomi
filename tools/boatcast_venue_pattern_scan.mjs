/** Capture a small, private frame survey for each BOATCAST venue. */
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [source, registry, output, repeatDate] = process.argv.slice(2);
if (!source || !registry || !output || (repeatDate && !/^\d{8}$/.test(repeatDate))) {
  throw new Error('usage: SOURCE STADIUMS_JSON NEW_OUTPUT_DIR [HEIWAJIMA_REPEAT_DATE]');
}
const port = 9454;
const moduleUrl = name => pathToFileURL(path.resolve(source, name)).href;
const { launchChrome } = await import(moduleUrl('chrome.mjs'));
const { run } = await import(moduleUrl('capture.mjs'));
const { stadiums } = JSON.parse(readFileSync(registry, 'utf8'));
const codes = Array.from({ length: 24 }, (_, i) => String(i + 1).padStart(2, '0'));
for (const code of codes) {
  const entry = stadiums[code];
  if (!entry || !/^\d{8}$/.test(entry.date) || !Number.isFinite(entry.duration) || entry.duration < 60 ||
      !Number.isInteger(entry.race) || entry.race < 1 || entry.race > 12) {
    throw new Error(`Invalid stadium registry entry: ${code}`);
  }
}
mkdirSync(output);
const profile = path.resolve(output, 'profile');
const captures = path.resolve(output, 'captures');
const fractions = [.40, .50, .59, .65, .69, .72, .75, .78, .81, .84, .88, .92, .96];
const results = [];
const chrome = await launchChrome({ port, profile });
try {
  const jobs = [
    ...(repeatDate ? [{ venue: '04', date: repeatDate, race: 11, duration: stadiums['04'].duration, purpose: 'second_date' }] : []),
    ...codes.map(venue => ({ venue, ...stadiums[venue], purpose: 'venue_pattern' })),
  ];
  for (const job of jobs) {
    const { venue, date, race, duration, purpose } = job;
    const seconds = fractions.map(f => Math.round(duration * f)).join(',');
    const status = await run(['--date', date, '--venue', venue, '--race', String(race),
      '--seconds', seconds, '--port', String(port), '--profile', profile, '--out', captures,
      '--video-timeout', '15', '--attach']);
    const row = { venue, date, race, purpose, status };
    results.push(row);
    writeFileSync(path.resolve(output, 'progress.json'), JSON.stringify(results, null, 2) + '\n');
    console.log('SURVEY', JSON.stringify(row));
  }
} finally {
  await chrome.stop();
}
