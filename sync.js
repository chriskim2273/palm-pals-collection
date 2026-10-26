/* PalmSync client: PIN gate + server sync for the Palm Pals gallery.
 * Runs after the gallery's own script. Wraps its persist() so every change
 * is saved locally (offline cache) and pushed to /api/state (server file).
 */
(function () {
'use strict';
var TOKEN_KEY = 'palmPals.syncToken';
var token = null;
try {
  token = sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || null;
} catch (e) { token = null; }

var pushTimer = null;

function gate() { return document.getElementById('pinGate'); }
function gateError(msg) {
  var el = document.getElementById('pinError');
  if (!el) return;
  el.textContent = msg || '';
  el.hidden = !msg;
}
function showGate(msg) {
  gateError(msg || '');
  gate().hidden = false;
  document.body.classList.add('pinLocked');
  setTimeout(function () {
    var i = document.getElementById('pinInput');
    if (i) i.focus();
  }, 60);
}
function hideGate() {
  gate().hidden = true;
  document.body.classList.remove('pinLocked');
}

function forgetToken() {
  token = null;
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
  } catch (e) {}
}

function schedulePush() {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(pushNow, 1500);
}

function pushNow() {
  if (!token) return;
  fetch('/api/state', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
    body: JSON.stringify(state)
  }).then(function (r) {
    if (r.status === 401) {
      forgetToken();
      showGate('Session expired. Enter your PIN again.');
      return;
    }
    if (!r.ok) throw new Error('push failed');
    status('Saved on your private server · Backups still recommended.');
  }).catch(function () {
    status('Saved in this browser · Server sync failed — will retry on next change.', true);
  });
}

function pull() {
  return fetch('/api/state', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(function (r) {
      if (r.status === 401) return 'unauth';
      if (!r.ok) throw new Error('pull failed');
      return r.json();
    })
    .then(function (srv) {
      if (srv === 'unauth') return 'unauth';
      try {
        var fresh = validate(srv);
        if (fresh.updatedAt > state.updatedAt) {
          state = fresh;
          localPersist();
          render();
        }
      } catch (e) { /* keep local state on bad payload */ }
      return 'ok';
    });
}

// Wrap the gallery's own persist(): local write-through + debounced push.
var localPersist = persist;
persist = function () {
  localPersist();
  schedulePush();
};

function doUnlock() {
  var input = document.getElementById('pinInput');
  var remember = document.getElementById('pinRemember');
  var go = document.getElementById('pinGo');
  var pin = (input.value || '').trim();
  if (!pin) { gateError('Enter your PIN.'); return; }
  go.disabled = true;
  gateError('');
  fetch('/api/unlock', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pin: pin })
  }).then(function (r) {
    return r.json().then(function (d) {
      if (!r.ok) throw new Error((d && d.error) || 'Unlock failed.');
      return d;
    });
  }).then(function (d) {
    token = d.token;
    try {
      if (remember && remember.checked) {
        localStorage.setItem(TOKEN_KEY, token);
        sessionStorage.removeItem(TOKEN_KEY);
      } else {
        sessionStorage.setItem(TOKEN_KEY, token);
        localStorage.removeItem(TOKEN_KEY);
      }
    } catch (e) {}
    input.value = '';
    return pull();
  }).then(function (res) {
    if (res === 'unauth') throw new Error('Session rejected. Try again.');
    hideGate();
    status('Unlocked · Your collection saves on your private server.');
  }).catch(function (err) {
    gateError(err.message || 'Unlock failed.');
  }).finally(function () {
    go.disabled = false;
  });
}

document.getElementById('pinGo').addEventListener('click', doUnlock);
document.getElementById('pinInput').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') doUnlock();
});

// Boot: existing token -> try silent sync, else show the gate.
if (token) {
  pull().then(function (res) {
    if (res === 'ok') {
      hideGate();
      status('Unlocked · Your collection saves on your private server.');
    } else {
      forgetToken();
      showGate('');
    }
  }).catch(function () {
    // Server unreachable: stay usable on the local copy, gate on next save.
    hideGate();
    status('Server unreachable · Changes save in this browser for now.', true);
  });
} else {
  showGate('');
}
})();
