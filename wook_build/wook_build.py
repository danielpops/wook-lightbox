# Wook lightbox builder for Autodesk Fusion. See README.md for the full story.
#
# WARNING: phase_body() deletes the active design's entire timeline and rebuilds from scratch.
# Run it in the Wook design (or an empty one), never in an unrelated design.
#
# Phases (run in this order; split up so each MCP call stays short):
#   phase_body()        W / oo / K body walls, dovetails, wire + power holes, pole collar + thread, snap grooves, pry slots
#   phase_caps(True)    front caps: black lip + translucent face + black skirt with snap bumps
#   phase_back()        fixed translucent back faces + full-depth black o window tubes (part of the body print)
#   phase_finish()      appearances (black / translucent white), health check
#   phase_check()       read-only: fit, snap, stop, dovetail, hole and overhang checks
# run(context) runs all of them, for use from Fusion's Scripts and Add-Ins dialog.
import adsk.core, adsk.fusion, math

TARGET_W_MM = 19 * 25.4
S = TARGET_W_MM / 237.2            # scale vs. the original 237.2 mm-wide version

# ---- scaled geometry (cm) ----
P = 0.5 * S; D = 2.6 * S; WALL = 0.2 * S; CAP_DEPTH = 0.6 * S; R = 0.3 * S
WIRE_Y = 3.24                      # cm; 14 mm wire hole spans 25.4..39.4 mm (W floor inner face is at 24.4)
# ---- fixed functional sizes (cm) ----
CLEAR = 0.01; TUBE_GAP = 0.02      # front cap fit: 0.1 mm per side (0.2 printed loose)
LAYER = 0.03                       # 0.3 mm layer height
LIP = 5 * LAYER                    # black lip on the wall rim: 1.5 mm
CAP_T = 5 * LAYER                  # translucent face + skirt wall: 1.5 mm
POWER_R = 0.7; WIRE_R = 0.7        # 14 mm wire + power holes
ROWS = 14
# snap bumps (mm, fixed)
BUMP_H = 0.5; BUMP_L = 10.0
# pry slots (mm, fixed)
PRY_W = 8.0; PRY_D = 1.5

mm = lambda cm: cm * 10
D_MM, LIP_MM, WALL_MM, CLR_MM, CAPD_MM = mm(D), mm(LIP), mm(WALL), mm(CLEAR), mm(CAP_DEPTH)

ZC = D_MM / 2
DT_DEPTH = 4.0 * S                 # how far the tail reaches into the o (mm)
DT_NECK = 13.0                     # tail width (front-back, mm) at the joint
DT_TIP = DT_NECK + 2 * 0.275 * DT_DEPTH   # ~15 deg flanks
DT_CLEAR = 0.4                     # per side; 0.2 was too tight to assemble on the first print
DT_Y0 = 47.0                       # tail bottom / socket floor (mm), above the 14 mm wire hole
BLK_Y0 = 42.0                      # socket block bottom (mm)
BLK_WALL = 3.0                     # socket wall around the slot (mm)
BLK_W = DT_DEPTH + DT_CLEAR + BLK_WALL
BLK_Z1 = ZC + DT_TIP / 2 + DT_CLEAR + BLK_WALL                              # front of the socket block
BLK_ZLOW = ZC - DT_TIP / 2 - DT_CLEAR - BLK_WALL - (DT_DEPTH + DT_CLEAR)    # back edge at the wall; 45 deg chamfer outward (self-supporting)
TOP_MM = 12 * P * 10

POLE_X = 26 * P
USER_PARAMS = [
    ("pole_hole_d", "19.05 mm", "Pole thread hole diameter (set to the thread's nominal size)"),
    ("pole_thread_len", "20 mm", "Thread depth up into the collar"),
    ("collar_w", "%.1f mm" % (25.05 * S), "Pole collar width (left-right); depth always matches the sign"),
    ("collar_h", "pole_thread_len + 2 mm", "Pole collar height below the sign: thread depth + 2 mm solid top (minimum)"),
    ("pole_thread_clear", "0.4 mm", "Print clearance on the pole thread, per side (radial). 0 = exact spec, which a broom handle could not start in"),
]
THREAD = ("ACME Screw Threads", "0.7500", "2G")

W = [
"XXXX........XXXX",
"XXXX........XXXX",
"XXXX........XXXX",
"XXXX........XXXX",
"XXXX........XXXX",
"XXXX..XXXX..XXXX",
"XXXX..XXXX..XXXX",
"XXXX..XXXX..XXXX",
"XXXX..XXXX..XXXX",
"XXXX..XXXX..XXXX",
"XXXXXXXXXXXXXXXX",
"XXXXXXXXXXXXXXXX",
"...XXXX..XXXX...",
"...XXXX..XXXX...",
]
O_OUTER = [(2,0),(8,0),(10,2),(10,8),(8,10),(2,10),(0,8),(0,2)]
O_WIN = (3, 7)
C = 4 * 7 / 5
K_POLY = [(0,0),(4,0),(4,C),(8,0),(12,0),(7,7),(12,14),(8,14),(4,14-C),(4,14),(0,14)]
LETTERS = [("W", ("bm", W), 0, False), ("o1", ("poly", O_OUTER), 16, True), ("o2", ("poly", O_OUTER), 26, True), ("k", ("poly", K_POLY), 36, False)]
V_FILL = [(24, 0), (25.9, 1.9), (25.9, 2.4), (26.1, 2.4), (26.1, 1.9), (28, 0)]
# snap bumps: (edge x, edge y) in absolute cells at the middle of a straight outline edge, inward normal (nx, ny)
BUMPS = {
    "W":  [(0, 8, 1, 0), (16, 8, -1, 0), (2, 14, 0, -1), (14, 14, 0, -1)],
    "o1": [(21, 0, 0, 1), (21, 10, 0, -1)],
    "o2": [(31, 0, 0, 1), (31, 10, 0, -1)],
    "k":  [(36, 7, 1, 0), (46, 14, 0, -1), (46, 0, 0, 1)],
}
PRY = {"W": 5, "o1": 19, "o2": 33, "k": 37}   # x (cells) on each letter's bottom edge (y = 0)


# ---------------------------------------------------------------- helpers
def app_design():
    app = adsk.core.Application.get()
    return app, adsk.fusion.Design.cast(app.activeProduct)

def comp_named(name):
    _, design = app_design()
    return [o.component for o in design.rootComponent.occurrences if o.component.name == name][0]

def body_named(comp, name):
    for b in comp.bRepBodies:
        if b.name == name: return b
    raise Exception("no body %s in %s" % (name, comp.name))

def cells(bm, x0):
    assert len(set(len(r) for r in bm)) == 1, "ragged bitmap"
    off = ROWS - len(bm); s = set()
    for r, row in enumerate(bm):
        for c, ch in enumerate(row):
            if ch == "X": s.add((x0 + c, ROWS - 1 - (r + off)))
    return s

def loops(s):
    nxt = {}
    def add(a, b):
        assert a not in nxt, "diagonal-only touch at %s" % (a,)
        nxt[a] = b
    for (x, y) in s:
        if (x, y - 1) not in s: add((x, y), (x + 1, y))
        if (x + 1, y) not in s: add((x + 1, y), (x + 1, y + 1))
        if (x, y + 1) not in s: add((x + 1, y + 1), (x, y + 1))
        if (x - 1, y) not in s: add((x, y + 1), (x, y))
    out = []
    while nxt:
        start = next(iter(nxt)); pts = [start]; cur = nxt.pop(start)
        while cur != start: pts.append(cur); cur = nxt.pop(cur)
        n = len(pts); simp = []
        for i in range(n):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
            if (b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0]) != 0: simp.append(b)
        out.append(simp)
    return out

def square(x0, lo, hi):
    return [(x0 + lo, lo), (x0 + hi, lo), (x0 + hi, hi), (x0 + lo, hi)]

def outer_loops(shape, x0):
    kind, data = shape
    if kind == "bm": return loops(cells(data, x0))
    return [[(x0 + x, y) for (x, y) in data]]

def draw(comp, lps, name):
    sk = comp.sketches.add(comp.xYConstructionPlane); sk.name = name
    sk.isComputeDeferred = True
    lines = sk.sketchCurves.sketchLines
    for lp in lps:
        pts = [adsk.core.Point3D.create(x * P, y * P, 0) for (x, y) in lp]
        first = prev = None
        for i in range(len(pts)):
            a = prev.endSketchPoint if prev else pts[0]
            b = first.startSketchPoint if i == len(pts) - 1 else pts[i + 1]
            ln = lines.addByTwoPoints(a, b)
            if first is None: first = ln
            prev = ln
    sk.isComputeDeferred = False
    profs = [sk.profiles.item(i) for i in range(sk.profiles.count)]
    def inside(a, b):
        e = 1e-6
        return (a.minPoint.x > b.minPoint.x+e and a.minPoint.y > b.minPoint.y+e and a.maxPoint.x < b.maxPoint.x-e and a.maxPoint.y < b.maxPoint.y-e)
    coll = adsk.core.ObjectCollection.create()
    for p in profs:
        if not any(inside(p.boundingBox, q.boundingBox) for q in profs if q is not p): coll.add(p)
    return coll

def extrude(comp, profs, start, dist):
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(profs, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(dist))
    if start: inp.startExtent = adsk.fusion.OffsetStartDefinition.create(adsk.core.ValueInput.createByReal(start))
    return ex.add(inp).bodies.item(0)

def sketch_normal(sk):
    o, x, y, z = sk.transform.getAsCoordinateSystem()
    return z

def prism(comp, axis, pts_mm, a0, a1, name):
    """Polygon (u, z) in mm, extruded along model axis 'x' or 'y' from a0 to a1 mm (u = the other in-plane axis)."""
    if axis == "y":
        plane = comp.xZConstructionPlane; P3 = lambda u, z: adsk.core.Point3D.create(u / 10, 0, z / 10); comp_n = lambda n: n.y
        ext = lambda bb: (bb.minPoint.y * 10, bb.maxPoint.y * 10)
    else:
        plane = comp.yZConstructionPlane; P3 = lambda u, z: adsk.core.Point3D.create(0, u / 10, z / 10); comp_n = lambda n: n.x
        ext = lambda bb: (bb.minPoint.x * 10, bb.maxPoint.x * 10)
    sk = comp.sketches.add(plane); sk.name = name
    sk.isComputeDeferred = True
    pts = [sk.modelToSketchSpace(P3(u, z)) for (u, z) in pts_mm]
    L = sk.sketchCurves.sketchLines; first = prev = None
    for i in range(len(pts)):
        a = prev.endSketchPoint if prev else pts[0]
        b = first.startSketchPoint if i == len(pts) - 1 else pts[i + 1]
        ln = L.addByTwoPoints(a, b)
        if first is None: first = ln
        prev = ln
    sk.isComputeDeferred = False
    assert sk.profiles.count == 1, "%s: %d profiles" % (name, sk.profiles.count)
    sgn = 1 if comp_n(sketch_normal(sk)) > 0 else -1
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(sgn * (a1 - a0) / 10))
    inp.startExtent = adsk.fusion.OffsetStartDefinition.create(adsk.core.ValueInput.createByReal(sgn * a0 / 10))
    f = ex.add(inp); f.name = name
    b = f.bodies.item(0)
    e0, e1 = ext(b.boundingBox)
    assert abs(e0 - a0) < 1e-3 and abs(e1 - a1) < 1e-3, name + " wrong direction"
    b.name = name
    return b

def prism_y(comp, pts_mm, y0, y1, name):
    return prism(comp, "y", pts_mm, y0, y1, name)

def z_edges(body):
    out = []
    for e in body.edges:
        g = e.geometry
        if isinstance(g, adsk.core.Line3D):
            a, b = g.startPoint, g.endPoint
            if abs(a.x-b.x) < 1e-6 and abs(a.y-b.y) < 1e-6: out.append((e, a))
    return out

def fillet(comp, groups):
    fi = comp.features.filletFeatures
    inp = fi.createInput()
    for r, edges in groups:
        if not edges: continue
        c = adsk.core.ObjectCollection.create()
        for e in edges: c.add(e)
        inp.edgeSetInputs.addConstantRadiusEdgeSet(c, adsk.core.ValueInput.createByReal(r), False)
    return fi.add(inp)

def round_vertical(comp, body):
    fillet(comp, [(R, [e for e, _ in z_edges(body)])])

def round_tube(comp, body, x0):
    cx = (x0 + 5) * P; cy = 5 * P; hw = (O_WIN[1] - O_WIN[0]) * P / 2
    inner, outer = [], []
    for e, p in z_edges(body):
        (inner if max(abs(p.x - cx), abs(p.y - cy)) <= hw + 1e-6 else outer).append(e)
    fillet(comp, [(R, inner), (R + WALL, outer)])

def zfaces(body, z):
    res = []
    for f in body.faces:
        g = f.geometry
        if g.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType and abs(abs(g.normal.z)-1) < 1e-6 and abs(f.pointOnFace.z - z) < 1e-5: res.append(f)
    return res

def shell(comp, faces, t):
    coll = adsk.core.ObjectCollection.create()
    for f in faces: coll.add(f)
    inp = comp.features.shellFeatures.createInput(coll, False)
    inp.insideThickness = adsk.core.ValueInput.createByReal(t)
    comp.features.shellFeatures.add(inp)

def combine(comp, target, tools, op, keep=False):
    coll = adsk.core.ObjectCollection.create()
    for t in tools: coll.add(t)
    inp = comp.features.combineFeatures.createInput(target, coll)
    inp.operation = op
    inp.isKeepToolBodies = keep
    return comp.features.combineFeatures.add(inp)

def cyl_cut(comp, bodies, plane, center, r, length):
    sk = comp.sketches.add(plane)
    sk.sketchCurves.sketchCircles.addByCenterRadius(sk.modelToSketchSpace(center), r)
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
    inp.setSymmetricExtent(adsk.core.ValueInput.createByReal(length), True)
    inp.participantBodies = bodies
    return ex.add(inp)

def outline_prism(comp, shape, x0, z0, h, name, extra_loops=()):
    b = extrude(comp, draw(comp, outer_loops(shape, x0) + list(extra_loops), name), z0, h)
    round_vertical(comp, b)
    return b

def cut_window_plug(comp, target, x0, z0, h, extra):
    """Cut the o window (outer size of the black window tube + `extra` clearance) out of `target`."""
    lo, hi = O_WIN; t = (WALL + extra) / P
    plug = extrude(comp, draw(comp, [square(x0, lo - t, hi + t)], "window plug"), z0, h)
    fillet(comp, [(R + WALL + extra, [e for e, _ in z_edges(plug)])])
    combine(comp, target, [plug], adsk.fusion.FeatureOperations.CutFeatureOperation)


# ---------------------------------------------------------------- features
def collar_body(comp, w_expr, h_expr):
    sk = comp.sketches.add(comp.xYConstructionPlane); sk.name = "Pole collar"
    L = sk.sketchCurves.sketchLines; G = sk.geometricConstraints; Dm = sk.sketchDimensions
    axis = L.addByTwoPoints(adsk.core.Point3D.create(POLE_X, -10, 0), adsk.core.Point3D.create(POLE_X, 1, 0))
    axis.isConstruction = True; axis.isFixed = True
    base = L.addByTwoPoints(adsk.core.Point3D.create(POLE_X - 8, 0, 0), adsk.core.Point3D.create(POLE_X + 8, 0, 0))
    base.isConstruction = True; base.isFixed = True
    rl = L.addTwoPointRectangle(adsk.core.Point3D.create(POLE_X - 2.5, -4.5, 0), adsk.core.Point3D.create(POLE_X + 2.5, 0, 0))
    top = [l for l in rl if abs(l.startSketchPoint.geometry.y) < 1e-6 and abs(l.endSketchPoint.geometry.y) < 1e-6][0]
    left = [l for l in rl if abs(l.startSketchPoint.geometry.x - l.endSketchPoint.geometry.x) < 1e-6 and l.startSketchPoint.geometry.x < POLE_X][0]
    G.addCollinear(top, base)
    G.addSymmetry(top.startSketchPoint, top.endSketchPoint, axis)
    Dm.addDistanceDimension(top.startSketchPoint, top.endSketchPoint, adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation, adsk.core.Point3D.create(POLE_X, 1.0, 0)).parameter.expression = w_expr
    Dm.addDistanceDimension(left.startSketchPoint, left.endSketchPoint, adsk.fusion.DimensionOrientations.VerticalDimensionOrientation, adsk.core.Point3D.create(POLE_X - 4, -2.2, 0)).parameter.expression = h_expr
    assert sk.profiles.count == 1, "collar profiles %d" % sk.profiles.count
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(D))
    f = ex.add(inp); f.name = "Pole collar"
    return f.bodies.item(0)

def add_pole_mount(comp, oo):
    _, design = app_design()
    um = design.userParameters
    for n, v, c in USER_PARAMS:
        p = um.itemByName(n)
        if p is None: um.add(n, adsk.core.ValueInput.createByString(v), "mm", c)
        else: p.comment = c
    collar = collar_body(comp, "collar_w", "collar_h")
    bottom = [e for e, p in z_edges(collar) if p.y < -0.5]
    assert len(bottom) == 2, "collar bottom edges: %d" % len(bottom)
    fillet(comp, [(R, bottom)]).name = "Pole collar round"
    vfill = extrude(comp, draw(comp, [V_FILL], "o-o V fill"), 0, D)
    trims = [outline_prism(comp, ("poly", O_OUTER), x0, 0, D, "vfill trim %d" % x0) for x0 in (16, 26)]
    combine(comp, vfill, trims, adsk.fusion.FeatureOperations.CutFeatureOperation)
    combine(comp, oo, [collar, vfill], adsk.fusion.FeatureOperations.JoinFeatureOperation).name = "Join pole collar"
    sk = comp.sketches.add(comp.xZConstructionPlane); sk.name = "Pole hole"
    cpt = sk.modelToSketchSpace(adsk.core.Point3D.create(POLE_X, 0, D / 2))
    circ = sk.sketchCurves.sketchCircles.addByCenterRadius(cpt, 0.95)
    circ.centerSketchPoint.isFixed = True
    sk.sketchDimensions.addDiameterDimension(circ, adsk.core.Point3D.create(cpt.x + 1.5, cpt.y + 1.5, 0)).parameter.expression = "pole_hole_d"
    up = sketch_normal(sk).y > 0
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
    inp.startExtent = adsk.fusion.OffsetStartDefinition.create(adsk.core.ValueInput.createByString(("-" if up else "") + "collar_h"))
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString(("" if up else "-") + "pole_thread_len"))
    inp.participantBodies = [oo]
    hole = ex.add(inp); hole.name = "Pole hole"
    cyl = [f for f in hole.sideFaces if f.geometry.surfaceType == adsk.core.SurfaceTypes.CylinderSurfaceType]
    assert len(cyl) == 1, "pole hole cyl faces: %d" % len(cyl)
    tf = comp.features.threadFeatures
    faces = adsk.core.ObjectCollection.create(); faces.add(cyl[0])
    tin = tf.createInput(faces, tf.createThreadInfo(True, *THREAD))
    tin.isModeled = True; tin.isFullLength = True
    th = tf.add(tin); th.name = "Pole thread"
    # Printed internal threads come out undersized; exact spec would not even start on a real broom handle.
    # Grow the whole thread (flanks, root, and the crest = the hole wall, which isn't part of the thread feature) outward.
    tfaces = list(th.faces)
    toks = set(f.entityToken for f in tfaces)
    minor_r = th.threadInfo.minorDiameter / 2
    crest = [f for f in oo.faces if f.geometry.surfaceType == adsk.core.SurfaceTypes.CylinderSurfaceType and f.entityToken not in toks
             and abs(f.geometry.radius - minor_r) < 0.02 and f.boundingBox.maxPoint.y < 0]
    assert len(crest) == 1, "pole thread crest faces: %d" % len(crest)
    ofs = comp.features.offsetFacesFeatures
    oc = ofs.add(ofs.createInput(tfaces + crest, adsk.core.ValueInput.createByString("-pole_thread_clear")))
    oc.name = "Pole thread clearance"
    return th

def snap_geom(ex_, ey_, nx, ny, front, groove):
    """(axis, pts(u,z) mm, a0, a1) for a snap bump on the cap skirt, or its groove in the body wall."""
    X, Y = ex_ * P * 10, ey_ * P * 10
    if nx != 0: axis, u_e, n, t_c = "y", X, nx, Y
    else:       axis, u_e, n, t_c = "x", Y, ny, X
    o = -n                                   # outward, toward the wall
    zm = D_MM - LIP_MM - CAPD_MM / 2 if front else LIP_MM + CAPD_MM / 2
    sg = -1 if front else 1                  # insertion direction in z
    if not groove:
        u0 = u_e + n * (WALL_MM + CLR_MM)    # skirt outer face
        # long ramp on the leading side, steeper retaining side toward the face
        pts = [(u0 - o * 0.1, zm + sg * 1.5), (u0 + o * BUMP_H, zm), (u0 - o * 0.1, zm - sg * 0.75)]
        half = BUMP_L / 2
    else:
        u0 = u_e + n * WALL_MM               # wall inner face
        pts = [(u0 - o * 0.1, zm + sg * 1.8), (u0 + o * (BUMP_H - CLR_MM + 0.2), zm), (u0 - o * 0.1, zm - sg * 1.05)]
        half = BUMP_L / 2 + 0.5
    return axis, pts, t_c - half, t_c + half

def add_dovetail(comp, letter, oo, xj, s, o_x0, tag):
    X = lambda d: xj + s * d
    nh, th = DT_NECK / 2, DT_TIP / 2
    flare = lambda d: nh + (th - nh) * d / DT_DEPTH
    trim = outline_prism(comp, ("poly", O_OUTER), o_x0, 0, D, tag + "_trim")
    tail = prism_y(comp, [(X(0), ZC - nh), (X(DT_DEPTH), ZC - th), (X(DT_DEPTH), ZC + th), (X(0), ZC + nh)], DT_Y0, TOP_MM, tag + " tail")
    combine(comp, tail, [trim], adsk.fusion.FeatureOperations.IntersectFeatureOperation, keep=True)
    block = prism_y(comp, [(X(0), BLK_ZLOW), (X(BLK_W), BLK_ZLOW + BLK_W), (X(BLK_W), BLK_Z1), (X(0), BLK_Z1)], BLK_Y0, TOP_MM, tag + " socket block")
    combine(comp, block, [trim], adsk.fusion.FeatureOperations.IntersectFeatureOperation, keep=True)
    comp.features.removeFeatures.add(trim)
    combine(comp, letter, [tail], adsk.fusion.FeatureOperations.JoinFeatureOperation)
    combine(comp, oo, [block], adsk.fusion.FeatureOperations.JoinFeatureOperation)
    d0, d1 = -1.0, DT_DEPTH + DT_CLEAR
    slot = prism_y(comp, [(X(d0), ZC - flare(d0) - DT_CLEAR), (X(d1), ZC - flare(d1) - DT_CLEAR),
                          (X(d1), ZC + flare(d1) + DT_CLEAR), (X(d0), ZC + flare(d0) + DT_CLEAR)], DT_Y0, TOP_MM + 10, tag + " socket slot")
    combine(comp, oo, [slot], adsk.fusion.FeatureOperations.CutFeatureOperation)

def pry_slot(comp, body, cx_cells, front, name):
    """Notch in the outer bottom corner of the wall rim, just under the lip, for a fingernail / flat screwdriver."""
    cx = cx_cells * P * 10
    z0 = (D_MM - LIP_MM - PRY_D) if front else (LIP_MM - 0.5)
    sk = comp.sketches.add(comp.xYConstructionPlane); sk.name = name
    sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create((cx - PRY_W / 2) / 10, -0.05, 0), adsk.core.Point3D.create((cx + PRY_W / 2) / 10, PRY_D / 10, 0))
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
    inp.startExtent = adsk.fusion.OffsetStartDefinition.create(adsk.core.ValueInput.createByReal(z0 / 10))
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal((PRY_D + 0.5) / 10))
    inp.participantBodies = [body]
    f = ex.add(inp); f.name = name


# ---------------------------------------------------------------- phases
def phase_body():
    app, design = app_design()
    root = design.rootComponent
    names = set(o.component.name for o in root.occurrences)
    assert names <= {"Body", "Front", "Back"}, "active design %s has other components %s; refusing to wipe it" % (app.activeDocument.name, names)
    assert BLK_Z1 < D_MM - LIP_MM - CAPD_MM - 0.3, "socket block reaches the front cap skirt"
    assert BLK_ZLOW > CAP_T * 10 + 2.0, "socket block too close to the back face"
    assert (WIRE_Y - WIRE_R) * 10 >= WALL_MM + P * 10 * 2 + 0.9, "wire hole cuts into the W floor"
    assert (WIRE_Y * 10 + WIRE_R * 10) < BLK_Y0 - 0.5, "wire hole hits socket block"
    tl = design.timeline
    tl.markerPosition = 0
    tl.deleteAllAfterMarker()
    I = adsk.core.Matrix3D.create()
    bodyC = root.occurrences.addNewComponent(I).component; bodyC.name = "Body"
    root.occurrences.addNewComponent(I).component.name = "Front"

    # walls run from the back face (z = 0) to one lip thickness short of the front; the front caps' black lip sits on the rim
    sh = {}
    for name, shape, x0, win in LETTERS:
        b = outline_prism(bodyC, shape, x0, 0, D - LIP, "body_" + name)
        shell(bodyC, zfaces(b, D - LIP) + zfaces(b, 0), WALL)
        sh[name] = b
    Wb, Kb, oo = sh["W"], sh["k"], sh["o1"]
    combine(bodyC, oo, [sh["o2"]], adsk.fusion.FeatureOperations.JoinFeatureOperation)
    Wb.name = "W"; oo.name = "oo"; Kb.name = "K"
    part = {"W": Wb, "o1": oo, "o2": oo, "k": Kb}

    add_dovetail(bodyC, Wb, oo, 16 * P * 10, +1, 16, "W-oo")
    add_dovetail(bodyC, Kb, oo, 36 * P * 10, -1, 26, "oo-K")

    for xj, parts in ((16, [Wb, oo]), (26, [oo]), (36, [oo, Kb])):
        pi = bodyC.constructionPlanes.createInput()
        pi.setByOffset(bodyC.yZConstructionPlane, adsk.core.ValueInput.createByReal(xj * P))
        cyl_cut(bodyC, parts, bodyC.constructionPlanes.add(pi), adsk.core.Point3D.create(xj * P, WIRE_Y, D / 2), WIRE_R, 2.0).name = "Wire hole x%d" % xj
    for xc, p_ in ((11, Wb), (38, Kb)):
        cyl_cut(bodyC, [p_], bodyC.xZConstructionPlane, adsk.core.Point3D.create(xc * P, 0, D / 2), POWER_R, 1.6).name = "Power hole x%d" % xc

    add_pole_mount(bodyC, oo)

    for front in (True,):              # back is fixed; only the front caps snap in
        side = "front"
        for name, lst in BUMPS.items():
            grooves = []
            for i, (bx, by, nx, ny) in enumerate(lst):
                axis, pts, a0, a1 = snap_geom(bx, by, nx, ny, front, True)
                grooves.append(prism(bodyC, axis, pts, a0, a1, "%s %s groove %d" % (side, name, i)))
            combine(bodyC, part[name], grooves, adsk.fusion.FeatureOperations.CutFeatureOperation).name = "%s %s snap grooves" % (side, name)
        for name, cx in PRY.items():
            pry_slot(bodyC, part[name], cx, front, "%s %s pry slot" % (side, name))

    print("phase_body ok:", [b.name for b in bodyC.bRepBodies], "timeline", tl.count)

def phase_caps(front):
    label = "Front" if front else "Back"
    comp = comp_named(label)
    zf0 = D - LIP if front else 0
    zs0 = D - LIP - CAP_DEPTH if front else LIP
    for name, shape, x0, win in LETTERS:
        tag = "%s %s" % (label, name)
        lip = outline_prism(comp, shape, x0, zf0, LIP, tag + " lip")          # exactly the wall's footprint
        shell(comp, zfaces(lip, zf0) + zfaces(lip, zf0 + LIP), WALL)
        face = outline_prism(comp, shape, x0, zf0, LIP, tag + " face")         # translucent, inside the wall
        combine(comp, face, [lip], adsk.fusion.FeatureOperations.CutFeatureOperation, keep=True)
        if win:                                                                 # clearance hole around the body's black window tube
            cut_window_plug(comp, face, x0, zf0, LIP, CLEAR)
        before = set(b.entityToken for b in comp.bRepBodies)
        sk_ = outline_prism(comp, shape, x0, zs0, CAP_DEPTH, tag + " skirt")
        cl = outline_prism(comp, shape, x0, zs0, CAP_DEPTH, tag + " skirt clear")
        shell(comp, zfaces(cl, zs0) + zfaces(cl, zs0 + CAP_DEPTH), WALL + CLEAR)
        skTok = sk_.entityToken
        tools = [b for b in comp.bRepBodies if b.entityToken not in before and b.entityToken != skTok]
        combine(comp, sk_, tools, adsk.fusion.FeatureOperations.CutFeatureOperation)
        shell(comp, zfaces(sk_, zs0) + zfaces(sk_, zs0 + CAP_DEPTH), CAP_T)
        bumps = []
        for i, (bx, by, nx, ny) in enumerate(BUMPS[name]):
            axis, pts, a0, a1 = snap_geom(bx, by, nx, ny, front, False)
            bumps.append(prism(comp, axis, pts, a0, a1, "%s snap %d" % (tag, i)))
        combine(comp, sk_, bumps, adsk.fusion.FeatureOperations.JoinFeatureOperation)
        # skirt stays a separate black body: it's hidden behind the wall, and keeping it out of the
        # translucent filament means a slow speed limit on that filament only slows the 5 face layers
        face.name = tag + " face"; sk_.name = tag + " skirt"; lip.name = tag + " lip"
    print("phase_caps(%s) ok:" % label, [b.name for b in comp.bRepBodies])

def phase_back():
    """Fixed translucent back faces (printed fused to the body with multi-material) + full-depth black o window tubes."""
    bodyC = comp_named("Body")
    part = {"W": "W", "o1": "oo", "o2": "oo", "k": "K"}
    for name, shape, x0, win in LETTERS:
        face = outline_prism(bodyC, shape, x0, 0, CAP_T, name + " back face")
        combine(bodyC, face, [body_named(bodyC, part[name])], adsk.fusion.FeatureOperations.CutFeatureOperation, keep=True)
        if win:
            cut_window_plug(bodyC, face, x0, 0, CAP_T, 0)
            lo, hi = O_WIN; t = WALL / P
            tube = extrude(bodyC, draw(bodyC, [square(x0, lo, hi), square(x0, lo - t, hi + t)], name + " window"), 0, D)
            round_tube(bodyC, tube, x0)
            tube.name = "oo window " + name
        face.name = name + " back face"
    print("phase_back ok:", [b.name for b in bodyC.bRepBodies])

def phase_finish():
    app, design = app_design()
    bodyC = comp_named("Body")
    assert bodyC.bRepBodies.count == 9, "expected 3 body parts + 4 back faces + 2 window tubes, got %d" % bodyC.bRepBodies.count
    lib = app.materialLibraries.itemByName('Fusion Appearance Library')
    def ap(n):
        return design.appearances.itemByName(n) or design.appearances.addByCopy(lib.appearances.itemByName(n), n)
    white = ap('Plastic - Translucent Matte (White)'); black = ap('Plastic - Matte (Black)')
    for o in design.rootComponent.occurrences:
        for b in o.component.bRepBodies:
            b.appearance = white if b.name.endswith(" face") else black      # only the faces are translucent
    tl = design.timeline
    bad = [(tl.item(i).name, tl.item(i).errorOrWarningMessage) for i in range(tl.count) if tl.item(i).healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState]
    print("phase_finish ok, timeline", tl.count, "unhealthy:", bad)

def phase_check():
    app, design = app_design()
    root = design.rootComponent
    bodyC, frontC = comp_named("Body"), comp_named("Front")
    for c in (bodyC, frontC):
        for b in c.bRepBodies:
            assert b.lumps.count == 1, "%s is in %d pieces" % (b.name, b.lumps.count)
    print("bodies: body %d %s, front %d" % (bodyC.bRepBodies.count, [b.name for b in bodyC.bRepBodies], frontC.bRepBodies.count))
    allb = [b for c in (bodyC, frontC) for b in c.bRepBodies]
    z0 = min(b.boundingBox.minPoint.z for b in allb); z1 = max(b.boundingBox.maxPoint.z for b in allb)
    x0 = min(b.boundingBox.minPoint.x for b in allb); x1 = max(b.boundingBox.maxPoint.x for b in allb)
    y0 = min(b.boundingBox.minPoint.y for b in allb); y1 = max(b.boundingBox.maxPoint.y for b in allb)
    print("overall %.1f x %.1f x %.1f mm" % ((x1-x0)*10, (y1-y0)*10, (z1-z0)*10))
    zr = lambda b: "%.2f..%.2f" % (b.boundingBox.minPoint.z*10, b.boundingBox.maxPoint.z*10)
    print("z mm: W %s | W back face %s | oo window o1 %s | Front W lip %s | Front W face %s" % (zr(body_named(bodyC, "W")), zr(body_named(bodyC, "W back face")), zr(body_named(bodyC, "oo window o1")), zr(body_named(frontC, "Front W lip")), zr(body_named(frontC, "Front W face"))))
    coll = adsk.core.ObjectCollection.create()
    for b in allb: coll.add(b)
    res = design.analyzeInterference(design.createInterferenceInput(coll))
    print("interferences (seated):", res.count)
    for i in range(res.count):
        r = res.item(i); print("   ", r.entityOne.name, "x", r.entityTwo.name)
    tb = adsk.fusion.TemporaryBRepManager.get()
    def overlap(a, b, dx=0, dy=0, dz=0):
        x = tb.copy(a); o = tb.copy(b)
        m = adsk.core.Matrix3D.create(); m.translation = adsk.core.Vector3D.create(dx / 10, dy / 10, dz / 10); tb.transform(x, m)
        tb.booleanOperation(x, o, adsk.fusion.BooleanTypes.IntersectionBooleanType)
        return x.volume * 1000 if x.lumps.count else 0.0
    part = {"W": "W", "o1": "oo", "o2": "oo", "k": "K"}
    for name in ("W", "o1", "o2", "k"):
        cap = body_named(frontC, "Front %s skirt" % name); lip = body_named(frontC, "Front %s lip" % name)
        tgt = body_named(bodyC, part[name])
        print("Front %-3s seated %.2f mm3 | pulled out 1 mm %.2f (snap >0) | lip pushed in 0.5 mm %.2f (stop >0) | shifted 0.15 mm sideways %.2f (>0 = fit tighter than 0.15)" % (
            name, overlap(cap, tgt), overlap(cap, tgt, dz=1.0), overlap(lip, tgt, dz=-0.5), overlap(cap, tgt, dy=0.15)))
    for name in ("o1", "o2"):
        cap = body_named(frontC, "Front %s face" % name); tube = body_named(bodyC, "oo window " + name)
        print("Front %s face vs window tube: seated %.2f, shifted 0.15 mm %.2f" % (name, overlap(cap, tube), overlap(cap, tube, dy=0.15)))
    oo = body_named(bodyC, "oo")
    for nm, sx in (("W", -1.0), ("K", 1.0)):
        p_ = body_named(bodyC, nm)
        slack = DT_CLEAR * DT_DEPTH / ((DT_TIP - DT_NECK) / 2)
        print("%s dovetail: drop-in +0/+20/+80 mm = %.3f/%.3f/%.3f ; sideways play %.2f mm, pulled %.1f mm = %.2f (>0 locked)" % (nm, overlap(p_, oo), overlap(p_, oo, dy=20), overlap(p_, oo, dy=80), slack, slack + 0.5, overlap(p_, oo, dx=sx * (slack + 0.5))))
    hs = sorted(set((b.name, "x" if abs(abs(f.geometry.axis.x) - 1) < 1e-6 else "y", round(f.geometry.origin.x*10,1), round(f.geometry.origin.y*10,1), round(f.geometry.radius*20,1))
                    for b in bodyC.bRepBodies for f in b.faces if f.geometry.surfaceType == adsk.core.SurfaceTypes.CylinderSurfaceType and abs(f.geometry.radius - WIRE_R) < 1e-4))
    print("14 mm holes (part, axis, x, y, dia):", hs)
    th = bodyC.features.threadFeatures.item(0)
    print("thread:", th.threadInfo.threadType, th.threadInfo.threadDesignation, "modeled", th.isModeled)
    print("socket block z range (mm): %.1f .. %.1f  | front cap skirt starts at z %.1f, back face ends at z %.1f" % (BLK_ZLOW, BLK_Z1, D_MM - LIP_MM - CAPD_MM, CAP_T * 10))
    print("overhangs flatter than 40 deg from horizontal, above the bed (body parts printed back face down):")
    for b in bodyC.bRepBodies:
        for f in b.faces:
            if f.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType: continue
            ok, nn = f.evaluator.getNormalAtPoint(f.pointOnFace)
            bb = f.boundingBox
            if ok and nn.z < -0.77 and bb.minPoint.z > 0.005 and f.area > 0.1:
                print("   %-14s area %5.0f mm2  x %.0f..%.0f  y %.0f..%.0f  z %.1f..%.1f  (%.0f deg from horizontal)" % (
                    b.name, f.area * 100, bb.minPoint.x*10, bb.maxPoint.x*10, bb.minPoint.y*10, bb.maxPoint.y*10, bb.minPoint.z*10, bb.maxPoint.z*10,
                    math.degrees(math.acos(min(1.0, -nn.z)))))


def run(context):
    """Entry point for Fusion's Scripts and Add-Ins dialog: full rebuild + checks (output goes to the Text Commands window)."""
    phase_body()
    phase_caps(True)
    phase_back()
    phase_finish()
    phase_check()
