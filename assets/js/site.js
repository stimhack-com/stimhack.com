// Behaviour the WordPress theme did with jQuery plugins, in plain JavaScript.

// Home grid: place each box in the shortest column, like jQuery Masonry.
// The column count follows calculateGrid in the wc-shortcodes plugin that drew
// the grid on WordPress (public/assets/js/posts.js 3.42): fewer columns when a
// column would be narrower than 200px, and one column when the window is 568px
// wide or less.
function masonryGrid(width, windowWidth, columns, gutter) {
  if (Number.isNaN(gutter) || gutter > 50 || gutter < 0) gutter = 20;
  const content = (n) => width - gutter * (n - 1);
  if (Math.floor(content(columns) / columns) < 200) {
    columns = Math.max(1, Math.floor(content(columns) / 200));
  }
  if (windowWidth <= 568) columns = 1;
  return { columns, gutter, width: Math.floor(content(columns) / columns) };
}

function layoutMasonry(grid) {
  const { columns, gutter, width } = masonryGrid(
    Math.floor(grid.getBoundingClientRect().width),
    document.documentElement.clientWidth,
    Number(grid.dataset.columns) || 2,
    Number(grid.dataset.gutterSpace),
  );
  if (columns === 1) {
    // Like the plugin, remove the layout so the boxes are in normal flow.
    grid.removeAttribute("style");
    for (const box of grid.children) box.removeAttribute("style");
    grid.style.height = "auto";
    return;
  }
  const boxes = grid.querySelectorAll(".wc-shortcodes-post-box");
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
      if (img.complete) return;
      // The plugin laid out again when images loaded or failed (imagesLoaded().always).
      img.addEventListener("load", run);
      img.addEventListener("error", run);
    });
  });
  window.addEventListener("resize", run);
  run();
}

// Video players keep the shape of their width and height attributes when the
// column is narrower than they are. On WordPress the theme did this with
// FitVids (js/frontend.js in Tempera, FitVids 1.0), which found video players
// by their address and did not change other iframes, so audio players and
// maps keep their fixed height here too.
const VIDEO_PLAYER = /^(https?:)?\/\/([^/]*\.)?(youtube\.com|youtube-nocookie\.com|player\.vimeo\.com)\//;

function initVideoEmbeds() {
  document.querySelectorAll(".entry-content iframe").forEach((iframe) => {
    const width = iframe.getAttribute("width");
    const height = iframe.getAttribute("height");
    if (!VIDEO_PLAYER.test(iframe.getAttribute("src") || "")) return;
    if (!/^[1-9]\d*$/.test(width) || !/^[1-9]\d*$/.test(height)) return;
    iframe.style.aspectRatio = `${width} / ${height}`;
    iframe.style.height = "auto";
  });
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

// Small screens: the theme replaces the menu with a <select>. On WordPress
// this was TinyNav (js/frontend.js in Tempera, TinyNav 1.03 mod 0.1.1) with
// the header " = Menu = ". The option with the page address is selected, and
// on other pages the header stays selected. Two items can have the same
// address; TinyNav selected both, so the select showed the last one.
function initMobileNav() {
  const menu = document.getElementById("prime_nav");
  if (!menu) return;
  const select = document.createElement("select");
  select.className = "tinynav tinynav1";
  select.add(new Option(" = Menu = ", ""));
  const here = window.location.protocol + "//" + window.location.host + window.location.pathname;
  const add = (ul, depth) => {
    for (const li of ul.children) {
      const a = li.querySelector(":scope > a");
      const indent = depth ? "\u00a0" + "-\u00a0".repeat(depth) : "";
      const option = new Option(indent + a.textContent.trim(), a.getAttribute("href"));
      if (a.href === here) option.selected = true;
      select.add(option);
      const sub = li.querySelector(":scope > ul");
      if (sub) add(sub, depth + 1);
    }
  };
  add(menu, 0);
  select.addEventListener("change", () => {
    if (select.value) window.location.href = select.value;
  });
  menu.after(select);
}

// Touch screens: the first tap on a top level menu item with a submenu opens
// the submenu, and the next tap on it follows the link. On WordPress the theme
// did this (js/frontend.js in Tempera). Here a tap follows the link when the
// submenu was already shown as the tap started, so a browser that shows the
// submenu on the first tap without a click needs two taps and not three. The
// submenu-open class keeps the submenu shown in a browser that does not keep
// :hover or focus after the cancelled click.
function initTouchMenu() {
  const menu = document.getElementById("prime_nav");
  if (!menu) return;
  const items = Array.from(menu.children).filter((li) => li.querySelector(":scope > ul"));
  let tap = null;
  items.forEach((li) => {
    const link = li.querySelector(":scope > a");
    const submenu = li.querySelector(":scope > ul");
    link.addEventListener("pointerdown", (event) => {
      tap = { link, touch: event.pointerType !== "mouse", shown: getComputedStyle(submenu).display !== "none" };
    });
    link.addEventListener("click", (event) => {
      const first = tap && tap.link === link && tap.touch && !tap.shown;
      tap = null;
      if (!first) return;
      event.preventDefault();
      li.classList.add("submenu-open");
    });
  });
  document.addEventListener("pointerdown", (event) => {
    items.forEach((li) => { if (!li.contains(event.target)) li.classList.remove("submenu-open"); });
  });
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

initVideoEmbeds();
initMasonry();
initBackToTop();
initMobileNav();
initTouchMenu();
initDecklists();
