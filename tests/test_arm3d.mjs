import * as THREE from "../twin/web/vendor/three.module.js";
import { buildArm } from "../twin/web/arm3d.js";
const label = () => { const o = new THREE.Object3D(); o.userData.set = () => {}; return o; };
const a = buildArm(THREE, { label });
const snap = (b, s, mag) => ({ base:{deg:b}, shoulder:{deg:s,load_pct:80}, io:{"Q0.7":mag}, geo_cfg:{reach:.42,h:.17,drop:.12},
  geom:{p:[.42*Math.sin(s*Math.PI/180)*Math.cos(b*Math.PI/180),.42*Math.sin(s*Math.PI/180)*Math.sin(b*Math.PI/180),.17+.42*Math.cos(s*Math.PI/180)]},
  part:{pos:[.4,0,.03],state:"carried",mass:5}, placed:null, points:[[0,0,.5],[.3,0,.2],[.4,0,.08],[0,.3,.2],[0,.4,.08]] });
for (const [b,s] of [[0,0],[0,86],[90,55]]) { const S = snap(b,s,1); S.geom.tip=[S.geom.p[0],S.geom.p[1],S.geom.p[2]-.12]; a.update(S); }
const box = new THREE.Box3().setFromObject(a.scene); console.log("scene ok, children", a.scene.children.length, "bbox", box.min.toArray().map(x=>x.toFixed(2)), box.max.toArray().map(x=>x.toFixed(2)));

// ---- CAD attach: build a tiny GLB, parse it with the real GLTFLoader, attach as link1 ----
import { GLTFLoader } from "../twin/web/vendor/loaders/GLTFLoader.js";
function glbTriangle() {
  const bin = Buffer.from(new Float32Array([0, 0, 0.17, 0.05, 0, 0.17, 0, 0, 0.59]).buffer);
  let text = JSON.stringify({ asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }], buffers: [{ byteLength: bin.length }],
    bufferViews: [{ buffer: 0, byteLength: bin.length }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: "VEC3", min: [0, 0, 0.17], max: [0.05, 0, 0.59] }] });
  while (text.length % 4) text += " ";
  const json = Buffer.from(text);
  const head = Buffer.alloc(12); head.writeUInt32LE(0x46546C67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(12 + 8 + json.length + 8 + bin.length, 8);
  const jh = Buffer.alloc(8); jh.writeUInt32LE(json.length, 0); jh.writeUInt32LE(0x4E4F534A, 4);
  const bh = Buffer.alloc(8); bh.writeUInt32LE(bin.length, 0); bh.writeUInt32LE(0x004E4942, 4);
  const all = Buffer.concat([head, jh, json, bh, bin]);
  return all.buffer.slice(all.byteOffset, all.byteOffset + all.length);
}
const gltf = await new Promise((res, rej) => new GLTFLoader().parse(glbTriangle(), "", res, rej));
const arm2 = buildArm(THREE, { label });
const names = arm2.attachBodies({ link1: gltf.scene });
{ const S = snap(0, 90, 0); S.geom.tip = [S.geom.p[0], S.geom.p[1], S.geom.p[2] - 0.12]; arm2.update(S); }
console.log("CAD attach ok:", names);
if (names[0] !== "link1") { console.error("attach failed"); process.exit(1); }
