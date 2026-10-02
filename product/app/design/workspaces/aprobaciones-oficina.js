(function () {
  "use strict";
  function tr(key, fallback) {
    var value = window.AlephI18n && window.AlephI18n.t ? window.AlephI18n.t(key) : key;
    return value && value !== key ? value : fallback;
  }
  var dialog = document.createElement("dialog");
  dialog.setAttribute("aria-label", tr("ws.office.approval_aria", "Guardar archivo de Oficina"));
  dialog.style.cssText = "max-width:520px;width:calc(100% - 48px);padding:24px;border:1px solid #aaa;border-radius:14px;margin:auto;color:#222;background:#fff;box-shadow:0 16px 60px #0005";
  var title = document.createElement("h2");
  title.textContent = tr("ws.office.approval_title", "Guardar archivo");
  var description = document.createElement("p");
  description.textContent = tr("ws.office.approval_description", "El editor de Oficina solicita guardar cambios en:");
  var path = document.createElement("p");
  path.style.cssText = "overflow-wrap:anywhere;font-weight:600;margin:16px 0";
  var error = document.createElement("p");
  error.setAttribute("role", "status");
  var actions = document.createElement("div");
  actions.style.cssText = "display:flex;gap:12px;justify-content:flex-end";
  var deny = document.createElement("button");
  deny.textContent = tr("ws.office.approval_deny", "Rechazar");
  var allow = document.createElement("button");
  allow.textContent = tr("ws.office.approval_allow", "Guardar cambio");
  [deny, allow].forEach(function (button) { button.style.cssText = "padding:9px 16px;border:1px solid #999;border-radius:8px;cursor:pointer"; actions.appendChild(button); });
  [title, description, path, error, actions].forEach(function (node) { dialog.appendChild(node); });
  document.body.appendChild(dialog);
  var current = null;
  var busy = false;
  function headers() {
    var user = window.AlephSession && window.AlephSession.get && window.AlephSession.get();
    return user && user.session_token ? { Authorization: "Bearer " + user.session_token } : null;
  }
  async function poll() {
    if (busy || document.hidden) return;
    var auth = headers();
    if (!auth) return;
    try {
      var response = await fetch("/v1/workspaces/oficina/aprobaciones", { headers: auth });
      if (!response.ok) return;
      var data = await response.json();
      current = data.items && data.items[0];
      if (!current) { if (dialog.open) dialog.close(); return; }
      path.textContent = (current.summary || "").replace(/^Write /, "");
      if (!dialog.open) { error.textContent = ""; dialog.showModal(); }
    } catch (_) { /* Next poll retries while the pack starts/restarts. */ }
  }
  async function decide(permitted) {
    if (!current || busy) return;
    busy = true; allow.disabled = deny.disabled = true;
    try {
      var response = await fetch("/v1/workspaces/oficina/aprobaciones/" + encodeURIComponent(current.id) + "?permitir=" + permitted,
        { method: "POST", headers: headers() || {} });
      if (!response.ok) throw new Error(tr("ws.office.approval_error", "No se pudo registrar la decisión. Intenta de nuevo."));
      current = null; dialog.close();
    } catch (cause) { error.textContent = cause.message; }
    finally { busy = false; allow.disabled = deny.disabled = false; }
  }
  allow.addEventListener("click", function () { decide(true); });
  deny.addEventListener("click", function () { decide(false); });
  dialog.addEventListener("cancel", function (event) { event.preventDefault(); decide(false); });
  window.setInterval(poll, 1500);
})();
