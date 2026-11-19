import * as THREE from "../twin/web/vendor/three.module.js";
import { buildArm } from "../twin/web/arm3d.js";
const label = () => { const o = new THREE.Object3D(); o.userData.set = () => {}; return o; };
const a = buildArm(THREE, { label });
const snap = (b, s, mag) => ({ base:{deg:b}, shoulder:{deg:s,load_pct:80}, io:{"Q0.7":mag}, geo_cfg:{reach:.42,h:.17,drop:.12},
  geom:{p:[.42*Math.sin(s*Math.PI/180)*Math.cos(b*Math.PI/180),.42*Math.sin(s*Math.PI/180)*Math.sin(b*Math.PI/180),.17+.42*Math.cos(s*Math.PI/180)]},
  part:{pos:[.4,0,.03],state:"carried",mass:5}, placed:null, points:[[0,0,.5],[.3,0,.2],[.4,0,.08],[0,.3,.2],[0,.4,.08]] });
for (const [b,s] of [[0,0],[0,86],[90,55]]) { const S = snap(b,s,1); S.geom.tip=[S.geom.p[0],S.geom.p[1],S.geom.p[2]-.12]; a.update(S); }
const box = new THREE.Box3().setFromObject(a.scene); console.log("scene ok, children", a.scene.children.length, "bbox", box.min.toArray().map(x=>x.toFixed(2)), box.max.toArray().map(x=>x.toFixed(2)));
