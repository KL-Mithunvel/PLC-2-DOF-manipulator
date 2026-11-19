/* Browser glue: renderer + orbit camera + text labels. Exposes window.Arm3D.update(snapshot). */
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { buildArm } from "./arm3d.js";

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
const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 20);
camera.up.set(0, 0, 1); camera.position.set(0.85, -0.95, 0.6);
const controls = new OrbitControls(camera, canvas);
controls.target.set(...arm.target); controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 0.5; controls.maxDistance = 4;
controls.update();
let snap = null;
new ResizeObserver(() => { const w = canvas.clientWidth, h = canvas.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }).observe(canvas);
(function loop() { requestAnimationFrame(loop); arm.update(window.__lastSnap || snap); controls.update(); renderer.render(arm.scene, camera); })();
window.Arm3D = { update: (s) => { snap = s; } };
