/* Browser glue: renderer + orbit camera + text labels. Exposes window.Arm3D.update(snapshot). */
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { buildArm } from "./arm3d.js";
import { buildGhost } from "./ghost3d.js";
import { GLTFLoader } from "./vendor/loaders/GLTFLoader.js";

function label(text, color) {
  const cv = document.createElement("canvas"); cv.width = 256; cv.height = 64;
  const tex = new THREE.CanvasTexture(cv);
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  spr.scale.set(0.16, 0.04, 1); spr.renderOrder = 10;
  const set = (t) => { if (spr.userData.t === t) return; spr.userData.t = t; const c = cv.getContext("2d"); c.clearRect(0, 0, 256, 64);
    c.font = "bold 34px Segoe UI, sans-serif"; c.textAlign = "center"; c.textBaseline = "middle"; c.lineWidth = 6; c.strokeStyle = "#000c"; c.strokeText(t, 128, 34); c.fillStyle = color; c.fillText(t, 128, 34); tex.needsUpdate = true; };
  spr.userData.set = set; set(text); return spr;
}

const canvas = document.getElementById("cvIso");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.shadowMap.enabled = true; renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
const arm = buildArm(THREE, { label });
const ghost = buildGhost(THREE, arm.scene);
const camera = new THREE.PerspectiveCamera(45, 1, 0.02, 30);
camera.up.set(0, 0, 1);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.12; controls.rotateSpeed = 0.8; controls.zoomSpeed = 1.1;
controls.zoomToCursor = true; controls.screenSpacePanning = true;
controls.minDistance = 0.12; controls.maxDistance = 8; controls.maxPolarAngle = Math.PI * 0.495;
controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };

/* ---- camera presets, animated; "reset" always works, so the view can never get lost ---- */
const T = new THREE.Vector3(...arm.target);
const PRESETS = {                       // offset from the arm target; z is up
  iso: { off: [0.85, -0.95, 0.6], name: "Iso" },
  top: { off: [0.0, -0.001, 1.7], name: "Top" },
  front: { off: [0.0, -1.7, 0.12], name: "Front" },
  side: { off: [1.7, 0.0, 0.12], name: "Side" },
  back: { off: [-0.85, 0.95, 0.6], name: "Back" },
};
let tween = null, follow = false, current = "iso";
function goTo(name, instant = false) {
  const p = PRESETS[name]; if (!p) return; current = name;
  const tgt = (follow && snap && snap.geom) ? new THREE.Vector3(...snap.geom.tip) : T.clone();
  const pos = tgt.clone().add(new THREE.Vector3(...p.off));
  if (instant) { camera.position.copy(pos); controls.target.copy(tgt); controls.update(); tween = null; }
  else tween = { t0: performance.now(), dur: 520, p0: camera.position.clone(), t0v: controls.target.clone(), p1: pos, t1v: tgt };
  document.querySelectorAll("#viewBar [data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === name));
}
function stepTween() {
  if (!tween) return;
  const k = Math.min(1, (performance.now() - tween.t0) / tween.dur), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
  camera.position.lerpVectors(tween.p0, tween.p1, e); controls.target.lerpVectors(tween.t0v, tween.t1v, e);
  if (k >= 1) tween = null;
}
function fit() {                         // frame the arm's whole reach from the current direction
  const dir = camera.position.clone().sub(controls.target).normalize();
  const tgt = T.clone(), pos = tgt.clone().add(dir.multiplyScalar(1.9));
  tween = { t0: performance.now(), dur: 450, p0: camera.position.clone(), t0v: controls.target.clone(), p1: pos, t1v: tgt };
}
// any manual interaction cancels a running animation
canvas.addEventListener("pointerdown", () => { tween = null; });
canvas.addEventListener("wheel", () => { tween = null; }, { passive: true });
canvas.addEventListener("dblclick", () => goTo("iso"));
goTo("iso", true);

const bar = document.getElementById("viewBar");
if (bar) {
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.view) goTo(b.dataset.view);
    else if (b.id === "vbFit") fit();
    else if (b.id === "vbReset") { follow = false; setFollow(); goTo("iso"); }
    else if (b.id === "vbFollow") { follow = !follow; setFollow(); }
    else if (b.id === "vbSize") { const w = document.getElementById("viewWrap"); w.classList.toggle("tall"); b.classList.toggle("on", w.classList.contains("tall")); }
    else if (b.id === "vbFull") { const w = document.getElementById("viewWrap"); if (document.fullscreenElement) document.exitFullscreen(); else w.requestFullscreen && w.requestFullscreen(); }
  });
}
function setFollow() { const b = document.getElementById("vbFollow"); if (b) b.classList.toggle("on", follow); }
// keyboard: only while the pointer is over the 3D view and no text field is focused
let hover = false;
const wrap = document.getElementById("viewWrap");
wrap.addEventListener("pointerenter", () => { hover = true; }); wrap.addEventListener("pointerleave", () => { hover = false; });
window.addEventListener("keydown", (e) => {
  if (!hover || /^(INPUT|SELECT|TEXTAREA)$/.test((document.activeElement || {}).tagName || "")) return;
  const map = { 1: "iso", 2: "top", 3: "front", 4: "side", 5: "back" };
  if (map[e.key]) goTo(map[e.key]);
  else if (e.key === "r" || e.key === "R") { follow = false; setFollow(); goTo("iso"); }
  else if (e.key === "f" || e.key === "F") { follow = !follow; setFollow(); }
  else if (e.key === "0") fit();
  else return;
  e.preventDefault();
});
let snap = null;
// optional CAD models (twin/web/models/manifest.json written by tools/import_cad.py)
(async () => {
  try {
    const r = await fetch("models/manifest.json", { cache: "no-store" });
    if (!r.ok) return;
    const man = await r.json(), loader = new GLTFLoader(), models = {}, frames = {}; let partCenter;
    for (const [name, info] of Object.entries(man.bodies)) {
      const g = await loader.loadAsync("models/" + info.file); models[name] = g.scene; frames[name] = info.frame === "yaw" && name === "base" ? "static" : info.frame;
      if (name === "part") partCenter = info.center;
    }
    arm.opts.frames = frames; arm.opts.partCenter = partCenter;
    console.log("CAD bodies attached:", arm.attachBodies(models));
  } catch (e) { console.warn("no CAD models:", e); }
})();
new ResizeObserver(() => { const w = canvas.clientWidth, h = canvas.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }).observe(canvas);
(function loop() { requestAnimationFrame(loop); const cur = window.__lastSnap || snap; if (cur && cur.geom) arm.update(cur); ghost.update(cur && cur.ghost); if (follow && cur && cur.geom && !tween) { const t = cur.geom.tip, d = new THREE.Vector3(t[0], t[1], t[2]).sub(controls.target).multiplyScalar(0.12); controls.target.add(d); camera.position.add(d); }
  stepTween(); controls.update(); renderer.render(arm.scene, camera); })();
window.Arm3D = { update: (s) => { snap = s; } };
