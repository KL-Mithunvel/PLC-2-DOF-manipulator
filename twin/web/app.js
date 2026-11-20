"use strict";
/* Digital twin front-end: HMI + operator panel + digital arm + live ladder + scope.
   All data comes from /api/stream (SSE); all inputs go to POST /api/cmd.            */
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const cmd = (o) => fetch("/api/cmd", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(o) }).catch(() => {});
let S = null;            // latest snapshot
let WATCH = {};          // operand values
let PROG = null;         // parsed program
const scope = [];        // scope samples

/* ===================================================================== HMI */
const HMI = $("#hmi");
const screens = {};
const bind = [];         // {el, fn(S)}
function screen(name, bg) { const d = el("div", "scr"); d.style.background = bg; HMI.appendChild(d); screens[name] = d; return d; }
function px(e, x, y, w, h) { e.style.left = x + "px"; e.style.top = y + "px"; if (w) e.style.width = w + "px"; if (h) e.style.height = h + "px"; return e; }
function txt(sc, x, y, t, o = {}) { const e = el("div", "hmi-txt", t); px(e, x, y); if (o.color) e.style.color = o.color; if (o.size) e.style.fontSize = o.size + "px"; if (o.weight) e.style.fontWeight = o.weight; if (o.lh) e.style.lineHeight = o.lh; sc.appendChild(e); return e; }
function ni(sc, x, y, w, h, get, set) {
  const wrap = el("div", "hmi-el"); px(wrap, x, y, w, h);
  const i = el("input", "hmi-ni"); i.type = "text"; i.style.height = h + "px"; i.style.fontSize = Math.min(22, h * .55) + "px";
  wrap.appendChild(i); sc.appendChild(wrap);
  if (set) {
    i.addEventListener("change", () => { const v = parseInt(i.value, 10); if (!isNaN(v)) set(v); });
    i.addEventListener("keydown", (e) => { if (e.key === "Enter") i.blur(); });
  } else { i.readOnly = true; i.style.cursor = "default"; }
  bind.push({ fn: (s) => { if (document.activeElement !== i) i.value = get(s); } });
  return i;
}
function btn(sc, x, y, w, h, label, tag, cls = "") {
  const b = el("div", "hmi-btn " + cls, label); px(b, x, y, w, h); sc.appendChild(b);
  if (tag.startsWith("go:")) { b.addEventListener("click", () => showScreen(tag.slice(3))); return b; }
  b.addEventListener("pointerdown", (e) => { b.setPointerCapture(e.pointerId); b.classList.add("down"); cmd({ type: "button", tag, down: true }); });
  const up = () => { if (b.classList.contains("down")) { b.classList.remove("down"); cmd({ type: "button", tag, down: false }); } };
  b.addEventListener("pointerup", up); b.addEventListener("pointercancel", up); b.addEventListener("lostpointercapture", up);
  return b;
}
function lamp(sc, x, y, d, get) { const l = el("div", "hmi-lamp off"); px(l, x, y, d, d); sc.appendChild(l); bind.push({ fn: (s) => { l.className = "hmi-lamp " + (get(s) ? "on" : "off"); } }); }
function sw(sc, x, y, w, h, get, on) { const s = el("div", "hmi-sw", "<i></i>"); px(s, x, y, w, h); sc.appendChild(s); s.onclick = () => on(!s.classList.contains("on")); bind.push({ fn: (st) => s.classList.toggle("on", !!get(st)) }); }

(function buildHMI() {
  const rated = (a, b) => `( RATED SPEED ${a} RPM<br>MAX SPEED ${b} RPM )`;
  /* ---- AUTO (Frame0, window 10) ---- */
  let a = screen("AUTO", "#7fffd4");
  txt(a, 403, 14, "AUTO", { color: "#0000ff", size: 38, weight: 400 });
  txt(a, 15, 138, "NUMBER OF CYCLE", { size: 26 });
  ni(a, 365, 133, 88, 40, (s) => s.regs.VW2036, (v) => cmd({ type: "numeric", tag: "CYCLES", value: v }));
  txt(a, 695, 130, "ACTUAL CYCLE NO.", { size: 22 });
  ni(a, 923, 125, 88, 42, (s) => s.regs[s.cycle_reg]);
  btn(a, 897, 182, 122, 34, "RESET", "RESET", "small").style.cssText += ";background:#4fb3ef;border-color:#4fb3ef;color:#e00;font-size:24px;border-radius:2px";
  txt(a, 25, 224, "CYCLE TIME", { size: 26 });
  txt(a, 350, 190, "MIN : SEC", { size: 24, weight: 400 });
  ni(a, 350, 222, 48, 40, (s) => s.hmi.cyc_min); txt(a, 410, 222, ":", { size: 34 });
  ni(a, 435, 222, 42, 40, (s) => s.hmi.cyc_sec);
  txt(a, 43, 328, "AUTO ON / OFF", { size: 26 });
  btn(a, 362, 320, 186, 60, "START", "START", "green"); btn(a, 570, 320, 186, 60, "STOP", "STOP", "green");
  const ln = el("div", "hmi-el"); px(ln, 0, 416, 1024, 4); ln.style.background = "#000"; a.appendChild(ln);
  txt(a, 438, 436, "HOME", { size: 28, color: "#ffa060" });
  txt(a, 228, 496, "BASE MOTOR", { size: 32, color: "#ffa060" }); txt(a, 535, 500, "SHOULDER MOTOR", { size: 32, color: "#ffa060" });
  lamp(a, 298, 533, 68, (s) => s.bits["M50.1"]); lamp(a, 622, 533, 68, (s) => s.bits["M50.0"]);
  btn(a, 2, 546, 112, 46, "MANUAL", "go:MANUAL", "nav"); btn(a, 882, 530, 112, 46, "SETTING", "go:SETTING", "nav");

  /* ---- MANUAL (Frame11, window 11/0) ---- */
  let m = screen("MANUAL", "#7b9bc3");
  txt(m, 361, 14, "MANUAL", { color: "#7fffd4", size: 38, weight: 400 });
  const p1 = el("div", "hmi-el"); px(p1, 5, 82, 1018, 350); p1.style.cssText += ";background:#e6e6fa;border:2px solid #9ec;border-radius:8px"; m.appendChild(p1);
  txt(m, 28, 186, "BASE MOTOR", { size: 28 }); txt(m, 22, 285, "SHOULDER MOTOR", { size: 28 });
  btn(m, 355, 181, 130, 50, "FWD", "BASE_FWD"); btn(m, 500, 181, 130, 50, "REV", "BASE_REV");
  btn(m, 360, 279, 125, 50, "UP", "SH_UP"); btn(m, 500, 279, 135, 50, "DOWN", "SH_DOWN");
  txt(m, 686, 140, "SPEED", { size: 20 });
  ni(m, 675, 183, 90, 45, (s) => s.regs.VD2020, (v) => cmd({ type: "numeric", tag: "BASE_SPEED", value: v }));
  ni(m, 675, 280, 90, 45, (s) => s.regs.VD2030, (v) => cmd({ type: "numeric", tag: "SH_SPEED", value: v }));
  txt(m, 783, 188, rated(1000, 1500), { size: 12, lh: "15px" }); txt(m, 793, 280, rated(1500, 2000), { size: 12, lh: "15px" });
  const p2 = el("div", "hmi-el"); px(p2, 2, 434, 1022, 100); p2.style.background = "#ff8fc8"; m.appendChild(p2);
  txt(m, 265, 466, "ELECTRO MAGNET", { size: 26 });
  sw(m, 585, 458, 90, 40, (s) => s.hmi.magnet_sw, (on) => cmd({ type: "switch", tag: "MAGNET", on }));
  btn(m, 900, 456, 115, 46, "AUTO", "go:AUTO", "nav");

  /* ---- SETTING (window 12) ---- */
  let t = screen("SETTING", "#7fffd4");
  txt(t, 403, 14, "SETTINGS", { color: "#0000ff", size: 38, weight: 400 });
  t.insertAdjacentHTML("beforeend", `<svg class="hmi-el" style="left:2px;top:2px" width="246" height="168" viewBox="0 0 246 168"><rect width="246" height="168" fill="#e6e6fa" stroke="#333"/>
    <g font-family="Times New Roman" font-weight="bold" font-size="17"><text x="100" y="22">INI..</text><text x="6" y="82">POS 1</text><text x="6" y="128">POS 2</text><text x="164" y="82">POS 3</text><text x="164" y="128">POS 4</text></g>
    <g stroke="#000" stroke-width="2.5" fill="none"><path d="M118 30 L72 66"/><path d="M76 74 L162 74"/><path d="M72 80 L72 118"/><path d="M168 80 L168 118"/></g>
    <rect x="54" y="140" width="42" height="18" fill="#ffd400" stroke="#333"/><rect x="146" y="140" width="46" height="18" fill="#ffd400" stroke="#333"/>
    <g font-size="12" font-weight="bold"><text x="58" y="153">PICK</text><text x="150" y="153">DROP</text></g></svg>`);
  const cols = [262, 425, 575, 721, 867, 1020], heads = ["INITIALIZATION", "POSITION 1", "POSITION 2", "POSITION 3", "POSITION 4"];
  const g = el("div", "hmi-el"); px(g, 262, 100, 758, 232); g.style.border = "4px solid #000"; t.appendChild(g);
  for (let r = 1; r <= 2; r++) { const h = el("div", "hmi-el"); px(h, 262, r === 1 ? 157 : 246, 758, 3); h.style.background = "#000"; t.appendChild(h); }
  for (let c = 1; c < 5; c++) { const v = el("div", "hmi-el"); px(v, cols[c] - 2, 100, 3, 232); v.style.background = "#000"; t.appendChild(v); }
  txt(t, 26, 185, "BASE MOTOR (M1)", { size: 22 }); txt(t, 22, 282, "SHOULDER MOTOR (M2)", { size: 22 });
  for (let i = 0; i < 5; i++) {
    const x0 = cols[i], w = cols[i + 1] - cols[i];
    txt(t, x0 + 4, 110, heads[i], { size: i === 0 ? 20 : 22 });
    const bi = 2300 + 4 * i, si = 2400 + 4 * i;
    ni(t, x0 + 8, 168, w - 18, 38, (s) => s.regs["VD" + bi], (v) => cmd({ type: "numeric", addr: "VD" + bi, value: v }));
    ni(t, x0 + 4, 262, w - 8, 38, (s) => s.regs["VD" + si], (v) => cmd({ type: "numeric", addr: "VD" + si, value: v }));
    btn(t, x0 + 24, 343, w - 36, 30, "TEACH", "TEACH" + i, "teach");
  }
  txt(t, 47, 440, "BASE MOTOR", { size: 30 }); txt(t, 47, 470, "( RATED SPEED 1000 RPM<br>MAX SPEED 1500 RPM )", { size: 12, lh: "14px" });
  txt(t, 42, 522, "SHOULDER MOTOR", { size: 30 }); txt(t, 47, 556, "( RATED SPEED 1500 RPM<br>MAX SPEED 2000 RPM )", { size: 12, lh: "14px" });
  btn(t, 340, 442, 130, 58, "FWD", "BASE_FWD"); btn(t, 483, 442, 130, 58, "REV", "BASE_REV");
  btn(t, 345, 520, 125, 50, "UP", "SH_UP"); btn(t, 485, 520, 135, 50, "DOWN", "SH_DOWN");
  txt(t, 670, 416, "SPEED", { size: 20 });
  ni(t, 658, 444, 90, 44, (s) => s.regs.VD2020, (v) => cmd({ type: "numeric", tag: "BASE_SPEED", value: v }));
  ni(t, 658, 527, 90, 44, (s) => s.regs.VD2030, (v) => cmd({ type: "numeric", tag: "SH_SPEED", value: v }));
  btn(t, 882, 530, 112, 46, "AUTO", "go:AUTO", "nav");
})();

/* ---- system windows of the panel (not part of the process; static replicas for reference): Wi-Fi/network (window 11) and Login (window 9) ---- */
(function buildSystemScreens() {
  const w = screen("WIFI", "linear-gradient(#1a7bff,#bfe0ff)");
  const sans = "font:16px Arial,sans-serif;color:#000";
  w.insertAdjacentHTML("beforeend", `
   <div class="hmi-el" style="left:68px;top:14px;width:888px;height:434px;background:#fff"></div>
   <div class="hmi-txt" style="left:152px;top:16px;font-size:26px;font-weight:400">WIFI Connection</div><div class="hmi-txt" style="left:541px;top:16px;font-size:26px;font-weight:400">Network</div>
   <div class="hmi-txt" style="left:217px;top:76px;font-size:26px;font-weight:400">WIFI</div>
   <div class="hmi-sw" style="left:356px;top:78px;width:66px;height:26px"><i style="width:22px;height:22px;top:2px"></i></div>
   <div class="hmi-el" style="left:545px;top:62px;width:404px;height:244px;border:1px solid #777;background:#fff"></div>
   <div class="hmi-el" style="left:173px;top:251px;width:233px;height:32px;border:1px solid #965;${sans};display:flex;align-items:center;justify-content:center">Not Select Wifi Network</div>
   <div class="hmi-btn" style="left:622px;top:316px;width:82px;height:36px;background:#fff;border:1px solid #888;color:#1a7bff;font-size:28px">&#9664;|</div>
   <div class="hmi-btn" style="left:777px;top:316px;width:82px;height:36px;background:#fff;border:1px solid #888;color:#1a7bff;font-size:28px">|&#9654;</div>
   <div class="hmi-el" style="left:545px;top:358px;width:296px;height:40px;border:1px solid #777;background:#fff;${sans};display:flex;align-items:center;justify-content:center">AAAAAAAAAAAAAAAA</div>
   <div class="hmi-el" style="left:545px;top:408px;width:296px;height:40px;border:1px solid #777;background:#fff;${sans};display:flex;align-items:center;justify-content:center">AAAAAAAAAAAAAAAA</div>
   <div class="hmi-txt" style="left:386px;top:416px;font-size:22px;font-weight:400">Enter Password</div>
   <div class="hmi-btn" style="left:846px;top:413px;width:100px;height:34px;background:#4fb3ef;border:0;color:#000;font:15px Arial">Join</div>
   <div class="hmi-txt" style="left:2px;top:462px;font-size:22px;font-weight:400">WIFI State:</div>
   <div class="hmi-el" style="left:139px;top:461px;width:114px;height:32px;border:1px solid #965;${sans};display:flex;align-items:center;justify-content:center">Disconnect</div>
   <div class="hmi-el" style="left:278px;top:463px;width:175px;height:30px;border:1px solid #965;${sans};display:flex;align-items:center;justify-content:center">AAAAAAAAAAAAAAAA</div>
   <div class="hmi-txt" style="left:560px;top:458px;font-size:22px;font-weight:400">IP:</div>
   <div class="hmi-el" style="left:605px;top:464px;width:200px;height:26px;border:1px solid #965;${sans};text-align:center">###&nbsp;.&nbsp;###&nbsp;.&nbsp;###&nbsp;.&nbsp;###</div>
   <div class="hmi-btn" style="left:824px;top:458px;width:192px;height:34px;background:#4fb3ef;border:0;color:#000;font:15px Arial">Remove This Network</div>
   <div class="hmi-el" style="left:0;top:496px;width:1024px;height:104px;background:linear-gradient(#e7f1ff,#bcd8ff)"></div>
   <div class="hmi-txt" style="left:16px;top:508px;font-size:22px;font-weight:400">Server:</div><div class="hmi-txt" style="left:16px;top:546px;font-size:22px;font-weight:400">Device N</div>
   <div class="hmi-el" style="left:111px;top:509px;width:216px;height:28px;border:1px solid #666;background:#fff;${sans};padding:4px 8px">China Server</div>
   <div class="hmi-txt" style="left:359px;top:508px;font-size:22px;font-weight:400">Setting:</div>
   <div class="hmi-sw" style="left:466px;top:512px;width:66px;height:26px"><i style="width:22px;height:22px;top:2px"></i></div>
   <div class="hmi-txt" style="left:365px;top:550px;font-size:22px;font-weight:400">State:</div>
   <div class="hmi-el" style="left:440px;top:549px;width:264px;height:34px;border:1px solid #965;background:#fff;${sans};display:flex;align-items:center;justify-content:center">Internet's NOT Working</div>
   <div class="hmi-txt" style="left:729px;top:508px;font-size:22px;font-weight:400">Virtual IP:</div>
   <div class="hmi-el" style="left:729px;top:549px;width:262px;height:32px;border:1px solid #965;background:#fff;${sans};text-align:center;line-height:32px">###&nbsp;.&nbsp;###&nbsp;.&nbsp;###&nbsp;.&nbsp;###</div>`);
  const l = screen("LOGIN", "#8a8f99");
  l.insertAdjacentHTML("beforeend", `
   <div class="hmi-el" style="left:309px;top:161px;width:405px;height:277px;background:#fff;border:1px solid #444">
    <div class="hmi-el" style="left:0;top:0;width:405px;height:38px;background:linear-gradient(#1a7bff,#4fb3ef);color:#fff;font:bold 22px Arial;padding:6px 8px">USER ACCESS&nbsp; LOGIN</div>
    <div class="hmi-el" style="left:367px;top:0;width:38px;height:38px;background:#ff4b5c;color:#fff;font:30px Arial;text-align:center;line-height:36px">&#10005;</div>
    <div class="hmi-txt" style="left:30px;top:62px;font:16px Arial;font-weight:400">USER NAME</div><div class="hmi-txt" style="left:30px;top:98px;font:16px Arial;font-weight:400;line-height:20px">ACCESS<br>PASSWORD</div>
    <div class="hmi-el" style="left:125px;top:58px;width:185px;height:26px;border:1px solid #777;background:#ccc"></div><div class="hmi-el" style="left:125px;top:84px;width:185px;height:80px;background:#c9c9c9"></div>
    <div class="hmi-btn" style="left:318px;top:57px;width:76px;height:32px;background:#fff;border:2px solid #1a7bff;color:#2b8a2b;font:bold 18px Arial">Login</div>
    <div class="hmi-btn" style="left:318px;top:111px;width:76px;height:32px;background:#fff;border:2px solid #1a7bff;color:#d00;font:bold 18px Arial">Logout</div>
    <div class="hmi-el" style="left:0;top:156px;width:405px;height:38px;background:linear-gradient(#1a7bff,#4fb3ef);color:#fff;font:bold 22px Arial;padding:6px 8px">USER LEVEL&nbsp; LOGIN</div>
    <div class="hmi-txt" style="left:28px;top:208px;font:16px Arial;font-weight:400;line-height:20px">LEVEL<br>PASSWORD</div>
    <div class="hmi-el" style="left:124px;top:211px;width:182px;height:28px;border:2px solid #1a7bff;background:#fff;text-align:center;font:16px Arial;line-height:26px">&times;&times;&times;&times;&times;&times;&times;&times;&times;&times;</div>
   </div>`);
  const sel = $("#selHmiScreen");
  sel.onchange = () => showScreen(sel.value);
})();

let curScreen = "AUTO";
function showScreen(n) { curScreen = n; if ($("#selHmiScreen")) $("#selHmiScreen").value = n; for (const k in screens) screens[k].classList.toggle("on", k === n); cmd({ type: "screen", name: n }); }
showScreen("AUTO");
new ResizeObserver(() => { const w = $("#hmiWrap").clientWidth; HMI.style.transform = `scale(${w / 1024})`; }).observe($("#hmiWrap"));

/* ===================================================================== controls */
$("#selLadderView").onchange = () => { applyLadderView(); lastDiagTrace = ""; };
$("#btnPause").onclick = () => cmd({ type: "pause", on: !S?.paused });
$("#btnStep").onclick = () => cmd({ type: "step" });
$("#selSpeed").onchange = (e) => cmd({ type: "speed", value: e.target.value });
$("#rngPayload").oninput = (e) => { $("#lblPayload").textContent = (+e.target.value).toFixed(1) + " kg"; cmd({ type: "payload", value: e.target.value }); };
$("#chkFeeder").onchange = (e) => cmd({ type: "feeder", on: e.target.checked });
$("#btnSpawn").onclick = () => cmd({ type: "spawn" });
$("#btnSave").onclick = () => cmd({ type: "save" });
$("#btnDefaults").onclick = () => cmd({ type: "defaults" });
$("#btnEstop").onclick = () => cmd({ type: "estop", pressed: !S?.estop });
$("#btnPower").onclick = () => cmd({ type: "power", on: !S?.powered });
const rb = $("#btnReset");
rb.addEventListener("pointerdown", (e) => { rb.setPointerCapture(e.pointerId); cmd({ type: "reset_btn", down: true }); });
["pointerup", "pointercancel"].forEach((ev) => rb.addEventListener(ev, () => cmd({ type: "reset_btn", down: false })));
document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x.id === "tab-" + b.dataset.tab));
  if (b.dataset.tab === "scope") drawScope();
  if (b.dataset.tab === "struct") drawStruct();
  if (b.dataset.tab === "cfg" && !cfgBuilt) buildCfg();
  if (S && S.bits && PROG) {                       // render at once instead of waiting for the next periodic refresh
    if (b.dataset.tab === "mem") updateMem(S);
    if (b.dataset.tab === "can") updateCan(S);
    if (b.dataset.tab === "struct") updateStructCards(S);
    if (b.dataset.tab === "ladder") updateLadder(S);
  }
  if (b.dataset.tab === "src") { if (!srcBuilt) buildSources(); }
});

/* ===================================================================== arm renderer */
const cam = { az: -0.75, el: 0.5, dist: 1.9, tx: 0.2, ty: 0.1, tz: 0.15 };
const cvIso = $("#cvIso"), cvTop = $("#cvTop"), cvSide = $("#cvSide");
let drag = null;
const trail = [];

function makeView(kind, w, h) {
  // returns project(p)->[x,y,depth,scale]
  const base = Math.min(w, h);
  if (kind === "iso") {
    const ca = Math.cos(cam.az), sa = Math.sin(cam.az), ce = Math.cos(cam.el), se = Math.sin(cam.el);
    return (p) => {
      const x = p[0] - cam.tx, y = p[1] - cam.ty, z = p[2] - cam.tz;
      const x1 = ca * x - sa * y, y1 = sa * x + ca * y;
      const sy = se * y1 + ce * z, d = ce * y1 - se * z;
      const k = base * 1.25 / (cam.dist + d);
      return [w / 2 + x1 * k, h * 0.58 - sy * k, d, k];
    };
  }
  if (kind === "top") { const k = base / 1.05; return (p) => [w / 2 + (p[0] - 0.05) * k, h / 2 - (p[1] - 0.22) * k, -p[2], k]; }
  const k = base / 0.85;      // side view: x to the right, z up
  return (p) => [w * 0.30 + p[0] * k, h * 0.82 - p[2] * k, p[1], k];
}

function drawScene(cv, kind) {
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const c = cv.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
  if (!S) return;
  const P = makeView(kind, W, H), prims = [];
  const g = S.geom, gc = S.geo_cfg, phi = S.base.deg * Math.PI / 180;
  const axisDir = [-Math.sin(phi), Math.cos(phi), 0];
  const add = (p, depth, fn) => prims.push({ d: depth, fn });
  const line = (a, b, wd, col, cap = "round") => { const pa = P(a), pb = P(b); add(0, (pa[2] + pb[2]) / 2, () => { c.strokeStyle = col; c.lineWidth = Math.max(1, wd * (pa[3] + pb[3]) / 2); c.lineCap = cap; c.beginPath(); c.moveTo(pa[0], pa[1]); c.lineTo(pb[0], pb[1]); c.stroke(); }); };
  const cyl = (cx, cy, z0, z1, r, col, top, n = 22) => {
    const ring = (z) => Array.from({ length: n }, (_, i) => P([cx + r * Math.cos(2 * Math.PI * i / n), cy + r * Math.sin(2 * Math.PI * i / n), z]));
    const b = ring(z0), t = ring(z1);
    for (let i = 0; i < n; i++) { const j = (i + 1) % n; const dd = (b[i][2] + b[j][2]) / 2, sh = 0.55 + 0.45 * Math.cos(2 * Math.PI * (i + .5) / n - cam.az);
      add(0, dd, () => { c.fillStyle = shade(col, sh); c.beginPath(); c.moveTo(b[i][0], b[i][1]); c.lineTo(b[j][0], b[j][1]); c.lineTo(t[j][0], t[j][1]); c.lineTo(t[i][0], t[i][1]); c.closePath(); c.fill(); }); }
    const dt = Math.min(...t.map((q) => q[2])) - 0.001;
    add(0, kind === "iso" ? dt - 1e-4 : dt, () => { c.fillStyle = top || shade(col, 1.15); c.beginPath(); t.forEach((q, i) => i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1])); c.closePath(); c.fill(); });
  };
  // floor grid + workspace ring (drawn first, not sorted)
  c.save();
  c.strokeStyle = "#26323f"; c.lineWidth = 1;
  for (let v = -0.6; v <= 0.61; v += 0.1) { for (const [a, b] of [[[v, -0.6, 0], [v, 0.6, 0]], [[-0.6, v, 0], [0.6, v, 0]]]) { const pa = P(a), pb = P(b); c.beginPath(); c.moveTo(pa[0], pa[1]); c.lineTo(pb[0], pb[1]); c.stroke(); } }
  c.setLineDash([6, 5]); c.strokeStyle = "#3d7bb5"; c.beginPath();
  for (let i = 0; i <= 64; i++) { const a = i / 64 * 2 * Math.PI, q = P([0.4215 * Math.cos(a), 0.4215 * Math.sin(a), 0]); i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]); }
  c.stroke(); c.setLineDash([]); c.restore();
  // taught points
  const names = ["INI", "1", "2 PICK", "3", "4 DROP"];
  S.points.forEach((pt, i) => { const q = P([pt[0], pt[1], pt[2]]); c.fillStyle = i === 2 ? "#ff4bd8" : i === 4 ? "#ffb020" : "#5f7a94"; c.beginPath(); c.arc(q[0], q[1], 3.5, 0, 7); c.fill(); if (kind !== "side") { c.font = "10px Segoe UI"; c.fillText(names[i], q[0] + 6, q[1] - 5); } });
  // tip trail
  if (trail.length > 1) { c.strokeStyle = "#ffb02066"; c.lineWidth = 1.5; c.beginPath(); trail.forEach((p, i) => { const q = P(p); i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]); }); c.stroke(); }
  // structure
  cyl(0, 0, 0, 0.10, 0.12, "#586878");                                        // base housing + motor
  cyl(0, 0, 0.10, gc.h - 0.04, 0.065, "#6c7d8f");                              // pedestal (rotates with phi, symmetric)
  const sh = g.shoulder, pp = g.p, tip = g.tip, off = 0.032;
  const sA = [sh[0] + axisDir[0] * 0.07, sh[1] + axisDir[1] * 0.07, sh[2]], sB = [sh[0] - axisDir[0] * 0.07, sh[1] - axisDir[1] * 0.07, sh[2]];
  line(sA, sB, 0.085, "#7d8ea0");                                              // shoulder joint housing (M8010)
  for (const sgn of [1, -1]) { const o = [axisDir[0] * off * sgn, axisDir[1] * off * sgn, 0]; line([sh[0] + o[0], sh[1] + o[1], sh[2]], [pp[0] + o[0], pp[1] + o[1], pp[2]], 0.028, "#c3ccd6"); }
  line([pp[0] + axisDir[0] * off, pp[1] + axisDir[1] * off, pp[2]], [pp[0] - axisDir[0] * off, pp[1] - axisDir[1] * off, pp[2]], 0.03, "#aeb8c4");
  line(pp, [tip[0], tip[1], tip[2] + 0.03], 0.03, "#d5dce4");                   // link-2
  const mag = S.io["Q0.7"];
  cyl(tip[0], tip[1], tip[2], tip[2] + 0.035, 0.032, mag ? "#d8409f" : "#8a8f99");
  // parts
  const part = (pt, col) => { if (!pt) return; const z0 = pt.pos[2] - gc.part_h / 2; cyl(pt.pos[0], pt.pos[1], z0, z0 + gc.part_h, gc.part_r, col); };
  part(S.placed, "#6a7683"); part(S.part, S.part && S.part.state === "carried" ? "#9aa7b4" : "#8996a3");
  prims.sort((a, b) => b.d - a.d); prims.forEach((p) => p.fn());
  // overlays
  c.fillStyle = "#c7d2de"; c.font = "11px Segoe UI";
  if (kind !== "iso") c.fillText(kind === "top" ? "TOP" : "SIDE", 6, 13);
  if (S.part && S.part.state === "carried") { const q = P(S.part.pos); c.fillStyle = "#fff"; c.font = "bold 12px Segoe UI"; c.fillText(S.part.mass.toFixed(1) + " kg", q[0] + 14, q[1]); }
}
function shade(hex, f) { const n = parseInt(hex.slice(1), 16); const r = Math.min(255, (n >> 16) * f) | 0, g = Math.min(255, ((n >> 8) & 255) * f) | 0, b = Math.min(255, (n & 255) * f) | 0; return `rgb(${r},${g},${b})`; }

/* ===================================================================== axis cards */
function axisCard(div, title, a, extra) {
  const pct = Math.min(100, a.load_pct), peak = a.tau_peak / a.tau_cont * 100;
  const col = a.load_pct > 100 ? "var(--bad)" : a.load_pct > 80 ? "var(--warn)" : "var(--ok)";
  div.innerHTML = `<h3>${title}</h3>
   <table><tr><td>angle</td><td>${a.deg.toFixed(2)}&deg; <span class="as">(target ${a.target_deg.toFixed(1)}&deg;)</span></td></tr>
   <tr><td>position actual 6064</td><td>${a.count.toLocaleString()} cnt</td></tr>
   <tr><td>velocity 606C</td><td>${a.rpm} rpm (motor)</td></tr>
   <tr><td>torque @ output</td><td>${a.tau.toFixed(1)} N&middot;m <small>/ ${a.tau_cont} cont, ${a.tau_peak} peak</small></td></tr>
   <tr><td>est. current</td><td>${(a.current_ma / 1000).toFixed(2)} A</td></tr>
   ${extra}</table>
   <div class="bar" title="load vs continuous torque rating"><i style="width:${pct}%;background:${col}"></i></div>
   <div><span class="tag ${a.enabled ? "on" : ""}">${a.enabled ? "ENABLED" : "DISABLED (brake)"}</span><span class="tag ${a.running ? "on" : ""}">RUN</span><span class="tag ${a.at_target ? "on" : ""}">TARGET REACHED</span>${a.saturated ? '<span class="tag bad">TORQUE LIMIT</span>' : ""}${a.overload_s > 1 ? '<span class="tag warn">OVER CONT. ' + a.overload_s.toFixed(0) + ' s</span>' : ""}
   <span class="tag">CW 0x${a.controlword.toString(16).toUpperCase().padStart(4, "0")}</span><span class="tag">SW 0x${a.statusword.toString(16).toUpperCase().padStart(4, "0")}</span></div>`;
}

/* ===================================================================== ladder (live IL) */
const lnEls = [], netEls = [];
let lastTrace = "", lastFollow = -1, lastDiagTrace = "";
async function buildLadder() {
  PROG = await (await fetch("/api/program")).json();
  const host = $("#ladder"); host.innerHTML = "";
  PROG.networks.forEach((n, ni) => {
    const d = el("div", "net"); d.appendChild(el("div", "nethead", `<i></i>Network ${n.index} <em>${n.label || ""}</em>`));
    for (let i = n.first; i < n.last; i++) {
      const ins = PROG.instrs[i], ln = el("div", "ln");
      ln.innerHTML = `<span class="act"></span><span class="op">${ins.op}</span><span class="ar">${ins.args.map((a) => `<span class="a" data-a="${a}">${a}</span>`).join(", ")}</span><span class="v"></span>`;
      d.appendChild(ln); lnEls[i] = ln;
    }
    host.appendChild(d); netEls[ni] = d;
  });
  buildNotes(); buildPdo();
  try { await buildDiagrams(); } catch (e) { console.warn("ladder diagram unavailable", e); $("#selLadderView").value = "list"; applyLadderView(); }
}
const diagEls = new Map();      // instruction index -> svg groups
async function buildDiagrams() {
  const L = await import("./ladder.js");
  const host = $("#ladderDiag"); host.innerHTML = "";
  PROG.networks.forEach((n, ni) => {
    const d = el("div", "net"); d.appendChild(el("div", "nethead", `<i></i>Network ${n.index} <em>${n.label || ""}</em>`));
    const sc = el("div", "dscroll"), svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    sc.appendChild(svg); d.appendChild(sc); host.appendChild(d);
    const ins = PROG.instrs.slice(n.first, n.last).map((x, k) => ({ op: x.op, args: x.args, idx: n.first + k }));
    const map = L.render(svg, L.layoutNetwork(ins));
    map.forEach((v, k) => diagEls.set(k, v));
    diagNets[ni] = d;
  });
  applyLadderView();
}
const diagNets = [];
function applyLadderView() {
  const diag = $("#selLadderView").value === "diagram";
  $("#ladderDiag").style.display = diag ? "" : "none"; $("#ladder").style.display = diag ? "none" : "";
}
function fmtVal(k, v) { return v === undefined ? "" : (k.startsWith("%") && /^%[IQM]\d+\.\d$|^%SM|^%BR/.test(k)) ? (v ? "1" : "0") : String(v); }
function updateLadder(s) {
  if (!PROG) return;
  const tr = s.trace;
  if (tr !== lastTrace) {
    for (let i = 0; i < tr.length; i++) { if (!lastTrace || tr[i] !== lastTrace[i]) { const v = tr.charCodeAt(i) - 48; lnEls[i].classList.toggle("t1", !!(v & 1)); lnEls[i].firstChild.textContent = (v & 2) ? "●" : ""; } }
    lastTrace = tr;
  }
  s.net_power.split("").forEach((c, i) => { netEls[i].classList.toggle("hot", c === "1"); if (diagNets[i]) diagNets[i].classList.toggle("hot", c === "1"); });
  if ($("#selLadderView").value === "diagram" && s.trace !== lastDiagTrace) {
    for (let i = 0; i < tr.length; i++) { if (!lastDiagTrace || tr[i] !== lastDiagTrace[i]) { const v = tr.charCodeAt(i) - 48, g = diagEls.get(i); if (g) g.forEach((e) => { e.classList.toggle("on", !!(v & 1)); e.classList.toggle("act", !!(v & 2)); }); } }
    lastDiagTrace = tr;
  }
  const only = $("#chkActive").checked; netEls.forEach((d, i) => { const hide = only && s.net_power[i] !== "1"; d.classList.toggle("hide", hide); if (diagNets[i]) diagNets[i].classList.toggle("hide", hide); });
  // operand values
  PROG.instrs.forEach((ins, i) => {
    const vEl = lnEls[i].lastChild; let t = "";
    ins.args.forEach((a) => { if (/^[TC]\d+$/.test(a)) { const w = WATCH[a]; if (w !== undefined) t += `${a}=${w}${WATCH[a + ".q"] ? " (Q)" : ""}  `; } else if (a in WATCH) t += `${fmtVal(a, WATCH[a])}  `; });
    if (vEl.textContent !== t) vEl.textContent = t;
  });
  // follow the auto sequence
  const b = s.bits; const flags = ["M31.0", "M31.1", "M31.2", "M31.3", "M31.4", "M31.5", "M31.6", "M31.7", "M32.0"], nets = [21, 22, 23, 24, 25, 26, 27, 28, 31, 34];
  let step = 0; while (step < flags.length && b[flags[step]]) step++;
  let target = b["M30.1"] ? nets[step] : b["M30.2"] ? 35 : b["M40.0"] ? 13 : -1;
  netEls.forEach((d, i) => { const f = PROG.networks[i].index === target; d.classList.toggle("focus", f); if (diagNets[i]) diagNets[i].classList.toggle("focus", f); });
  if ($("#chkFollow").checked && target !== lastFollow && $("#tab-ladder").classList.contains("on")) {
    lastFollow = target; const idx = PROG.networks.findIndex((n) => n.index === target);
    if (idx >= 0) { const diag = $("#selLadderView").value === "diagram" && diagNets[idx]; const box = diag ? $("#ladderDiag") : $("#ladder"); box.scrollTop = (diag ? diagNets[idx] : netEls[idx]).offsetTop - 40; }
  }
}

/* ===================================================================== memory / CAN tabs */
const BITDESC = { "M20.1": "base jog FWD", "M20.2": "base jog REV", "M20.3": "shoulder UP", "M20.4": "shoulder DOWN", "M20.5": "manual magnet",
  "M22.0": "teach INIT", "M22.1": "teach POS1", "M22.2": "teach POS2", "M22.3": "teach POS3", "M22.4": "teach POS4",
  "M30.0": "auto START", "M30.1": "auto running", "M30.2": "stop / complete", "M30.4": "counter reset", "M30.6": "auto magnet",
  "M31.0": "step 0: INIT reached", "M31.1": "step 1: POS1", "M31.2": "step 2: POS2 (pick)", "M31.3": "step 3: pick delay T21", "M31.4": "step 4: lift POS1",
  "M31.5": "step 5: POS3", "M31.6": "step 6: POS4 (drop)", "M31.7": "step 7: drop done", "M32.0": "return phase", "M33.0": "end-of-run at INIT",
  "M33.6": "C2/C3 reset", "M34.3": "C4 reset", "M40.0": "homing", "M50.0": "shoulder at home", "M50.1": "base at home", "M10.0": "drive enable delay done", "M10.1": "drive disabled", "SM0.3": "1 s clock" };
function updateMem(s) {
  const bits = Object.entries(s.bits).map(([k, v]) => `<tr><td>%${k}</td><td>${BITDESC[k] || ""}</td><td><span class="tag ${v ? "on" : ""}">${v}</span></td></tr>`).join("");
  const regs = Object.entries(s.regs).map(([k, v]) => `<tr><td>%${k}</td><td class="n">${v.toLocaleString()}</td></tr>`).join("");
  const tm = Object.entries(s.timers).map(([k, t]) => `<tr><td>${k} ${t.kind}</td><td class="n">${t.ms} ms / ${t.pt}</td><td><span class="tag ${t.q ? "on" : ""}">${t.q}</span></td></tr>`).join("");
  const ct = Object.entries(s.counters).map(([k, c]) => `<tr><td>${k} CTU</td><td class="n">${c.n} / ${c.pv}</td><td><span class="tag ${c.q ? "on" : ""}">${c.q}</span></td></tr>`).join("");
  $("#memView").innerHTML = `<div class="memgrid"><div><b>Bit memory</b><table class="dt">${bits}</table></div><div><b>Registers (V/M)</b><table class="dt">${regs}</table></div><div><b>Timers</b><table class="dt">${tm}</table><br><b>Counters</b><table class="dt">${ct}</table></div></div>`;
}
let pdoRows = [];
function buildPdo() { pdoRows = PROG.pdo; }
function updateCan(s) {
  if (!pdoRows.length) return;
  const rows = pdoRows.map((r, i) => { const v = s.pdo[i]; const hex = r.bits === 16 ? "0x" + (v & 0xffff).toString(16).toUpperCase().padStart(4, "0") : r.bits === 8 ? "0x" + (v & 0xff).toString(16).toUpperCase().padStart(2, "0") : "";
    return `<tr><td>${r.node}</td><td><span class="tag ${r.dir === "RX" ? "on" : ""}">${r.dir === "RX" ? "PLC&rarr;drive" : "drive&rarr;PLC"}</span></td><td>${r.cob}</td><td>${r.obj}</td><td>%${r.addr}</td><td class="n">${v.toLocaleString()}</td><td class="n">${hex}</td></tr>`; }).join("");
  $("#canView").innerHTML = `<div style="margin-bottom:6px;color:var(--dim)">CANopen master node 127 &middot; 1000 kbps &middot; slaves 1 (base) and 2 (shoulder) &middot; heartbeat 500 ms &middot; network ${s.can_online ? '<span class="tag on">OPERATIONAL</span>' : '<span class="tag warn">starting ' + Math.round(s.can_boot * 100) + "%</span>"}</div>
   <table class="dt"><tr><th>node</th><th>dir</th><th>COB-ID</th><th>object</th><th>PLC address</th><th>value</th><th>hex</th></tr>${rows}</table>`;
}

/* ===================================================================== scope */
const SCOPE_PANELS = [
  { title: "angle (deg)", series: [["base_deg", "#4aa3ff"], ["sh_deg", "#3ddc84"], ["base_ref", "#4aa3ff77", 1], ["sh_ref", "#3ddc8477", 1]] },
  { title: "motor speed (rpm)", series: [["base_rpm", "#4aa3ff"], ["sh_rpm", "#3ddc84"]] },
  { title: "output torque (N.m)", series: [["base_nm", "#4aa3ff"], ["sh_nm", "#3ddc84"], ["sh_grav", "#ffb020", 1]] },
  { title: "motor current (A): solid = twin estimate, dashed = measured sensor", series: [["base_a", "#4aa3ff"], ["sh_a", "#3ddc84"], ["base_a_meas", "#4aa3ff99", 1], ["sh_a_meas", "#3ddc8499", 1]] },
  { title: "magnet %Q0.7", series: [["mag", "#ff4bd8"]], fixed: [0, 1] }];
const STRUCT_PANELS = [
  { title: "reaction bending moment (N.m): solid = base flange (overturning), dashed = shoulder axis.  Ansys Pose A = 30.9", series: [["m_flange", "#4aa3ff"], ["m_shoulder", "#ffb020", 1]], refs: [[30.9, "Pose A", "#ff5252"]] },
  { title: "equivalent stress (MPa): joint / link-1 / link-2 / base.  Ansys peak 8.81 (joint, Pose A)", series: [["s_joint", "#ff5252"], ["s_link1", "#3ddc84"], ["s_link2", "#4aa3ff"], ["s_base", "#aaaaaa", 1]], refs: [[8.81, "Ansys max", "#ff525299"]] },
  { title: "minimum factor of safety (capped at 15).  Ansys-reported minimum 4.63 (joint, Pose B)", series: [["fos_min", "#3ddc84"]], refs: [[4.63, "Ansys min", "#ff525299"], [1.5, "typical min 1.5", "#ffb02099"]], fixed: [0, 16] },
  { title: "link-2 tip deflection (um).  Ansys max 85.2", series: [["defl_um", "#ffb020"]], refs: [[85.2, "Ansys max", "#ff525299"]] }];

function plotPanels(cv, panels, T = 25) {
  if (!cv.clientWidth) return;
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const c = cv.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
  if (scope.length < 2) return;
  const t1 = scope[scope.length - 1].t, t0 = t1 - T, ml = 62, mr = 10;
  const ph = (H - 8) / panels.length, data = scope.filter((s) => s.t >= t0);
  panels.forEach((p, pi) => {
    const y0 = 4 + pi * ph + 14, h = ph - 22;
    let lo = Infinity, hi = -Infinity; p.series.forEach(([k]) => data.forEach((s) => { if (s[k] === undefined) return; lo = Math.min(lo, s[k]); hi = Math.max(hi, s[k]); }));
    if (p.refs) p.refs.forEach(([v]) => { if (isFinite(lo) && v < hi * 4 + 1) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    if (p.fixed) [lo, hi] = p.fixed; if (!isFinite(lo)) { lo = 0; hi = 1; } if (hi - lo < 1e-6) { hi += 1; lo -= 1; } const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const Y = (v) => y0 + h * (1 - (v - lo) / (hi - lo));
    c.fillStyle = "#8394a7"; c.font = "11px Segoe UI"; c.fillText(p.title, ml, y0 - 4);
    c.strokeStyle = "#243140"; c.strokeRect(ml, y0, W - ml - mr, h);
    c.fillText(hi.toFixed(1), 4, y0 + 9); c.fillText(lo.toFixed(1), 4, y0 + h);
    if (lo < 0 && hi > 0) { const zy = Y(0); c.strokeStyle = "#31404f"; c.beginPath(); c.moveTo(ml, zy); c.lineTo(W - mr, zy); c.stroke(); }
    (p.refs || []).forEach(([v, name, col]) => { if (v < lo || v > hi) return; c.strokeStyle = col; c.setLineDash([2, 4]); c.beginPath(); c.moveTo(ml, Y(v)); c.lineTo(W - mr, Y(v)); c.stroke(); c.setLineDash([]); c.fillStyle = col; c.fillText(name, W - mr - 6 - name.length * 5.5, Y(v) - 3); });
    p.series.forEach(([k, col, dash]) => { c.strokeStyle = col; c.lineWidth = dash ? 1 : 1.6; c.setLineDash(dash ? [4, 3] : []); c.beginPath();
      let pen = false; data.forEach((s) => { if (s[k] === undefined) return; const x = ml + (s.t - t0) / T * (W - ml - mr), y = Y(s[k]); pen ? c.lineTo(x, y) : c.moveTo(x, y); pen = true; }); c.stroke(); c.setLineDash([]); });
  });
}
function drawScope() { plotPanels($("#cvScope"), SCOPE_PANELS); }
function drawStruct() { plotPanels($("#cvStruct"), STRUCT_PANELS); }
function updateStructCards(s) {
  const st = s.structural; if (!st) return;
  const rows = Object.entries(st.bodies).map(([k, b]) => `<tr><td>${k}</td><td class="n">${b.stress_mpa.toFixed(2)} MPa</td><td class="n">${b.defl_um.toFixed(1)} um</td><td class="n">${b.fos >= 15 ? "&ge;15" : b.fos.toFixed(1)}</td>
    <td style="width:160px"><div class="bar"><i style="width:${Math.min(100, b.stress_mpa / b.yield_mpa * 100 * 8)}%"></i></div></td></tr>`).join("");
  $("#structCards").innerHTML = `<table class="dt"><tr><th>body</th><th>stress</th><th>max deflection</th><th>FOS</th><th>stress vs yield (x8)</th></tr>${rows}</table>
   <div style="margin-top:6px;color:var(--dim)">flange moment <b>${st.moment_flange.toFixed(1)}</b> N&middot;m (Pose A ref ${st.ref_moment.flange.toFixed(1)}) &middot; axial ${st.axial_n.toFixed(0)} N &middot; min FOS <b>${st.min_fos.toFixed(1)}</b> (${st.min_fos_body || "-"})</div>`;
}

/* ===================================================================== notes */
function buildNotes() {
  $("#notes").innerHTML = `
  <h3>What is simulated</h3><ul>
   <li><b>PLC:</b> the exported ladder <code>MAIN_MAIN.ilp</code> (39 networks) is parsed and executed instruction by instruction every ${S ? S.scan_ms : 5} ms scan &mdash; nothing is re-implemented by hand, so every latch, timer and counter behaves as in the program. The <i>Ladder</i> tab shows power flow per instruction.</li>
   <li><b>CANopen:</b> the PDO map of the real project (node 1 base, node 2 shoulder) moves controlword / target / speed to the drives and position / speed / current back, after the 3 s master power-on delay.</li>
   <li><b>Drives:</b> CiA402 subset: 0x0F enable (brake released), 0x2F run to absolute target, 0x10F halt; trapezoid profile, PID + feed-forward position loop, torque limit at the rated peak.</li>
   <li><b>Arm:</b> base yaw + shoulder pitch, 420 mm reach, link masses 2.0 / 1.5 kg, <b>5 kg</b> payload picked by the electromagnet. Gravity torque, inertia (including the payload and reflected rotor inertia) and coupling of the base inertia with the shoulder angle are computed live.</li>
   <li><b>HMI:</b> the three screens of the Kinco project (Auto, Manual, Setting); widgets write the same PLC bits/registers the ladder uses.</li></ul>
  <h3>Findings from running the real program</h3><ul>
   <li><b>%VW2400 overlaps %VD2400.</b> The cycle counter C2 is copied to %VW2400 every scan, which overwrites the low 16 bits of the taught shoulder INIT position. After a finished run the shoulder parks about 3&deg; away from true home, so the shoulder-home lamp stays off until RESET (%I0.1) is pressed. Set <code>fix_vw2400_overlap = True</code> in <code>twin/config.py</code> to see the program with the counter mirror moved.</li>
   <li><b>M30.6 (magnet latch) is not cleared by E-stop.</b> After an E-stop in mid-cycle the magnet re-energises as soon as the E-stop is released.</li>
   <li><b>Speed in auto mode:</b> the ladder writes the speed register (60FF) only in jog/home networks. In auto the drive's own profile velocity (6081) must be doing the work &mdash; modelled with a fallback <i>profile_rpm</i> (500 rpm, assumed) whenever 60FF = 0.</li>
   <li><b>Mode of operation (6060)</b> is never written by the PLC; the twin assumes the drives are pre-set to position mode.</li></ul>
  <h3 class="as">Assumed values &mdash; replace with measurements</h3><ul>
   <li>Position unit = motor encoder counts (15-bit, 32768/rev, per the CANopen manual) before the harmonic reducer; velocity unit = motor rpm (HMI limits 1500 / 2000 rpm). With that, the shoulder jog range of 674,624 counts is 91.5&deg; &mdash; i.e. home = arm vertical, lower limit = horizontal.</li>
   <li>Timer base 10 ms for T1&hellip;T26 and %SM0.3 = 1 s clock. Compare the simulated cycle time with the real one and tell me the ratio.</li>
   <li>Shoulder axis height 170 mm, drop link 120 mm, rotor inertias, friction, torque constants, base structure inertia 0.05 kg&middot;m&sup2;, link masses (the paper itself says 2.0/1.5 kg are assumed).</li>
   <li>Default taught points (INIT 0&deg;/0&deg;, pick 0&deg;/86&deg;, drop 90&deg;/86&deg;, hover 55&deg;). Teach your real ones on the Setting screen, then press <i>Save taught data</i>.</li>
   <li>HMI button actions (momentary START/STOP/RESET/jog; maintained magnet switch) &mdash; the DTools tag addresses were not readable.</li></ul>`;
}



/* ===================================================================== settings tab (live configuration) */
let cfgBuilt = false;
async function buildCfg() {
  cfgBuilt = true;
  const r = await (await fetch("/api/cmd", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: "config_get" }) })).json();
  const rows = Object.entries(r.keys).map(([k, [label, kind]]) => `<tr><td>${label}</td><td><code>${k}</code></td><td>${kind === "bool"
    ? `<input type="checkbox" data-k="${k}" ${r.config[k] ? "checked" : ""}>` : `<input type="number" step="any" data-k="${k}" value="${r.config[k]}" style="width:110px">`}</td></tr>`).join("");
  $("#cfgView").innerHTML = `<p style="color:var(--dim)">Changing a value rebuilds the PLC like a power cycle (taught data kept, arm keeps its pose). Assumed values are tagged <code>[assumed]</code> in <code>twin/config.py</code>.</p>
    <table class="dt">${rows}</table><p><button id="btnCfgApply">Apply</button> <button id="btnCfgSave">Apply and save to twin_config.json</button> <span id="cfgMsg" style="color:var(--dim)"></span></p>`;
  const collect = () => { const v = {}; document.querySelectorAll("#cfgView [data-k]").forEach((i) => { v[i.dataset.k] = i.type === "checkbox" ? i.checked : parseFloat(i.value); }); return v; };
  const send = async (save) => { const res = await (await fetch("/api/cmd", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: "config", values: collect(), save }) })).json(); $("#cfgMsg").textContent = res.ok ? (save ? "applied and saved" : "applied") : (res.error || "error"); };
  $("#btnCfgApply").onclick = () => send(false); $("#btnCfgSave").onclick = () => send(true);
}

/* ===================================================================== data sources tab */
let srcBuilt = false;
const post = (o) => cmd(o);
function buildSources() {
  const host = $("#srcView"); srcBuilt = true;
  host.innerHTML = `
  <div class="memgrid">
   <div><b>View</b><table class="dt">
     <tr><td>primary source</td><td><select id="selSrc"><option>sim</option><option>replay</option></select></td></tr>
     <tr><td>ghost (shadow) arm</td><td><select id="selGhost"><option>none</option></select></td></tr></table>
     <p style="color:var(--dim)">The translucent cyan arm in the 3D view is the ghost: any second source (live PLC encoders, mocap, a recorded run) drawn over the primary one.</p></div>
   <div><b>Recorder</b><table class="dt">
     <tr><td>source</td><td><select id="selRecSrc"><option>sim</option></select></td></tr>
     <tr><td id="recState">idle</td><td><button id="btnRec">Record</button></td></tr></table>
     <p style="color:var(--dim)">Logs go to <code>logs/*.jsonl</code> (snapshot schema v1).</p></div>
   <div><b>Replay</b><table class="dt">
     <tr><td>log</td><td><select id="selLog"></select> <button id="btnLoad">Load</button></td></tr>
     <tr><td>transport</td><td><button id="btnRPlay">Play/Pause</button> <select id="selRSpeed"><option>0.25</option><option selected>1</option><option>2</option><option>5</option></select>x</td></tr>
     <tr><td>position</td><td><input id="rngSeek" type="range" min="0" max="1000" value="0" style="width:200px"> <span id="lblSeek"></span></td></tr></table></div>
   <div><b>Live sources</b><div id="liveSrc" style="color:var(--dim)">none registered. Start with <code>run_twin.py --plc HOST</code> / <code>--sensors</code> / <code>--mocap</code>.</div></div>
  </div>`;
  $("#selSrc").onchange = (e) => { SRC = e.target.value; connect(); };
  $("#selGhost").onchange = (e) => { GHOST = e.target.value; connect(); };
  $("#btnRec").onclick = () => { const src = $("#selRecSrc").value; const r = src === "sim" ? HUB.recorder : (HUB.recorders && HUB.recorders[src]) || { active: false }; post({ type: r.active ? "record_stop" : "record_start", source: src }); };
  $("#btnLoad").onclick = () => { const f = $("#selLog").value; if (f) post({ type: "replay_load", file: f }); };
  $("#btnRPlay").onclick = () => post({ type: "replay_play", on: !(HUB && HUB.replay.playing) });
  $("#selRSpeed").onchange = (e) => post({ type: "replay_speed", value: e.target.value });
  $("#rngSeek").oninput = (e) => post({ type: "replay_seek", frac: e.target.value / 1000 });
}
function updateSources(s) {
  if (!srcBuilt) buildSources();
  if (!HUB) return;
  const g = $("#selGhost"), want = ["none", ...HUB.sources.filter((x) => x !== SRC)];
  if (g.options.length !== want.length || [...g.options].some((o, i) => o.value !== want[i])) { g.innerHTML = want.map((x) => `<option ${x === GHOST ? "selected" : ""}>${x}</option>`).join(""); }
  const l = $("#selLog"); if (document.activeElement !== l && l.options.length !== HUB.logs.length) l.innerHTML = HUB.logs.map((f) => `<option ${f === HUB.replay.file ? "selected" : ""}>${f}</option>`).join("");
  const rs = $("#selRecSrc"), wantRec = ["sim", ...Object.keys(HUB.live)];
  if (rs.options.length !== wantRec.length) rs.innerHTML = wantRec.map((x) => `<option>${x}</option>`).join("");
  const rr = rs.value === "sim" ? HUB.recorder : (HUB.recorders && HUB.recorders[rs.value]) || { active: false, frames: 0, file: "" };
  $("#recState").textContent = rr.active ? `recording ${rr.file} (${rr.frames} frames)` : "idle";
  $("#btnRec").textContent = rr.active ? "Stop" : "Record";
  const r = HUB.replay; $("#lblSeek").textContent = r.file ? `${r.file}  ${r.pos.toFixed(1)} / ${r.duration.toFixed(1)} s` : "no log loaded";
  if (document.activeElement !== $("#rngSeek") && r.duration) $("#rngSeek").value = Math.round(r.pos / r.duration * 1000);
  $("#liveSrc").innerHTML = Object.keys(HUB.live).length ? Object.entries(HUB.live).map(([k, v]) => `<div><b>${k}</b>: <span class="tag ${v.connected ? "on" : "warn"}">${v.connected ? "connected" : "not connected"}</span> ${v.info || ""}</div>`).join("") : $("#liveSrc").innerHTML;
}

/* ===================================================================== main loop */
let frame = 0;
function render() {
  frame++;
  if (S && S.bits && S.load) {
    const s = S;
    $("#chipCan").textContent = s.powered ? (s.can_online ? "CANopen OK" : `CANopen starting ${Math.round(s.can_boot * 100)}%`) : "POWER OFF";
    $("#chipCan").className = "chip " + (!s.powered ? "bad" : s.can_online ? "ok" : "warn");
    $("#chipScan").textContent = `scan ${s.scan_ms} ms #${s.scan_count}`;
    $("#chipTime").textContent = `t = ${s.t.toFixed(1)} s`;
    $("#chipCycle").textContent = `run ${s.cycle_s.toFixed(1)} s | picks ${s.picks}`;
    $("#btnPause").textContent = s.paused ? "Resume" : "Pause";
    $("#btnEstop").classList.toggle("pressed", s.estop);
    $("#btnPower").classList.toggle("off", !s.powered); $("#btnPower").innerHTML = `POWER<br><small>${s.powered ? "ON" : "OFF"}</small>`;
    const L = (id, v) => $(id).classList.toggle("on", !!v);
    L("#ledI00", s.io["I0.0"]); L("#ledI01", s.io["I0.1"]); L("#ledQ07", s.io["Q0.7"]); L("#ledM301", s.bits["M30.1"]);
    L("#ledM400", s.bits["M40.0"]); L("#ledM500", s.bits["M50.0"]); L("#ledM501", s.bits["M50.1"]);
    // HMI replica mirrors the real PLC (read-only) while the ghost source is the live PLC; otherwise it shows the simulation
    const mirror = s.ghost && s.ghost.source === "plc" && s.ghost.regs && s.ghost.hmi;
    $("#hmi").classList.toggle("mirror", !!mirror);
    if (frame % 2 === 0) bind.forEach((b) => b.fn(mirror ? { ...s, regs: s.ghost.regs, bits: { ...s.bits, ...s.ghost.bits }, hmi: { ...s.hmi, ...s.ghost.hmi }, cycle_reg: s.ghost.cycle_reg } : s));
    drawScene(cvTop, "top"); drawScene(cvSide, "side");
    const ld = s.load;
    $("#viewInfo").innerHTML = `payload on magnet: <b>${ld.payload_kg.toFixed(1)} kg</b> &nbsp;|&nbsp; shoulder gravity torque ${ld.t_grav.toFixed(1)} N&middot;m (unloaded ${ld.t_grav_unloaded.toFixed(1)}) &nbsp;|&nbsp; J<sub>sh</sub> ${ld.j_shoulder.toFixed(2)} &nbsp; J<sub>base</sub> ${ld.j_base.toFixed(2)} kg&middot;m&sup2;`;
    if (s.ghost && s.ghost.geom) {
      const g = s.ghost, d = Math.hypot(...s.geom.tip.map((v, i) => (v - g.geom.tip[i]) * 1000));
      $("#viewInfo").innerHTML += `<br><span style="color:#4ae0ff">ghost (${g.source}) &Delta; base ${(g.base.deg - s.base.deg).toFixed(2)}&deg; &nbsp; shoulder ${(g.shoulder.deg - s.shoulder.deg).toFixed(2)}&deg; &nbsp; tip ${d.toFixed(1)} mm</span>`;
    }
    if (frame % 3 === 0) {
      const meas = (k) => { const m = s.sensors && s.sensors[k]; return m ? `<tr><td>measured (sensor)</td><td>${(m.mA / 1000).toFixed(2)} A &middot; ${(m.mV / 1000).toFixed(1)} V &middot; ${m.W.toFixed(1)} W</td></tr>` : ""; };
      axisCard($("#axBase"), "Base motor &mdash; node 1 &middot; M8025 101:1", s.base, `<tr><td>inertia J</td><td>${ld.j_base.toFixed(2)} kg&middot;m&sup2;</td></tr>` + meas("base"));
      axisCard($("#axSh"), "Shoulder motor &mdash; node 2 &middot; M8010 81:1", s.shoulder, `<tr><td>gravity torque</td><td>${ld.t_grav.toFixed(1)} N&middot;m</td></tr>` + meas("shoulder"));
      $("#logbox").textContent = (s.log || []).slice().reverse().join("\n");
    }
    if (frame % 4 === 0) updateLadder(s);
    if (frame % 6 === 0) { if ($("#tab-mem").classList.contains("on")) updateMem(s); if ($("#tab-can").classList.contains("on")) updateCan(s); }
    if (frame % 6 === 0 && $("#tab-scope").classList.contains("on")) drawScope();
    if (frame % 6 === 0 && $("#tab-struct").classList.contains("on")) { drawStruct(); updateStructCards(s); }
  }
  if (S && frame % 10 === 0 && $("#tab-src").classList.contains("on")) updateSources(S);
  requestAnimationFrame(render);
}
let ES = null, SRC = "sim", GHOST = "none", HUB = null;
function connect() {
  if (location.search.includes("snap")) {
    Promise.all([fetch("/api/state").then((r) => r.json()), fetch("/api/scope").then((r) => r.json())]).then(([s, sc]) => { s.watch = {}; S = window.__lastSnap = s; sc.forEach((x) => scope.push(x)); const sc2 = /screen=(\w+)/.exec(location.search); if (sc2) showScreen(sc2[1]); const m = /tab=(\w+)/.exec(location.search); if (m) document.querySelector(`#tabs button[data-tab=${m[1]}]`).click(); });
    return;
  }
  if (ES) ES.close();
  const es = ES = new EventSource(`/api/stream?source=${SRC}&ghost=${GHOST}`);
  es.onmessage = (e) => {
    const s = JSON.parse(e.data); if (s.empty) return; S = window.__lastSnap = s; if (s.watch) WATCH = s.watch; if (s.hub) HUB = s.hub;
    if (!s.geom) return;
    if (s.sample && (!scope.length || scope[scope.length - 1].t !== s.sample.t)) { scope.push(s.sample); if (scope.length > 800) scope.shift(); }
    const tp = s.geom.tip; if (!trail.length || Math.hypot(tp[0] - trail[trail.length - 1][0], tp[1] - trail[trail.length - 1][1], tp[2] - trail[trail.length - 1][2]) > 0.006) { trail.push(tp.slice()); if (trail.length > 260) trail.shift(); }
    if (s.cfg_payload !== undefined) $("#rngPayload").value !== String(s.cfg_payload) && document.activeElement !== $("#rngPayload") && ($("#rngPayload").value = s.cfg_payload, $("#lblPayload").textContent = s.cfg_payload.toFixed(1) + " kg");
  };
  es.onerror = () => { if (ES === es) { es.close(); setTimeout(connect, 1000); } };
}
buildLadder().then(() => { connect(); requestAnimationFrame(render); });
