"""The single-page client UI served by the web console (unit W2).

Self-contained HTML (inline CSS + JS, no external assets) so the stdlib server
can serve it as one string. Spanish UI, theme-aware, mobile-friendly.
"""

PAGE_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentTrust — tu agente contrata el trabajo</title>
<style>
  :root {
    --bg: #0f1220; --card: #1a1e33; --fg: #e8eaf2; --muted: #9aa0bd;
    --accent: #6ea8fe; --ok: #57d9a3; --bad: #ff7a90; --line: #2a2f4a;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f4f6fb; --card:#fff; --fg:#161a2b; --muted:#5b6178;
            --accent:#2f6fed; --ok:#12925f; --bad:#c0334b; --line:#e2e6f0; }
  }
  /* Manual override via the floating switch (wins over the OS preference). */
  :root[data-theme="dark"] {
    --bg:#0f1220; --card:#1a1e33; --fg:#e8eaf2; --muted:#9aa0bd;
    --accent:#6ea8fe; --ok:#57d9a3; --bad:#ff7a90; --line:#2a2f4a;
  }
  :root[data-theme="light"] {
    --bg:#f4f6fb; --card:#fff; --fg:#161a2b; --muted:#5b6178;
    --accent:#2f6fed; --ok:#12925f; --bad:#c0334b; --line:#e2e6f0;
  }
  .theme-toggle {
    position: fixed; top: 16px; right: 16px; z-index: 50;
    width: 46px; height: 46px; border-radius: 999px;
    border: 1px solid var(--line); background: var(--card); color: var(--fg);
    font-size: 1.25rem; line-height: 1; cursor: pointer;
    box-shadow: 0 6px 18px rgba(0,0,0,.18); transition: transform .15s;
  }
  .theme-toggle:hover { transform: scale(1.08); }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
    font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  .wrap { max-width: 680px; margin: 0 auto; padding: 32px 20px 64px; }
  h1 { font-size: 1.7rem; margin: 0 0 4px; }
  .sub { color: var(--muted); margin: 0 0 28px; }
  .card { background:var(--card); border:1px solid var(--line);
    border-radius:14px; padding:22px; margin-bottom:20px; }
  label { display:block; font-weight:600; margin:14px 0 6px; }
  input, select { width:100%; padding:11px 12px; border-radius:9px;
    border:1px solid var(--line); background:var(--bg); color:var(--fg);
    font-size:1rem; }
  button { margin-top:20px; width:100%; padding:13px; border:0;
    border-radius:10px; background:var(--accent); color:#fff; font-size:1rem;
    font-weight:600; cursor:pointer; }
  button:disabled { opacity:.6; cursor:progress; }
  button.approve { background:var(--ok); margin-top:14px; }
  .hidden { display:none; }
  .badge { display:inline-block; padding:3px 10px; border-radius:999px;
    font-size:.8rem; font-weight:700; }
  .badge.ok { background:rgba(87,217,163,.16); color:var(--ok); }
  .badge.bad { background:rgba(255,122,144,.16); color:var(--bad); }
  .meta { color:var(--muted); margin:12px 0; }
  .meta b { color:var(--fg); }
  pre { background:var(--bg); border:1px solid var(--line); border-radius:10px;
    padding:14px; overflow:auto; max-height:320px; font-size:.82rem; }
  .err { color:var(--bad); }
  .foot { color:var(--muted); font-size:.82rem; margin-top:28px; }
  .provider { margin-top:28px; }
  .provider h2 { font-size:1.15rem; margin:0 0 4px; }
  .sub2 { color:var(--muted); font-size:.9rem; margin:0 0 6px; }
  button.secondary { background:transparent; border:1px solid var(--accent);
    color:var(--accent); }
  .pmsg { margin-top:14px; font-size:.92rem; }
  .pmsg.ok { color:var(--ok); }
  .pmsg.bad { color:var(--bad); }
  .auth-panel { display: flex; gap: 10px; margin-bottom: 20px; }
  .auth-panel button { margin: 0; width: auto; padding: 10px 16px; }
  .auth-form { display: none; }
  .auth-form.show { display: block; }
  .reputation-card { background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; padding: 22px; margin-bottom: 20px; }
  .reputation-item { margin: 8px 0; }
  .reputation-label { color: var(--muted); font-size: 0.9rem; }
  .reputation-value { font-weight: 600; color: var(--ok); }
  .user-info { color: var(--muted); margin-bottom: 16px; }
</style>
</head>
<body>
<button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()"
  aria-label="Cambiar tema" title="Cambiar entre claro y oscuro">🌙</button>
<div class="wrap">
  <h1>AgentTrust</h1>
  <p class="sub">Decí qué necesitás. Tu agente busca un proveedor, negocia el
  precio y trae el trabajo — verificado por un tercero independiente.</p>

  <div class="auth-panel">
    <button id="login-btn" onclick="showAuthForm('login')">Acceder</button>
    <button id="register-btn" onclick="showAuthForm('register')">Registrarse</button>
    <button id="logout-btn" class="hidden secondary" onclick="logout()">Salir</button>
  </div>

  <div id="reputation-display" class="reputation-card hidden">
    <h2>Tu Reputación</h2>
    <div id="reputation-content"></div>
  </div>

  <div id="auth-login" class="auth-form card">
    <h2>Acceder a AgentTrust</h2>
    <label for="login-principal">Tu Principal (clave ed25519)</label>
    <textarea id="login-principal" placeholder="Pega tu principal aquí (base64 o hex de tu clave ed25519)"
      style="min-height: 100px; font-family: monospace; font-size: 0.85rem;"></textarea>
    <button onclick="performLogin()">Acceder</button>
    <div id="login-msg" class="hidden"></div>
  </div>

  <div id="auth-register" class="auth-form card">
    <h2>Registrarse en AgentTrust</h2>
    <p class="sub2">Para comenzar, pega tu principal (clave ed25519).
    Si no tenés uno, podés generar uno externo con ferramentas como tweetnacl.js.</p>
    <label for="register-principal">Tu Principal (clave ed25519)</label>
    <textarea id="register-principal" placeholder="Pega tu principal aquí (base64 o hex de tu clave ed25519)"
      style="min-height: 100px; font-family: monospace; font-size: 0.85rem;"></textarea>
    <button onclick="performRegister()">Registrarse</button>
    <div id="register-msg" class="hidden"></div>
  </div>

  <div class="card">
    <label for="text">¿Qué necesitás?</label>
    <input id="text" type="text" autocomplete="off"
      placeholder="Ej: necesito infra para una app web con 3 contenedores"
      onkeydown="if(event.key==='Enter')run()">
    <button id="go" onclick="run()">Pedirlo a mi agente</button>
  </div>

  <div id="result" class="card hidden"></div>

  <div class="card provider">
    <h2>¿Tenés un agente proveedor?</h2>
    <p class="sub2">Registralo sin CLI: pegá la URL donde corre tu agente y el
    sistema lee su Agent Card, valida que hable la capa de confianza, y lo suma
    a la red para que compita por tareas.</p>
    <label for="purl">URL de tu agente</label>
    <input id="purl" type="text" autocomplete="off"
      placeholder="http://127.0.0.1:8200"
      onkeydown="if(event.key==='Enter')registerProvider()">
    <button id="pgo" class="secondary" onclick="registerProvider()">Registrar mi agente</button>
    <div id="presult" class="pmsg hidden"></div>
  </div>

  <p class="foot">MVP demo: la tarea es generación de infraestructura Terraform
  (la capacidad con verificación objetiva). El traductor de lenguaje natural y
  más capacidades son pasos siguientes.</p>
</div>

<script>
// Session management
const SESSION_STORAGE_KEY = 'agentTrust_session';

function getSession() {
  try {
    var saved = localStorage.getItem(SESSION_STORAGE_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch (e) {
    return null;
  }
}

function setSession(session) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch (e) {}
  updateUIForSession();
}

function clearSession() {
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch (e) {}
  updateUIForSession();
}

function updateUIForSession() {
  var session = getSession();
  var loginBtn = document.getElementById('login-btn');
  var registerBtn = document.getElementById('register-btn');
  var logoutBtn = document.getElementById('logout-btn');
  var authForms = document.querySelectorAll('.auth-form');
  var repDisplay = document.getElementById('reputation-display');

  if (session && session.principal_id) {
    // User is logged in
    loginBtn.classList.add('hidden');
    registerBtn.classList.add('hidden');
    logoutBtn.classList.remove('hidden');
    authForms.forEach(f => f.classList.remove('show'));
    loadAndDisplayReputation(session.principal_id);
  } else {
    // User is not logged in
    loginBtn.classList.remove('hidden');
    registerBtn.classList.remove('hidden');
    logoutBtn.classList.add('hidden');
    repDisplay.classList.add('hidden');
  }
}

async function loadAndDisplayReputation(principal_id) {
  try {
    var resp = await fetch('/api/reputation/' + encodeURIComponent(principal_id));
    if (!resp.ok) {
      console.error('Could not load reputation:', resp.status);
      return;
    }
    var data = await resp.json();
    displayReputation(data, principal_id);
  } catch (e) {
    console.error('Error loading reputation:', e);
  }
}

function displayReputation(data, principal_id) {
  var repDisplay = document.getElementById('reputation-display');
  var repContent = document.getElementById('reputation-content');

  var html = '<p class="user-info">Principal: <code style="font-size: 0.85rem; color: var(--fg);">' +
    esc(principal_id.substring(0, 20)) + '...</code></p>';

  var rep = data.reputation_records || [];
  if (rep.length === 0) {
    html += '<p class="reputation-item">Aún sin historial de tareas.</p>';
  } else {
    var totalVerified = 0, totalRejected = 0;
    rep.forEach(function(r) {
      totalVerified += r.tasks_verified || 0;
      totalRejected += r.tasks_rejected || 0;
    });

    html += '<div class="reputation-item">' +
      '<div class="reputation-label">Tareas verificadas</div>' +
      '<div class="reputation-value">' + totalVerified + '</div></div>';
    html += '<div class="reputation-item">' +
      '<div class="reputation-label">Tareas rechazadas</div>' +
      '<div class="reputation-value">' + totalRejected + '</div></div>';

    if (totalVerified + totalRejected > 0) {
      var rate = totalVerified / (totalVerified + totalRejected);
      html += '<div class="reputation-item">' +
        '<div class="reputation-label">Tasa de verificación</div>' +
        '<div class="reputation-value">' + (rate * 100).toFixed(1) + '%</div></div>';
    }
  }

  repContent.innerHTML = html;
  repDisplay.classList.remove('hidden');
}

function showAuthForm(form) {
  var login = document.getElementById('auth-login');
  var register = document.getElementById('auth-register');

  if (form === 'login') {
    login.classList.add('show');
    register.classList.remove('show');
  } else {
    login.classList.remove('show');
    register.classList.add('show');
  }
}

async function performRegister() {
  var principal = document.getElementById('register-principal').value.trim();
  var msg = document.getElementById('register-msg');

  if (!principal) {
    msg.className = 'pmsg bad';
    msg.textContent = 'Pegá tu principal.';
    msg.classList.remove('hidden');
    return;
  }

  msg.classList.add('hidden');
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Registrando…';

  try {
    var resp = await fetch('/api/auth/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({principal_id: principal})
    });
    var data = await resp.json();

    if (resp.ok) {
      setSession({principal_id: data.principal_id});
      msg.className = 'pmsg ok';
      msg.innerHTML = '✓ Registrado. Accediendo...';
      msg.classList.remove('hidden');
      setTimeout(function() {
        document.getElementById('register-principal').value = '';
      }, 1500);
    } else {
      msg.className = 'pmsg bad';
      msg.textContent = data.error || 'No se pudo registrar.';
      msg.classList.remove('hidden');
    }
  } catch (e) {
    msg.className = 'pmsg bad';
    msg.textContent = 'Error: ' + e;
    msg.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Registrarse';
  }
}

async function performLogin() {
  var principal = document.getElementById('login-principal').value.trim();
  var msg = document.getElementById('login-msg');

  if (!principal) {
    msg.className = 'pmsg bad';
    msg.textContent = 'Pegá tu principal.';
    msg.classList.remove('hidden');
    return;
  }

  msg.classList.add('hidden');
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Accediendo…';

  try {
    var resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({principal_id: principal})
    });
    var data = await resp.json();

    if (resp.ok) {
      setSession({principal_id: data.principal_id});
      msg.className = 'pmsg ok';
      msg.innerHTML = '✓ Acceso concedido.';
      msg.classList.remove('hidden');
      setTimeout(function() {
        document.getElementById('login-principal').value = '';
      }, 1500);
    } else {
      msg.className = 'pmsg bad';
      msg.textContent = data.error || 'No se pudo acceder.';
      msg.classList.remove('hidden');
    }
  } catch (e) {
    msg.className = 'pmsg bad';
    msg.textContent = 'Error: ' + e;
    msg.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Acceder';
  }
}

function logout() {
  clearSession();
  document.getElementById('login-principal').value = '';
  document.getElementById('register-principal').value = '';
}

async function run() {
  var btn = document.getElementById('go');
  var res = document.getElementById('result');
  btn.disabled = true; btn.textContent = 'Buscando y negociando…';
  res.classList.remove('hidden');
  res.innerHTML = '<p class="meta">Tu agente está descubriendo proveedores, ' +
    'negociando y esperando la verificación…</p>';
  try {
    var r = await fetch('/api/task', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ text: document.getElementById('text').value })
    });
    var o = await r.json();
    if (!r.ok) { res.innerHTML = '<p class="err">Error: ' + (o.error||'') + '</p>'; return; }
    render(o);
  } catch (e) {
    res.innerHTML = '<p class="err">No se pudo completar: ' + e + '</p>';
  } finally {
    btn.disabled = false; btn.textContent = 'Pedirlo a mi agente';
  }
}

function render(o) {
  var res = document.getElementById('result');
  if (o.status === 'verified') {
    var tf = (o.artifacts && o.artifacts['main.tf']) || '';
    var understood = o.interpretation
      ? '<p class="meta">Tu agente entendió: <b>' + esc(o.interpretation) + '</b></p>'
      : '';
    res.innerHTML = understood +
      '<span class="badge ok">✓ Verificado independientemente</span>' +
      '<p class="meta">Contratado: <b>' + esc(o.provider_name) + '</b><br>' +
      'Pagaste <b>' + o.price_paid + ' ' + (o.currency||'') + '</b> · ' +
      'compitieron <b>' + o.offers_considered + '</b> ofertas</p>' +
      '<pre>' + esc(tf) + '</pre>' +
      '<button class="approve" onclick="approve(this)">Aprobar y quedármelo</button>';
  } else {
    res.innerHTML =
      '<span class="badge bad">No completado (' + esc(o.status) + ')</span>' +
      '<p class="meta">' + esc(o.reason || '') + '</p>';
  }
}

function approve(btn) {
  btn.disabled = true;
  btn.textContent = '✓ Aprobado — tu agente completó la tarea';
}

async function registerProvider() {
  var btn = document.getElementById('pgo');
  var out = document.getElementById('presult');
  btn.disabled = true; btn.textContent = 'Registrando…';
  out.className = 'pmsg'; out.textContent = 'Leyendo tu Agent Card…';
  try {
    var r = await fetch('/api/register-provider', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url: document.getElementById('purl').value })
    });
    var o = await r.json();
    if (r.ok && o.registered) {
      out.className = 'pmsg ok';
      out.innerHTML = '✓ Registrado: <b>' + esc(o.name || o.principal_id) +
        '</b> · capacidades: ' + esc((o.capabilities || []).join(', ')) +
        '. Ya compite por tareas.';
    } else {
      out.className = 'pmsg bad'; out.textContent = o.error || 'No se pudo registrar.';
    }
  } catch (e) {
    out.className = 'pmsg bad'; out.textContent = 'Error: ' + e;
  } finally {
    btn.disabled = false; btn.textContent = 'Registrar mi agente';
  }
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function currentTheme() {
  var explicit = document.documentElement.getAttribute('data-theme');
  if (explicit) return explicit;
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark' : 'light';
}

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  // Show the icon of what a click will switch TO: moon = go dark, sun = go light.
  document.getElementById('theme-toggle').textContent = t === 'dark' ? '☀️' : '🌙';
}

function toggleTheme() {
  var next = currentTheme() === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  try { localStorage.setItem('theme', next); } catch (e) {}
}

(function () {
  var saved = null;
  try { saved = localStorage.getItem('theme'); } catch (e) {}
  applyTheme(saved === 'dark' || saved === 'light' ? saved : currentTheme());
  // Initialize session UI
  updateUIForSession();
})();
</script>
</body>
</html>
"""
