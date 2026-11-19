/* Graphical ladder view built from the IL program.
   IL semantics -> diagram: LD starts a rung, AND = series contact, OR = parallel branch around everything so far,
   "AND(" / "OR(" ... ")" = nested series / parallel group; comparisons, timers, counters and MOVE/ADD/SUB/ST/S/R are
   boxes/coils in series (power flows through them; the IL machine gates them with the accumulator).
   Pure functions (no DOM) except render(): unit-tested in node.                                      */

const INVISIBLE = new Set(["__CR_EQ_1", "__CR_RESTORE"]);
const CONTACTS = new Set(["LD", "LDN", "AND", "ANDN", "OR", "ORN"]);

export function buildTree(instrs) {
  // instrs: [{op, args, text, idx}] of ONE network.  Returns tree: {t:"ser",c:[..]} | {t:"par",c:[..]} | {t:"el",...}
  let cur = null;
  const stack = [];
  const ser = (a, b) => (a === null ? b : a.t === "ser" ? { t: "ser", c: [...a.c, b] } : { t: "ser", c: [a, b] });
  const par = (a, b) => (a === null ? b : a.t === "par" ? { t: "par", c: [...a.c, b] } : { t: "par", c: [a, b] });
  for (const ins of instrs) {
    const op = ins.op;
    if (INVISIBLE.has(op)) continue;
    if (op === "AND(" || op === "OR(") { stack.push({ op: op.slice(0, -1), cur }); cur = null; continue; }
    if (op === ")") { const f = stack.pop(); cur = f.op === "AND" ? ser(f.cur, cur) : par(f.cur, cur); continue; }
    let el;
    if (CONTACTS.has(op)) el = { t: "el", kind: "contact", neg: op.endsWith("N"), label: ins.args[0], idx: ins.idx };
    else if (["GT", "LT", "GE", "LE", "EQ", "NE"].includes(op)) el = { t: "el", kind: "cmp", label: `${op} ${ins.args.join(", ")}`, idx: ins.idx };
    else if (["TON", "TOF", "CTU"].includes(op)) el = { t: "el", kind: "block", label: `${op} ${ins.args.join(", ")}`, idx: ins.idx };
    else if (["ST", "S", "R"].includes(op)) el = { t: "el", kind: "coil", mode: op, label: ins.args[0], idx: ins.idx };
    else el = { t: "el", kind: "block", label: `${op} ${ins.args.join(", ")}`, idx: ins.idx };      // MOVE, ADD, SUB
    if (op === "LD" || op === "LDN") cur = cur === null ? el : ser(cur, el);
    else if (op === "OR" || op === "ORN") cur = par(cur, el);
    else cur = ser(cur, el);
  }
  while (stack.length) { const f = stack.pop(); cur = f.op === "AND" ? ser(f.cur, cur) : par(f.cur, cur); }    // tolerate unbalanced input
  return cur || { t: "ser", c: [] };
}

const W = { contact: 86, cmp: 150, block: 168, coil: 100 }, H = { contact: 40, cmp: 40, block: 40, coil: 40 }, GAP = 14, PAR_PAD = 10;

export function measure(n) {
  if (n.t === "el") { n.w = W[n.kind]; n.h = H[n.kind]; n.mid = n.h / 2; }
  else if (n.t === "ser") {
    n.c.forEach(measure);
    n.mid = Math.max(0, ...n.c.map((c) => c.mid));
    const below = Math.max(0, ...n.c.map((c) => c.h - c.mid));
    n.h = n.mid + below;
    n.w = n.c.reduce((s, c) => s + c.w, 0) + GAP * Math.max(0, n.c.length - 1);
  } else {
    n.c.forEach(measure);
    n.w = Math.max(...n.c.map((c) => c.w)) + 2 * PAR_PAD;
    n.h = n.c.reduce((s, c) => s + c.h, 0) + GAP * (n.c.length - 1);
    n.mid = n.c[0].mid;
  }
  return n;
}

export function place(n, x, y, out = []) {
  // y = top of node; returns flat drawing list [{type, x, y, ...}]
  if (n.t === "el") { out.push({ type: "el", x, y, w: n.w, h: n.h, node: n }); }
  else if (n.t === "ser") {
    let cx = x;
    const midY = y + n.mid;
    n.c.forEach((c, i) => {
      place(c, cx, midY - c.mid, out);
      if (i < n.c.length - 1) out.push({ type: "wire", x1: cx + c.w, y1: midY, x2: cx + c.w + GAP, y2: midY });
      cx += c.w + GAP;
    });
  } else {
    let cy = y;
    const tops = [];
    n.c.forEach((c) => { place(c, x + PAR_PAD + (n.w - 2 * PAR_PAD - c.w) / 2, cy, out); tops.push(cy + c.mid); cy += c.h + GAP; });
    n.c.forEach((c, i) => {                                       // horizontal stubs to the vertical bars
      out.push({ type: "wire", x1: x, y1: tops[i], x2: x + PAR_PAD + (n.w - 2 * PAR_PAD - c.w) / 2, y2: tops[i] });
      out.push({ type: "wire", x1: x + PAR_PAD + (n.w - 2 * PAR_PAD - c.w) / 2 + c.w, y1: tops[i], x2: x + n.w, y2: tops[i] });
    });
    out.push({ type: "wire", x1: x, y1: tops[0], x2: x, y2: tops[tops.length - 1] });
    out.push({ type: "wire", x1: x + n.w, y1: tops[0], x2: x + n.w, y2: tops[tops.length - 1] });
  }
  return out;
}

export function layoutNetwork(instrs) {
  const tree = measure(buildTree(instrs));
  const railX = 18, pad = 12;
  const items = place(tree, railX, pad, []);
  const width = railX + tree.w + 60, height = tree.h + 2 * pad;
  return { tree, items, width, height, midY: pad + tree.mid, railX };
}

/** Draw into an SVG element; returns Map(instrIndex -> [svg elements]) for live colouring. */
export function render(svg, layout, doc = document) {
  const NS = "http://www.w3.org/2000/svg", map = new Map();
  const mk = (tag, attrs, parent = svg) => { const e = doc.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
  svg.setAttribute("width", layout.width); svg.setAttribute("height", layout.height);
  mk("line", { x1: layout.railX, y1: layout.midY - 0, x2: layout.railX, y2: layout.midY, class: "lw" });
  mk("rect", { x: layout.railX - 3, y: 4, width: 3, height: layout.height - 8, class: "rail" });
  mk("rect", { x: layout.width - 22, y: 4, width: 3, height: layout.height - 8, class: "rail" });
  mk("line", { x1: layout.railX, y1: layout.midY, x2: layout.railX + 0.1, y2: layout.midY, class: "lw" });
  layout.items.filter((i) => i.type === "wire").forEach((w) => mk("line", { x1: w.x1, y1: w.y1, x2: w.x2, y2: w.y2, class: "lw" }));
  mk("line", { x1: layout.railX + layout.tree.w, y1: layout.midY, x2: layout.width - 19, y2: layout.midY, class: "lw" });
  for (const it of layout.items.filter((i) => i.type === "el")) {
    const n = it.node, g = mk("g", { class: "el " + n.kind }), cy = it.y + it.h / 2;
    const text = (t, x, y, cls) => { const e = mk("text", { x, y, class: cls || "lt", "text-anchor": "middle" }, g); e.textContent = t; return e; };
    if (n.kind === "contact") {
      mk("line", { x1: it.x, y1: cy, x2: it.x + 26, y2: cy, class: "lw" }, g); mk("line", { x1: it.x + it.w - 26, y1: cy, x2: it.x + it.w, y2: cy, class: "lw" }, g);
      mk("line", { x1: it.x + 26, y1: cy - 11, x2: it.x + 26, y2: cy + 11, class: "cb" }, g); mk("line", { x1: it.x + it.w - 26, y1: cy - 11, x2: it.x + it.w - 26, y2: cy + 11, class: "cb" }, g);
      if (n.neg) mk("line", { x1: it.x + 28, y1: cy + 9, x2: it.x + it.w - 28, y2: cy - 9, class: "cb" }, g);
      text(n.label.replace("%", ""), it.x + it.w / 2, it.y - 1);
    } else if (n.kind === "coil") {
      mk("line", { x1: it.x, y1: cy, x2: it.x + 24, y2: cy, class: "lw" }, g); mk("line", { x1: it.x + it.w - 24, y1: cy, x2: it.x + it.w, y2: cy, class: "lw" }, g);
      mk("circle", { cx: it.x + it.w / 2, cy, r: 14, class: "cb fill" }, g);
      text(n.mode === "ST" ? "" : n.mode, it.x + it.w / 2, cy + 4, "lt in");
      text(n.label.replace("%", ""), it.x + it.w / 2, it.y - 1);
    } else {
      mk("rect", { x: it.x + 2, y: it.y, width: it.w - 4, height: it.h, rx: 4, class: "cb box" }, g);
      text(n.label.replace(/%/g, ""), it.x + it.w / 2, cy + 4, "lt in");
    }
    if (!map.has(n.idx)) map.set(n.idx, []);
    map.get(n.idx).push(g);
  }
  return map;
}
