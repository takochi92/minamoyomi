(function () {
  'use strict';
  if (location.origin !== 'https://teilog.com') return;
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', {scope:'/',updateViaCache:'none'}).catch(function () {});
    });
  }
  var pending, button = document.getElementById('install-app'), status = document.getElementById('install-status');
  function installed() { return window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true; }
  function showInstalled() {
    if (button) button.hidden = true;
    if (status) status.textContent = 'ホーム画面から起動しています。';
  }
  if (installed()) showInstalled();
  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault(); pending = event;
    if (button && !installed()) button.hidden = false;
  });
  if (button) button.addEventListener('click', async function () {
    if (!pending) return;
    var prompt = pending; pending = null; button.hidden = true;
    try {
      await prompt.prompt(); var choice = await prompt.userChoice;
      if (status) status.textContent = choice.outcome === 'accepted' ? '追加が完了したら、ホーム画面の「艇ろぐ」から開けます。' : 'あとからブラウザのメニューでも追加できます。';
    } catch (_) { if (status) status.textContent = '下の手順でブラウザのメニューから追加してください。'; }
  });
  window.addEventListener('appinstalled', function () {
    pending = null; if (button) button.hidden = true;
    if (status) status.textContent = '追加しました。ホーム画面の「艇ろぐ」から開けます。';
  });
})();
