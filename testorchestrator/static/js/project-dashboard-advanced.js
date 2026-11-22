/* Project dashboard advanced analytics — on-demand refresh +
 * drill-through. Same policy as dashboard-advanced.js: manual refresh
 * only (never the live poll), uirevision preserves zoom/legend,
 * single in-flight request with stale-response guard. */
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

  function bindClick(el) {
    if (el.__advBound || typeof el.on !== "function") return;
    el.__advBound = true;
    el.on("plotly_click", function (ev) {
      var pts = (ev && ev.points) || [];
      for (var i = 0; i < pts.length; i++) {
        var cd = pts[i].customdata;
        var target = (typeof cd === "string") ? cd
          : (cd && typeof cd === "object") ? cd.url : null;
        if (typeof target === "string" && target.charAt(0) === "/") {
          window.location.href = target;
          return;
        }
      }
    });
  }

  window.addEventListener("load", function () {
    document.querySelectorAll("[data-adv]").forEach(bindClick);
  });

  function tableRows(key, tables) {
    var rows = [];
    if (key === "history") {
      var h = tables.history || {cases: [], runs: [], cells: {}};
      h.cases.forEach(function (c) {
        h.runs.forEach(function (r) {
          var cell = h.cells[c + "|" + r.id];
          rows.push("<tr><td>" + esc(c) + "</td><td>" + esc(r.label) +
            "</td><td>" + r.attempt + "</td><td>" +
            (cell ? esc(cell.status) : "—") + "</td><td>" +
            (cell ? cell.duration + "s" : "") + "</td></tr>");
        });
      });
    } else if (key === "durations") {
      (tables.suite_durations || []).forEach(function (s) {
        s.durations.forEach(function (d, i) {
          rows.push("<tr><td>" + esc(s.suite) + "</td><td>" + d +
            "</td><td><a href='/executions/" + esc(s.executions[i]) +
            "'><code>" + esc(s.executions[i].slice(0, 8)) +
            "</code></a></td></tr>");
        });
      });
    } else if (key === "env") {
      (tables.env_cells || []).forEach(function (c) {
        var na = function (v, suffix) {
          return v === null || v === undefined ? "N/A" : v + (suffix || "");
        };
        rows.push("<tr><td>" + esc(c.suite) + "</td><td>" + esc(c.env) +
          "</td><td>" + c.runs + "</td><td>" + na(c.run_pass_rate) +
          "</td><td>" + na(c.case_pass_rate) + "</td><td>" +
          na(c.median_duration) + "</td></tr>");
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
        if (seq !== serial) return;
        ["history", "durations", "env"].forEach(function (k) {
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
