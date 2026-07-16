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
</style>
</head>
<body>
<div class="wrap">
  <h1>AgentTrust</h1>
  <p class="sub">Decí qué necesitás. Tu agente busca un proveedor, negocia el
  precio y trae el trabajo — verificado por un tercero independiente.</p>

  <div class="card">
    <label for="text">¿Qué necesitás?</label>
    <input id="text" type="text" autocomplete="off"
      placeholder="Ej: necesito infra para una app web con 3 contenedores"
      onkeydown="if(event.key==='Enter')run()">
    <button id="go" onclick="run()">Pedirlo a mi agente</button>
  </div>

  <div id="result" class="card hidden"></div>

  <p class="foot">MVP demo: la tarea es generación de infraestructura Terraform
  (la capacidad con verificación objetiva). El traductor de lenguaje natural y
  más capacidades son pasos siguientes.</p>
</div>

<script>
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

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
</script>
</body>
</html>
"""
