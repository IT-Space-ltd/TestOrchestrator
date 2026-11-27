/* Schedule form — per-framework field visibility + target inference.
   Hidden framework-specific inputs are DISABLED, so they never post —
   switching the framework cannot carry stale values into the saved
   schedule (server-side validation is the authoritative backstop). */
(function () {
  "use strict";

  function applyFwVisibility(form) {
    const sel = form.querySelector("#sch-framework");
    if (!sel) return;
    const fw = sel.value;
    form.querySelectorAll("[data-fws]").forEach((el) => {
      const mine = (el.dataset.fws || "").split(/\s+/).includes(fw);
      el.hidden = !mine;
      el.querySelectorAll("input,select,textarea").forEach((inp) => {
        inp.disabled = !mine;
      });
    });
  }

  function inferFromTargets(form) {
    const sel = form.querySelector("#sch-framework");
    if (!sel) return;
    // First selected repository target decides the framework —
    // the case-selector posts case_refs[] hidden inputs in order.
    const refs = [...form.querySelectorAll('input[name="case_refs"]')]
      .map((x) => x.value);
    const caseRoot = form.querySelector("[data-case-selector]");
    let meta = [];
    try { meta = JSON.parse(caseRoot?.dataset.cases || "[]"); }
    catch (e) { meta = []; }
    const fwByValue = {};
    meta.forEach((x) => {
      if (typeof x === "object" && x !== null) fwByValue[x.v] = x.fw;
    });
    const first = refs.find((r) => fwByValue[r]);
    if (first) {
      const fw = fwByValue[first] || "katalon";
      if ([...sel.options].some((o) => o.value === fw)) sel.value = fw;
      // read-only presentation: value still posts (not disabled),
      // but the user cannot change it — the target owns it now.
      sel.style.pointerEvents = "none";
      sel.tabIndex = -1;
      sel.setAttribute("aria-readonly", "true");
      sel.classList.add("inferred");
    } else {
      sel.style.pointerEvents = "";
      sel.tabIndex = 0;
      sel.removeAttribute("aria-readonly");
      sel.classList.remove("inferred");
    }
    applyFwVisibility(form);
  }

  function syncTargetKind(form) {
    const kindSel = form.querySelector("#sch-target-kind");
    if (!kindSel) return;
    // reselect first visible option if the current one is hidden
    const cur = kindSel.selectedOptions[0];
    if (!cur || cur.hidden) {
      const firstVis = [...kindSel.options].find((o) => !o.hidden);
      if (firstVis) kindSel.value = firstVis.value;
    }
    const kind = kindSel.value;
    const caseRoot = form.querySelector("[data-case-selector]");
    if (caseRoot) {
      // plan: the picker is irrelevant — the plan owns its suites
      const pickerField = caseRoot.closest(".field");
      if (pickerField) {
        pickerField.style.display = kind === "plan" ? "none" : "";
      }
      caseRoot.dataset.filterKind =
        kind === "collection" ? "collection" : "suite";
      caseRoot.dispatchEvent(new Event("cases:refresh"));
    }
    syncCollectionInfo(form);
  }

  function syncCollectionInfo(form) {
    const info = form.querySelector("#sch-collection-info");
    const kindSel = form.querySelector("#sch-target-kind");
    if (!info) return;
    info.hidden = true;
    info.textContent = "";
    if (!kindSel || kindSel.value !== "collection") return;
    const caseRoot = form.querySelector("[data-case-selector]");
    let meta = [];
    try { meta = JSON.parse(caseRoot?.dataset.cases || "[]"); }
    catch (e) { meta = []; }
    const refs = [...form.querySelectorAll('input[name="case_refs"]')]
      .map((x) => x.value);
    const lines = [];
    meta.forEach((cs) => {
      if (typeof cs !== "object" || cs === null) return;
      if (cs.kind !== "collection" || !refs.includes(cs.v)) return;
      const mode = (cs.runmode || "sequential").toUpperCase();
      const members = (cs.members && cs.members.length)
        ? cs.members.join(", ") : "no member suites recorded";
      lines.push(`${(cs.l || "").split("·")[0].trim()} — run mode ` +
                 `${mode}; members: ${members}`);
    });
    if (lines.length) {
      info.textContent = lines.join("\n");
      info.style.whiteSpace = "pre-line";
      info.hidden = false;
    }
  }

  document.querySelectorAll("form").forEach((form) => {
    const sel = form.querySelector("#sch-framework");
    if (!sel) return;
    sel.addEventListener("change", () => {
      applyFwVisibility(form);
      syncTargetKind(form);
    });
    const kindSel = form.querySelector("#sch-target-kind");
    if (kindSel) {
      kindSel.addEventListener("change", () => syncTargetKind(form));
    }
    form.addEventListener("click", (e) => {
      if (e.target.closest("[data-case-selector]")) {
        setTimeout(() => syncCollectionInfo(form), 0);
      }
    });
    setTimeout(() => syncTargetKind(form), 0);
    // the case-selector re-renders on click — re-infer after each
    form.addEventListener("click", (e) => {
      if (e.target.closest("[data-case-selector]")) {
        setTimeout(() => inferFromTargets(form), 0);
      }
    });
    applyFwVisibility(form);
    inferFromTargets(form);
  });
})();
