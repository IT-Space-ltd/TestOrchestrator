/* Guided Add Storage: show only the field group for the chosen
 * destination type and, inside object storage, the chosen provider;
 * hidden groups are disabled so incompatible settings are never
 * submitted. */
(function () {
  var form = document.getElementById("add-store-form");
  if (!form) return;
  function sync() {
    var kind = form.querySelector("input[name=kind]:checked");
    form.querySelectorAll(".store-cfg").forEach(function (fs) {
      var on = kind && fs.dataset.kind === kind.value;
      fs.hidden = !on;
      fs.disabled = !on;
    });
    var provider = form.querySelector("select[name=provider]");
    var pv = provider && provider.value;
    form.querySelectorAll(".provider-cfg").forEach(function (fs) {
      var on = kind && kind.value === "object" &&
               fs.dataset.provider === pv;
      fs.hidden = !on;
      fs.disabled = !on;
    });
  }
  form.addEventListener("change", sync);
  sync();
})();

/* Cancel buttons inside <details> disclosure forms: data-close-details
 * carries the target details id — no inline handlers (CSP). */
document.addEventListener("click", function (ev) {
  var btn = ev.target.closest("[data-close-details]");
  if (!btn) return;
  var d = document.getElementById(btn.getAttribute("data-close-details"));
  if (d) d.open = false;
});
