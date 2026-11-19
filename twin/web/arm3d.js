/* Three.js model of the 2-DOF arm. Pure scene construction + update(snapshot): no renderer, no DOM,
   so it can be unit-tested in node.  World frame = the simulator's frame: metres, z up,
   base yaw about z, shoulder pitch measured from vertical-up (theta = 0 is home).            */
export function buildArm(THREE, { label }) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x121a23);
  scene.fog = new THREE.Fog(0x121a23, 2.5, 6);

  const M = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, metalness: 0.35, roughness: 0.55, ...o });
  const mats = {
    steel: M(0x5b6b7c), dark: M(0x3b4754), alu: M(0xc3ccd6, { metalness: 0.6, roughness: 0.35 }),
    motor: M(0x2f6f9f), magnet: M(0x80858f), magnetOn: M(0xd8409f, { emissive: 0xd8409f, emissiveIntensity: 0.9 }),
    part: M(0x8996a3, { metalness: 0.7, roughness: 0.4 }), placed: M(0x606b77, { metalness: 0.7, roughness: 0.5 }),
  };
  const cylZ = (r, h, mat) => { const g = new THREE.CylinderGeometry(r, r, h, 40); g.rotateX(Math.PI / 2); const m = new THREE.Mesh(g, mat); m.castShadow = m.receiveShadow = true; return m; };
  const cylY = (r, h, mat) => { const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 40), mat); m.castShadow = true; return m; };
  const box = (x, y, z, mat) => { const m = new THREE.Mesh(new THREE.BoxGeometry(x, y, z), mat); m.castShadow = m.receiveShadow = true; return m; };

  // ---- lights, floor, workspace ----
  scene.add(new THREE.HemisphereLight(0xcfe3ff, 0x20262e, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(1.2, -0.8, 2.2); sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024); Object.assign(sun.shadow.camera, { left: -1, right: 1, top: 1, bottom: -1, near: 0.5, far: 6 });
  scene.add(sun);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 2.4), new THREE.MeshStandardMaterial({ color: 0x1b2430, roughness: 0.95 }));
  floor.receiveShadow = true; scene.add(floor);
  const grid = new THREE.GridHelper(2.4, 24, 0x3a4a5c, 0x26323f); grid.rotation.x = Math.PI / 2; grid.position.z = 0.001; scene.add(grid);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.4205, 0.4225, 128), new THREE.MeshBasicMaterial({ color: 0x3d7bb5, side: THREE.DoubleSide }));
  ring.position.z = 0.002; scene.add(ring);
  const axes = new THREE.AxesHelper(0.15); axes.position.set(-0.55, -0.55, 0.002); scene.add(axes);

  // ---- arm (dimensions from the paper / config; heights are assumed) ----
  let cfg = { reach: 0.42, h: 0.17, drop: 0.12, part_r: 0.04, part_h: 0.05 };
  const base = cylZ(0.12, 0.10, mats.steel); base.position.z = 0.05; scene.add(base);
  const yaw = new THREE.Group(); scene.add(yaw);
  const pedestal = cylZ(0.065, cfg.h - 0.10, mats.dark); pedestal.position.z = 0.10 + (cfg.h - 0.10) / 2; yaw.add(pedestal);
  const shoulder = new THREE.Group(); shoulder.position.z = cfg.h; yaw.add(shoulder);
  const jointMat = mats.motor.clone();
  const housing = cylY(0.05, 0.13, jointMat); housing.rotation.x = 0; housing.rotation.z = 0; shoulder.add(housing);   // axis = Y (pitch axis)
  const link = new THREE.Group(); shoulder.add(link);                                                               // +Z = along the arm
  for (const s of [1, -1]) { const plate = box(0.045, 0.012, cfg.reach, mats.alu); plate.position.set(0, s * 0.032, cfg.reach / 2); link.add(plate); }
  const cross = box(0.04, 0.076, 0.02, mats.alu); cross.position.z = cfg.reach - 0.01; link.add(cross);
  const pin = cylY(0.014, 0.1, mats.dark); pin.position.z = cfg.reach; link.add(pin);
  const drop = new THREE.Group(); scene.add(drop);                                                                    // link-2: stays vertical
  const link2 = box(0.03, 0.03, cfg.drop, mats.alu); link2.position.z = -cfg.drop / 2; drop.add(link2);
  const magnet = cylZ(0.032, 0.035, mats.magnet); magnet.position.z = -cfg.drop - 0.0175; drop.add(magnet);
  const glow = new THREE.PointLight(0xff4bd8, 0, 0.25); glow.position.z = -cfg.drop - 0.05; drop.add(glow);

  // ---- parts, taught points, trail ----
  const partMesh = cylZ(cfg.part_r, cfg.part_h, mats.part); partMesh.visible = false; scene.add(partMesh);
  const placedMesh = cylZ(cfg.part_r, cfg.part_h, mats.placed); placedMesh.visible = false; scene.add(placedMesh);
  const massLabel = label("5.0 kg", "#ffffff"); massLabel.visible = false; scene.add(massLabel);
  const names = ["INI", "1", "2 PICK", "3", "4 DROP"], cols = [0x5f7a94, 0x5f7a94, 0xff4bd8, 0x5f7a94, 0xffb020];
  const pts = names.map((n, i) => {
    const g = new THREE.Group(), s = new THREE.Mesh(new THREE.SphereGeometry(0.009, 16, 12), new THREE.MeshBasicMaterial({ color: cols[i] }));
    const l = label(n, "#c7d2de"); l.position.z = 0.03; g.add(s, l); scene.add(g); return g; });
  const N = 300, trailPos = new Float32Array(N * 3), trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute("position", new THREE.BufferAttribute(trailPos, 3)); trailGeo.setDrawRange(0, 0);
  const trailLine = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0xffb020, transparent: true, opacity: 0.55 })); trailLine.frustumCulled = false; scene.add(trailLine);
  let trailN = 0, last = null;

  function update(S) {
    if (!S) return;
    const gc = S.geo_cfg;
    if (gc && (gc.reach !== cfg.reach || gc.h !== cfg.h || gc.drop !== cfg.drop)) { cfg = gc; rebuildDims(); }
    const phi = S.base.deg * Math.PI / 180, th = S.shoulder.deg * Math.PI / 180;
    yaw.rotation.z = phi; link.rotation.y = th;
    drop.position.set(...S.geom.p);
    const on = !!S.io["Q0.7"];
    magnet.material = on ? mats.magnetOn : mats.magnet; glow.intensity = on ? 0.25 : 0;
    const f = Math.min(1, S.shoulder.load_pct / 100);                       // joint colour = load vs continuous rating
    jointMat.color.setRGB(0.18 + 0.75 * f, 0.43 - 0.2 * f, 0.62 - 0.5 * f);
    if (S.part) { partMesh.visible = true; partMesh.position.set(...S.part.pos); }
    else partMesh.visible = false;
    if (S.placed) { placedMesh.visible = true; placedMesh.position.set(...S.placed.pos); } else placedMesh.visible = false;
    massLabel.visible = !!(S.part && S.part.state === "carried");
    if (massLabel.visible) { massLabel.position.set(S.part.pos[0], S.part.pos[1], S.part.pos[2] + 0.09); if (massLabel.userData.set) massLabel.userData.set(S.part.mass.toFixed(1) + " kg"); }
    S.points.forEach((p, i) => pts[i].position.set(p[0], p[1], p[2]));
    const tip = S.geom.tip;
    if (!last || Math.hypot(tip[0] - last[0], tip[1] - last[1], tip[2] - last[2]) > 0.006) {
      if (trailN === N) { trailPos.copyWithin(0, 3); trailN--; }
      trailPos.set(tip, trailN * 3); trailN++; last = tip.slice();
      trailGeo.attributes.position.needsUpdate = true; trailGeo.setDrawRange(0, trailN);
    }
  }
  function rebuildDims() {
    shoulder.position.z = cfg.h; pedestal.scale.z = (cfg.h - 0.10) / (0.17 - 0.10); pedestal.position.z = 0.10 + (cfg.h - 0.10) / 2;
    link.children.forEach((c) => { if (c.geometry && c.geometry.parameters && c.geometry.parameters.depth > 0.3) { c.scale.z = cfg.reach / 0.42; c.position.z = cfg.reach / 2; } });
    cross.position.z = cfg.reach - 0.01; pin.position.z = cfg.reach;
    link2.scale.z = cfg.drop / 0.12; link2.position.z = -cfg.drop / 2; magnet.position.z = -cfg.drop - 0.0175; glow.position.z = -cfg.drop - 0.05;
  }
  return { scene, update, target: [0.15, 0.12, 0.2] };
}
