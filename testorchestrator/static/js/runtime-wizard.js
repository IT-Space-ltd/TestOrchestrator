/* Guided Add Runtime (M16): show only the toolchain fieldset for
 * the chosen framework; hidden fieldsets are disabled so
 * incompatible settings are never submitted. */
(function () {
  var form = document.getElementById("runtime-wizard");
  if (!form) return;
  function sync() {
    var fw = form.querySelector("input[name=framework]:checked");
    form.querySelectorAll(".fw-cfg").forEach(function (fs) {
      var on = fw && fs.dataset.fw === fw.value;
      fs.hidden = !on;
      fs.disabled = !on;
    });
  }
  form.addEventListener("change", sync);
  sync();
})();
