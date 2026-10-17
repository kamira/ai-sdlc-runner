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
// Ids the page gives to elements it builds. Looked up in the tree, so an element that is not in it
// is not found; every other id is a fixed element of the page and is made on first use.
const BUILT = ["panelerr", "panelok", "paneltitle"];
const document = {
  get activeElement() { return active; },
  createElement: (t) => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: (t) => { const e = new El("#text"); e._text = t; return e; },
  addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); },
  querySelector(sel) {
    if (sel[0] === "#" && BUILT.indexOf(sel.slice(1)) >= 0) {
      const root = byId["#panel"];
      return (root && root.all((c) => c.id === sel.slice(1))[0]) || null;
    }
    if (sel[0] === "#") return byId[sel] = byId[sel] || Object.assign(new El("div"), { id: sel.slice(1) });
    const flowBox = byId["#flow"];
    return flowBox ? flowBox.querySelector(sel) : null;
  },
};

let inflight = 0;
const sent = [];
const refusing = {};          // "METHOD path" or path -> sentence: the fake answer for a route, 409
const holds = {};             // "METHOD path" -> promise: the next such request waits for it first
const context = vm.createContext({
  document, console, JSON, Math, Object, Array, String, Number, Error, Promise, setTimeout,
  location: { hash: "#token=" + token, pathname: "/", host: base.replace("http://", "") },
  history: { replaceState() {} },
  sessionStorage: (() => { const s = {}; return { getItem: (k) => s[k] || null, setItem: (k, v) => { s[k] = v; } }; })(),
  fetch: (path, opts) => {
    const key = opts.method + " " + path;
    if (holds[key]) {
      const gate = holds[key];
      delete holds[key];
      return gate.then(() => context.fetch(path, opts));
    }
    inflight++;
    sent.push({ path, method: opts.method, body: opts.body ? JSON.parse(opts.body) : null });
    // A request counts as in flight until the page has read its body, not only until the headers
    // arrive: the page's `.then` after `r.json()` is what starts the next request.
    const counted = (r) => {
      const read = r.json.bind(r);
      r.json = () => read().finally(() => { inflight--; });
      return r;
    };
    const say = refusing[key] || refusing[path];
    if (say) {
      return Promise.resolve(counted(new Response(JSON.stringify({ error: say }),
                                                  { status: 409 })));
    }
    return fetch(base + path, opts).then(counted, (e) => { inflight--; throw e; });
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
const text = (id) => {
  const e = document.querySelector(id);
  return e ? e.textContent.replace(/\s+/g, " ").trim() : "";
};
const who = (e) => (e ? (e.attrs["aria-label"] || e._text) : null);
const mounted = (e) => !!e && byId["#panel"].all((c) => c === e).length === 1;
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
  } else if (scenario === "usage") {               // the panel drawn from a body of our choosing
    run("drawUsage(" + JSON.stringify(args.data) + ")");
    const u = byId["#usage"];
    out.text = text("#usage");
    out.bars = u.all((c) => c.attrs.role === "progressbar").map((b) => ({
      label: b.attrs["aria-label"], min: b.attrs["aria-valuemin"], max: b.attrs["aria-valuemax"],
      now: b.attrs["aria-valuenow"], valuetext: b.attrs["aria-valuetext"],
      width: b.children[0].style.width }));
  } else if (scenario === "usage_wire") {          // the page's own fetch, to the real /usage
    run('refreshUsage(true)'); await settle();
    out.text = text("#usage");
    out.bars = byId["#usage"].all((c) => c.attrs.role === "progressbar").length;
    out.fetched = sent.filter((s) => s.path === "/usage").length;
  } else if (scenario === "usage_on_apply") {      // refreshed when the run changes, not on a timer
    run("apply(state)"); await settle(); run("apply(state)"); await settle();
    out.afterSame = sent.filter((s) => s.path === "/usage").length;
    run("apply(Object.assign({}, state, { state: 'running' }))"); await settle();
    out.afterChange = sent.filter((s) => s.path === "/usage").length;
  } else if (scenario === "usage_clock") {         // an open page: time passes, no new ask
    run("apply(state)"); await settle();
    run("nowMs = function () { return " + args.first + "; }");
    run("drawUsage(" + JSON.stringify(args.data) + ")");
    out.before = text("#usage");
    out.barsBefore = byId["#usage"].all((c) => c.attrs.role === "progressbar").length;
    run("nowMs = function () { return " + args.later + "; }");
    run("apply(state)"); await settle();
    out.after = text("#usage");
    out.barsAfter = byId["#usage"].all((c) => c.attrs.role === "progressbar").length;
    out.fetched = sent.filter((s) => s.path === "/usage").length;
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
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    run("save(" + JSON.stringify(args.path) + ", " + JSON.stringify(args.body) + ")");
    await settle(); out.error = text("#panelerr");
  } else if (scenario === "save_models") {          // tick a model on a node, press save
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    const p = byId["#panel"];
    for (const m of args.tick) { const b = box(p, m); b.checked = true; b.onchange(); }
    button(p, "save the models for " + args.node).onclick(); await settle();
    out.error = text("#panelerr"); out.status = text("#panelok");
    out.sent = sent.filter((s) => s.method === "POST");
  } else if (scenario === "save_dimensions") {      // reorder / untick seats, press save
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    for (const step of args.steps) {
      const p = byId["#panel"];
      if (step.move) button(p, step.move).onclick();
      if (step.untick) { const b = box(p, "open the " + step.untick + " seat"); b.checked = false; b.onchange(); }
      if (step.tick) { const b = box(p, "open the " + step.tick + " seat"); b.checked = true; b.onchange(); }
    }
    button(byId["#panel"], args.press || "save the review dimensions").onclick(); await settle();
    out.error = text("#panelerr"); out.status = text("#panelok");
    out.sent = sent.filter((s) => s.method === "POST");
  } else if (scenario === "save_seat_models") {
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    const p = byId["#panel"];
    for (const m of args.tick) {
      const b = p.all((c) => c.tagName === "input" && c.attrs["aria-label"] === m)[args.nth || 0];
      b.checked = true; b.onchange();
    }
    button(p, "save " + args.seat + " models").onclick(); await settle();
    out.error = text("#panelerr"); out.status = text("#panelok");
    out.sent = sent.filter((s) => s.method === "POST");
  } else if (scenario === "two_sections") {          // edit two sections, save one: the other keeps
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    const p = byId["#panel"];
    const boxes = (q, label) =>
      q.all((c) => c.tagName === "input" && c.attrs["aria-label"] === label);
    const seatBox = (a) => boxes(p, a.model)[a.nth];
    for (const a of args.seats) { seatBox(a).checked = true; seatBox(a).onchange(); }
    for (const d of args.untick || []) {
      const b = box(p, "open the " + d + " seat"); b.checked = false; b.onchange();
    }
    button(p, "save " + args.seats[0].seat + " models").onclick(); await settle();
    const q = byId["#panel"];
    out.status = text("#panelok"); out.error = text("#panelerr");
    out.focus = who(active); out.focusMounted = mounted(active);
    out.otherSeatTicked = boxes(q, args.seats[1].model)[args.seats[1].nth].checked;
    out.dimensionsTicked = (args.untick || []).map(
      (d) => box(q, "open the " + d + " seat").checked);
    button(q, "save " + args.seats[1].seat + " models").onclick(); await settle();
    out.error2 = text("#panelerr"); out.status2 = text("#panelok");
    out.sent = sent.filter((s) => s.method === "POST");
  } else if (scenario === "stale_editor") {         // a second tab moves the version
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    out.openedAt = run("state.version");
    const p = byId["#panel"];
    for (const m of args.tick) { const b = box(p, m); b.checked = true; b.onchange(); }
    run('api("POST", "/config/seats",' +
        ' { seat: "risk", model_id: ["local"], version: state.version })' +
        '.then(function () { return api("GET", "/run"); }).then(function (s) { state = s; })');
    await settle();
    out.movedTo = run("state.version");
    button(p, "save the models for " + args.node).onclick(); await settle();
    out.error = text("#panelerr"); out.status = text("#panelok");
    out.sent = sent.filter((s) => s.method === "POST" && s.path === "/config/nodes");
  } else if (scenario === "open_refused") {        // GET /config/nodes is refused on open
    refusing["/config/nodes"] = args.say;
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    out.error = text("#panelerr"); out.panel = text("#panel"); out.hidden = byId["#panel"].hidden;
  } else if (scenario === "focus") {               // the control acted on keeps focus
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    let p = byId["#panel"];
    const b = box(p, "open the security seat"); b.checked = true; b.onchange();
    out.afterTick = { who: who(active), mounted: mounted(active) };
    button(p, "move security earlier").onclick();
    out.afterMove = { who: who(active), mounted: mounted(active) };
    const m = p.all((c) => c.tagName === "input" && c.attrs["aria-label"] === "opus")[args.nth];
    m.checked = true; m.onchange();
    out.afterPick = { who: who(active), mounted: mounted(active) };
    button(p, "save the review dimensions").onclick(); await settle();
    out.afterSave = { who: who(active), mounted: mounted(active) };
  } else if (scenario === "live") {                // the two lines a result is announced on
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    out.live = { status: document.querySelector("#panelok").attrs["aria-live"],
                 error: document.querySelector("#panelerr").attrs.role };
  } else if (scenario === "late_save") {          // a save answered after another panel opened
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    const p = byId["#panel"];
    const b = p.all((c) => c.tagName === "input" && c.attrs["aria-label"] === args.model)[args.nth];
    b.checked = true; b.onchange();
    let release;
    holds["POST /config/seats"] = new Promise((r) => { release = r; });
    button(p, "save " + args.seat + " models").onclick();
    run("openPanel(" + JSON.stringify(args.other) + ")"); await settle();
    out.openedAt = run("panelVersion");
    release(); await settle();
    out.versionAfter = run("panelVersion");
    out.status = text("#panelok"); out.error = text("#panelerr");
    out.stored = (await (await fetch(base + "/config/nodes",
      { headers: { "X-Operator-Token": token } })).json()).seat_models;
    const q = byId["#panel"];
    button(q, "save " + args.seat + " models").onclick(); await settle();
    out.error2 = text("#panelerr"); out.status2 = text("#panelok");
  } else if (scenario === "overlap") {             // two panels opened, the first answers last
    let release;
    holds["GET /config/nodes"] = new Promise((r) => { release = r; });
    run("openPanel(" + JSON.stringify(args.first) + ")");
    run("state.version = state.version + 50");
    out.second = run("state.version");
    run("openPanel(" + JSON.stringify(args.second) + ")"); await settle();
    release(); await settle();
    out.panelVersion = run("panelVersion"); out.title = text("#paneltitle");
  } else if (scenario === "readback_refused") {    // the write lands, the read-back is refused
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    const p = byId["#panel"];
    if (args.press === "seat") {
      const b = p.all((c) => c.tagName === "input" && c.attrs["aria-label"] === "opus")[args.nth];
      b.checked = true; b.onchange();
    } else {
      const b = box(p, "open the security seat"); b.checked = true; b.onchange();
    }
    refusing["GET /config/seats"] = args.say;
    button(p, args.press === "seat" ? "save " + args.seat + " models"
                                    : "save the review dimensions").onclick();
    await settle();
    out.status = text("#panelok"); out.error = text("#panelerr");
  } else if (scenario === "opened") {              // where focus is after open, and after close
    run("openPanel(" + JSON.stringify(args.node) + ")");
    out.atOpen = { id: active && active.id, tabindex: active && active.attrs.tabindex };
    await settle();
    out.afterLoad = { id: active && active.id, mounted: mounted(active) };
    docListeners.keydown.forEach((f) => f({ key: "Escape" })); await settle();
    out.afterClose = active && active.attrs["data-node"];
  } else if (scenario === "chart") {               // what the chart says about visited nodes
    run("state = { at: " + JSON.stringify(args.at) + ", visited: " + JSON.stringify(args.visited) +
        ", version: 1 }");
    run("drawFlow()");
    const nodes = byId["#flow"].all((c) => c.tagName === "g" && c.attrs["data-node"] !== undefined);
    out.nodes = {};
    for (const g of nodes) {
      out.nodes[g.attrs["data-node"]] = { label: g.attrs["aria-label"], text: g.textContent };
    }
    out.edges = byId["#flow"].all((c) => c.tagName === "path" && c.attrs["data-from"] !== undefined)
      .map((c) => ({ from: c.attrs["data-from"], to: c.attrs["data-to"],
                     cls: c.attrs["class"], label: c.attrs["aria-label"] || null }));
  } else if (scenario === "plan_seat") {           // a seat the plan sets
    run("openPanel(" + JSON.stringify(args.node) + ")"); await settle();
    const p = byId["#panel"];
    out.text = text("#panel");
    out.buttons = p.all((c) => c.tagName === "button").map((x) => x._text);
    out.locked = p.all((c) => c.tagName === "input" && c.disabled).length;
  }
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
