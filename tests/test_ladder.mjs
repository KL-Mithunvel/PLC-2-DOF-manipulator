// Ladder diagram builder: structure checks on the real program (twin/plc/MAIN_MAIN.ilp)
import { readFileSync } from "node:fs";
import { buildTree, layoutNetwork } from "../twin/web/ladder.js";

const src = readFileSync(new URL("../twin/plc/MAIN_MAIN.ilp", import.meta.url), "latin1").replace(/\r/g, "").split("\n");
const nets = []; let cur = null;
for (const raw of src) {
  const line = raw.trim(); if (!line) continue;
  const m = /^\(\*\s*Network\s+(\d+)\s*\*\)$/.exec(line);
  if (m) { cur = { index: +m[1], instrs: [] }; nets.push(cur); continue; }
  if (line.startsWith("(*")) continue;
  const [op, ...rest] = line.split(/\s+/); const args = rest.join(" ").split(",").map((a) => a.trim()).filter(Boolean);
  cur.instrs.push({ op, args, idx: nets.reduce((n, x) => n + x.instrs.length, 0) });
}
let fail = 0; const check = (c, msg) => { if (!c) { console.error("FAIL:", msg); fail++; } };
check(nets.length === 39, "39 networks");

const count = (n) => (n.t === "el" ? 1 : n.c.reduce((s, c) => s + count(c), 0));
for (const n of nets) {
  const visible = n.instrs.filter((i) => !["__CR_EQ_1", "__CR_RESTORE", "AND(", "OR(", ")"].includes(i.op)).length;
  const lay = layoutNetwork(n.instrs);
  check(count(lay.tree) === visible, `network ${n.index}: ${count(lay.tree)} elements for ${visible} instructions`);
  check(Number.isFinite(lay.width) && Number.isFinite(lay.height) && lay.width > 0 && lay.height > 0, `network ${n.index} size`);
  check(lay.items.every((i) => Object.values(i).every((v) => typeof v !== "number" || Number.isFinite(v))), `network ${n.index} finite coordinates`);
}

// Network 1:  I0.0 in series with (M20.1 || M20.2 || I0.1 || M30.0), then TON, MOVE, ST
const t1 = buildTree(nets[1].instrs);
check(t1.t === "ser" && t1.c.length === 5, "N1 series of 5");
check(t1.c[0].label === "%I0.0" && t1.c[1].t === "par" && t1.c[1].c.length === 4, "N1 contact then 4-way parallel group");
check(t1.c[2].label.startsWith("TON") && t1.c[3].label.startsWith("MOVE") && t1.c[4].kind === "coil", "N1 TON, MOVE, coil");
// Network 18: I0.0 and ((M30.0 M50.0 M50.1 in series) || M30.1), then !I0.1 !M30.2, ST, R
const t18 = buildTree(nets[18].instrs);
check(t18.c[1].t === "par" && t18.c[1].c[0].t === "ser" && t18.c[1].c[0].c.length === 3 && t18.c[1].c[1].label === "%M30.1", "N18 start/latch structure");
check(t18.c[2].neg && t18.c[3].neg, "N18 normally-closed contacts");
// Network 12: nested OR( LD ...) groups each carrying a MOVE pair
const t12 = buildTree(nets[12].instrs);
check(JSON.stringify(t12).includes('"M22.4"') || JSON.stringify(t12).includes("%M22.4"), "N12 contains teach bit M22.4");

if (fail) process.exit(1);
console.log(`ladder ok: ${nets.length} networks laid out`);
