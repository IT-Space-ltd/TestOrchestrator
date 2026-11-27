/* Test tree — expand/collapse with keyboard navigation.
   roving tabindex: one tree row is tabbable at a time; arrows move
   and expand/collapse per the treeview ARIA pattern. */
(function () {
  "use strict";
  document.querySelectorAll("[data-test-tree]").forEach((tree) => {
    const items = () =>
      [...tree.querySelectorAll('[role="treeitem"]')]
        .filter((li) => li.offsetParent !== null);
    function focusable(li) {
      return li.querySelector(".tree-toggle:not([disabled])") ||
             li.querySelector(".tree-leaf") || li;
    }
    items().forEach((li, i) => {
      const f = focusable(li);
      f.tabIndex = i === 0 ? 0 : -1;
    });
    function setExpanded(li, expand) {
      const grp = li.querySelector(':scope > ul[role="group"]');
      if (!grp) return;
      grp.hidden = !expand;
      li.setAttribute("aria-expanded", String(expand));
      const tog = li.querySelector(":scope > .tree-toggle");
      if (tog) tog.textContent = expand ? "▾" : "▸";
    }
    tree.addEventListener("click", (e) => {
      const tog = e.target.closest(".tree-toggle");
      if (!tog) return;
      const li = tog.closest('[role="treeitem"]');
      setExpanded(li, li.getAttribute("aria-expanded") !== "true");
    });
    tree.addEventListener("keydown", (e) => {
      const list = items();
      const cur = document.activeElement.closest('[role="treeitem"]');
      const idx = list.indexOf(cur);
      if (idx === -1) return;
      const expanded = cur.getAttribute("aria-expanded") === "true";
      const hasGroup = !!cur.querySelector(':scope > ul[role="group"]');
      if (e.key === "ArrowDown" && list[idx + 1]) {
        focusable(list[idx + 1]).focus(); e.preventDefault();
      } else if (e.key === "ArrowUp" && list[idx - 1]) {
        focusable(list[idx - 1]).focus(); e.preventDefault();
      } else if (e.key === "ArrowRight" && hasGroup && !expanded) {
        setExpanded(cur, true); e.preventDefault();
      } else if (e.key === "ArrowLeft" && hasGroup && expanded) {
        setExpanded(cur, false); e.preventDefault();
      } else if (e.key === "Enter" || e.key === " ") {
        if (hasGroup) {
          setExpanded(cur, !expanded); e.preventDefault();
        }
      }
    });
    tree.addEventListener("focusin", (e) => {
      items().forEach((li) => { focusable(li).tabIndex = -1; });
      const li = e.target.closest('[role="treeitem"]');
      if (li) focusable(li).tabIndex = 0;
    });
  });
})();
