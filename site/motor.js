/* Move existing cards so open history, notes and favorites stay intact. */
(() => {
  const select = document.getElementById('motor-sort');
  const list = document.querySelector('.mt-list');
  if (!select || !list) return;
  const cards = Array.from(list.children).filter(node => node.classList.contains('mt'));
  const allowed = new Set(Array.from(select.options, option => option.value));
  const storageKey = 'teilog.motor.sort';
  const value = (card, key) => {
    const raw = card.dataset[key];
    return raw == null || raw === '' || !Number.isFinite(Number(raw)) ? null : Number(raw);
  };
  const sort = () => {
    const key = allowed.has(select.value) ? select.value : 'top2';
    cards.sort((a, b) => {
      const av = value(a, key), bv = value(b, key);
      if (av == null || bv == null) {
        if (av !== bv) return av == null ? 1 : -1;
      } else if (av !== bv) return key === 'number' ? av - bv : bv - av;
      return Number(a.dataset.number) - Number(b.dataset.number);
    });
    const fragment = document.createDocumentFragment();
    cards.forEach(card => fragment.appendChild(card));
    list.appendChild(fragment);
    document.getElementById('motor-sort-status').textContent = `${cards.length}基`;
  };
  try {
    const saved = localStorage.getItem(storageKey);
    if (allowed.has(saved)) select.value = saved;
  } catch (_) { /* Sorting also works when browser storage is unavailable. */ }
  sort();
  select.addEventListener('change', () => {
    sort();
    try { localStorage.setItem(storageKey, select.value); } catch (_) {}
  });
})();
