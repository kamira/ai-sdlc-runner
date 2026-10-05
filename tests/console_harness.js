// Runs the console page's own script against a fake DOM and a REAL `runner serve` (CHG-20261005-03).
//
// usage: node console_harness.js <index.html> <base url> <token> <scenario> [json args]
//
// The page's script is loaded as it ships, minus its start-up chain (everything from "// --- go"),
// so a test drives the same `drawFlow`, `renderPanel`, `save` and `api` a browser would, and the
// requests go over HTTP to the real server. What this is not: a browser. Layout, CSS and focus
// rings are not exercised, and the fake DOM implements only what the page's code calls.
"use strict";
const fs = require("fs");
const vm = require("vm");

const [, , pagePath, base, token, scenario, rawArgs] = process.argv;
const args = rawArgs ? JSON.parse(rawArgs) : {};
const html = fs.readFileSync(pagePath, "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>"));

// -- the layout alone, lifted out of the page: it must need nothing but its own constants --------
if (scenario === "layout") {
  const consts = script.match(/^var W = .*;$/m)[0];
  const fn = script.slice(script.indexOf("// LAYOUT-BEGIN"), script.indexOf("// LAYOUT-END"));
  const sandbox = vm.createContext({});          // no document, no window, no fetch
  vm.runInContext(consts + "\n" + fn, sandbox);
  const out = args.sets.map((nodes, i) => JSON.parse(JSON.stringify(
    sandbox.layout(nodes, args.widths ? args.widths[i] : undefined))));
  console.log(JSON.stringify(out));
  process.exit(0);
}

// -- a fake DOM, only as deep as the page's code goes ---------------------------------------------
const byId = {};
let active = null;
const docListeners = {};
class El {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {};
    this.className = ""; this._text = ""; this._html = ""; this.style = {}; this.hidden = false;
    this.id = ""; this.disabled = false; this.value = ""; this.checked = false;
  }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(c, ref) {
    const i = this.children.indexOf(ref);
    this.children.splice(i < 0 ? this.children.length : i, 0, c); return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  focus() { active = this; }
  get textContent() { return [this._text].concat(this.children.map((c) => c.textContent)).join(" "); }
  set textContent(v) { this._text = String(v); this.children = []; }
  set innerHTML(v) { this._html = String(v); this._text = ""; this.children = []; }
  get innerHTML() { return this._html; }
  matches(sel) {
    let m;
    if ((m = /^\[data-node="(.*)"\]$/.exec(sel))) return this.attrs["data-node"] === m[1];
    if (sel[0] === ".") {
      const have = (this.className || this.attrs["class"] || "").split(/\s+/);
      return sel.slice(1).split(".").every((c) => have.indexOf(c) >= 0);
    }
    return false;
  }
  all(pred, out) {
    out = out || [];
    this.children.forEach((c) => { if (pred(c)) out.push(c); c.all(pred, out); });
    return out;
  }
  querySelector(sel) { return this.all((c) => c.matches(sel))[0] || null; }
}
const document = {
  get activeElement() { return active; },
  createElement: (t) => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: (t) => { const e = new El("#text"); e._text = t; return e; },
  addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); },
  querySelector(sel) {
    if (sel[0] === "#") return byId[sel] = byId[sel] || Object.assign(new El("div"), { id: sel.slice(1) });
    const flowBox = byId["#flow"];
    return flowBox ? flowBox.querySelector(sel) : null;
  },
};

let inflight = 0;
const sent = [];
const context = vm.createContext({
  document, console, JSON, Math, Object, Array, String, Number, Error, Promise, setTimeout,
  location: { hash: "#token=" + token, pathname: "/", host: base.replace("http://", "") },
  history: { replaceState() {} },
  sessionStorage: (() => { const s = {}; return { getItem: (k) => s[k] || null, setItem: (k, v) => { s[k] = v; } }; })(),
  fetch: (path, opts) => {
    inflight++;
    sent.push({ path, method: opts.method, body: opts.body ? JSON.parse(opts.body) : null });
    return fetch(base + path, opts).finally(() => { inflight--; });
  },
});
vm.runInContext(script.slice(0, script.indexOf("// --- go")), context);
const run = (code) => vm.runInContext(code, context);

async function settle() {
  for (let quiet = 0; quiet < 3;) {
    await new Promise((r) => setTimeout(r, 25));
    quiet = inflight === 0 ? quiet + 1 : 0;
  }
}
const text = (id) => (byId[id] ? byId[id].textContent.replace(/\s+/g, " ").trim() : "");
const find = (root, pred) => root.all(pred)[0];
const button = (root, label) => find(root, (c) => c.tagName === "button" &&
  (c._text === label || c.attrs["aria-label"] === label));
const box = (root, label) => find(root, (c) => c.tagName === "input" && c.attrs["aria-label"] === label);

async function boot() {
  run('api("GET", "/flow").then(function (f) { flow = f.nodes; return refreshConfig(); })' +
      '.then(function () { return api("GET", "/run"); }).then(function (s) { state = s; })');
  await settle();
}

(async () => {
  await boot();
  const out = {};
  if (scenario === "expand") {
    const app = document.querySelector("#app"), btn = document.querySelector("#expand");
    btn.attrs["aria-pressed"] = "false";
    const fire = () => btn.onclick();
    run("drawFlow()");
    out.before = { cls: app.className, pressed: btn.attrs["aria-pressed"] };
    fire(); out.expanded = { cls: app.className, pressed: btn.attrs["aria-pressed"] };
    const g = byId["#flow"].all((c) => c.attrs["data-node"] !== undefined && c.tagName === "g")[0];
    g.listeners.click.forEach((f) => f({})); await settle();
    out.afterOpen = { cls: app.className, pressed: btn.attrs["aria-pressed"] };
    fire(); fire();
    out.afterTwo = { cls: app.className, pressed: btn.attrs["aria-pressed"] };
  } else if (scenario === "models") {
    run("drawModels()");
    out.models = text("#models");
  } else if (scenario === "keyboard") {
    run("drawFlow()");
    const nodes = byId["#flow"].all((c) => c.attrs["data-node"] !== undefined && c.tagName === "g");
    out.nodes = nodes.map((g) => ({ id: g.attrs["data-node"], tabindex: g.attrs.tabindex,
                                    label: g.attrs["aria-label"] }));
    const key = (k) => (g) => g.listeners.keydown.forEach((f) => f({ key: k, preventDefault() {} }));
    const g = nodes[args.index || 0];
    out.target = g.attrs["data-node"];
    key("Tab")(g); await settle(); out.afterTab = run("picked");
    key("Enter")(g); await settle(); out.afterEnter = run("picked");
    out.panelShown = !byId["#panel"].hidden;
    docListeners.keydown.forEach((f) => f({ key: "Escape" })); await settle();
    out.afterEscape = run("picked"); out.panelHiddenAfterEscape = byId["#panel"].hidden;
    out.focusAfterEscape = active && active.attrs["data-node"];
    key(" ")(nodes[1]); await settle(); out.afterSpace = run("picked");
    nodes[2].listeners.click.forEach((f) => f({})); await settle(); out.afterClick = run("picked");
  } else if (scenario === "panel") {
    out.panels = {};
    for (const id of args.ids) {
      run("openPanel(" + JSON.stringify(id) + ")"); await settle();
      const p = byId["#panel"];
      out.panels[id] = { text: text("#panel"), hidden: p.hidden,
                         buttons: p.all((c) => c.tagName === "button").map((b) => b._text),
                         boxes: p.all((c) => c.tagName === "input").length };
    }
  } else if (scenario === "drive_save") {          // the page's own save(), with a body of our choosing
    run("picked = " + JSON.stringify(args.node)); run("renderPanel()");
    run("save(" + JSON.stringify(args.path) + ", " + JSON.stringify(args.body) + ")");
    await settle(); out.error = text("#panelerr");
  } else if (scenario === "save_models") {          // tick a model on a node, press save
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    const p = byId["#panel"];
    for (const m of args.tick) { const b = box(p, m); b.checked = true; b.onchange(); }
    button(p, "save the models for " + args.node).onclick(); await settle();
    out.error = text("#panelerr"); out.sent = sent.filter((s) => s.method === "POST");
  } else if (scenario === "save_dimensions") {      // reorder / untick seats, press save
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    for (const step of args.steps) {
      const p = byId["#panel"];
      if (step.move) button(p, step.move).onclick();
      if (step.untick) { const b = box(p, "open the " + step.untick + " seat"); b.checked = false; b.onchange(); }
      if (step.tick) { const b = box(p, "open the " + step.tick + " seat"); b.checked = true; b.onchange(); }
    }
    button(byId["#panel"], args.press || "save the review dimensions").onclick(); await settle();
    out.error = text("#panelerr"); out.sent = sent.filter((s) => s.method === "POST");
  } else if (scenario === "save_seat_models") {
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    const p = byId["#panel"];
    for (const m of args.tick) {
      const b = p.all((c) => c.tagName === "input" && c.attrs["aria-label"] === m)[args.nth || 0];
      b.checked = true; b.onchange();
    }
    button(p, "save " + args.seat + " models").onclick(); await settle();
    out.error = text("#panelerr"); out.sent = sent.filter((s) => s.method === "POST");
  }
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
