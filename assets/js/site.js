// Behaviour the WordPress theme did with jQuery plugins, in plain JavaScript.

// Home grid: place each box in the shortest column, like jQuery Masonry.
function layoutMasonry(grid) {
  const columns = Number(grid.dataset.columns) || 2;
  const gutter = Number(grid.dataset.gutterSpace) || 0;
  const boxes = grid.querySelectorAll(".wc-shortcodes-post-box");
  const width = (grid.clientWidth - gutter * (columns - 1)) / columns;
  const heights = new Array(columns).fill(0);
  boxes.forEach((box) => {
    box.style.position = "absolute";
    box.style.width = `${width}px`;
    const col = heights.indexOf(Math.min(...heights));
    box.style.left = `${col * (width + gutter)}px`;
    box.style.top = `${heights[col]}px`;
    heights[col] += box.offsetHeight + gutter;
  });
  grid.style.height = `${Math.max(...heights)}px`;
}

function initMasonry() {
  const grids = document.querySelectorAll(".wc-shortcodes-posts-layout-masonry");
  const run = () => grids.forEach(layoutMasonry);
  grids.forEach((grid) => {
    grid.querySelectorAll("img").forEach((img) => {
      if (!img.complete) img.addEventListener("load", run);
    });
  });
  window.addEventListener("resize", run);
  run();
}

// Back to top button, shown after scrolling 500px.
function initBackToTop() {
  const button = document.getElementById("toTop");
  if (!button) return;
  const update = () => button.classList.toggle("visible", window.scrollY > 500);
  window.addEventListener("scroll", update, { passive: true });
  button.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  update();
}

// Small screens: the theme replaces the menu with a <select> (TinyNav).
function initMobileNav() {
  const menu = document.getElementById("prime_nav");
  if (!menu) return;
  const select = document.createElement("select");
  select.className = "tinynav tinynav1";
  let chosen = false;
  const add = (ul, depth) => {
    for (const li of ul.children) {
      const a = li.querySelector(":scope > a");
      const option = new Option("- ".repeat(depth) + a.textContent.trim(), a.getAttribute("href"));
      // Two items can share a URL; keep the first match selected.
      if (!chosen && li.classList.contains("current-menu-item")) option.selected = chosen = true;
      select.add(option);
      const sub = li.querySelector(":scope > ul");
      if (sub) add(sub, depth + 1);
    }
  };
  add(menu, 0);
  select.addEventListener("change", () => { window.location.href = select.value; });
  menu.after(select);
}

// Tournament decklists: search box filters rows, headers sort columns.
function initDecklists() {
  const table = document.getElementById("decklists");
  if (!table) return;
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const search = document.querySelector("#decks .deck-search");
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    rows.forEach((row) => { row.hidden = q !== "" && !row.textContent.toLowerCase().includes(q); });
  });
  table.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const asc = !th.classList.contains("asc");
      table.querySelectorAll("th[data-sort]").forEach((h) => h.classList.remove("asc", "desc"));
      th.classList.add(asc ? "asc" : "desc");
      const cls = th.dataset.sort;
      const numeric = th.hasAttribute("data-numeric");
      const key = (row) => row.querySelector(`td.${cls}`).textContent.trim();
      const cmp = numeric
        ? (a, b) => Number(key(a)) - Number(key(b))
        : (a, b) => key(a).localeCompare(key(b));
      rows.sort((a, b) => (asc ? cmp(a, b) : cmp(b, a))).forEach((row) => tbody.append(row));
    });
  });
}

initMasonry();
initBackToTop();
initMobileNav();
initDecklists();
