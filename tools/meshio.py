"""Mesh helpers for the CAD import: STL/OBJ reading, mass properties of a closed mesh, GLB writing.  Pure Python.

Mesh = list of triangles, each triangle = three (x, y, z) tuples.  Units: whatever the file uses; apply ``scale`` to get metres.
"""
from __future__ import annotations

import json
import math
import re
import struct

Tri = tuple


def read_stl(path: str, scale: float = 1.0) -> list[Tri]:
    data = open(path, "rb").read()
    tris: list[Tri] = []
    if len(data) >= 84 and 84 + struct.unpack_from("<I", data, 80)[0] * 50 == len(data):      # binary STL
        n = struct.unpack_from("<I", data, 80)[0]
        for i in range(n):
            v = struct.unpack_from("<12f", data, 84 + i * 50)
            tris.append(tuple(tuple(c * scale for c in v[3 + 3 * k:6 + 3 * k]) for k in range(3)))
        return tris
    pts = [tuple(float(c) * scale for c in m.groups()) for m in
           re.finditer(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data.decode("ascii", "ignore"))]
    return [tuple(pts[i:i + 3]) for i in range(0, len(pts) - 2, 3)]


def read_obj(path: str, scale: float = 1.0) -> list[Tri]:
    verts, tris = [], []
    for line in open(path, encoding="utf-8", errors="ignore"):
        if line.startswith("v "):
            verts.append(tuple(float(c) * scale for c in line.split()[1:4]))
        elif line.startswith("f "):
            idx = [int(tok.split("/")[0]) for tok in line.split()[1:]]
            idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
            for k in range(1, len(idx) - 1):                         # fan triangulation
                tris.append((verts[idx[0]], verts[idx[k]], verts[idx[k + 1]]))
    return tris


def read_mesh(path: str, scale: float = 1.0) -> list[Tri]:
    return read_obj(path, scale) if path.lower().endswith(".obj") else read_stl(path, scale)


def write_stl(path: str, tris: list[Tri]) -> None:
    with open(path, "wb") as fh:
        fh.write(b"mesh".ljust(80, b"\0") + struct.pack("<I", len(tris)))
        for t in tris:
            n = _normal(t)
            fh.write(struct.pack("<12fH", *n, *t[0], *t[1], *t[2], 0))


def _normal(t: Tri) -> tuple:
    ax, ay, az = (t[1][i] - t[0][i] for i in range(3))
    bx, by, bz = (t[2][i] - t[0][i] for i in range(3))
    n = (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)
    ln = math.sqrt(sum(c * c for c in n)) or 1.0
    return tuple(c / ln for c in n)


def box_mesh(sx: float, sy: float, sz: float, center=(0.0, 0.0, 0.0)) -> list[Tri]:
    """Closed box, outward-facing triangles (for tests and placeholders)."""
    x0, y0, z0 = (center[0] - sx / 2, center[1] - sy / 2, center[2] - sz / 2)
    x1, y1, z1 = (center[0] + sx / 2, center[1] + sy / 2, center[2] + sz / 2)
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    return [(v[q[0]], v[q[i]], v[q[i + 1]]) for q in quads for i in (1, 2)]


def mass_properties(tris: list[Tri], density: float) -> dict:
    """Mass, COM and inertia tensor about the COM of a closed, consistently oriented mesh (signed tetrahedra).
    Units follow the mesh (metres -> kg, m, kg.m^2 with density in kg/m^3)."""
    vol = 0.0
    com = [0.0, 0.0, 0.0]
    # second moments about the origin: integral of x_i x_j dV
    P = [[0.0] * 3 for _ in range(3)]
    for a, b, c in tris:
        v = (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        vol += v
        for i in range(3):
            com[i] += v * (a[i] + b[i] + c[i]) / 4.0
        for i in range(3):
            for j in range(3):
                s = 2 * (a[i] * a[j] + b[i] * b[j] + c[i] * c[j]) + (a[i] * b[j] + a[j] * b[i] + a[i] * c[j] + a[j] * c[i] + b[i] * c[j] + b[j] * c[i])
                P[i][j] += v * s / 20.0
    if abs(vol) < 1e-18:
        raise ValueError("mesh has zero volume (open or degenerate)")
    sign = 1.0 if vol > 0 else -1.0                      # tolerate inverted winding
    vol *= sign
    com = [sign * c / vol for c in com]
    mass = density * vol
    P = [[sign * p * density for p in row] for row in P]
    tr = P[0][0] + P[1][1] + P[2][2]
    I0 = [[(tr if i == j else 0.0) - P[i][j] for j in range(3)] for i in range(3)]    # about the origin
    I = [[I0[i][j] - mass * ((sum(c * c for c in com) if i == j else 0.0) - com[i] * com[j]) for j in range(3)] for i in range(3)]
    return {"volume": vol, "mass": mass, "com": com, "inertia": I}


def transform(tris: list[Tri], offset=(0.0, 0.0, 0.0)) -> list[Tri]:
    return [tuple(tuple(v[i] + offset[i] for i in range(3)) for v in t) for t in tris]


def write_glb(path: str, tris: list[Tri], color=(0.7, 0.75, 0.8, 1.0), name: str = "mesh") -> None:
    """Single-mesh GLB with flat-shaded normals and a PBR material."""
    pos, nor = [], []
    for t in tris:
        n = _normal(t)
        for v in t:
            pos.extend(v)
            nor.extend(n)
    pb = struct.pack(f"<{len(pos)}f", *pos)
    nb = struct.pack(f"<{len(nor)}f", *nor)
    xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
    gltf = {
        "asset": {"version": "2.0", "generator": "plc-2-dof twin tools"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": list(color), "metallicFactor": 0.4, "roughnessFactor": 0.5}, "doubleSided": True}],
        "buffers": [{"byteLength": len(pb) + len(nb)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pb), "target": 34962},
                        {"buffer": 0, "byteOffset": len(pb), "byteLength": len(nb), "target": 34962}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(pos) // 3, "type": "VEC3",
                       "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
                      {"bufferView": 1, "componentType": 5126, "count": len(nor) // 3, "type": "VEC3"}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    binchunk = pb + nb
    binchunk += b"\0" * (-len(binchunk) % 4)
    total = 12 + 8 + len(js) + 8 + len(binchunk)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fh.write(struct.pack("<II", len(binchunk), 0x004E4942) + binchunk)
