/* Advanced analytics — on-demand refresh + drill-through.
 * Deliberately NOT wired into the ~5 s live poll: charts are fetched on
 * load and on Refresh only, so an in-progress investigation is never
 * repainted mid-inspection. uirevision in each figure preserves zoom and
 * legend toggles across compatible updates. Single in-flight request;
 * a slow response can never overwrite a newer one (request serial). */
(function () {
  var script = document.currentScript;
  var url = script && script.dataset.url;
  if (!url) return;

  var btn = document.getElementById("adv-refresh");
  var updatedEl = document.getElementById("adv-updated");
  var inFlight = false, serial = 0;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;",
              '"': "&quot;", "'": "&#39;"}[c];
    });
  }

  function draw(key, fig) {
    var el = document.querySelector("[data-adv='" + key + "']");
    if (!el || typeof Plotly === "undefined") return;
    if (!fig || !fig.data || !fig.data.length) {
      el.innerHTML = "";
      return;
    }
    Plotly.react(el, fig.data, fig.layout,
      {responsive: true, displaylogo: false});
    bindClick(el);
  }

  /* Drill-through: any point whose customdata carries a URL navigates
   * to the filtered executions list / execution detail. plotly_click is
   * an emitter event on the plot div — el.on only exists after Plotly
   * has drawn into it, so bind lazily. */
  function bindClick(el) {
    if (el.__advBound || typeof el.on !== "function") return;
    el.__advBound = true;
    el.on("plotly_click", function (ev) {
      var pts = (ev && ev.points) || [];
      for (var i = 0; i < pts.length; i++) {
        var cd = pts[i].customdata;
        if (typeof cd === "string" && cd.charAt(0) === "/") {
          window.location.href = cd;
          return;
        }
      }
    });
  }

  window.addEventListener("load", function () {
    document.querySelectorAll("[data-adv]").forEach(bindClick);
  });

  function tableRows(key, tables) {
    /* Rebuild the accessible data tables from the same payload. */
    var rows = [];
    if (key === "comparison") {
      (tables.project_outcomes || []).forEach(function (r) {
        rows.push("<tr><td>" + esc(r.project) + "</td><td>" + r.passed +
          "</td><td>" + r.failed + "</td><td>" + r.incomplete +
          "</td><td>" + r.none + "</td></tr>");
      });
    } else if (key === "first_final") {
      (tables.first_final || []).forEach(function (r) {
        rows.push("<tr><td>" + esc(r.day) + "</td><td>" + r.total +
          "</td><td>" + r.first_passed + "</td><td>" + r.final_passed +
          "</td><td>" + r.retried + "</td></tr>");
      });
    } else if (key === "queue") {
      (tables.queue_wait || []).forEach(function (r) {
        rows.push("<tr><td>" + esc(r.day) + "</td><td>queue wait</td><td>" +
          r.n + "</td><td>" + r.median + "</td><td>" + r.p95 + "</td></tr>");
      });
      (tables.turnaround || []).forEach(function (r) {
        rows.push("<tr><td>" + esc(r.day) + "</td><td>turnaround</td><td>" +
          r.n + "</td><td>" + r.median + "</td><td>" + r.p95 + "</td></tr>");
      });
    }
    return rows.join("");
  }

  function refresh() {
    if (inFlight) return;
    inFlight = true;
    var seq = ++serial;
    if (btn) btn.disabled = true;
    fetch(url, {headers: {"Accept": "application/json"}, cache: "no-store"})
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (seq !== serial) return;            // stale response
        ["comparison", "first_final", "queue"].forEach(function (k) {
          draw(k, data.charts[k]);
          var tbl = document.getElementById("adv-tbl-" + k);
          if (tbl && tbl.tBodies && tbl.tBodies[0]) {
            tbl.tBodies[0].innerHTML = tableRows(k, data.tables);
          }
        });
        if (updatedEl) {
          updatedEl.textContent =
            "Updated " + data.generated_at.slice(0, 19) + "Z";
        }
      })
      .catch(function () {
        if (updatedEl) {
          updatedEl.textContent = "Refresh failed — showing previous data";
        }
      })
      .finally(function () {
        inFlight = false;
        if (btn) btn.disabled = false;
      });
  }

  if (btn) btn.addEventListener("click", refresh);
})();
