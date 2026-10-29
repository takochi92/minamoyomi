/* Date navigation only: today's pages keep their existing live update. */
(() => {
  document.querySelectorAll('.day-picker').forEach(form => {
    const input = form.querySelector('input[type=date]'), status = form.querySelector('[role=alert]');
    form.addEventListener('submit', event => {
      event.preventDefault();
      const value = input.value;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value < input.min || value > input.max || !input.checkValidity()) {
        status.textContent = '過去1か月から今日までの日付を選んでください。';
        return;
      }
      const date = value.replace(/-/g, '');
      if (date === form.dataset.today) { location.assign(form.dataset.current); return; }
      const home = new URL(form.dataset.home, location.href);
      const target = new URL(`races/${date}.html`, home);
      if (form.dataset.venue) target.hash = 'v' + form.dataset.venue;
      location.assign(target.href);
    });
  });
  function openVenue() {
    if (/^#v\d{2}$/.test(location.hash)) {
      const venue = document.querySelector(location.hash);
      if (venue && venue.classList.contains('archive-venue')) venue.open = true;
    }
  }
  window.addEventListener('hashchange', openVenue);
  openVenue();
})();
