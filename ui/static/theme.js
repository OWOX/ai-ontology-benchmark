// Spec: docs/specs/ui.md (Left menu)
// Light, dark, or system theme. Loaded in <head> so the page never paints in the wrong theme. The choice is kept
// in localStorage under "theme"; "system" removes data-theme and lets prefers-color-scheme decide.
(function () {
  const KEY = "theme";
  const CHOICES = ["light", "dark", "system"];
  function read() { try { const v = localStorage.getItem(KEY); return CHOICES.includes(v) ? v : "system"; } catch (e) { return "system"; } }
  function apply(v) {
    if (v === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", v);
  }
  apply(read());
  document.addEventListener("DOMContentLoaded", () => {
    const box = document.getElementById("theme");
    if (!box) return;
    const mark = (v) => box.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.theme === v)));
    mark(read());
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-theme]");
      if (!b) return;
      try { localStorage.setItem(KEY, b.dataset.theme); } catch (err) { /* blocked storage only loses the choice */ }
      apply(b.dataset.theme);
      mark(b.dataset.theme);
    });
  });
})();
