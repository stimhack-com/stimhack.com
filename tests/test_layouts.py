"""Tests for the rendered site built from layouts/ and content/.

Run: python3 -m unittest discover tests
"""
import atexit
import contextlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from site_build import FIXTURE_CONFIG, ROOT, build, hugo, published_pages

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "migration"))
import check_site  # noqa: E402
from front_matter import content_files  # noqa: E402


# Tests that run the site script in node skip when node is not on PATH,
# except in CI: GitHub Actions sets CI=true, and there they fail, so that the
# job cannot pass with the site script untested. The default environment
# variables at https://docs.github.com/en/actions/reference/workflows-and-actions/variables
# say "CI: Always set to true." (checked 2026-09-25).
needs_node = unittest.skipUnless(shutil.which("node") or os.environ.get("CI"), "needs node")


def comment_ids(path):
    html = (build() / path / "index.html").read_text()
    return re.findall(r'<div id="comment-(\d+)">', html)


class PageComments(unittest.TestCase):
    def test_pages_show_their_imported_comments(self):
        self.assertEqual(comment_ids("drafting"), ["318"])
        self.assertEqual(comment_ids("tournament-decklists"), ["132", "133", "308"])

    def test_posts_still_show_their_comments(self):
        self.assertTrue(comment_ids("drafting-with-netrunner"))


class TermDescriptions(unittest.TestCase):
    def test_author_description_is_escaped_once(self):
        html = (build() / "author" / "ian" / "index.html").read_text()
        description = re.search(r'<div id="author-description"><h2>Ian L</h2>(Ian .*? his wife)', html)
        self.assertEqual(description[1], "Ian &amp; his wife")


class HomeGrid(unittest.TestCase):
    def test_thumbnail_links_to_its_own_post(self):
        html = (build() / "index.html").read_text()
        boxes = html.split('<div class="wc-shortcodes-post-box ')[1:]
        thumbnails = []
        titles = []
        for box in boxes:
            thumbnail = re.search(r'wc-shortcodes-entry-thumbnail"><a href="([^"]*)" title="([^"]*)"', box)
            if thumbnail:
                thumbnails.append(thumbnail.groups())
                title = re.search(r'wc-shortcodes-entry-title"><a href="([^"]*)" rel="bookmark">([^<]*)</a>', box)
                titles.append(title.groups())
        self.assertTrue(thumbnails)
        self.assertEqual(thumbnails, titles)


# Run the site script from argv[1] in node with a fake home page that has one
# grid of boxes. argv[2] is a JSON scenario: the window and grid widths, the
# box heights, the boxes whose image is still loading, and steps that change
# the widths or heights and then fire "resize" on the window or "load" or
# "error" on the loading images. Print the grid and box styles after the
# script runs and after each step as a JSON list.
LAYOUT_GRID = r"""
const fs = require("fs"), vm = require("vm");
const [file, json] = process.argv.slice(1);
const scenario = JSON.parse(json);
const on = (target) => {
  target.listeners = {};
  target.addEventListener = (type, fn) => { (target.listeners[type] ||= []).push(fn); };
  return target;
};
const styled = (el) => {
  el.style = {};
  el.removeAttribute = (name) => { if (name === "style") el.style = {}; };
  return el;
};
const images = [];
const boxes = scenario.heights.map((height, i) => {
  const own = (scenario.loading || []).includes(i) ? [on({complete: false})] : [];
  images.push(...own);
  return styled({offsetHeight: height, querySelectorAll: (sel) => (sel === "img" ? own : [])});
});
const grid = styled({dataset: {columns: "2", gutterSpace: "20"}, children: boxes,
  querySelectorAll: (sel) => (sel === ".wc-shortcodes-post-box" ? boxes : sel === "img" ? images : [])});
const documentElement = {};
const context = on(vm.createContext({console, document: {documentElement,
  querySelectorAll: (sel) => (sel.includes("wc-shortcodes-posts") ? [grid] : []),
  getElementById: () => null}}));
context.window = context;
const resize = (step) => {
  if (step.window !== undefined) context.innerWidth = documentElement.clientWidth = step.window;
  if (step.width !== undefined) {
    grid.clientWidth = grid.offsetWidth = step.width;
    grid.getBoundingClientRect = () => ({width: step.width});
  }
  (step.heights || []).forEach((height, i) => { boxes[i].offsetHeight = height; });
};
const snapshot = () => ({grid: {...grid.style}, boxes: boxes.map((box) => ({...box.style}))});
resize(scenario);
vm.runInContext(fs.readFileSync(file, "utf8"), context);
const results = [snapshot()];
for (const step of scenario.steps || []) {
  resize(step);
  const targets = step.fire === "resize" ? [context] : images;
  targets.forEach((target) => (target.listeners[step.fire] || []).forEach((fn) => fn({type: step.fire})));
  results.push(snapshot());
}
console.log(JSON.stringify(results));
"""


def layout_grid(scenario):
    """Return the home grid and box styles that the built site script sets in scenario, as LAYOUT_GRID describes."""
    out = build()
    script = re.search(r'<script src="(/js/site[^"]*\.js)"', (out / "index.html").read_text())[1]
    run = subprocess.run(["node", "-e", LAYOUT_GRID, str(out / script.lstrip("/")), json.dumps(scenario)],
                         capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def box(left, top, width):
    return {"position": "absolute", "width": f"{width}px", "left": f"{left}px", "top": f"{top}px"}


# The wc-shortcodes plugin that drew the grid on WordPress
# (public/assets/js/posts.js 3.42, calculateGrid and runMasonry) used fewer
# columns when a column would be narrower than 200px and one column when the
# window was 568px wide or less. With one column it removed the style
# attributes of the grid and the boxes, so the boxes are in normal flow, and
# set the grid height to auto.
ONE_COLUMN = {"grid": {"height": "auto"}, "boxes": [{}, {}, {}]}


@needs_node
class HomeGridLayout(unittest.TestCase):
    maxDiff = None

    def test_wide_window_shows_two_columns(self):
        [result] = layout_grid({"window": 1200, "width": 880, "heights": [100, 50, 70]})
        self.assertEqual(result, {"grid": {"height": "160px"},
                                  "boxes": [box(0, 0, 430), box(450, 0, 430), box(450, 70, 430)]})

    def test_phone_window_shows_one_column(self):
        [result] = layout_grid({"window": 400, "width": 370, "heights": [100, 50, 70]})
        self.assertEqual(result, ONE_COLUMN)

    def test_window_of_568px_or_less_shows_one_column(self):
        [result] = layout_grid({"window": 568, "width": 540, "heights": [100, 50, 70]})
        self.assertEqual(result, ONE_COLUMN)
        [result] = layout_grid({"window": 569, "width": 540, "heights": [100, 50, 70]})
        self.assertEqual(result["boxes"], [box(0, 0, 260), box(280, 0, 260), box(280, 70, 260)])

    def test_grid_too_narrow_for_two_200px_columns_shows_one_column(self):
        [result] = layout_grid({"window": 1000, "width": 419, "heights": [100, 50, 70]})
        self.assertEqual(result, ONE_COLUMN)
        [result] = layout_grid({"window": 1000, "width": 420, "heights": [100, 50, 70]})
        self.assertEqual(result["boxes"], [box(0, 0, 200), box(220, 0, 200), box(220, 70, 200)])

    def test_resize_changes_between_one_and_two_columns(self):
        results = layout_grid({"window": 400, "width": 370, "heights": [100, 50, 70], "steps": [
            {"window": 1200, "width": 880, "fire": "resize"},
            {"window": 400, "width": 370, "fire": "resize"},
        ]})
        self.assertEqual(results[0], ONE_COLUMN)
        self.assertEqual(results[1]["boxes"], [box(0, 0, 430), box(450, 0, 430), box(450, 70, 430)])
        self.assertEqual(results[2], ONE_COLUMN)

    def test_image_that_fails_to_load_lays_out_the_grid_again(self):
        # The first box is tall while its image loads and short when it fails,
        # so the third box moves from the second column to the first.
        for event in ["load", "error"]:
            with self.subTest(event=event):
                results = layout_grid({"window": 1200, "width": 880, "heights": [300, 50, 70], "loading": [0],
                                       "steps": [{"heights": [40, 50, 70], "fire": event}]})
                self.assertEqual(results[0]["boxes"][2], box(450, 70, 430))
                self.assertEqual(results[1]["boxes"][2], box(0, 60, 430))


# Run the site script from argv[1] in node with a fake page whose post content
# has the iframes in argv[2], a JSON list of attribute objects. Print the
# style that the script gives each iframe as a JSON list.
STYLE_IFRAMES = r"""
const fs = require("fs"), vm = require("vm");
const [file, json] = process.argv.slice(1);
const iframes = JSON.parse(json).map((attrs) => ({
  style: {}, src: attrs.src, getAttribute: (name) => (name in attrs ? attrs[name] : null),
}));
const context = vm.createContext({console, document: {documentElement: {},
  querySelectorAll: (sel) => (sel.includes("iframe") ? iframes : []),
  getElementById: () => null}});
context.window = context;
context.addEventListener = () => {};
vm.runInContext(fs.readFileSync(file, "utf8"), context);
console.log(JSON.stringify(iframes.map((iframe) => ({...iframe.style}))));
"""


def iframe_styles(iframes):
    """Return the style that the built site script gives each iframe in iframes, as STYLE_IFRAMES describes."""
    out = build()
    script = re.search(r'<script src="(/js/site[^"]*\.js)"', (out / "index.html").read_text())[1]
    run = subprocess.run(["node", "-e", STYLE_IFRAMES, str(out / script.lstrip("/")), json.dumps(iframes)],
                         capture_output=True, text=True, check=True)
    return dict(zip((f"{i['src']} {i.get('width')}x{i.get('height')}" for i in iframes), json.loads(run.stdout)))


@needs_node
class VideoEmbeds(unittest.TestCase):
    # FitVids 1.0 ($.fn.fitVids in the Tempera theme, .export/theme/wp-content/themes/tempera/js/frontend.js)
    # keeps YouTube and Vimeo players, Kickstarter video.html iframes, and all
    # object and embed elements at the shape of their width and height
    # attributes (frontend.js lines 213-220). content/ has no Kickstarter
    # iframe, object or embed, so the site script matches only YouTube and
    # Vimeo players. FitVids skips players narrower than the content column
    # (frontend.js line 235); here every player keeps its shape, so a 600x400
    # player is not 400px high on a phone. These tests check the styles that
    # the script sets, not the size that a browser renders.
    maxDiff = None

    def test_video_players_keep_the_shape_of_their_size_attributes(self):
        # Sizes from content/: 900x506 is most YouTube embeds, 900x675 and
        # 600x400 are older ones.
        videos = [
            {"src": "https://www.youtube.com/embed/vIUevBbIzkI?feature=oembed", "width": "900", "height": "506"},
            {"src": "https://www.youtube.com/embed/jpsrCVbeb1g?feature=oembed", "width": "900", "height": "675"},
            {"src": "https://www.youtube.com/embed/4Wf3k1ThAaE?autohide=2", "width": "600", "height": "400"},
            {"src": "https://www.youtube-nocookie.com/embed/vIUevBbIzkI", "width": "560", "height": "315"},
            {"src": "https://player.vimeo.com/video/1", "width": "640", "height": "360"},
        ]
        self.assertEqual(iframe_styles(videos), {
            f"{v['src']} {v['width']}x{v['height']}": {"aspectRatio": f"{v['width']} / {v['height']}", "height": "auto"}
            for v in videos})

    def test_other_iframes_keep_their_height(self):
        # Audio players and the map on /playgroup-finder/ have a fixed height,
        # and a player without numeric sizes has no shape to keep.
        others = [
            {"src": "https://w.soundcloud.com/player/?visual=true", "width": "900", "height": "450"},
            {"src": "https://waitwaitdrm.podomatic.com/embed/frame/posting/1", "width": "580", "height": "85"},
            {"src": "https://mapsengine.google.com/map/embed?mid=1", "width": "640", "height": "480"},
            {"src": "https://www.youtube.com/embed/vIUevBbIzkI"},
            {"src": "https://www.youtube.com/embed/vIUevBbIzkI", "width": "100%", "height": "506"},
        ]
        self.assertEqual(iframe_styles(others), {
            f"{o['src']} {o.get('width')}x{o.get('height')}": {} for o in others})


class MenuParser(HTMLParser):
    """Read the items of the main menu (ul#prime_nav) as a list of
    {"text", "href", "classes", "children"} dicts."""

    def __init__(self):
        super().__init__()
        self.menu = None
        self.lists = []
        self.items = []
        self.in_link = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "ul" and attrs.get("id") == "prime_nav":
            self.menu = []
            self.lists = [self.menu]
        elif not self.lists:
            return
        elif tag == "ul":
            self.items[-1]["children"] = []
            self.lists.append(self.items[-1]["children"])
        elif tag == "li":
            item = {"text": "", "href": None, "classes": (attrs.get("class") or "").split(), "children": None}
            self.lists[-1].append(item)
            self.items.append(item)
        elif tag == "a":
            self.items[-1]["href"] = attrs["href"]
            self.in_link = True

    def handle_endtag(self, tag):
        if not self.lists:
            return
        if tag == "ul":
            self.lists.pop()
        elif tag == "li":
            self.items.pop()
        elif tag == "a":
            self.in_link = False

    def handle_data(self, data):
        if self.in_link:
            self.items[-1]["text"] += data


# Run the site script from argv[1] in node with a fake page at the address in
# argv[2] whose main menu is argv[3], a JSON list of MenuParser items. Then
# choose each option whose text is in argv[4], a JSON list, as a reader does:
# the select fires "change" only when the choice differs from the selected
# option. Print the options of the menu select, the text of the option that
# was selected before the choices, and each address the script navigated to.
MOBILE_NAV = r"""
const fs = require("fs"), vm = require("vm");
const [file, url, menuJson, chooseJson] = process.argv.slice(1);
const navigations = [];
const page = new URL(url);
const location = {protocol: page.protocol, host: page.host, pathname: page.pathname};
Object.defineProperty(location, "href", {get: () => url, set: (value) => { navigations.push(value); }});
const list = (items) => ({children: items.map((item) => {
  // A browser resolves the href property of a link against the page address.
  const a = {textContent: item.text, href: new URL(item.href, url).href,
    getAttribute: (name) => (name === "href" ? item.href : null), addEventListener: () => {}};
  const sub = item.children ? list(item.children) : null;
  return {classList: {contains: (name) => item.classes.includes(name)},
    querySelector: (sel) => (sel === ":scope > a" ? a : sel === ":scope > ul" ? sub : null)};
})});
const menu = list(JSON.parse(menuJson));
// A select without the multiple attribute shows the last option that is
// selected, or the first option when none is.
class Option {
  constructor(text = "", value) { this.text = text; this.selected = false; if (value !== undefined) this._value = value; }
  get value() { return this._value !== undefined ? this._value : this.text.replace(/[ \t\n\f\r]+/g, " ").trim(); }
}
const select = {options: [], listeners: {},
  add(option) { this.options.push(option); },
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
  get selectedIndex() {
    const i = this.options.findLastIndex((option) => option.selected);
    return i === -1 && this.options.length ? 0 : i;
  },
  set selectedIndex(index) { this.options.forEach((option, i) => { option.selected = i === index; }); },
  get value() { const option = this.options[this.selectedIndex]; return option ? option.value : ""; },
};
let inserted = null;
menu.after = (el) => { inserted = el; };
const context = vm.createContext({console, Option, location, document: {documentElement: {},
  addEventListener: () => {},
  querySelectorAll: () => [],
  getElementById: (id) => (id === "prime_nav" ? menu : null),
  createElement: (tag) => (tag === "select" ? select : null)}});
context.window = context;
context.addEventListener = () => {};
vm.runInContext(fs.readFileSync(file, "utf8"), context);
if (inserted !== select) throw new Error("the select is not after the menu");
const selected = select.options[select.selectedIndex].text;
for (const text of JSON.parse(chooseJson)) {
  const index = select.options.findIndex((option) => option.text === text);
  if (index === -1) throw new Error(`no option ${JSON.stringify(text)}`);
  if (index === select.selectedIndex) continue;
  select.selectedIndex = index;
  (select.listeners.change || []).forEach((fn) => fn({type: "change"}));
}
console.log(JSON.stringify({options: select.options.map((option) => [option.text, option.value]), selected, navigations}));
"""


def mobile_nav(path, choose=()):
    """Run the built site script on the built page at path, as MOBILE_NAV describes."""
    out = build()
    page = (out / path.lstrip("/") / "index.html").read_text()
    script = re.search(r'<script src="(/js/site[^"]*\.js)"', page)[1]
    parser = MenuParser()
    parser.feed(page)
    run = subprocess.run(["node", "-e", MOBILE_NAV, str(out / script.lstrip("/")), f"https://stimhack.com{path}",
                          json.dumps(parser.menu), json.dumps(list(choose))],
                         capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(run.stderr)
    return json.loads(run.stdout)


@needs_node
class MobileNav(unittest.TestCase):
    # On small screens the site shows the menu as a select like the one that
    # TinyNav 1.03 mod 0.1.1 makes ($.fn.tinyNav in the Tempera theme,
    # .export/theme/wp-content/themes/tempera/js/frontend.js), with the
    # header ' = Menu = '. The header is the first option. The option whose
    # address is the page address is selected, and on other pages the header
    # stays selected. Choosing the header does not navigate. Child items start
    # with a non-breaking space and "- " with a non-breaking space.
    maxDiff = None
    HEADER = " = Menu = "

    def test_menu_items_follow_the_header(self):
        options = mobile_nav("/about/")["options"]
        self.assertEqual(options[0][0], self.HEADER)
        self.assertEqual(options[1:], [
            ["Home", "/"],
            ["Tournament Winning Decklists", "/tournament-decklists/"],
            ["Forums", "http://forum.stimhack.com/"],
            ["Articles and Guides", "/category/articles/"],
            ["\u00a0-\u00a0Classic Articles", "/classic-articles/"],
            ["\u00a0-\u00a0Set Reviews", "/set-reviews/"],
            ["\u00a0-\u00a0Cube Drafting", "/cube-drafting/"],
            ["\u00a0-\u00a0New Players", "/new-players/"],
            ["\u00a0-\u00a0All Articles", "/category/articles/"],
            ["Videos and Podcasts", "/category/videos-and-podcasts/"],
            ["Playgroup Finder", "/playgroup-finder/"],
            ["About", "/about/"],
        ])

    def test_menu_page_selects_its_option(self):
        # TinyNav selected every option with the page address, and a select
        # shows the last of them, so the articles category shows All Articles.
        for path, text in [("/", "Home"), ("/about/", "About"), ("/set-reviews/", "\u00a0-\u00a0Set Reviews"),
                           ("/category/articles/", "\u00a0-\u00a0All Articles")]:
            with self.subTest(path=path):
                self.assertEqual(mobile_nav(path)["selected"], text)

    def test_page_outside_the_menu_selects_the_header(self):
        # The post is in the articles category, so its menu marks Articles
        # and Guides, but its address is not in the menu.
        for path in ["/tag/art/", "/author/alexfrog/", "/category/articles/page/2/",
                     "/7-things-you-can-do-to-get-better-at-netrunner/"]:
            with self.subTest(path=path):
                self.assertEqual(mobile_nav(path)["selected"], self.HEADER)

    def test_choosing_home_from_a_page_outside_the_menu_goes_home(self):
        self.assertEqual(mobile_nav("/tag/art/", choose=["Home"])["navigations"], ["/"])

    def test_choosing_an_item_goes_to_its_address(self):
        self.assertEqual(mobile_nav("/about/", choose=["Playgroup Finder"])["navigations"], ["/playgroup-finder/"])

    def test_choosing_the_header_does_not_navigate(self):
        self.assertEqual(mobile_nav("/about/", choose=[self.HEADER])["navigations"], [])


# Run the site script from argv[1] in node with a fake page at the address in
# argv[2] whose main menu is argv[3], a JSON list of MenuParser items, and tap
# or click menu items as argv[5] describes. argv[4] is a JSON list of the
# classes that the site CSS uses to show the submenu of an item
# (#access li.<class> > ul). argv[5] is a JSON object:
#   browser: "hover-kept" keeps :hover on the last element that was tapped,
#     and fires click on each tap, as headless Chromium with touch emulation did.
#     "hover-lost" does not keep :hover after a tap, and fires click on each tap.
#     "hover-no-click" keeps :hover like "hover-kept", but does not fire click
#     when the :hover of the tap shows a submenu that was hidden.
#   taps: a list of {text, input}. text is the text of a menu link, or
#     "outside" for the page content. input is "touch", "mouse", "keyboard"
#     (the Enter key: a keydown, then a click), "scroll" (a touch that the
#     browser cancels because it becomes a scroll: a pointerdown, then a
#     pointercancel, and no click) or "activate" (a click with no key or
#     pointer events before it, as from assistive technology or a script).
# A tap on a link in a hidden submenu is not possible. After a navigation the
# page is gone, so the remaining taps are not done. Print, for each tap, the
# address it navigated to or null, and the text of each top level item whose
# submenu is shown after it.
TOUCH_MENU = r"""
const fs = require("fs"), vm = require("vm");
const [file, url, menuJson, openClassesJson, scenarioJson] = process.argv.slice(1);
const openClasses = JSON.parse(openClassesJson);
const {browser, taps} = JSON.parse(scenarioJson);
const page = new URL(url);
const location = {protocol: page.protocol, host: page.host, pathname: page.pathname, href: url};
class El {
  constructor(tag, parent, {classes = [], attrs = {}, text = ""} = {}) {
    this.tagName = tag.toUpperCase(); this.parentNode = parent; this.children = []; this.listeners = {};
    this.attrs = attrs; this.text = text; this.style = {};
    const own = this.classes = new Set(classes);
    this.classList = {
      add: (...names) => names.forEach((name) => own.add(name)),
      remove: (...names) => names.forEach((name) => own.delete(name)),
      contains: (name) => own.has(name),
      toggle: (name, force) => { const on = force === undefined ? !own.has(name) : force; on ? own.add(name) : own.delete(name); return on; },
    };
    if (parent) parent.children.push(this);
  }
  get className() { return [...this.classes].join(" "); }
  set className(value) { this.classes.clear(); value.split(/\s+/).filter(Boolean).forEach((name) => this.classes.add(name)); }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(""); }
  get href() { return new URL(this.attrs.href, url).href; }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }
  contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }
  querySelector(sel) {
    const child = /^:scope > (\w+)$/.exec(sel);
    if (!child) throw new Error(`fake querySelector does not support ${sel}`);
    return this.children.find((c) => c.tagName === child[1].toUpperCase()) || null;
  }
  closest(sel) {
    if (!/^\w+$/.test(sel)) throw new Error(`fake closest does not support ${sel}`);
    for (let n = this; n instanceof El; n = n.parentNode) if (n.tagName === sel.toUpperCase()) return n;
    return null;
  }
  after(el) { this.inserted = el; }
}
const body = new El("body", null);
const menu = new El("ul", body, {attrs: {id: "prime_nav"}});
const content = new El("div", body, {attrs: {id: "content"}});
const links = new Map();
const build = (ul, items) => items.forEach((item) => {
  const li = new El("li", ul, {classes: item.classes});
  const a = new El("a", li, {attrs: {href: item.href}});
  const span = new El("span", a, {text: item.text});
  links.set(item.text.trim(), span);
  if (item.children) build(new El("ul", li, {classes: ["sub-menu"]}), item.children);
});
build(menu, JSON.parse(menuJson));
let hovered = null;
const isSubmenu = (el) => el.tagName === "UL" && el.parentNode && el.parentNode.tagName === "LI";
const shown = (ul) => openClasses.some((name) => ul.parentNode.classes.has(name)) || (hovered !== null && ul.parentNode.contains(hovered));
const getComputedStyle = (el) => (isSubmenu(el) && !shown(el) ? {display: "none", visibility: "hidden"} : {display: "block", visibility: "visible"});
const document = {documentElement: {}, body, listeners: {},
  addEventListener: El.prototype.addEventListener, removeEventListener: El.prototype.removeEventListener,
  querySelectorAll: () => [],
  getElementById: (id) => (id === "prime_nav" ? menu : null),
  createElement: (tag) => new El(tag, null)};
body.parentNode = document;
function Option(text, value) { this.text = text; this.value = value; }
const context = vm.createContext({console, Option, location, document, getComputedStyle});
context.window = context;
context.listeners = {};
context.addEventListener = El.prototype.addEventListener.bind(context);
context.removeEventListener = El.prototype.removeEventListener.bind(context);
document.parentNode = context;
// The fake select from the small screen menu has only the methods that the script calls.
El.prototype.add = function () {};
vm.runInContext(fs.readFileSync(file, "utf8"), context);
const dispatch = (target, type, props = {}) => {
  const event = {type, target, defaultPrevented: false, ...props,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }};
  for (let n = target; n && !event.stopped; n = n.parentNode) {
    event.currentTarget = n;
    for (const fn of [...((n.listeners || {})[type] || [])]) fn.call(n, event);
  }
  return event;
};
const openItems = () => menu.children.filter((li) => {
  const ul = li.querySelector(":scope > ul");
  return ul && getComputedStyle(ul).display !== "none";
}).map((li) => li.querySelector(":scope > a").textContent.trim());
const results = [];
for (const {text, input} of taps) {
  const target = text === "outside" ? content : links.get(text);
  if (!target) throw new Error(`no link ${JSON.stringify(text)}`);
  for (let n = target.parentNode; n instanceof El; n = n.parentNode) {
    if (isSubmenu(n) && getComputedStyle(n).display === "none") throw new Error(`${text} is in a hidden submenu`);
  }
  const hiddenBefore = new Set(openItems());
  let click = true;
  if (input === "touch") {
    dispatch(target, "pointerdown", {pointerType: "touch"});
    dispatch(target, "touchstart", {touches: [{}]});
    dispatch(target, "pointerup", {pointerType: "touch"});
    dispatch(target, "touchend", {touches: []});
    hovered = target;
    if (browser === "hover-no-click" && openItems().some((item) => !hiddenBefore.has(item))) click = false;
  } else if (input === "scroll") {
    dispatch(target, "pointerdown", {pointerType: "touch"});
    dispatch(target, "pointercancel", {pointerType: "touch"});
    click = false;
  } else if (input === "keyboard") {
    dispatch(target, "keydown", {key: "Enter"});
  } else if (input === "mouse") {
    hovered = target;
    dispatch(target, "pointerdown", {pointerType: "mouse"});
    dispatch(target, "mousedown");
    dispatch(target, "pointerup", {pointerType: "mouse"});
    dispatch(target, "mouseup");
  }
  let navigated = null;
  if (click) {
    const event = dispatch(target, "click", {pointerType: input === "keyboard" || input === "activate" ? "" : input});
    const a = target.closest("a");
    if (a && !event.defaultPrevented) navigated = a.getAttribute("href");
  }
  if (input === "touch" && browser === "hover-lost") hovered = null;
  results.push({navigated, open: openItems()});
  if (navigated) break;
}
console.log(JSON.stringify(results));
"""


def css_open_classes(out):
    """Return the classes that the built site CSS uses to show the submenu of a menu item."""
    css = "".join(path.read_text() for path in (out / "css").glob("*.css"))
    classes = []
    for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if not re.search(r"display:\s*block", declarations):
            continue
        for selector in selectors.split(","):
            match = re.fullmatch(r"#access(?: ul)? li\.([\w-]+)\s*>\s*ul", selector.strip())
            if match:
                classes.append(match[1])
    return classes


def touch_menu(browser, taps, path="/about/"):
    """Tap the menu of the built page at path in browser, as TOUCH_MENU describes.

    taps is a list of link texts, or of (text, input) pairs for input other than touch.
    """
    out = build()
    html_page = (out / path.lstrip("/") / "index.html").read_text()
    script = re.search(r'<script src="(/js/site[^"]*\.js)"', html_page)[1]
    parser = MenuParser()
    parser.feed(html_page)
    taps = [{"text": tap, "input": "touch"} if isinstance(tap, str) else {"text": tap[0], "input": tap[1]}
            for tap in taps]
    run = subprocess.run(["node", "-e", TOUCH_MENU, str(out / script.lstrip("/")), f"https://stimhack.com{path}",
                          json.dumps(parser.menu), json.dumps(css_open_classes(out)),
                          json.dumps({"browser": browser, "taps": taps})],
                         capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(run.stderr)
    return json.loads(run.stdout)


@needs_node
class TouchMenu(unittest.TestCase):
    # On touch screens wider than the small screen menu, the WordPress theme
    # (js/frontend.js in Tempera) cancelled the first tap on a top level menu
    # item that has a submenu, so the submenu opened, and followed the link on
    # the second tap. Without this, a browser that follows the link on the
    # first tap shows no way to the submenu items. Browsers differ in what
    # they do on a tap, so the tests run each browser model that TOUCH_MENU
    # describes. The models do not include focus, which some browsers give to
    # a tapped link.
    maxDiff = None
    ARTICLES = "Articles and Guides"
    TAP_BROWSERS = ["hover-kept", "hover-lost"]

    def test_first_tap_on_item_with_submenu_opens_the_submenu(self):
        for browser in self.TAP_BROWSERS + ["hover-no-click"]:
            with self.subTest(browser=browser):
                self.assertEqual(touch_menu(browser, [self.ARTICLES]),
                                 [{"navigated": None, "open": [self.ARTICLES]}])

    def test_second_tap_follows_the_link(self):
        for browser in self.TAP_BROWSERS + ["hover-no-click"]:
            with self.subTest(browser=browser):
                self.assertEqual(touch_menu(browser, [self.ARTICLES, self.ARTICLES]), [
                    {"navigated": None, "open": [self.ARTICLES]},
                    {"navigated": "/category/articles/", "open": [self.ARTICLES]},
                ])

    def test_submenu_item_can_be_tapped_after_the_first_tap(self):
        for browser in self.TAP_BROWSERS + ["hover-no-click"]:
            with self.subTest(browser=browser):
                self.assertEqual(touch_menu(browser, [self.ARTICLES, "Set Reviews"]), [
                    {"navigated": None, "open": [self.ARTICLES]},
                    {"navigated": "/set-reviews/", "open": [self.ARTICLES]},
                ])

    def test_tap_outside_closes_the_submenu_and_the_next_tap_is_a_first_tap(self):
        for browser in self.TAP_BROWSERS:
            with self.subTest(browser=browser):
                self.assertEqual(touch_menu(browser, [self.ARTICLES, "outside", self.ARTICLES]), [
                    {"navigated": None, "open": [self.ARTICLES]},
                    {"navigated": None, "open": []},
                    {"navigated": None, "open": [self.ARTICLES]},
                ])

    def test_item_without_submenu_follows_the_link_on_the_first_tap(self):
        for browser in self.TAP_BROWSERS + ["hover-no-click"]:
            with self.subTest(browser=browser):
                self.assertEqual(touch_menu(browser, ["About"]), [{"navigated": "/about/", "open": []}])

    def test_click_after_a_tap_that_fired_no_click_follows_the_link(self):
        # A tap that fires no click leaves no state that makes a later click
        # that is not from that tap open the submenu: in "hover-no-click" the
        # first tap fires no click, and a touch that becomes a scroll fires
        # no click in any browser model.
        cases = [
            ("hover-no-click", [self.ARTICLES, "outside", (self.ARTICLES, "keyboard")]),
            ("hover-no-click", [self.ARTICLES, (self.ARTICLES, "keyboard")]),
            ("hover-no-click", [self.ARTICLES, "outside", (self.ARTICLES, "activate")]),
        ] + [(browser, [(self.ARTICLES, "scroll"), (self.ARTICLES, tool)])
             for browser in self.TAP_BROWSERS + ["hover-no-click"] for tool in ["keyboard", "activate"]]
        for browser, taps in cases:
            with self.subTest(browser=browser, taps=taps):
                self.assertEqual(touch_menu(browser, taps)[-1]["navigated"], "/category/articles/")

    def test_mouse_and_keyboard_follow_the_link_on_the_first_click(self):
        for browser in self.TAP_BROWSERS:
            for tool in ["mouse", "keyboard"]:
                with self.subTest(browser=browser, input=tool):
                    self.assertEqual(touch_menu(browser, [(self.ARTICLES, tool)])[0]["navigated"],
                                     "/category/articles/")


def root_context_uses_in_blocks(text):
    """Yield each action that uses $. inside a range or with block."""
    stack = []
    for action in re.findall(r"{{-?\s*(.*?)\s*-?}}", text, re.S):
        keyword = action.split(maxsplit=1)[0] if action.split() else ""
        if keyword in ("range", "with", "if", "define", "block"):
            stack.append(keyword)
        elif keyword == "end":
            stack.pop()
        elif ("range" in stack or "with" in stack) and "$." in action:
            yield action


class RootContext(unittest.TestCase):
    def test_page_templates_do_not_use_root_context_in_blocks(self):
        # In a page template $ is the page that is rendered, so $. inside
        # range or with names that page and not the current item. Partials
        # are not checked: in a partial $ is the value the caller gives, and
        # term.html gives article-summary.html the post. No shortcode uses $.
        found = []
        for path in sorted((ROOT / "layouts").rglob("*")):
            parts = path.relative_to(ROOT / "layouts").parts
            if path.is_file() and parts[0] not in ("_partials", "_shortcodes"):
                found += [(str(path.relative_to(ROOT)), a) for a in root_context_uses_in_blocks(path.read_text())]
        self.assertEqual(found, [])


def archive_summaries(out):
    """Return (post URL, summary text) for each post entry on the category archive pages in out."""
    found = []
    for page in sorted(out.glob("category/**/index.html")):
        for article in page.read_text().split("<article ")[1:]:
            summary = re.search(r'<div class="entry-summary">.*?<p>([^<]*)</p>', article, re.S)
            if summary:
                url = re.search(r'<h2 class="entry-title"><a href="([^"]*)"', article)[1]
                found.append((url, html.unescape(summary[1])))
    return found


def feed_descriptions(out):
    """Return (post URL, description text) for each item in the RSS feed in out."""
    items = re.findall(r"<item>.*?<link>https://stimhack\.com(/[^<]*)</link>.*?<description>([^<]*)</description>", (out / "index.xml").read_text(), re.S)
    return [(url, html.unescape(text)) for url, text in items]


def meta_description(out, url):
    """Return the text of the meta description on the page at url."""
    page = (out / url.strip("/") / "index.html").read_text()
    return html.unescape(re.search(r'<meta name="description" content="([^"]*)">', page)[1])


def front_matter_summaries(content):
    """Return {post URL: front matter summary} for each post in content that has one."""
    return {url: post.front["summary"] for url, post in all_posts(content).items() if post.front.get("summary")}


def is_start_of(text, summary):
    """Tell if text is summary, or the start of summary with " …" added as Hugo's truncate does."""
    return text == summary or (text.endswith(" …") and summary.startswith(text.removesuffix(" …")))


FIXTURE = ROOT / "tests" / "fixtures" / "summaries"
LOOKALIKES = 'Lock of the Year <tm> picks, *sounds of a ruckus*, "quoted" & R&amp;D'


class FrontMatterSummaries(unittest.TestCase):
    """Migrated posts keep the WordPress excerpt as plain text in front matter summary."""

    maxDiff = None

    def test_archive_entry_shows_summary_as_written(self):
        entries = dict(archive_summaries(build(FIXTURE)))
        self.assertEqual(entries["/markup-lookalikes/"], LOOKALIKES)

    def test_feed_description_shows_summary_as_written(self):
        items = dict(feed_descriptions(build(FIXTURE)))
        self.assertEqual(items["/markup-lookalikes/"], LOOKALIKES)

    def test_meta_description_shows_summary_as_written(self):
        self.assertEqual(meta_description(build(FIXTURE), "/markup-lookalikes/"), LOOKALIKES)

    def test_summary_divider_in_content_does_not_replace_summary(self):
        out = build(FIXTURE)
        self.assertEqual(dict(archive_summaries(out))["/summary-divider/"], "The excerpt from front matter.")
        self.assertEqual(dict(feed_descriptions(out))["/summary-divider/"], "The excerpt from front matter.")

    def test_post_without_summary_uses_summary_from_content(self):
        # Hugo makes the summary from the rendered content, so the typographer
        # has made the quotes curly.
        out = build(FIXTURE)
        expected = "First paragraph of a \u201cnew\u201d post & more. Second paragraph."
        self.assertEqual(" ".join(dict(archive_summaries(out))["/new-post/"].split()), expected)
        self.assertEqual(" ".join(dict(feed_descriptions(out))["/new-post/"].split()), expected)

    def test_post_without_summary_has_meta_description_from_content(self):
        # The new post archetype writes summary: "", and CONTRIBUTING.md
        # says a post without a summary gets the start of the post.
        out = build(FIXTURE)
        site_description = tomllib.loads((ROOT / "hugo.toml").read_text())["params"]["description"]
        for url, start in [
            ("/new-post/", "First paragraph of a “new” post & more."),
            ("/empty-summary/", "A post made from the archetype, which leaves summary empty."),
        ]:
            with self.subTest(url=url):
                text = meta_description(out, url)
                self.assertNotEqual(text, site_description)
                self.assertTrue(text.startswith(start), text)

    def test_page_has_meta_description_from_content(self):
        text = meta_description(build(), "/drafting/")
        self.assertTrue(text.startswith("Cube drafting is a fun Netrunner variant"), text)

    def test_home_and_archive_pages_have_site_description(self):
        out = build(FIXTURE)
        site_description = tomllib.loads((ROOT / "hugo.toml").read_text())["params"]["description"]
        for url in ["/", "/category/articles/", "/author/ian/"]:
            with self.subTest(url=url):
                self.assertEqual(meta_description(out, url), site_description)

    def test_post_with_only_an_embed_has_site_description(self):
        # The summary Hugo makes from a post that is only an iframe or an
        # image is only white space, which is not a description.
        out = build(FIXTURE)
        site_description = tomllib.loads((ROOT / "hugo.toml").read_text())["params"]["description"]
        for url in ["/iframe-only/", "/image-only/"]:
            with self.subTest(url=url):
                self.assertEqual(meta_description(out, url), site_description)

    def test_post_with_only_an_embed_has_empty_summary_in_archive_and_feed(self):
        out = build(FIXTURE)
        archive = dict(archive_summaries(out))
        feed = dict(feed_descriptions(out))
        for url in ["/iframe-only/", "/image-only/"]:
            with self.subTest(url=url):
                self.assertEqual((archive[url], feed[url]), ("", ""))

    def test_no_meta_description_is_only_white_space(self):
        out = build()
        blank = []
        for path in sorted(out.rglob("*.html")):
            found = re.search(r'<meta name="description" content="([^"]*)">', path.read_text())
            if found and not html.unescape(found[1]).strip():
                blank.append((str(path.relative_to(out)), found[1]))
        self.assertEqual(blank, [])

    def test_long_meta_description_is_cut_between_characters_not_inside_an_entity(self):
        # The text has "R&D a < b AT&T" at character 160, so a cut made after
        # escaping would leave part of an entity such as "&am".
        out = build(FIXTURE)
        attribute = re.search(
            r'<meta name="description" content="([^"]*)">',
            (out / "long-post" / "index.html").read_text(),
        )[1]
        self.assertEqual(re.findall(r"&(?!amp;|lt;|gt;|#34;|#39;|quot;)", attribute), [])
        post = (FIXTURE / "posts" / "long-post.md").read_text().split("---\n")[2].strip()
        self.assertTrue(is_start_of(html.unescape(attribute), post), attribute)
        self.assertLessEqual(len(html.unescape(attribute)), 162)

    def test_every_archive_entry_shows_summary_as_written(self):
        summaries = front_matter_summaries(ROOT / "content")
        wrong = [
            (url, text, summaries[url])
            for url, text in archive_summaries(build())
            if url in summaries and text != summaries[url]
        ]
        self.assertEqual(wrong, [])

    def test_every_feed_description_shows_summary_as_written(self):
        summaries = front_matter_summaries(ROOT / "content")
        wrong = [
            (url, text, summaries[url])
            for url, text in feed_descriptions(build())
            if url in summaries and text != summaries[url]
        ]
        self.assertEqual(wrong, [])

    def test_every_meta_description_shows_summary_as_written(self):
        out = build()
        wrong = []
        for url, summary in front_matter_summaries(ROOT / "content").items():
            text = meta_description(out, url)
            if not is_start_of(text, summary):
                wrong.append((url, text, summary))
        self.assertEqual(wrong, [])

    def test_templates_get_summaries_from_the_summary_partial(self):
        # .Summary renders the front matter summary as Markdown. Only
        # summary-text.html reads it or the front matter summary.
        found = []
        for path in sorted((ROOT / "layouts").rglob("*")):
            name = str(path.relative_to(ROOT))
            if path.is_file() and name != "layouts/_partials/summary-text.html":
                for action in re.findall(r"{{-?\s*(.*?)\s*-?}}", path.read_text(), re.S):
                    if re.search(r"\.(Summary|Params\.summary)\b", action):
                        found.append((name, action))
        self.assertEqual(found, [])


def head(out, url):
    """Return (title, canonical URL) from the head of the page at url."""
    page = (out / url.strip("/") / "index.html").read_text()
    title = re.search(r"<title>([^<]*)</title>", page)[1]
    canonical = re.search(r'<link rel="canonical" href="([^"]*)">', page)
    return html.unescape(title), canonical and canonical[1]


class PaginatedArchives(unittest.TestCase):
    """Page N of an archive has its own title and its own canonical URL."""

    maxDiff = None

    def test_later_page_has_own_title_and_canonical(self):
        self.assertEqual(
            head(build(), "/category/articles/page/2/"),
            ("Articles - StimHack | Page 2", "https://stimhack.com/category/articles/page/2/"),
        )

    def test_every_later_archive_page_has_own_title_and_canonical(self):
        out = build()
        wrong = []
        pages = 0
        for path in sorted(out.glob("*/*/page/*/index.html")):
            number = int(path.parent.name)
            if number == 1:
                continue  # Hugo writes page/1/ as a redirect to the first page.
            pages += 1
            url = "/" + str(path.parent.relative_to(out)) + "/"
            title, canonical = head(out, url)
            if not title.endswith(f" - StimHack | Page {number}") or canonical != "https://stimhack.com" + url:
                wrong.append((url, title, canonical))
        self.assertGreater(pages, 0)
        self.assertEqual(wrong, [])

    def test_first_page_keeps_title_and_canonical(self):
        self.assertEqual(
            head(build(), "/category/articles/"),
            ("Articles - StimHack", "https://stimhack.com/category/articles/"),
        )

    def test_post_keeps_title_and_canonical(self):
        self.assertEqual(
            head(build(), "/drafting-with-netrunner/"),
            ("Drafting with Netrunner - StimHack", "https://stimhack.com/drafting-with-netrunner/"),
        )


UNTITLED = ROOT / "tests" / "fixtures" / "untitled"


class UntitledPages(unittest.TestCase):
    """A page without a title stops the CI build, and the error names its file.

    Without a title the page has the title " - StimHack", an empty heading,
    and an empty title in the feed.
    """

    def test_page_without_title_fails_the_build_and_names_its_file(self):
        with tempfile.TemporaryDirectory() as out:
            # The flags of the build step in .github/workflows/site.yml.
            result = subprocess.run(
                [*hugo(), "--source", str(ROOT), "--destination", out, "--contentDir", str(UNTITLED),
                 "--config", FIXTURE_CONFIG, "--printPathWarnings", "--panicOnWarning"],
                capture_output=True,
                text=True,
            )
            names = ["no-title", "empty-title", "blank-title"]
            titles = {name: head(Path(out), f"/{name}/")[0] for name in names if (Path(out) / name).exists()}
        self.assertNotEqual(result.returncode, 0, f"The build succeeded. Page titles: {titles}")
        for name in names:
            self.assertIn(str(UNTITLED / "posts" / f"{name}.md"), result.stdout + result.stderr)


def pager_items(out, url):
    """Return the pager of the archive page at url as (text, href, class) items, or None when it has no pager."""
    page = (out / url.strip("/") / "index.html").read_text()
    nav = re.search(r'<nav class="pagination">(.*?)</nav>', page, re.S)
    if not nav:
        return None
    items = []
    for tag, attrs, text in re.findall(r"<(a|span)\b([^>]*)>([^<]*)</\1>", nav[1]):
        href = re.search(r"""href=["']([^"']*)["']""", attrs)
        cls = re.search(r"""class=["']([^"']*)["']""", attrs)
        items.append((html.unescape(text), href and href[1], cls and cls[1]))
    return items


def wordpress_pager(base, pages, current, span=2):
    """Return the pager items the WordPress theme showed on page current of an archive with pages pages.

    This is the pager function of the old theme: range 2, showitems 2 * range + 1.
    """
    if pages == 1:
        return None

    def url(number):
        return base if number == 1 else f"{base}page/{number}/"

    showitems = 2 * span + 1
    items = []
    if current > 2 and current > span + 1 and showitems < pages:
        items.append(("«", url(1), None))
    if current > 1 and showitems < pages:
        items.append(("‹", url(current - 1), None))
    for number in range(1, pages + 1):
        if pages <= showitems or current - span <= number <= current + span:
            if number == current:
                items.append((str(number), None, "current"))
            else:
                items.append((str(number), url(number), "inactive"))
    if current < pages and showitems < pages:
        items.append(("›", url(current + 1), None))
    if current < pages - 1 and current + span - 1 < pages and showitems < pages:
        items.append(("»", url(pages), None))
    return items


def archive_page_counts(out):
    """Return {archive URL: number of pages} for every term archive in out."""
    counts = {}
    for index in sorted(out.glob("*/*/index.html")):
        archive = index.parent
        if archive.parts[-2] not in ("category", "tag", "author"):
            continue
        numbers = [int(p.name) for p in (archive / "page").glob("*") if p.name.isdigit()]
        counts["/" + str(archive.relative_to(out)) + "/"] = max(numbers, default=1)
    return counts


class ArchivePager(unittest.TestCase):
    """The archive pager shows the same items as the pager of the WordPress theme.

    The tests build the posts that came from WordPress, which gave the
    archives the numbers of pages that they had on WordPress.
    """

    maxDiff = None

    def test_archive_with_five_pages_shows_every_page_and_no_arrows(self):
        # Live WordPress, /category/tournament-report/ page 1:
        # <span class='current'>1</span> and links to pages 2 to 5, no arrows.
        base = "/category/tournament-report/"
        self.assertEqual(archive_page_counts(migrated_site())[base], 5)
        self.assertEqual(
            pager_items(migrated_site(), base),
            [("1", None, "current")] + [(str(n), f"{base}page/{n}/", "inactive") for n in range(2, 6)],
        )

    def test_long_archive_pages_match_wordpress(self):
        # Live WordPress, /category/articles/ (26 pages).
        base = "/category/articles/"
        p = lambda n: base if n == 1 else f"{base}page/{n}/"
        self.assertEqual(archive_page_counts(migrated_site())[base], 26)
        expected = {
            1: [("1", None, "current"), ("2", p(2), "inactive"), ("3", p(3), "inactive"),
                ("›", p(2), None), ("»", p(26), None)],
            3: [("‹", p(2), None), ("1", p(1), "inactive"), ("2", p(2), "inactive"),
                ("3", None, "current"), ("4", p(4), "inactive"), ("5", p(5), "inactive"),
                ("›", p(4), None), ("»", p(26), None)],
            4: [("«", p(1), None), ("‹", p(3), None), ("2", p(2), "inactive"),
                ("3", p(3), "inactive"), ("4", None, "current"), ("5", p(5), "inactive"),
                ("6", p(6), "inactive"), ("›", p(5), None), ("»", p(26), None)],
            25: [("«", p(1), None), ("‹", p(24), None), ("23", p(23), "inactive"),
                 ("24", p(24), "inactive"), ("25", None, "current"), ("26", p(26), "inactive"),
                 ("›", p(26), None)],
        }
        for number, items in expected.items():
            with self.subTest(page=number):
                self.assertEqual(pager_items(migrated_site(), p(number)), items)

    def test_every_archive_page_matches_wordpress(self):
        out = migrated_site()
        counts = archive_page_counts(out)
        # The build must have archives on both sides of the five page limit.
        self.assertTrue({1, 2, 5, 6, 26} <= set(counts.values()))
        wrong = []
        for base, pages in counts.items():
            for number in range(1, pages + 1):
                url = base if number == 1 else f"{base}page/{number}/"
                expected = wordpress_pager(base, pages, number)
                actual = pager_items(out, url)
                if actual != expected:
                    wrong.append((url, actual, expected))
        self.assertEqual(wrong[:5], [])


FEEDS = ["index.xml", "feed/index.html"]


def feed_guids(out, feed):
    """Return (post URL path, guid element as written) for each item in the feed file in out."""
    text = (out / feed).read_text()
    # Parse first, so a feed that is not valid XML fails here.
    ElementTree.fromstring(text.encode())
    items = re.findall(r"<item>.*?<link>([^<]*)</link>.*?(<guid[^>]*>[^<]*</guid>)", text, re.S)
    return [(urlsplit(link).path, guid) for link, guid in items]


def wordpress_posts(content):
    """Return {post URL: front matter} for each post in content that came from WordPress."""
    return {url: post.front for url, post in all_posts(content).items() if post.front.get("wp_id")}


@cache
def migrated_content(content):
    """Return a copy of content without the posts that did not come from WordPress.

    The checks against the live WordPress feeds and archives build the site
    from this copy, so the posts that contributors add do not change them.
    """
    copy = Path(tempfile.mkdtemp(prefix="stimhack-migrated-"))
    atexit.register(shutil.rmtree, copy, ignore_errors=True)
    shutil.copytree(content, copy, dirs_exist_ok=True)
    for path, front in content_files(copy / "posts"):
        # Hugo makes a page bundle of the folder of a content file named index,
        # and a branch bundle of one named _index, in any content format
        # (common/paths/pathparser.go in the Hugo source).
        if path.stem == "index" and not front.get("wp_id"):
            shutil.rmtree(path.parent)
        elif path.stem != "_index" and path.exists() and not front.get("wp_id"):
            path.unlink()
    return copy


def migrated_site(environment=None):
    """Return the site built from the posts in content/ that came from WordPress."""
    return build(migrated_content(ROOT / "content"), environment)


class FeedGuids(unittest.TestCase):
    """Feed readers know items by GUID, so migrated posts keep the GUID WordPress gave them.

    The tests build only the posts that came from WordPress, so each site
    feed has 20 of them. Each post that a contributor adds takes the place of
    one of them in the feeds of the real site.
    """

    maxDiff = None

    def assert_wordpress_guids(self, out):
        posts = wordpress_posts(ROOT / "content")
        for feed in FEEDS:
            with self.subTest(feed=feed):
                items = [(url, guid) for url, guid in feed_guids(out, feed) if url in posts]
                self.assertEqual(len(items), 20)
                expected = [(url, f'<guid isPermaLink="false">{posts[url].get("wp_guid")}</guid>') for url, _ in items]
                self.assertEqual(items, expected)

    def test_migrated_posts_keep_wordpress_guid(self):
        self.assert_wordpress_guids(migrated_site())

    def test_staging_feed_has_production_guids(self):
        self.assert_wordpress_guids(migrated_site(environment="staging"))

    def test_older_post_keeps_its_http_guid(self):
        # WordPress wrote http: GUIDs for its older posts. The main feed shows
        # only the newest posts, so the fixture has an older one.
        out = build(FIXTURE)
        for feed in FEEDS:
            with self.subTest(feed=feed):
                guids = dict(feed_guids(out, feed))
                self.assertEqual(guids["/old-post/"], '<guid isPermaLink="false">http://stimhack.com/?p=23</guid>')

    def test_every_migrated_post_has_its_wordpress_guid(self):
        wrong = [
            (url, front.get("wp_guid"))
            for url, front in wordpress_posts(ROOT / "content").items()
            if not re.fullmatch(rf"https?://stimhack\.com/\?p={front['wp_id']}", str(front.get("wp_guid")))
        ]
        self.assertEqual(wrong[:5], [])

    def test_post_without_wordpress_id_has_permalink_guid(self):
        out = build(FIXTURE)
        for feed in FEEDS:
            with self.subTest(feed=feed):
                guids = dict(feed_guids(out, feed))
                self.assertIn(guids["/new-post/"], [
                    "<guid>https://stimhack.com/new-post/</guid>",
                    '<guid isPermaLink="true">https://stimhack.com/new-post/</guid>',
                ])


# The first three pages of https://stimhack.com/feed/ (5 items each) before cutover.
# The site built from the posts that came from WordPress (migrated_site) starts with them.
WORDPRESS_FEED = [
    "/queen-bee-2023/",
    "/a-look-back-at-the-borealis-cycle/",
    "/queen-bee-2022/",
    "/deconstructing-shellgame-by-tehepicwin/",
    "/on-the-rational-player/",
    "/skill-deepdive-tactical-2-runs/",
    "/skill-deepdive-tactical-1/",
    "/state-of-the-game-2021/",
    "/everything-you-need-to-know-about-tournaments-besides-playing-netrunner/",
    "/what-makes-netrunner-special/",
    "/dead-or-alive-2018/",
    "/skill-deepdive-strategy/",
    "/yugioh-and-you-by-sanjay/",
    "/single-sided-swiss-how-it-works-by-ysengrin/",
    "/flavor-text-power-rankings/",
]


class FeedCategories(unittest.TestCase):
    """The WordPress feed left out posts in the decklists category."""

    maxDiff = None

    def test_feed_lists_the_posts_wordpress_listed(self):
        out = migrated_site()
        for feed in FEEDS:
            with self.subTest(feed=feed):
                urls = [url for url, _ in feed_guids(out, feed)]
                self.assertEqual(urls[:len(WORDPRESS_FEED)], WORDPRESS_FEED)

    def test_feed_leaves_out_decklists(self):
        # The newest posts in decklists. All three are in other categories too.
        decklists = [
            "/why-i-hate-shaper-and-you-should-too/",
            "/no-deck-is-an-island-tech-in-context-by-eric-keilback/",
            "/pawnshop-2020-a-primer/",
        ]
        out = build()
        for feed in FEEDS:
            with self.subTest(feed=feed):
                urls = [url for url, _ in feed_guids(out, feed)]
                self.assertEqual([url for url in decklists if url in urls], [])

    def test_feeds_leave_out_decklists_written_other_ways(self):
        # Hugo puts a post in the category whose slug matches a category of
        # its front matter, so "Decklists" and a single value not in a list
        # both put a post in decklists.
        out = build(FEED_CATEGORIES)
        archive = (out / "category" / "decklists" / "index.html").read_text()
        listed = re.findall(r'<h2 class="entry-title"><a href="([^"]*)"', archive)
        self.assertEqual(listed, ["/single-category/", "/capitalised/", "/slug-list/"])
        expected = {
            "index.xml": ["/articles-only/"],
            "feed/index.html": ["/articles-only/"],
            "category/articles/index.xml": ["/articles-only/"],
            "category/articles/feed/index.html": ["/articles-only/"],
            "category/decklists/index.xml": [],
            "category/decklists/feed/index.html": [],
        }
        for feed, urls in expected.items():
            with self.subTest(feed=feed):
                self.assertEqual([url for url, _ in feed_guids(out, feed)], urls)

    def test_templates_get_category_posts_from_the_category_page(self):
        # Templates find the posts in a category from the category page, whose
        # pages are the posts its archive lists (archive-pager.html). They do
        # not use the names as written in front matter or site.Taxonomies.
        # Hugo reads a key of .Params in any case (GetMapValue in
        # tpl/tplimpl/template_funcs.go), and a Taxonomy keys its terms by
        # the name in lower case (resources/page/taxonomy.go). Get and Count
        # take a term and the other methods list every term.
        taxonomy = r"(?:categories|tags|authors)\b"
        pattern = re.compile(
            rf"Params\.{taxonomy}"
            rf"|\bParams?\s+[\"`]{taxonomy}[\"`]"
            r"|Taxonomies\.\w+\.(?!(?:Alphabetical|ByCount|TaxonomyArray|Page)\b)\w+"
            r"|\bindex\s+[\w.$]*Taxonomies\b",
            re.IGNORECASE,
        )
        found = [
            (str(path.relative_to(ROOT)), match[0])
            for path in sorted((ROOT / "layouts").rglob("*"))
            if path.is_file()
            for match in pattern.finditer(path.read_text())
        ]
        self.assertEqual(found, [])


FEED_CATEGORIES = ROOT / "tests" / "fixtures" / "feed-categories"


def served(out, url):
    """Return the text GitHub Pages serves for the URL path url, or None when it serves a 404."""
    target = out / url.lstrip("/")
    for path in (target, target / "index.html"):
        if path.is_file():
            return path.read_text()
    return None


def feed_items(text):
    """Return (post URL path, date) for each item in the RSS text."""
    items = ElementTree.fromstring(text.encode()).iter("item")
    return [
        (urlsplit(item.findtext("link")).path, parsedate_to_datetime(item.findtext("pubDate")))
        for item in items
    ]


class Post(NamedTuple):
    """A post that Hugo publishes: its front matter, with the keys in lower case, and its date."""

    front: dict
    date: datetime


def all_posts(content):
    """Return {post URL: Post} for each post in content that Hugo publishes.

    Hugo gives the URL, the date and the posts that it publishes
    (published_pages), so the tests cannot disagree with the site on them.
    The front matter comes from the content file, with its keys in lower
    case: Hugo reads the keys of front matter in any case (PrepareParams in
    common/hmaps/params.go in the Hugo source). A post whose front matter is
    not YAML raises ValueError: content_files reads only YAML.
    """
    fronts = {path.resolve(): front for path, front in content_files(content / "posts")}
    posts = {}
    for page in published_pages(content):
        if page["kind"] != "page" or page["section"] != "posts":
            continue
        if page["path"] not in fronts:
            raise ValueError(f"no YAML front matter in {page['path']}")
        front = {key.lower(): value for key, value in fronts[page["path"]].items()}
        posts[urlsplit(page["permalink"]).path] = Post(front, datetime.fromisoformat(page["date"]))
    return posts


CONFIG = tomllib.loads((ROOT / "hugo.toml").read_text())
EXCLUDED = set(CONFIG["params"]["feedExcludeCategories"])
FEED_LIMIT = CONFIG["services"]["rss"]["limit"]
CATEGORY_SPELLINGS = ROOT / "tests" / "fixtures" / "category-spellings"


def category_slugs(front):
    """Return the slugs of the categories that Hugo files the post with front matter front under.

    Hugo takes one value that is not a list as one category, and makes the
    slug of a name in lower case with a hyphen for each space (the archives in
    test_feeds_leave_out_decklists_written_other_ways and
    test_feed_check_finds_posts_whose_categories_are_not_written_as_slugs).
    A name with other characters raises ValueError: this function does not
    copy what Hugo does with them.
    """
    names = front.get("categories") or []
    if isinstance(names, str):
        names = [names]
    slugs = set()
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9]+(?:[ -][A-Za-z0-9]+)*", name):
            raise ValueError(f"no known slug for category {name!r}")
        slugs.add(name.lower().replace(" ", "-"))
    return slugs


def category_feed_errors(out, content):
    """Return what is wrong with each category feed in out, built from content.

    A category feed must list the newest posts in the category, newest first,
    and no post in a category of feedExcludeCategories.
    """
    posts = all_posts(content)
    wrong = []
    for slug in sorted(p.parent.name for p in out.glob("category/*/index.html")):
        for url in [f"/category/{slug}/feed/", f"/category/{slug}/index.xml"]:
            text = served(out, url)
            if text is None:
                wrong.append((url, "not served"))
                continue
            items = feed_items(text)
            eligible = {
                link: post.date
                for link, post in posts.items()
                if slug in category_slugs(post.front) and not EXCLUDED & category_slugs(post.front)
            }
            links = [link for link, _ in items]
            dates = [date for _, date in items]
            if len(links) != min(FEED_LIMIT, len(eligible)):
                wrong.append((url, "count", len(links), len(eligible)))
            elif not set(links) <= set(eligible):
                wrong.append((url, "not eligible", sorted(set(links) - set(eligible))))
            elif dates != sorted(dates, reverse=True):
                wrong.append((url, "not newest first"))
            elif links and any(eligible[link] > dates[-1] for link in set(eligible) - set(links)):
                wrong.append((url, "misses a newer post"))
    return wrong


class CategoryFeeds(unittest.TestCase):
    """WordPress served a feed for each category at /category/<slug>/feed/."""

    maxDiff = None

    def test_articles_feed_lists_the_posts_wordpress_listed(self):
        # Live WordPress, https://stimhack.com/category/articles/feed/ before cutover.
        # It leaves out why-i-hate-shaper-and-you-should-too, which is in decklists too.
        wordpress = [
            "/queen-bee-2023/",
            "/a-look-back-at-the-borealis-cycle/",
            "/queen-bee-2022/",
            "/deconstructing-shellgame-by-tehepicwin/",
            "/on-the-rational-player/",
        ]
        for url in ["/category/articles/feed/", "/category/articles/index.xml"]:
            with self.subTest(url=url):
                text = served(migrated_site(), url)
                self.assertIsNotNone(text, f"{url} is not served")
                urls = [link for link, _ in feed_items(text)]
                self.assertEqual(urls[:len(wordpress)], wordpress)

    def test_decklists_feed_is_empty(self):
        # Live WordPress, https://stimhack.com/category/decklists/feed/: no items.
        text = served(build(), "/category/decklists/feed/")
        self.assertIsNotNone(text, "/category/decklists/feed/ is not served")
        self.assertEqual(feed_items(text), [])

    def test_every_category_feed_lists_its_newest_posts_without_excluded_ones(self):
        out = build()
        self.assertGreater(len(list(out.glob("category/*/index.html"))), 10)
        self.assertEqual(category_feed_errors(out, ROOT / "content"), [])

    def test_feed_check_finds_posts_whose_categories_are_not_written_as_slugs(self):
        # The posts of these fixtures write categories as titles, with capital
        # letters or as one value and not a list. Their feeds are correct, so
        # the check of every category feed must find no error.
        out = build(CATEGORY_SPELLINGS)
        archive = (out / "category" / "tournament-report" / "index.html").read_text()
        self.assertEqual(re.findall(r'<h2 class="entry-title"><a href="([^"]*)"', archive), ["/report/"])
        expected = {
            "/feed/": ["/report/", "/article/"],
            "/category/articles/feed/": ["/article/"],
            "/category/decklists/feed/": [],
            "/category/tournament-report/feed/": ["/report/"],
        }
        for url, links in expected.items():
            with self.subTest(url=url):
                self.assertEqual([link for link, _ in feed_items(served(out, url))], links)
        for content in [CATEGORY_SPELLINGS, FEED_CATEGORIES]:
            with self.subTest(content=content.name):
                self.assertEqual(category_feed_errors(build(content), content), [])

    def test_category_feed_items_keep_wordpress_guid(self):
        out = migrated_site()
        posts = wordpress_posts(ROOT / "content")
        for feed in ["category/articles/feed/index.html", "category/articles/index.xml"]:
            with self.subTest(feed=feed):
                items = feed_guids(out, feed)
                self.assertEqual(len(items), FEED_LIMIT)
                expected = [(url, f'<guid isPermaLink="false">{posts[url]["wp_guid"]}</guid>') for url, _ in items]
                self.assertEqual(items, expected)

    def test_category_feed_names_itself(self):
        text = served(build(), "/category/articles/feed/")
        self.assertIsNotNone(text, "/category/articles/feed/ is not served")
        self.assertIn('<atom:link href="https://stimhack.com/category/articles/feed/" rel="self"', text)
        self.assertIn("<link>https://stimhack.com/category/articles/</link>", text)

    def test_category_pages_link_to_their_feed(self):
        out = build()
        for url in ["/category/articles/", "/category/articles/page/2/", "/category/decklists/"]:
            with self.subTest(url=url):
                slug = url.split("/")[2]
                self.assertIn(
                    f'<link rel="alternate" type="application/rss+xml" title="StimHack &raquo; {html.escape(slug.title())} Category Feed"'
                    f' href="https://stimhack.com/category/{slug}/feed/">',
                    served(out, url),
                )

    def test_site_feed_is_still_at_its_old_urls(self):
        out = build()
        for url in ["/feed/", "/index.xml"]:
            with self.subTest(url=url):
                self.assertIn('<atom:link href="https://stimhack.com/feed/" rel="self"', served(out, url))


def build_with_params(params, out, content=CATEGORY_SPELLINGS):
    """Build content into out with FIXTURE_CONFIG and the site params in params.

    Return the finished Hugo process. The params go in a third config file:
    Hugo reads an environment variable such as HUGO_PARAMS_FEEDEXCLUDECATEGORIES
    as a string, not a list.
    """
    extra = Path(out) / "params.toml"
    extra.write_text("[params]\n" + "".join(f"  {key} = {json.dumps(value)}\n" for key, value in params.items()))
    return subprocess.run(
        [*hugo(), "--source", str(ROOT), "--destination", str(Path(out) / "public"),
         "--contentDir", str(content), "--config", f"{FIXTURE_CONFIG},{extra}"],
        capture_output=True,
        text=True,
    )


def home_grid(out):
    """Return the URL of each post in the home page grid of the site in out, or None when there is no home page."""
    home = Path(out) / "public" / "index.html"
    if not home.exists():
        return None
    return re.findall(r'wc-shortcodes-entry-title"><a href="([^"]*)"', home.read_text())


def site_feed(out):
    """Return the URL path of each item in the site feed of the site in out, or None when there is no feed."""
    feed = Path(out) / "public" / "index.xml"
    return [url for url, _ in feed_guids(feed.parent, feed.name)] if feed.exists() else None


class CategoryParams(unittest.TestCase):
    """homeCategory and feedExcludeCategories in hugo.toml name categories.

    A name that is not a category, such as a misspelt or renamed one, stops
    the build and the error names it. Otherwise the home page would show the
    posts of every category, and the feeds would leave out nothing.
    """

    def test_home_category_that_is_not_a_category_fails_the_build_and_names_it(self):
        with tempfile.TemporaryDirectory() as out:
            result = build_with_params({"homeCategory": "nosuch"}, out)
            grid = home_grid(out)
        self.assertNotEqual(result.returncode, 0, f"The build succeeded. Home page grid: {grid}")
        self.assertIn('homeCategory "nosuch"', result.stdout + result.stderr)

    def test_feed_exclude_category_that_is_not_a_category_fails_the_build_and_names_it(self):
        for name in ["nosuch", ""]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as out:
                result = build_with_params({"feedExcludeCategories": [name]}, out)
                feed = site_feed(out)
                self.assertNotEqual(result.returncode, 0, f"The build succeeded. Site feed: {feed}")
                self.assertIn(f'feedExcludeCategories has "{name}"', result.stdout + result.stderr)

    def test_category_with_a_page_and_no_posts_is_valid(self):
        # content/categories/<slug>/_index.md gives a category a page. The
        # real site has one for each category, so a category that has lost
        # its last post is still a category. A fixture without a post in a
        # category of hugo.toml needs one too.
        with tempfile.TemporaryDirectory() as out:
            content = Path(out) / "content"
            shutil.copytree(CATEGORY_SPELLINGS, content)
            (content / "categories" / "unused").mkdir(parents=True)
            (content / "categories" / "unused" / "_index.md").write_text("---\ntitle: Unused\n---\n")
            result = build_with_params({"homeCategory": "unused", "feedExcludeCategories": ["unused"]}, out, content)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(home_grid(out), [])
            self.assertEqual(site_feed(out), ["/decklist/", "/report/", "/article/"])

    def test_home_category_shows_the_posts_that_write_it_as_a_title(self):
        # The fixture posts write their categories with capital letters, and
        # report.md writes tournament-report as "Tournament Report". No post
        # writes a category as its slug.
        expected = {
            "tournament-report": ["/report/"],
            "articles": ["/decklist/", "/article/"],
            "decklists": ["/decklist/"],
        }
        for slug, posts in expected.items():
            with self.subTest(slug=slug), tempfile.TemporaryDirectory() as out:
                result = build_with_params({"homeCategory": slug}, out)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(home_grid(out), posts)

    def test_empty_home_category_shows_the_newest_posts_of_every_category(self):
        with tempfile.TemporaryDirectory() as out:
            result = build_with_params({"homeCategory": ""}, out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(home_grid(out), ["/decklist/", "/report/", "/article/"])

    def test_empty_feed_exclude_categories_leaves_out_nothing(self):
        with tempfile.TemporaryDirectory() as out:
            result = build_with_params({"feedExcludeCategories": []}, out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(site_feed(out), ["/decklist/", "/report/", "/article/"])


def build_with_menu(menu, out, content=CATEGORY_SPELLINGS):
    """Build content into out with hugo.toml and the main menu in menu, a TOML string.

    Return the finished Hugo process. The menus of the second config file
    replace the menus of hugo.toml.
    """
    extra = Path(out) / "menu.toml"
    extra.write_text(menu)
    return subprocess.run(
        [*hugo(), "--source", str(ROOT), "--destination", str(Path(out) / "public"),
         "--contentDir", str(content), "--config", f"{ROOT / 'hugo.toml'},{extra}"],
        capture_output=True,
        text=True,
    )


def menu_links(out):
    """Return each item of the main menu on the home page of the site in out as 'name href="..."'."""
    home = Path(out) / "public" / "index.html"
    if not home.exists():
        return None
    parser = MenuParser()
    parser.feed(home.read_text())

    def links(items):
        for item in items:
            yield f'{item["text"].strip()} href="{item["href"]}"'
            yield from links(item["children"] or [])

    return list(links(parser.menu))


# Menu entries whose pages are in CATEGORY_SPELLINGS, and a link to another site.
MENU = """
[[menus.main]]
  name = "Home"
  pageRef = "/"
  weight = 10
[[menus.main]]
  name = "Forums"
  url = "http://forum.stimhack.com/"
  weight = 20
[[menus.main]]
  identifier = "articles"
  name = "Articles and Guides"
  pageRef = "/categories/articles"
  weight = 30
[[menus.main]]
  parent = "articles"
  name = "All Articles"
  pageRef = "/categories/articles"
  weight = 1
"""


class MenuEntries(unittest.TestCase):
    """Each entry of the main menu in hugo.toml links to a page or to a URL.

    A pageRef that names no page, such as a misspelt one or the path of a
    page that moved, stops the build and the error names the entry.
    Otherwise Hugo gives the entry an empty URL, and the menu links to the
    page that shows it.
    """

    def test_entry_whose_page_ref_names_no_page_fails_the_build_and_names_it(self):
        entries = {
            "top level": ("Missing", '  pageRef = "/pages/nosuch"\n  weight = 40\n'),
            "child": ("Missing Child", '  parent = "articles"\n  pageRef = "/pages/nosuch-child"\n  weight = 2\n'),
            "no pageRef or url": ("Nowhere", "  weight = 50\n"),
        }
        for case, (name, fields) in entries.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as out:
                result = build_with_menu(MENU + f'[[menus.main]]\n  name = "{name}"\n{fields}', out)
                links = menu_links(out)
                self.assertNotEqual(result.returncode, 0, f"The build succeeded. Menu: {links}")
                self.assertIn(f'"{name}"', result.stdout + result.stderr)
                page_ref = re.search(r'pageRef = ("[^"]*")', fields)
                if page_ref:
                    self.assertIn(page_ref[1], result.stdout + result.stderr)

    def test_entries_with_a_page_or_a_url_build(self):
        with tempfile.TemporaryDirectory() as out:
            result = build_with_menu(MENU, out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(menu_links(out), [
                'Home href="/"',
                'Forums href="http://forum.stimhack.com/"',
                'Articles and Guides href="/category/articles/"',
                'All Articles href="/category/articles/"',
            ])


# Open a built page once for each query string after argv[2]: run its inline
# scripts in node with a fetch that reads files from the build and a location
# that records replace(). Print what each opening did as a JSON list.
OPEN_PAGE = r"""
const fs = require("fs"), path = require("path"), vm = require("vm");
const [out, page, ...searches] = process.argv.slice(1);
const html = fs.readFileSync(path.join(out, page), "utf8");
const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)]
  .filter(([, attrs]) => !/\bsrc=/.test(attrs)).map(([, , code]) => code);

async function open(search) {
  const result = {replaced: null, fetched: [], errors: []};
  const location = {href: "https://stimhack.com/" + search, origin: "https://stimhack.com",
    pathname: "/", search, hash: "", replace(url) { result.replaced = url; }};
  function fetch(url) {
    const pathname = new URL(url, location.href).pathname;
    result.fetched.push(pathname);
    const file = path.join(out, pathname);
    const found = fs.existsSync(file) && fs.statSync(file).isFile();
    return Promise.resolve({ok: found, status: found ? 200 : 404,
      json: async () => { if (!found) throw new Error("404"); return JSON.parse(fs.readFileSync(file, "utf8")); }});
  }
  const context = vm.createContext({location, fetch, URL, URLSearchParams, console,
    addEventListener() {}, document: {documentElement: {style: {}}}});
  context.window = context;
  for (const code of scripts) {
    try { vm.runInContext(code, context); } catch (e) { result.errors.push(String(e)); }
  }
  await new Promise((resolve) => setTimeout(resolve, 20));
  return result;
}

(async () => {
  const results = [];
  for (const search of searches) results.push(await open(search));
  console.log(JSON.stringify(results));
})();
"""


def open_page(out, page, *searches):
    """Return what the inline scripts of page did when it was opened with each query string in searches."""
    run = subprocess.run(["node", "-e", OPEN_PAGE, str(out), page, *searches],
                         capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def wordpress_ids(content):
    """Return {WordPress ID: URL} for each post and page in content that came from WordPress."""
    ids = {front["wp_id"]: url for url, front in wordpress_posts(content).items()}
    for path, front in content_files(content / "pages"):
        if front.get("wp_id"):
            ids[front["wp_id"]] = front["url"]
    return ids


@needs_node
class PostIdLinks(unittest.TestCase):
    """/?p=<ID> and /?page_id=<ID> open the post or page with that ID.

    These are the forms of the WordPress GUIDs in the export. Each post in
    .export/posts.json has a GUID /?p=<ID>. In .export/pages.json, 14 of the
    16 pages have a GUID /?page_id=<ID>. Page 8083 (glossary-2) has the GUID
    http://stimhack.com/glossary-2/ and page 7011 has no GUID.
    """

    maxDiff = None

    def assert_opens(self, search, expected, page="index.html"):
        [result] = open_page(build(), page, search)
        self.assertEqual((result["replaced"], result["errors"]), (expected, []))

    def test_post_id_goes_to_the_post(self):
        self.assert_opens("?p=5525", "/2014-world-championship-report-1st-place/")

    def test_page_id_goes_to_the_page(self):
        self.assert_opens("?page_id=1879", "/articles-and-guides/")

    def test_either_parameter_takes_any_id(self):
        # No post in .export/posts.json has the ID of a page in .export/pages.json,
        # and the script looks up both parameters in one map, so either finds either.
        self.assert_opens("?p=1879", "/articles-and-guides/")
        self.assert_opens("?page_id=5525", "/2014-world-championship-report-1st-place/")

    def test_posts_restored_from_the_internet_archive_keep_their_id(self):
        self.assert_opens("?p=52", "/drafting-with-netrunner/")
        self.assert_opens("?p=798", "/cube-drafting-revisited/")

    def test_other_parameters_do_not_stop_the_redirect(self):
        self.assert_opens("?utm_source=x&p=5525&replytocom=1", "/2014-world-championship-report-1st-place/")

    def test_unknown_id_stays_on_the_home_page(self):
        for search in ["?p=999999", "?p=abc", "?p=", "?page_id=0"]:
            with self.subTest(search=search):
                self.assert_opens(search, None)

    def test_home_page_without_id_does_not_load_the_map(self):
        searches = ["", "?s=netrunner", "?paged=2", "?pp=5525"]
        results = open_page(build(), "index.html", *searches)
        self.assertEqual([(r["replaced"], r["fetched"], r["errors"]) for r in results], [(None, [], [])] * len(searches))

    def test_not_found_page_redirects_old_id_links_too(self):
        self.assert_opens("?p=5525", "/2014-world-championship-report-1st-place/", page="404.html")

    def test_every_post_and_page_id_goes_to_its_url(self):
        ids = wordpress_ids(ROOT / "content")
        self.assertGreater(len(ids), 1900)
        results = open_page(build(), "index.html", *(f"?p={wp_id}" for wp_id in ids))
        wrong = [
            (wp_id, result["replaced"], url)
            for (wp_id, url), result in zip(ids.items(), results)
            if (result["replaced"], result["errors"]) != (url, [])
        ]
        self.assertEqual(wrong[:5], [])


EXPORT = ROOT / ".export"


@unittest.skipUnless((EXPORT / "pages.json").exists() and (EXPORT / "posts.json").exists(), "needs the WordPress export")
class ExportIdsInMap(unittest.TestCase):
    """wp-ids.json has the ID of each post and page in the export that the site still serves."""

    def test_every_served_export_url_has_its_id(self):
        out = build()
        urls = json.loads((out / "wp-ids.json").read_text())
        pages = json.loads((EXPORT / "pages.json").read_text())
        posts = json.loads((EXPORT / "posts.json").read_text())
        page_urls = {urlsplit(page["link"]).path for page in pages}
        served = [
            (item["id"], urlsplit(item["link"]).path)
            for item in pages + posts
            # A link to the home page already opens the home page.
            if urlsplit(item["link"]).path != "/"
            and (out / urlsplit(item["link"]).path.strip("/") / "index.html").exists()
        ]
        self.assertGreater(len(served), 1900)
        # A post with the URL of a page has a URL of its own (see convert_posts).
        posts_at_page_urls = {post["id"] for post in posts if urlsplit(post["link"]).path in page_urls}
        wrong = [
            (wp_id, urls.get(str(wp_id)), url)
            for wp_id, url in served
            if urls.get(str(wp_id)) != url and not (wp_id in posts_at_page_urls and str(wp_id) in urls)
        ]
        self.assertEqual(wrong, [])


def id_problems(out):
    """Return the lines about WordPress IDs that scripts/check_site.py prints for the built site in out."""
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
        check_site.main([str(out)])
    return [line for line in stdout.getvalue().splitlines() if line.startswith("WordPress ID")]


class ListedIds(unittest.TestCase):
    """The check of the built site finds a WordPress ID that /wp-ids.json lost.

    CI does not have the export, so ExportIdsInMap does not run there, and
    PostIdLinks takes its IDs from the content files.
    """

    def test_reports_a_page_that_lost_its_wp_id(self):
        content = Path(tempfile.mkdtemp(prefix="stimhack-lost-id-"))
        self.addCleanup(shutil.rmtree, content, ignore_errors=True)
        shutil.copytree(ROOT / "content", content, dirs_exist_ok=True)
        about = content / "pages" / "about.html"
        text = about.read_text()
        self.assertIn("\nwp_id: 2\n", text)
        about.write_text(text.replace("\nwp_id: 2\n", "\n", 1))
        self.assertEqual(id_problems(build(content)), ["WordPress ID missing from /wp-ids.json: 2 /about/"])

    def test_the_site_has_every_listed_id(self):
        self.assertEqual(id_problems(build()), [])


BUNDLES = ROOT / "tests" / "fixtures" / "bundles"


def linked_paths(out, url):
    """Return the paths on the site that the page at url links to, resolved against url."""
    hosts = check_site.SITE_HOSTS | {check_site.built_host(out)}
    return set(check_site.site_paths(url, (out / url.strip("/") / "index.html").read_text(), hosts))


class BundleFiles(unittest.TestCase):
    """A new post keeps its images and files in its folder and refers to them by file name.

    A video post shows its whole content on archive pages, so there the
    references must still point to the files in the post folder.
    """

    maxDiff = None

    def test_archive_pages_link_to_the_files_in_the_post_folder(self):
        out = build(BUNDLES)
        files = {"/bundle-video/hedge-fund.png", "/bundle-video/rules.pdf"}
        for url in ["/bundle-video/", "/category/videos-and-podcasts/", "/tag/bundles/", "/author/ian/"]:
            with self.subTest(url=url):
                paths = linked_paths(out, url)
                self.assertEqual(files - paths, set(), sorted(p for p in paths if p.endswith((".png", ".pdf"))))

    def test_no_page_has_a_broken_link(self):
        self.assertEqual(missing_targets(build(BUNDLES)), [])


def missing_targets(out):
    """Return (page URL, path) for each path on the site that a page in the built site out links to and that is not a file."""
    hosts = check_site.SITE_HOSTS | {check_site.built_host(out)}
    broken = []
    for page in sorted(out.rglob("*.html")):
        url = "/" + page.relative_to(out).as_posix()
        broken += [
            (url, path) for path in check_site.site_paths(url, page.read_text(), hosts) if not check_site.exists(out, path)
        ]
    return broken


class KnownBrokenLinks(unittest.TestCase):
    """The check skips the links in tests/known-broken-links.txt, which were already broken on WordPress.

    Each line must be a path as check_site.site_paths gives it for a link in
    the built site. A line in another form, such as a percent-encoded path or
    a path without its trailing slash, skips nothing, and the check then
    reports the link.
    """

    def test_each_listed_path_is_a_broken_link_in_the_built_site(self):
        broken = {path for _, path in missing_targets(build())}
        self.assertNotEqual(check_site.KNOWN_BROKEN, set())
        self.assertEqual(sorted(check_site.KNOWN_BROKEN - broken), [])

    def test_the_check_reports_no_broken_link_in_the_built_site(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            check_site.main([str(build())])
        self.assertEqual([line for line in stdout.getvalue().splitlines() if line.startswith("broken link in ")], [])


class StagingRobots(unittest.TestCase):
    """The staging site asks search engines not to index its pages with a noindex meta tag.

    A crawler reads the tag only if robots.txt lets it fetch the page. Google:
    "For the noindex rule to be effective, the page or resource must not be
    blocked by a robots.txt file"
    (https://developers.google.com/search/docs/crawling-indexing/block-indexing).
    """

    NOINDEX = '<meta name="robots" content="noindex, nofollow">'

    def test_robots_txt_lets_crawlers_fetch_the_pages_with_the_noindex_tag(self):
        out = build(environment="staging")
        robots = RobotFileParser()
        robots.parse((out / "robots.txt").read_text().splitlines())
        pages = [
            "/" + page.relative_to(out).as_posix().removesuffix("index.html")
            for page in sorted(out.rglob("*.html"))
            if self.NOINDEX in page.read_text()
        ]
        self.assertIn("/", pages)
        blocked = [url for url in pages if not robots.can_fetch("*", url)]
        self.assertEqual(blocked[:5], [])

    def test_every_staging_html_page_has_the_noindex_tag(self):
        # Crawlers can fetch every page, so a page without the tag can be
        # indexed. The feeds at feed/index.html are RSS, not HTML.
        out = build(environment="staging")
        missing = [
            page.relative_to(out).as_posix()
            for page in sorted(out.rglob("*.html"))
            if page.read_text().startswith("<!DOCTYPE html>") and self.NOINDEX not in page.read_text()
        ]
        self.assertEqual(missing[:5], [])


if __name__ == "__main__":
    unittest.main()
