/* CSP-safe replacements for former inline <script>/onX= handlers.
 * Everything here is delegated or element-presence-guarded — included
 * once from base.html and inert on pages without the target elements. */
(function () {
  "use strict";

  // --- data-confirm: former onsubmit/onclick="return confirm('…')" ---
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute &&
      e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest("[data-confirm]");
    if (el && !window.confirm(el.getAttribute("data-confirm"))) {
      e.preventDefault();
      e.stopPropagation();
    }
    // data-check-group: select-all / clear checkboxes in a group
    var tog = e.target.closest && e.target.closest("[data-check-group]");
    if (tog) {
      var on = tog.getAttribute("data-check-on") === "1";
      document.querySelectorAll(tog.getAttribute("data-check-group"))
        .forEach(function (c) { c.checked = on; });
    }
    // data-check-radio: reveal a CSS-radiogroup tab (e.g. releases)
    var rc = e.target.closest && e.target.closest("[data-check-radio]");
    if (rc) {
      var r = document.getElementById(
        rc.getAttribute("data-check-radio"));
      if (r) { r.checked = true; }
      e.preventDefault();
    }
  });

  // --- project filter on user/project access pages ---
  var pf = document.getElementById("proj-filter");
  if (pf) {
    pf.addEventListener("input", function () {
      var q = pf.value.toLowerCase();
      document.querySelectorAll(".proj-row").forEach(function (r) {
        r.style.display = (r.dataset.name || "")
          .includes(q) ? "" : "none";
      });
    });
  }

  // --- SSH fields reveal on the add-target form ---
  var sshBox = document.getElementById("ssh-fields");
  if (sshBox) {
    var syncSsh = function () {
      var sel = document.querySelector(
        '#target-type-field input[name="target_type"]:checked');
      sshBox.style.display = (sel && sel.value === "ssh") ? "" : "none";
    };
    document.querySelectorAll(
      '#target-type-field input[name="target_type"]'
    ).forEach(function (r) {
      r.addEventListener("change", syncSsh);
    });
    syncSsh();
  }

  // --- account page: detected time zone suggestion ---
  try {
    var detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    var input = document.getElementById("timezone");
    if (detected && input && detected !== input.value) {
      var note = document.getElementById("tz-detect-note");
      var txt = document.getElementById("tz-detected");
      var btn = document.getElementById("tz-use-detected");
      if (note && txt && btn) {
        txt.textContent = detected;
        note.hidden = false;
        btn.addEventListener("click", function () {
          if (!input.querySelector(
            'option[value="' + detected + '"]')) {
            var o = document.createElement("option");
            o.value = o.textContent = detected;
            input.appendChild(o);
          }
          input.value = detected;
        });
      }
    }
  } catch (e) { /* detection unavailable — page works without it */ }
})();
