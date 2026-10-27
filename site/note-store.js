/* Shared note format and conflict-safe changes. No network or credentials. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TeiNoteModel = factory();
})(typeof window === 'undefined' ? this : window, function () {
  'use strict';
  var GROUPS = ['racer', 'motor', 'fav'];
  function copy(x) { return JSON.parse(JSON.stringify(x)); }
  function same(a, b) { return JSON.stringify(a == null ? null : a) === JSON.stringify(b == null ? null : b); }
  function plain(x) { return !!x && typeof x === 'object' && !Array.isArray(x); }
  function safeKey(k) { return typeof k === 'string' && k.length > 0 && k.length <= 120 && !['__proto__', 'constructor', 'prototype'].includes(k) && !k.includes('\u0000'); }
  function amount(x) { return Number.isSafeInteger(x) && x >= 0 && x <= 1000000000; }
  function normalize(x) {
    if (!plain(x)) throw new Error('記録ファイルの形式が違います。');
    var out = { racer: {}, motor: {}, fav: {}, bets: [], budget: 0 };
    GROUPS.forEach(function (g) {
      var box = x[g] || {};
      if (!plain(box) || Object.keys(box).length > 10000) throw new Error('記録の件数が多すぎます。');
      Object.keys(box).forEach(function (k) {
        var v = box[k];
        if (!safeKey(k) || !plain(v)) throw new Error('記録の形式を確認してください。');
        var row = {};
        ['name', 'text', 't', 'jcd', 'no', 'venue'].forEach(function (f) {
          if (v[f] != null) {
            if (!['string', 'number'].includes(typeof v[f]) || String(v[f]).length > (f === 'text' ? 20000 : 200)) throw new Error('記録の文字数が多すぎます。');
            row[f] = String(v[f]);
          }
        });
        if (g === 'motor' && v.favorite === true) row.favorite = true;
        if (g !== 'fav' && !row.text && !row.favorite) return;
        out[g][k] = row;
      });
    });
    if (!Array.isArray(x.bets || []) || (x.bets || []).length > 20000) throw new Error('収支の件数が多すぎます。');
    var seen = new Set();
    (x.bets || []).forEach(function (b) {
      if (!plain(b) || !safeKey(b.id) || seen.has(b.id) || !/^\d{8}$/.test(b.date || '') || !amount(b.inv || 0) || !amount(b.ret || 0)) throw new Error('収支の形式を確認してください。');
      seen.add(b.id);
      var row = { id: b.id, date: b.date, inv: b.inv || 0, ret: b.ret || 0 };
      ['memo', 'venue', 'jcd'].forEach(function (f) { if (b[f] != null) { if (typeof b[f] !== 'string' || b[f].length > 2000) throw new Error('収支の文字数が多すぎます。'); row[f] = b[f]; } });
      if (b.rno != null) { if (!Number.isInteger(+b.rno) || +b.rno < 1 || +b.rno > 12) throw new Error('レース番号を確認してください。'); row.rno = +b.rno; }
      out.bets.push(row);
    });
    if (!amount(x.budget || 0)) throw new Error('予算を確認してください。');
    out.budget = x.budget || 0;
    if (new TextEncoder().encode(JSON.stringify(out)).length > 1000000) throw new Error('記録が大きすぎます。ファイルに保存して整理してください。');
    return out;
  }
  function empty() { return normalize({}); }
  function flatten(data) {
    var d = normalize(data), cells = {};
    GROUPS.forEach(function (g) { Object.keys(d[g]).sort().forEach(function (k) { cells[g + ':' + k] = d[g][k]; }); });
    d.bets.forEach(function (b) { cells['bet:' + b.id] = b; });
    cells.budget = d.budget;
    return cells;
  }
  function inflate(cells) {
    var d = empty();
    Object.keys(cells).sort().forEach(function (k) {
      if (cells[k] == null) return;
      if (k === 'budget') { d.budget = cells[k]; return; }
      var i = k.indexOf(':'), g = k.slice(0, i), id = k.slice(i + 1);
      if (g === 'bet') d.bets.push(cells[k]);
      else if (GROUPS.includes(g) && safeKey(id)) d[g][id] = cells[k];
    });
    return normalize(d);
  }
  function changes(before, after) {
    var a = flatten(before), b = flatten(after), result = [];
    Array.from(new Set(Object.keys(a).concat(Object.keys(b)))).sort().forEach(function (k) {
      if (!same(a[k], b[k])) result.push({ key: k, before: a[k] == null ? null : a[k], value: b[k] == null ? null : b[k] });
    });
    return copy(result);
  }
  function rebase(remote, ops) {
    var cells = flatten(remote), conflicts = [], acknowledged = [], blocked = new Set();
    var last = {}, alreadySaved = new Set();
    ops.forEach(function (op) { last[op.key] = op; });
    Object.keys(last).forEach(function (k) { if (same(cells[k], last[k].value)) alreadySaved.add(k); });
    ops.forEach(function (op) {
      if (!plain(op) || !safeKey(op.key)) throw new Error('未同期の記録を確認してください。');
      if (alreadySaved.has(op.key)) { acknowledged.push(op.id); return; }
      var current = cells[op.key] == null ? null : cells[op.key];
      if (blocked.has(op.key)) { conflicts.push({ op: op, remote: current }); return; }
      if (same(current, op.value)) { acknowledged.push(op.id); return; }
      if (same(current, op.before)) {
        if (op.value == null) delete cells[op.key]; else cells[op.key] = copy(op.value);
        acknowledged.push(op.id);
      } else { blocked.add(op.key); conflicts.push({ op: op, remote: copy(current) }); }
    });
    return { data: inflate(cells), conflicts: conflicts, acknowledged: acknowledged };
  }
  function overlay(remote, ops) {
    var cells = flatten(remote);
    ops.forEach(function (op) { if (op.value == null) delete cells[op.key]; else cells[op.key] = copy(op.value); });
    return inflate(cells);
  }
  function importGuest(cloud, guest) {
    // Only fill missing records. Conflicting text/amounts require an explicit choice.
    var a = flatten(cloud), b = flatten(guest), conflicts = [];
    Object.keys(b).forEach(function (k) {
      if (k === 'budget' && !b[k]) return;
      if (a[k] == null || (k === 'budget' && !a[k])) a[k] = b[k];
      else if (!same(a[k], b[k])) conflicts.push({ key: k, cloud: a[k], guest: b[k] });
    });
    return { data: inflate(a), conflicts: conflicts };
  }
  return { copy: copy, same: same, normalize: normalize, empty: empty, flatten: flatten, inflate: inflate, changes: changes, rebase: rebase, overlay: overlay, importGuest: importGuest };
});
