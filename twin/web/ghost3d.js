/* Translucent "ghost" arm for shadow mode: shows a second pose source (live PLC encoders, mocap,
   recorded run, ...) on top of the main arm. Needs only base.deg, shoulder.deg and geom.p/tip. */
export function buildGhost(THREE, scene) {
  const mat = new THREE.MeshBasicMaterial({ color: 0x4ae0ff, transparent: true, opacity: 0.42, depthWrite: false });
  const edge = new THREE.LineBasicMaterial({ color: 0x9af0ff });
  const root = new THREE.Group(); root.visible = false; scene.add(root);
  const yaw = new THREE.Group(); root.add(yaw);
  const shoulder = new THREE.Group(); yaw.add(shoulder);
  const link = new THREE.Group(); shoulder.add(link);
  const mk = (geo, parent) => { const m = new THREE.Mesh(geo, mat); parent.add(m); parent.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), edge)); return m; };
  const ped = new THREE.Group(); yaw.add(ped);
  const pedGeo = new THREE.CylinderGeometry(0.065, 0.065, 0.07, 24); pedGeo.rotateX(Math.PI / 2); pedGeo.translate(0, 0, 0.135); mk(pedGeo, ped);
  const housing = new THREE.CylinderGeometry(0.05, 0.05, 0.13, 24); mk(housing, shoulder);
  const plateGeo = new THREE.BoxGeometry(0.045, 0.012, 0.42); plateGeo.translate(0, 0.032, 0.21); const plate2 = plateGeo.clone(); plate2.translate(0, -0.064, 0);
  mk(plateGeo, link); mk(plate2, link);
  const drop = new THREE.Group(); root.add(drop);
  const l2 = new THREE.BoxGeometry(0.03, 0.03, 0.12); l2.translate(0, 0, -0.06); mk(l2, drop);
  const tipDot = new THREE.Mesh(new THREE.SphereGeometry(0.012, 12, 10), new THREE.MeshBasicMaterial({ color: 0x4ae0ff })); root.add(tipDot);
  let h = 0.17;
  function update(S) {
    if (!S || !S.geom || !S.base) { root.visible = false; return; }
    root.visible = true;
    const gc = S.geo_cfg;
    if (gc && gc.h !== h) { h = gc.h; shoulder.position.z = h; }
    yaw.rotation.z = S.base.deg * Math.PI / 180; link.rotation.y = S.shoulder.deg * Math.PI / 180;
    drop.position.set(...S.geom.p); tipDot.position.set(...S.geom.tip);
  }
  shoulder.position.z = h;
  return { update, root };
}
