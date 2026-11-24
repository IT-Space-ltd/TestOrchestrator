/* Guided Add Storage: show only the field group for the chosen
 * destination type; hidden groups are disabled so incompatible
 * settings are never submitted. */
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
  }
  form.addEventListener("change", sync);
  sync();
})();
