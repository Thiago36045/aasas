import bpy
import bmesh
import math
import random
import os
from mathutils import Vector

# ============================================================
# IT SUPPORT - THE LAB   (V7 STATIC LAB, Blender 5.1)
# - Texturas 100 % procedurales (sin archivos de imagen, casi no usan RAM)
# - Iluminacion y exposicion corregidas (la V5 quedaba quemada/blanca)
# - Laboratorio y PC HP 8200 USDT con muchisimo mas detalle
# - Escena estatica: sin animacion, sin video y sin keyframes
# ============================================================

# ------------------------------------------------------------
# AJUSTES RAPIDOS  (si algo te queda muy claro u oscuro, toca SOLO esto)
# ------------------------------------------------------------
QUALITY = "PREVIEW"      # "PREVIEW" (rapido) o "FINAL" (calidad maxima)
EXPOSURE = -0.15          # mas negativo = mas oscuro
LIGHT_SCALE = 0.75       # multiplica la potencia de TODAS las luces
EMIS = 0.65              # multiplica el brillo de neones / LEDs / pantallas
VIEW_TRANSFORM = "AgX"   # "AgX" o "Standard" (Standard conserva mas los colores)

R90 = math.radians(90)
scene = bpy.context.scene


# ============================================================
# 0. RESET
# ============================================================

def reset_scene():
    try:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.lights,
                  bpy.data.cameras, bpy.data.materials):
        for b in list(block):
            if b.users == 0:
                block.remove(b)
    for g in list(bpy.data.node_groups):
        if g.name.startswith("LAB_COMPOSITOR"):
            bpy.data.node_groups.remove(g)
    scene.timeline_markers.clear()


reset_scene()


def make_collection(name):
    col = bpy.data.collections.new(name)
    scene.collection.children.link(col)
    return col


COL_ARCH = make_collection("01_ARCHITECTURE")
COL_STAGE = make_collection("02_PRESENTATION")
COL_PC = make_collection("03_HERO_PC_HP8200")
COL_SERVER = make_collection("04_SERVERS")
COL_PROPS = make_collection("05_PROPS")
COL_LIGHT = make_collection("06_LIGHTS")
COL_CAMERA = make_collection("07_CAMERAS")


# ============================================================
# 1. SISTEMA DE MATERIALES PROCEDURALES
# ============================================================

def rgba(c, k=1.0):
    return (min(c[0] * k, 1.0), min(c[1] * k, 1.0), min(c[2] * k, 1.0), 1.0)


def _put(nt, node, idx, v):
    if isinstance(v, bpy.types.NodeSocket):
        nt.links.new(v, node.inputs[idx])
    else:
        node.inputs[idx].default_value = v


def _noise(nt, vec, scale=1.0, detail=4.0, rough=0.55, dist=0.0):
    n = nt.nodes.new("ShaderNodeTexNoise")
    nt.links.new(vec, n.inputs["Vector"])
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    n.inputs["Distortion"].default_value = dist
    return n.outputs["Fac"]


def _ramp(nt, fac, stops, interp="LINEAR"):
    n = nt.nodes.new("ShaderNodeValToRGB")
    n.color_ramp.interpolation = interp
    els = n.color_ramp.elements
    for _ in range(max(len(stops) - 2, 0)):
        els.new(1.0)
    for e, (pos, col) in zip(els, stops):
        e.position = pos
        e.color = col
    nt.links.new(fac, n.inputs["Fac"])
    return n.outputs["Color"]


def _maprange(nt, val, a0, a1, b0, b1):
    n = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(val, n.inputs["Value"])
    n.inputs["From Min"].default_value = a0
    n.inputs["From Max"].default_value = a1
    n.inputs["To Min"].default_value = b0
    n.inputs["To Max"].default_value = b1
    return n.outputs["Result"]


def _mix(nt, fac, a, b, blend="MIX"):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = blend
    cols = [i for i in n.inputs if i.type == "RGBA"]
    _put(nt, n, 0, fac)
    for sock, v in ((cols[0], a), (cols[1], b)):
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, sock)
        else:
            sock.default_value = v
    return [o for o in n.outputs if o.type == "RGBA"][0]


def _bump(nt, bsdf, height, strength=0.1, dist=0.02):
    b = nt.nodes.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = strength
    b.inputs["Distance"].default_value = dist
    nt.links.new(height, b.inputs["Height"])
    nt.links.new(b.outputs["Normal"], bsdf.inputs["Normal"])


def build_tex(m, bsdf, kind, base, rough, plane="XYZ", scale=1.0, bump=0.08, **kw):
    nt = m.node_tree
    nodes, links = nt.nodes, nt.links
    tc = nodes.new("ShaderNodeTexCoord")
    obj = tc.outputs["Object"]

    def swz(vec, pl):
        if pl == "XYZ":
            return vec
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(vec, sep.inputs["Vector"])
        cmb = nodes.new("ShaderNodeCombineXYZ")
        for dst, src in zip("XYZ", pl):
            links.new(sep.outputs[src], cmb.inputs[dst])
        return cmb.outputs["Vector"]

    def scl(vec, s):
        mp = nodes.new("ShaderNodeMapping")
        links.new(vec, mp.inputs["Vector"])
        if isinstance(s, (int, float)):
            s = (s, s, s)
        mp.inputs["Scale"].default_value = s
        return mp.outputs["Vector"]

    P = swz(obj, plane)
    BC, RG = bsdf.inputs["Base Color"], bsdf.inputs["Roughness"]

    if kind == "brushed":          # metal cepillado (vetas estiradas)
        n = _noise(nt, scl(P, (2 * scale, 90 * scale, 90 * scale)), 1.0, 4.0, 0.6)
        links.new(_maprange(nt, n, 0.3, 0.7, max(rough - 0.10, 0.03), rough + 0.15), RG)
        links.new(_mix(nt, n, rgba(base, 0.75), rgba(base, 1.2)), BC)
        _bump(nt, bsdf, n, bump)

    elif kind == "grain":          # plastico / goma / anodizado con grano fino
        n = _noise(nt, scl(P, 260 * scale), 1.0, 3.0, 0.65)
        links.new(_maprange(nt, n, 0.3, 0.7, max(rough - 0.06, 0.03), min(rough + 0.10, 1.0)), RG)
        links.new(_mix(nt, n, rgba(base, 0.8), rgba(base, 1.25)), BC)
        _bump(nt, bsdf, n, bump, 0.01)

    elif kind == "floor":          # piso pulido con manchas, rayones y variacion por baldosa
        big = _noise(nt, scl(P, 0.22 * scale), 1.0, 5.0, 0.55, 0.3)
        col = _mix(nt, big, rgba(base, 0.6), rgba(base, 1.6))
        oi = nodes.new("ShaderNodeObjectInfo")
        rr = _maprange(nt, oi.outputs["Random"], 0.0, 1.0, 0.0, 0.45)
        col = _mix(nt, rr, col, rgba(base, 2.2))
        links.new(col, BC)
        sc = _noise(nt, scl(P, (3 * scale, 70 * scale, 3 * scale)), 1.0, 3.0, 0.6)
        links.new(_maprange(nt, sc, 0.3, 0.7, max(rough * 0.6, 0.03), rough + 0.25), RG)
        _bump(nt, bsdf, sc, 0.05, 0.01)

    elif kind == "wall":           # paneles metalicos atornillados
        brk = nodes.new("ShaderNodeTexBrick")
        try:
            brk.offset = 0.0
        except Exception:
            pass
        links.new(swz(obj, plane), brk.inputs["Vector"])
        brk.inputs["Color1"].default_value = rgba(base, 1.0)
        brk.inputs["Color2"].default_value = rgba(base, 1.35)
        brk.inputs["Mortar"].default_value = rgba(base, 0.15)
        brk.inputs["Scale"].default_value = 1.0
        brk.inputs["Mortar Size"].default_value = 0.012
        brk.inputs["Mortar Smooth"].default_value = 0.1
        brk.inputs["Brick Width"].default_value = kw.get("bw", 3.0)
        brk.inputs["Row Height"].default_value = kw.get("rh", 2.1)
        links.new(brk.outputs["Color"], BC)
        n = _noise(nt, scl(P, 6 * scale), 1.0, 5.0, 0.6)
        links.new(_maprange(nt, n, 0.3, 0.7, max(rough - 0.1, 0.05), rough + 0.2), RG)
        _bump(nt, bsdf, brk.outputs["Fac"], 0.4, 0.02)

    elif kind == "pcb":            # mascara de soldadura verde con pistas y pads dorados
        vo = nodes.new("ShaderNodeTexVoronoi")
        vo.feature = "DISTANCE_TO_EDGE"
        links.new(scl(P, 5.0 * scale), vo.inputs["Vector"])
        tr = _ramp(nt, vo.outputs["Distance"], [(0.0, rgba(base, 3.4)), (0.045, rgba(base, 1.0))], "CONSTANT")
        v2 = nodes.new("ShaderNodeTexVoronoi")
        links.new(scl(P, 24.0 * scale), v2.inputs["Vector"])
        mask = _ramp(nt, v2.outputs["Distance"], [(0.0, (1, 1, 1, 1)), (0.07, (0, 0, 0, 1))], "CONSTANT")
        links.new(_mix(nt, mask, tr, (0.55, 0.38, 0.1, 1.0)), BC)
        links.new(mask, bsdf.inputs["Metallic"])
        _bump(nt, bsdf, vo.outputs["Distance"], 0.12, 0.01)

    elif kind == "screen":         # pantalla con lineas de barrido y manchas de luz
        v = scl(P, 1.0)
        wv = nodes.new("ShaderNodeTexWave")
        wv.wave_type = "BANDS"
        wv.bands_direction = "Y"
        links.new(v, wv.inputs["Vector"])
        wv.inputs["Scale"].default_value = kw.get("wscale", 20.0)
        scan = _ramp(nt, wv.outputs["Fac"], [(0.0, (0.55, 0.55, 0.55, 1)), (0.5, (1, 1, 1, 1))])
        n1 = _noise(nt, scl(P, kw.get("nscale", 2.5)), 1.0, 6.0, 0.6)
        pat = _ramp(nt, n1, [(0.35, (0.0, 0.05, 0.14, 1)), (0.65, (0.0, 0.5, 1.0, 1))])
        links.new(_mix(nt, 1.0, pat, scan, "MULTIPLY"), bsdf.inputs["Emission Color"])

    elif kind == "hazard":         # franjas amarillas y negras
        wv = nodes.new("ShaderNodeTexWave")
        wv.wave_type = "BANDS"
        wv.bands_direction = "DIAGONAL"
        links.new(scl(P, 1.0), wv.inputs["Vector"])
        wv.inputs["Scale"].default_value = kw.get("wscale", 6.0)
        links.new(_ramp(nt, wv.outputs["Fac"], [(0.0, (0.9, 0.62, 0.02, 1)), (0.5, (0.02, 0.02, 0.02, 1))],
                        "CONSTANT"), BC)
        _bump(nt, bsdf, _noise(nt, scl(P, 200.0), 1.0, 2.0, 0.6), 0.05, 0.01)

    elif kind == "keys":           # teclado
        ck = nodes.new("ShaderNodeTexChecker")
        links.new(scl(P, 1.0), ck.inputs["Vector"])
        ck.inputs["Scale"].default_value = kw.get("kscale", 30.0)
        ck.inputs["Color1"].default_value = rgba(base, 1.8)
        ck.inputs["Color2"].default_value = rgba(base, 0.4)
        links.new(ck.outputs["Color"], BC)
        _bump(nt, bsdf, ck.outputs["Fac"], 0.5, 0.01)

    elif kind == "perf":           # chapa perforada
        vo = nodes.new("ShaderNodeTexVoronoi")
        vo.feature = "F1"
        links.new(scl(P, 1.0), vo.inputs["Vector"])
        vo.inputs["Scale"].default_value = kw.get("pscale", 28.0)
        vo.inputs["Randomness"].default_value = 0.0
        links.new(_ramp(nt, vo.outputs["Distance"], [(0.0, (0.003, 0.004, 0.005, 1)), (0.33, rgba(base))],
                        "CONSTANT"), BC)
        _bump(nt, bsdf, vo.outputs["Distance"], 0.5, 0.02)

    elif kind == "fabric":         # tela de la banqueta
        n = _noise(nt, scl(P, 500 * scale), 2.0, 0.7)
        links.new(_mix(nt, n, rgba(base, 0.7), rgba(base, 1.3)), BC)
        _bump(nt, bsdf, n, 0.6, 0.01)

    elif kind == "dust":           # polvo
        n = _noise(nt, scl(P, 25 * scale), 4.0, 0.6)
        links.new(_mix(nt, n, rgba(base, 0.7), rgba(base, 1.4)), BC)
        _bump(nt, bsdf, _noise(nt, scl(P, 120 * scale), 3.0, 0.7), 0.5, 0.02)

    elif kind == "barcode":        # etiqueta blanca con codigo de barras
        wv = nodes.new("ShaderNodeTexWave")
        wv.wave_type = "BANDS"
        wv.bands_direction = "X"
        links.new(scl(P, 1.0), wv.inputs["Vector"])
        wv.inputs["Scale"].default_value = kw.get("wscale", 60.0)
        wv.inputs["Distortion"].default_value = 2.5
        links.new(_ramp(nt, wv.outputs["Fac"], [(0.0, (0.02, 0.02, 0.02, 1)), (0.5, (0.9, 0.9, 0.88, 1))],
                        "CONSTANT"), BC)


def mat(name, color, metallic=0.0, rough=0.5, emis=None, es=0.0,
        trans=0.0, coat=0.0, tex=None, **kw):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    m.diffuse_color = (color[0], color[1], color[2], 1.0)
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF") if nt else None
    if bsdf is None:
        return m

    def setin(key, value):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = value

    setin("Base Color", (color[0], color[1], color[2], 1.0))
    setin("Metallic", metallic)
    setin("Roughness", rough)
    if emis:
        setin("Emission Color", (emis[0], emis[1], emis[2], 1.0))
        setin("Emission Strength", es * EMIS)
    if trans:
        setin("Transmission Weight", trans)
    if coat:
        setin("Coat Weight", coat)
        setin("Coat Roughness", 0.12)
    if tex:
        try:
            build_tex(m, bsdf, tex, color, rough, **kw)
        except Exception as e:
            print("Textura '%s' no aplicada en %s: %s" % (tex, name, e))
    return m


def plastic(name, color):
    return mat(name, color, 0.0, 0.35, coat=0.3, tex="grain", bump=0.05)


# --- materiales base ---
MAT_FLOOR = mat("Floor", (0.020, 0.032, 0.050), 0.0, 0.10, coat=0.6, tex="floor")
MAT_FLOOR_TILE = mat("Floor Tile", (0.040, 0.058, 0.080), 0.55, 0.20, coat=0.3, tex="floor")
MAT_WALL_SIDE = mat("Wall Panel Side", (0.030, 0.045, 0.068), 0.65, 0.38, tex="wall", plane="YZX")
MAT_WALL_BACK = mat("Wall Panel Back", (0.030, 0.045, 0.068), 0.65, 0.38, tex="wall", plane="XZY")
MAT_CEILING = mat("Ceiling Panel", (0.020, 0.028, 0.040), 0.6, 0.45, tex="wall", plane="XYZ", bw=3.0, rh=3.0)
MAT_BLACK = mat("Anodized Black", (0.012, 0.016, 0.022), 0.85, 0.30, tex="grain", bump=0.06)
MAT_STEEL = mat("Steel", (0.18, 0.20, 0.23), 0.95, 0.30, tex="brushed")
MAT_ALUMINUM = mat("Aluminum", (0.45, 0.47, 0.50), 0.95, 0.28, tex="brushed")
MAT_RUBBER = mat("Rubber", (0.010, 0.011, 0.012), 0.0, 0.75, tex="grain", bump=0.15)
MAT_PCB = mat("PCB", (0.008, 0.070, 0.025), 0.1, 0.35, tex="pcb")
MAT_COPPER = mat("Copper", (0.45, 0.14, 0.05), 0.95, 0.28, tex="grain", bump=0.03)
MAT_GOLD = mat("Gold", (0.62, 0.40, 0.08), 1.0, 0.22, tex="grain", bump=0.02)
MAT_GLASS = mat("Glass", (0.60, 0.80, 0.90), 0.0, 0.04, trans=1.0)
MAT_HP = mat("HP Black Plastic", (0.014, 0.015, 0.018), 0.1, 0.38, coat=0.35, tex="grain", bump=0.12)
MAT_DUST = mat("Dust", (0.25, 0.23, 0.20), 0.0, 1.0, tex="dust")
MAT_PASTE_DRY = mat("Paste Dry", (0.28, 0.27, 0.25), 0.1, 0.9, tex="dust")
MAT_PASTE_NEW = mat("Paste New", (0.78, 0.80, 0.84), 0.6, 0.25)
MAT_HAZARD = mat("Hazard", (0.9, 0.62, 0.02), 0.0, 0.5, tex="hazard")
MAT_KEYS = mat("Keyboard Keys", (0.04, 0.045, 0.055), 0.0, 0.4, tex="keys")
MAT_PERF = mat("Perforated Metal", (0.22, 0.25, 0.30), 0.9, 0.35, tex="perf")
MAT_FABRIC = mat("Seat Fabric", (0.03, 0.08, 0.28), 0.0, 0.95, tex="fabric")
MAT_STICKER = mat("Barcode Sticker", (0.9, 0.9, 0.88), 0.0, 0.5, tex="barcode")

# pantallas / LEDs / neones (emision ya multiplicada por EMIS)
MAT_SCREEN = mat("Screen", (0.003, 0.010, 0.020), 0.2, 0.10, emis=(0.0, 0.5, 1.0), es=2.2,
                 tex="screen", plane="XZY", wscale=26.0)
MAT_SCREEN_BIG = mat("Screen Big", (0.003, 0.010, 0.020), 0.2, 0.10, emis=(0.0, 0.5, 1.0), es=2.0,
                     tex="screen", plane="XZY", wscale=5.0, nscale=1.0)
MAT_SCREEN_HUD = mat("Screen HUD", (0.003, 0.010, 0.020), 0.2, 0.10, emis=(0.0, 0.5, 1.0), es=1.6,
                     tex="screen", plane="XZY", wscale=9.0, nscale=1.5)
MAT_LCD = mat("LCD", (0.2, 0.3, 0.2), 0.0, 0.3, emis=(0.5, 0.8, 0.4), es=0.8)
MAT_CYAN = mat("LED Cyan", (0.005, 0.02, 0.03), 0.0, 0.4, emis=(0.0, 0.7, 1.0), es=6)
MAT_BLUE = mat("LED Blue", (0.005, 0.01, 0.04), 0.0, 0.4, emis=(0.02, 0.15, 1.0), es=6)
MAT_GREEN = mat("LED Green", (0.005, 0.025, 0.01), 0.0, 0.4, emis=(0.0, 1.0, 0.2), es=6)
MAT_RED = mat("LED Red", (0.04, 0.005, 0.003), 0.0, 0.4, emis=(1.0, 0.02, 0.01), es=6)
MAT_AMBER = mat("LED Amber", (0.05, 0.02, 0.003), 0.0, 0.4, emis=(1.0, 0.35, 0.02), es=6)
MAT_VIOLET = mat("LED Violet", (0.02, 0.005, 0.05), 0.0, 0.4, emis=(0.5, 0.1, 1.0), es=6)
MAT_WHITE = mat("Label White", (0.6, 0.7, 0.8), 0.0, 0.4, emis=(0.7, 0.85, 1.0), es=3.5)

# plasticos de colores
MAT_PL_RED = plastic("Plastic Red", (0.55, 0.03, 0.025))
MAT_PL_BLUE = plastic("Plastic Blue", (0.02, 0.10, 0.60))
MAT_PL_YELLOW = plastic("Plastic Yellow", (0.80, 0.55, 0.02))
MAT_PL_WHITE = plastic("Plastic White", (0.70, 0.72, 0.74))
MAT_PL_ORANGE = plastic("Plastic Orange", (0.75, 0.22, 0.02))
MAT_PL_GREEN = plastic("Plastic Green", (0.03, 0.45, 0.10))
MAT_PL_VIOLET = plastic("Plastic Violet", (0.30, 0.06, 0.55))
MAT_PL_BLACK = plastic("Plastic Black", (0.02, 0.02, 0.025))
CABLE_MATS = [MAT_PL_BLUE, MAT_PL_YELLOW, MAT_PL_RED, MAT_PL_GREEN, MAT_PL_ORANGE, MAT_PL_VIOLET]




# ============================================================
# V7 VIEWPORT / MATERIAL DISPLAY
# Fuerza colores reales en Solid y Material Preview.
# Blender puede mostrar todo blanco si el viewport esta en
# Color: SINGLE o si los objetos no tienen color de viewport.
# ============================================================

def setup_viewport_material_colors():
    # Colores de viewport por material: conserva los colores de la escena
    # incluso antes de entrar a Rendered.
    for m in bpy.data.materials:
        try:
            if m.use_nodes:
                bsdf = m.node_tree.nodes.get("Principled BSDF")
                if bsdf and "Base Color" in bsdf.inputs:
                    c = bsdf.inputs["Base Color"].default_value
                    m.diffuse_color = (c[0], c[1], c[2], 1.0)
        except Exception:
            pass

    # Cada objeto hereda el color de su material.
    for o in scene.objects:
        if o.type != "MESH" or not o.data.materials:
            continue
        try:
            m = o.data.materials[0]
            if m:
                o.color = m.diffuse_color
        except Exception:
            pass

    # Solid: mostrar MATERIAL, no SINGLE/OBJECT aleatorio.
    # Material Preview/Rendered quedan habilitados normalmente.
    try:
        for screen in bpy.data.screens:
            for space in screen.spaces:
                if space.type == "VIEW_3D":
                    sh = space.shading
                    sh.color_type = "MATERIAL"
                    sh.show_shadows = True
                    sh.show_cavity = True
                    try:
                        sh.cavity_type = "WORLD"
                        sh.curvature_ridge_factor = 1.6
                        sh.curvature_valley_factor = 1.2
                    except Exception:
                        pass
    except Exception as e:
        print("Viewport colors:", e)


setup_viewport_material_colors()


# ============================================================
# 2. GEOMETRIA SIN bpy.ops
# ============================================================

def _finish(name, bm, smooth=False):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        try:
            for p in me.polygons:
                p.use_smooth = True
        except Exception:
            pass
    return me


def mesh_box(name, h):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    for v in bm.verts:
        v.co.x *= h[0]
        v.co.y *= h[1]
        v.co.z *= h[2]
    return _finish(name, bm)


def mesh_cyl(name, r, depth, seg=48):
    """Cilindro con lados suaves y tapas planas (vertices separados)."""
    bm = bmesh.new()
    ts, bs, tc, bc = [], [], [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        x, y = r * math.cos(a), r * math.sin(a)
        ts.append(bm.verts.new((x, y, depth / 2)))
        bs.append(bm.verts.new((x, y, -depth / 2)))
        tc.append(bm.verts.new((x, y, depth / 2)))
        bc.append(bm.verts.new((x, y, -depth / 2)))
    bm.faces.new(tc)
    bm.faces.new(bc[::-1])
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new((bs[i], bs[j], ts[j], ts[i]))
    return _finish(name, bm, smooth=True)


def mesh_torus(name, R, r, seg=48, ring=12):
    bm = bmesh.new()
    grid = []
    for i in range(seg):
        u = 2 * math.pi * i / seg
        row = []
        for j in range(ring):
            v = 2 * math.pi * j / ring
            rr = R + r * math.cos(v)
            row.append(bm.verts.new((rr * math.cos(u), rr * math.sin(u), r * math.sin(v))))
        grid.append(row)
    for i in range(seg):
        for j in range(ring):
            bm.faces.new((grid[i][j], grid[(i + 1) % seg][j],
                          grid[(i + 1) % seg][(j + 1) % ring], grid[i][(j + 1) % ring]))
    return _finish(name, bm, smooth=True)


def mesh_sphere(name, r, seg=8, rings=6):
    bm = bmesh.new()
    top = bm.verts.new((0, 0, r))
    bot = bm.verts.new((0, 0, -r))
    rows = []
    for i in range(1, rings):
        th = math.pi * i / rings
        rows.append([bm.verts.new((r * math.sin(th) * math.cos(2 * math.pi * j / seg),
                                   r * math.sin(th) * math.sin(2 * math.pi * j / seg),
                                   r * math.cos(th))) for j in range(seg)])
    for j in range(seg):
        k = (j + 1) % seg
        bm.faces.new((top, rows[0][k], rows[0][j]))
        bm.faces.new((bot, rows[-1][j], rows[-1][k]))
    for i in range(len(rows) - 1):
        for j in range(seg):
            k = (j + 1) % seg
            bm.faces.new((rows[i][j], rows[i][k], rows[i + 1][k], rows[i + 1][j]))
    return _finish(name, bm, smooth=True)


def add_obj(name, data, loc, rot, col):
    o = bpy.data.objects.new(name, data)
    o.location = loc
    o.rotation_euler = rot
    col.objects.link(o)
    return o


def box(name, c, h, mat_, col, bevel=0.02, rot=(0, 0, 0)):
    me = mesh_box(name, h)
    o = add_obj(name, me, c, rot, col)
    o.data.materials.append(mat_)
    if bevel > 0:
        m = o.modifiers.new("Bevel", "BEVEL")
        m.width = bevel
        m.segments = 3
        try:                       # bordes suaves y caras planas nitidas
            m.harden_normals = True
            for p in me.polygons:
                p.use_smooth = True
        except Exception:
            pass
    return o


def cyl(name, c, r, depth, mat_, col, rot=(0, 0, 0), seg=48):
    o = add_obj(name, mesh_cyl(name, r, depth, seg), c, rot, col)
    o.data.materials.append(mat_)
    return o


def torus(name, c, R, r, mat_, col, rot=(0, 0, 0), seg=48):
    o = add_obj(name, mesh_torus(name, R, r, seg), c, rot, col)
    o.data.materials.append(mat_)
    return o


def sphere(name, c, r, mat_, col, scale=(1, 1, 1)):
    o = add_obj(name, mesh_sphere(name, r), c, (0, 0, 0), col)
    o.scale = scale
    o.data.materials.append(mat_)
    return o


def text(name, body, loc, size, mat_, col, rot=(R90, 0, 0), align="CENTER"):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.size = size
    cu.extrude = 0.008
    o = add_obj(name, cu, loc, rot, col)
    cu.materials.append(mat_)
    return o


def cable(name, pts, radius, mat_, col):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.resolution_u = 16
    cu.bevel_depth = radius
    cu.bevel_resolution = 3
    cu.use_fill_caps = True
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, co in zip(sp.bezier_points, pts):
        bp.co = co
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    o = add_obj(name, cu, (0, 0, 0), (0, 0, 0), col)
    cu.materials.append(mat_)
    return o


def empty(name, loc, col, size=0.3):
    o = bpy.data.objects.new(name, None)
    o.empty_display_type = "PLAIN_AXES"
    o.empty_display_size = size
    o.location = loc
    col.objects.link(o)
    bpy.context.view_layer.update()
    return o


def adopt(child, parent):
    """Parent que conserva la posicion actual del hijo."""
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    return child


def point_at(obj, target):
    direction = Vector(target) - Vector(obj.location)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def area_light(name, loc, energy, size, color, target):
    d = bpy.data.lights.new(name, "AREA")
    d.energy = energy * LIGHT_SCALE
    d.shape = "DISK"
    d.size = size
    d.color = color
    o = add_obj(name, d, loc, (0, 0, 0), COL_LIGHT)
    point_at(o, target)
    return o


def point_light(name, loc, energy, color, radius=0.25):
    d = bpy.data.lights.new(name, "POINT")
    d.energy = energy * LIGHT_SCALE
    d.color = color
    d.shadow_soft_size = radius
    return add_obj(name, d, loc, (0, 0, 0), COL_LIGHT)


# LEDs estaticos: V7 no usa parpadeos ni keyframes.
MAT_LED_G = [MAT_GREEN, MAT_GREEN, MAT_GREEN]
MAT_LED_A = MAT_AMBER



# ============================================================
# 3. ARQUITECTURA
# ============================================================

box("FLOOR_BASE", (0, 0, -0.2), (15, 11, 0.2), MAT_FLOOR, COL_ARCH, 0.02)
for tx in range(-12, 13, 3):
    for ty in range(-9, 10, 3):
        box("FLOOR_TILE", (tx, ty, 0.025), (1.42, 1.42, 0.025), MAT_FLOOR_TILE, COL_ARCH, 0.015)

box("LEFT_WALL", (-14.8, 0, 4.25), (0.2, 11, 4.25), MAT_WALL_SIDE, COL_ARCH, 0.03)
box("RIGHT_WALL", (14.8, 0, 4.25), (0.2, 11, 4.25), MAT_WALL_SIDE, COL_ARCH, 0.03)
box("BACK_WALL", (0, 10.8, 4.25), (14.8, 0.2, 4.25), MAT_WALL_BACK, COL_ARCH, 0.03)
box("CEILING", (0, 0, 8.35), (14.8, 11, 0.15), MAT_CEILING, COL_ARCH, 0.03)

# Zocalos y tiras LED de colores a lo largo de las paredes
box("SKIRT_LEFT", (-14.5, 0, 0.2), (0.1, 10.6, 0.15), MAT_STEEL, COL_ARCH, 0.02)
box("SKIRT_RIGHT", (14.5, 0, 0.2), (0.1, 10.6, 0.15), MAT_STEEL, COL_ARCH, 0.02)
box("SKIRT_BACK", (0, 10.5, 0.2), (14.4, 0.1, 0.15), MAT_STEEL, COL_ARCH, 0.02)
box("STRIP_LEFT", (-14.47, 0, 0.5), (0.02, 10.4, 0.03), MAT_CYAN, COL_ARCH, 0)
box("STRIP_RIGHT", (14.47, 0, 0.5), (0.02, 10.4, 0.03), MAT_AMBER, COL_ARCH, 0)
box("STRIP_BACK", (0, 10.47, 0.5), (14.2, 0.02, 0.03), MAT_VIOLET, COL_ARCH, 0)

# Ranuras verticales de luz en las paredes
for sy in (-9.0, -7.0, 8.2, 9.2):
    box("WALL_SLIT_L", (-14.55, sy, 4.2), (0.03, 0.08, 2.0), MAT_CYAN, COL_ARCH, 0)
for sy in (-9.0, -6.0, -3.0, 3.0, 6.0, 9.0):
    box("WALL_SLIT_R", (14.55, sy, 4.2), (0.03, 0.08, 2.0), MAT_AMBER, COL_ARCH, 0)

# Columnas, vigas, luminarias
for cx in (-14.1, 14.1):
    for cy in (-9.8, 0, 9.8):
        box("COLUMN", (cx, cy, 4.1), (0.16, 0.16, 4.1), MAT_STEEL, COL_ARCH, 0.025)
        box("COLUMN_BASE", (cx, cy, 0.12), (0.24, 0.24, 0.07), MAT_BLACK, COL_ARCH, 0.02)
        for k in (-1, 1):
            for j in (-1, 1):
                cyl("COLUMN_BOLT", (cx + k * 0.17, cy + j * 0.17, 0.2), 0.025, 0.04, MAT_GOLD, COL_ARCH, seg=8)
for bx in (-12, -6, 0, 6, 12):
    box("CEILING_BEAM", (bx, 0, 8.05), (0.10, 10.4, 0.12), MAT_STEEL, COL_ARCH, 0.02)
for by in (-8, -4, 0, 4, 8):
    box("CEILING_CROSSBEAM", (0, by, 7.83), (14.0, 0.08, 0.10), MAT_STEEL, COL_ARCH, 0.02)
for lx in (-9, 0, 9):
    for ly in (-6, 0, 6):
        box("LIGHT_FRAME", (lx, ly, 7.66), (2.1, 0.38, 0.06), MAT_BLACK, COL_ARCH, 0.025)
        box("LIGHT_PANEL", (lx, ly, 7.58), (1.85, 0.24, 0.018), MAT_WHITE, COL_ARCH, 0.008)
        for hx in (-1.6, 1.6):
            cyl("LIGHT_HANGER", (lx + hx, ly, 7.96), 0.03, 0.48, MAT_STEEL, COL_ARCH, seg=12)

# Rejillas de ventilacion en el techo
for vx in (-4.5, 4.5):
    for vy in (-3, 3):
        box("VENT_FRAME", (vx, vy, 8.13), (0.9, 0.9, 0.03), MAT_BLACK, COL_ARCH, 0.01)
        for k in range(7):
            box("VENT_SLAT", (vx, vy - 0.72 + k * 0.24, 8.10), (0.85, 0.04, 0.02), MAT_STEEL, COL_ARCH, 0.005)

# Conductos de aire laterales con anillos y soportes
for sx in (-1, 1):
    cyl("AIR_DUCT", (sx * 12.9, 0, 7.35), 0.4, 19.0, MAT_STEEL, COL_ARCH, rot=(R90, 0, 0), seg=48)
    for dy in range(-9, 10, 2):
        torus("DUCT_RING", (sx * 12.9, dy, 7.35), 0.40, 0.03, MAT_ALUMINUM, COL_ARCH, rot=(R90, 0, 0))
    for dy in (-6, 0, 6):
        box("DUCT_STRAP", (sx * 12.9, dy, 7.97), (0.04, 0.2, 0.22), MAT_STEEL, COL_ARCH, 0.005)

# Tuberias laterales con abrazaderas
for sx in (-1, 1):
    for pz in (5.4, 6.0, 6.6):
        cyl("PIPE", (sx * 14.45, 0, pz), 0.055, 19.0, MAT_COPPER if pz == 6.0 else MAT_STEEL,
            COL_ARCH, rot=(R90, 0, 0), seg=24)
        for py in (-6, 0, 6):
            box("PIPE_CLAMP", (sx * 14.53, py, pz), (0.07, 0.09, 0.09), MAT_STEEL, COL_ARCH, 0.01)

# Puerta (pared izquierda) con manija, teclado de acceso y carteles
box("DOOR_FRAME", (-14.52, -4.0, 2.6), (0.08, 1.55, 2.6), MAT_STEEL, COL_ARCH, 0.04)
box("DOOR_GLASS", (-14.45, -4.0, 2.65), (0.025, 1.2, 2.25), MAT_GLASS, COL_ARCH, 0.02)
box("DOOR_STATUS", (-14.45, -4.0, 5.45), (0.015, 0.9, 0.035), MAT_GREEN, COL_ARCH, 0)
cyl("DOOR_HANDLE", (-14.36, -2.75, 2.6), 0.035, 0.7, MAT_ALUMINUM, COL_ARCH, seg=16)
for hz in (2.3, 2.9):
    cyl("DOOR_HANDLE_MOUNT", (-14.40, -2.75, hz), 0.03, 0.1, MAT_ALUMINUM, COL_ARCH, rot=(0, R90, 0), seg=12)
box("DOOR_KEYPAD", (-14.50, -1.8, 2.8), (0.04, 0.22, 0.34), MAT_BLACK, COL_ARCH, 0.02)
for kr in range(4):
    for kc in range(3):
        box("KEYPAD_KEY", (-14.455, -1.95 + kc * 0.15, 2.98 - kr * 0.14), (0.01, 0.045, 0.035),
            MAT_PL_WHITE, COL_ARCH, 0.005)
box("KEYPAD_LED", (-14.455, -1.8, 3.1), (0.01, 0.15, 0.015), MAT_GREEN, COL_ARCH, 0)
text("DOOR_SIGN", "PERSONAL AUTORIZADO", (-14.36, -4.0, 5.7), 0.22, MAT_WHITE, COL_ARCH, rot=(R90, 0, R90))
box("EXIT_SIGN", (-14.52, -6.4, 4.4), (0.03, 0.75, 0.26), MAT_GREEN, COL_ARCH, 0.01)
text("EXIT_TEXT", "SALIDA", (-14.47, -6.4, 4.4), 0.3, MAT_WHITE, COL_ARCH, rot=(R90, 0, R90))

# Pizarra de contenidos del trabajo (pared izquierda)
box("BOARD_PLATE", (-14.52, 3.5, 4.5), (0.05, 3.0, 1.95), MAT_BLACK, COL_ARCH, 0.03)
for dz in (-1.93, 1.93):
    box("BOARD_EDGE", (-14.47, 3.5, 4.5 + dz), (0.012, 3.0, 0.03), MAT_CYAN, COL_ARCH, 0)
text("BOARD_TITLE", "MANTENIMIENTO PREVENTIVO", (-14.46, 3.5, 5.95), 0.34, MAT_CYAN, COL_ARCH, rot=(R90, 0, R90))
for i, line in enumerate(["1. QUE ES EL MANTENIMIENTO PREVENTIVO", "2. MANTENIMIENTO FISICO",
                          "3. MANTENIMIENTO DEL SISTEMA", "4. ALMACENAMIENTO Y DATOS",
                          "5. BUENAS PRACTICAS DE USO", "6. DIAGNOSTICO PREVENTIVO",
                          "7. SEGURIDAD (ESD)", "8. REGISTRO DEL MANTENIMIENTO"]):
    text("BOARD_LINE", line, (-14.46, 3.5, 5.35 - i * 0.36), 0.22, MAT_WHITE, COL_ARCH, rot=(R90, 0, R90))

# Cartel ESD (pared derecha) con franjas de peligro
box("ESD_PLATE", (14.52, 0, 5.0), (0.05, 3.0, 0.7), MAT_BLACK, COL_ARCH, 0.02)
for dz in (-0.62, 0.62):
    box("ESD_HAZARD", (14.47, 0, 5.0 + dz), (0.012, 3.0, 0.08), MAT_HAZARD, COL_ARCH, 0)
text("ESD_TEXT", "ZONA PROTEGIDA ESD", (14.46, 0, 5.0), 0.42, MAT_AMBER, COL_ARCH, rot=(R90, 0, -R90))

# Matafuegos y botiquin (pared derecha)
cyl("EXTINGUISHER", (14.3, -8.5, 1.5), 0.22, 1.2, MAT_PL_RED, COL_PROPS)
cyl("EXTINGUISHER_VALVE", (14.3, -8.5, 2.18), 0.08, 0.16, MAT_ALUMINUM, COL_PROPS, seg=16)
box("EXTINGUISHER_HANDLE", (14.3, -8.5, 2.3), (0.04, 0.16, 0.03), MAT_BLACK, COL_PROPS, 0.01)
cable("EXTINGUISHER_HOSE", [(14.3, -8.32, 2.15), (14.3, -8.1, 1.7), (14.3, -8.28, 1.2)], 0.025,
      MAT_PL_BLACK, COL_PROPS)
for sz in (1.1, 1.9):
    torus("EXTINGUISHER_STRAP", (14.3, -8.5, sz), 0.22, 0.02, MAT_BLACK, COL_PROPS)
box("EXTINGUISHER_SIGN", (14.52, -8.5, 3.1), (0.02, 0.35, 0.35), MAT_PL_RED, COL_PROPS, 0.01)
text("EXTINGUISHER_TEXT", "EXTINTOR", (14.48, -8.5, 3.1), 0.14, MAT_WHITE, COL_PROPS, rot=(R90, 0, -R90))
box("FIRST_AID", (14.5, -6.0, 3.5), (0.08, 0.4, 0.3), MAT_PL_WHITE, COL_PROPS, 0.03)
box("FIRST_AID_CROSS_V", (14.41, -6.0, 3.5), (0.01, 0.07, 0.2), MAT_PL_GREEN, COL_PROPS, 0)
box("FIRST_AID_CROSS_H", (14.41, -6.0, 3.5), (0.01, 0.2, 0.07), MAT_PL_GREEN, COL_PROPS, 0)


def cctv(pos, target, arm_x):
    piv = empty("CCTV_PIVOT", pos, COL_PROPS, 0.2)
    point_at(piv, target)
    bpy.context.view_layer.update()
    kids = [
        box("CCTV_BODY", (0, 0, -0.35), (0.11, 0.11, 0.35), MAT_PL_WHITE, COL_PROPS, 0.03),
        box("CCTV_HOOD", (0, 0, -0.22), (0.14, 0.14, 0.1), MAT_BLACK, COL_PROPS, 0.03),
        cyl("CCTV_LENS", (0, 0, -0.72), 0.075, 0.1, MAT_BLACK, COL_PROPS, seg=24),
        cyl("CCTV_LENS_GLASS", (0, 0, -0.775), 0.055, 0.01, MAT_BLUE, COL_PROPS, seg=24),
        cyl("CCTV_LED", (0.11, 0, -0.5), 0.02, 0.02, MAT_RED, COL_PROPS, rot=(0, R90, 0), seg=8),
    ]
    for k in kids:
        k.parent = piv
    cyl("CCTV_ARM", (arm_x, pos[1], pos[2]), 0.04, 0.6, MAT_STEEL, COL_PROPS, rot=(0, R90, 0), seg=12)


cctv((-14.0, -9.3, 7.4), (0, 0, 2.5), -14.3)
cctv((14.0, -9.3, 7.4), (0, 0, 2.5), 14.3)


# ============================================================
# 4. PLATAFORMA CENTRAL
# ============================================================

cyl("PRESENTATION_PLATFORM", (0, -0.8, 0.12), 5.1, 0.24, MAT_BLACK, COL_STAGE, seg=96)
torus("PLATFORM_OUTER_RING", (0, -0.8, 0.25), 4.75, 0.055, MAT_CYAN, COL_STAGE, seg=96)
torus("PLATFORM_INNER_RING", (0, -0.8, 0.255), 4.15, 0.025, MAT_BLUE, COL_STAGE, seg=96)
torus("PLATFORM_EDGE_RING", (0, -0.8, 0.02), 5.12, 0.03, MAT_VIOLET, COL_STAGE, seg=96)
for i, (px, py) in enumerate([(-2.3, -2.1), (2.3, -2.1), (-2.3, 0.7), (2.3, 0.7)]):
    cyl("PRESENTER_POSITION_%d" % (i + 1), (px, py, 0.26), 0.28, 0.025, MAT_CYAN, COL_STAGE)
    torus("PRESENTER_RING_%d" % (i + 1), (px, py, 0.27), 0.34, 0.012, MAT_WHITE, COL_STAGE)


# ============================================================
# 5. PANTALLA DE COMANDO (fondo)
# ============================================================

box("COMMAND_FRAME", (0, 10.45, 4.15), (8.5, 0.12, 3.0), MAT_STEEL, COL_ARCH, 0.07)
box("COMMAND_SCREEN", (0, 10.30, 4.15), (8.0, 0.025, 2.55), MAT_SCREEN_BIG, COL_ARCH, 0.03)
for z in (2.5, 3.0, 3.5, 4.0, 4.5):
    box("SCREEN_LINE", (-4.5, 10.26, z), (1.6, 0.012, 0.018), MAT_CYAN, COL_ARCH, 0)
    box("SCREEN_LINE", (2.8, 10.26, z), (1.8, 0.012, 0.018), MAT_BLUE, COL_ARCH, 0)
for k in range(6):                                  # grafico de barras en la pantalla
    box("SCREEN_BAR", (4.9 + k * 0.28, 10.26, 2.2 + 0.2 * (k % 4)), (0.09, 0.012, 0.2 + 0.2 * (k % 4)),
        MAT_GREEN if k % 2 else MAT_AMBER, COL_ARCH, 0)
text("COMMAND_TITLE", "IT SUPPORT // SYSTEM ONLINE", (0, 10.20, 5.9), 0.38, MAT_CYAN, COL_ARCH)
text("LAB_LOGO", "THE LAB", (0, 10.20, 7.55), 0.55, MAT_CYAN, COL_ARCH)
for tz in (5.5, 6.2):
    box("WALL_CABLE_TRAY", (0, 9.9, tz), (12.5, 0.18, 0.10), MAT_STEEL, COL_ARCH, 0.02)


# ============================================================
# 6. SERVIDORES (con puertas perforadas, patch panel y cables de colores)
# ============================================================

def server_rack(x, y, idx):
    for sx in (-0.85, 0.85):
        for sy in (-0.45, 0.45):
            box("RACK_FOOT", (x + sx, y + sy, 0.12), (0.10, 0.10, 0.12), MAT_RUBBER, COL_SERVER, 0.02)
    box("SERVER_RACK", (x, y, 3.15), (1.15, 0.58, 3.0), MAT_BLACK, COL_SERVER, 0.06)
    box("SERVER_FRONT", (x, y - 0.61, 3.15), (0.98, 0.025, 2.72), MAT_PERF, COL_SERVER, 0.025)
    for hx in (-0.9, 0.9):
        cyl("RACK_HANDLE", (x + hx, y - 0.68, 3.15), 0.025, 0.7, MAT_ALUMINUM, COL_SERVER, seg=12)
    box("RACK_LABEL", (x, y - 0.64, 0.5), (0.4, 0.01, 0.1), MAT_BLACK, COL_SERVER, 0.005)
    text("RACK_ID", "SRV-%02d" % (idx + 1), (x, y - 0.655, 0.5), 0.12, MAT_CYAN, COL_SERVER)
    for i in range(12):
        z = 0.85 + i * 0.42
        box("SERVER_UNIT", (x, y - 0.65, z), (0.82, 0.025, 0.135), MAT_BLACK, COL_SERVER, 0.012)
        box("SERVER_UNIT_TRIM", (x + 0.6, y - 0.668, z), (0.12, 0.006, 0.09),
            (MAT_PL_BLUE, MAT_PL_ORANGE, MAT_PL_GREEN)[(i + idx) % 3], COL_SERVER, 0)
        for j in range(3):
            led = MAT_LED_G[(i + j + idx) % 3] if j != 1 else (MAT_LED_A if (i + idx) % 4 == 0 else MAT_CYAN)
            box("SERVER_LED", (x - 0.58 + j * 0.12, y - 0.69, z), (0.018, 0.008, 0.018), led, COL_SERVER, 0)
    # patch panel superior + cables de colores
    box("PATCH_PANEL", (x, y - 0.66, 5.85), (0.85, 0.02, 0.1), MAT_BLACK, COL_SERVER, 0.008)
    for k in range(8):
        px = x - 0.7 + k * 0.2
        box("PATCH_PORT", (px, y - 0.685, 5.85), (0.05, 0.01, 0.045), MAT_RUBBER, COL_SERVER, 0.003)
        cable("PATCH_CABLE", [(px, y - 0.70, 5.80), (px + 0.04, y - 0.92, 5.66), (px, y - 0.72, 5.50)],
              0.02, CABLE_MATS[(k + idx) % 6], COL_SERVER)
    # ventiladores en el techo del rack
    for fx in (-0.55, 0.55):
        cyl("RACK_TOP_FAN", (x + fx, y, 6.2), 0.36, 0.08, MAT_BLACK, COL_SERVER)
        torus("RACK_TOP_FAN_RING", (x + fx, y, 6.25), 0.33, 0.015, MAT_CYAN, COL_SERVER)
        cyl("RACK_TOP_FAN_HUB", (x + fx, y, 6.26), 0.09, 0.03, MAT_STEEL, COL_SERVER, seg=24)
    cable("RACK_DATA_CABLE", [(x, 9.8, 5.45), (x, 9.1, 5.75), (x, 8.3, 5.3)], 0.03,
          CABLE_MATS[idx % 6], COL_SERVER)


for _i, rx in enumerate((-11.5, -8.7, 8.7, 11.5)):
    server_rack(rx, 7.7, _i)


# ============================================================
# 7. MESAS DE TRABAJO, EQUIPOS, HERRAMIENTAS Y BANQUETAS
# ============================================================

BENCH_TOP = 2.26


def workbench(x, y, s):
    for sx in (-3.1, 3.1):
        for sy in (-0.65, 0.65):
            box("BENCH_LEG", (x + sx, y + sy, 1.05), (0.11, 0.11, 1.05), MAT_BLACK, COL_PROPS, 0.025)
            box("BENCH_FOOT", (x + sx, y + sy, 0.06), (0.15, 0.15, 0.04), MAT_RUBBER, COL_PROPS, 0.01)
    box("BENCH_TOP", (x, y, 2.15), (3.5, 0.80, 0.11), MAT_STEEL, COL_PROPS, 0.07)
    box("BENCH_EDGE_LED", (x, y - 0.81, 2.15), (3.4, 0.012, 0.02), MAT_CYAN, COL_PROPS, 0)
    box("BENCH_SHELF", (x, y, 0.55), (3.0, 0.65, 0.07), MAT_BLACK, COL_PROPS, 0.025)
    box("TOOL_RAIL", (x, y + 0.68, 3.0), (3.15, 0.035, 0.045), MAT_STEEL, COL_PROPS, 0.015)
    for px in (-3.0, 3.0):
        box("RAIL_POST", (x + px, y + 0.68, 2.64), (0.04, 0.04, 0.38), MAT_STEEL, COL_PROPS, 0.01)
    # gabinete con 3 cajones de colores
    cx = x + s * 1.95
    box("BENCH_CABINET", (cx, y, 1.1), (0.9, 0.6, 0.93), MAT_BLACK, COL_PROPS, 0.03)
    for k, zc in enumerate((0.5, 1.1, 1.7)):
        box("DRAWER_FRONT", (cx, y - 0.62, zc), (0.82, 0.02, 0.27), MAT_STEEL, COL_PROPS, 0.015)
        box("DRAWER_TAG", (cx, y - 0.645, zc + 0.12), (0.3, 0.005, 0.04),
            (MAT_PL_ORANGE, MAT_PL_BLUE, MAT_PL_GREEN)[k], COL_PROPS, 0)
        cyl("DRAWER_HANDLE", (cx, y - 0.68, zc - 0.05), 0.022, 0.5, MAT_ALUMINUM, COL_PROPS,
            rot=(0, R90, 0), seg=12)
    # regleta electrica colgada del riel y cable al piso
    sx_ = x + s * 1.2
    box("POWER_STRIP", (sx_, y + 0.66, 2.86), (0.5, 0.05, 0.07), MAT_PL_WHITE, COL_PROPS, 0.015)
    for k in range(5):
        box("POWER_SOCKET", (sx_ - 0.36 + k * 0.18, y + 0.605, 2.86), (0.05, 0.008, 0.04), MAT_BLACK, COL_PROPS, 0)
    box("POWER_STRIP_LED", (sx_ + 0.45, y + 0.605, 2.9), (0.02, 0.008, 0.02), MAT_RED, COL_PROPS, 0)
    cable("POWER_STRIP_CABLE", [(sx_, y + 0.7, 2.82), (sx_, y + 0.85, 1.6), (sx_ + 0.3, y + 1.4, 0.06)],
          0.04, MAT_PL_BLACK, COL_PROPS)


def monitor(x, y, label):
    box("MONITOR_BASE", (x, y, BENCH_TOP + 0.05), (0.6, 0.3, 0.05), MAT_BLACK, COL_PROPS, 0.025)
    box("MONITOR_STAND", (x, y + 0.05, BENCH_TOP + 0.65), (0.07, 0.07, 0.6), MAT_STEEL, COL_PROPS, 0.02)
    zc = BENCH_TOP + 1.75
    box("MONITOR_FRAME", (x, y, zc), (1.3, 0.07, 0.68), MAT_BLACK, COL_PROPS, 0.05)
    box("MONITOR_DISPLAY", (x, y - 0.075, zc), (1.18, 0.018, 0.55), MAT_SCREEN, COL_PROPS, 0.025)
    box("MONITOR_LED", (x + 1.1, y - 0.085, zc - 0.62), (0.02, 0.01, 0.012), MAT_GREEN, COL_PROPS, 0)
    for k in range(5):
        box("MONITOR_BAR", (x - 0.45 + k * 0.05, y - 0.1, zc + 0.38 - k * 0.19),
            (0.55 - k * 0.07, 0.006, 0.03), (MAT_CYAN, MAT_GREEN, MAT_AMBER)[k % 3], COL_PROPS, 0)
    text("MONITOR_TEXT", label, (x + 0.55, y - 0.105, zc + 0.38), 0.12, MAT_WHITE, COL_PROPS)


def air_duster(x, y):
    z0 = BENCH_TOP
    cyl("AIRCAN_BODY", (x, y, z0 + 0.5), 0.2, 1.0, MAT_ALUMINUM, COL_PROPS, seg=32)
    cyl("AIRCAN_LABEL", (x, y, z0 + 0.5), 0.205, 0.55, MAT_PL_BLUE, COL_PROPS, seg=32)
    cyl("AIRCAN_LABEL_BAND", (x, y, z0 + 0.72), 0.207, 0.08, MAT_PL_WHITE, COL_PROPS, seg=32)
    cyl("AIRCAN_NECK", (x, y, z0 + 1.06), 0.1, 0.12, MAT_ALUMINUM, COL_PROPS, seg=24)
    box("AIRCAN_TRIGGER", (x, y - 0.06, z0 + 1.16), (0.07, 0.1, 0.04), MAT_PL_RED, COL_PROPS, 0.015)
    cyl("AIRCAN_NOZZLE", (x, y - 0.17, z0 + 1.14), 0.025, 0.22, MAT_PL_BLACK, COL_PROPS, rot=(R90, 0, 0), seg=12)


def paste_syringe(x, y):
    z = BENCH_TOP + 0.075
    cyl("SYRINGE_BODY", (x, y, z), 0.06, 0.9, MAT_GLASS, COL_PROPS, rot=(0, R90, 0), seg=20)
    cyl("SYRINGE_PASTE", (x - 0.05, y, z), 0.048, 0.65, MAT_PASTE_NEW, COL_PROPS, rot=(0, R90, 0), seg=20)
    cyl("SYRINGE_PLUNGER", (x - 0.62, y, z), 0.035, 0.35, MAT_PL_WHITE, COL_PROPS, rot=(0, R90, 0), seg=16)
    cyl("SYRINGE_PLUNGER_CAP", (x - 0.8, y, z), 0.09, 0.02, MAT_PL_WHITE, COL_PROPS, rot=(0, R90, 0), seg=20)
    cyl("SYRINGE_NEEDLE", (x + 0.56, y, z), 0.015, 0.22, MAT_STEEL, COL_PROPS, rot=(0, R90, 0), seg=10)


def ipa_bottle(x, y):
    z0 = BENCH_TOP
    cyl("IPA_BOTTLE", (x, y, z0 + 0.3), 0.16, 0.6, MAT_PL_WHITE, COL_PROPS, seg=28)
    cyl("IPA_LABEL", (x, y, z0 + 0.28), 0.165, 0.28, MAT_PL_BLUE, COL_PROPS, seg=28)
    cyl("IPA_CAP", (x, y, z0 + 0.66), 0.09, 0.14, MAT_PL_RED, COL_PROPS, seg=20)
    text("IPA_TEXT", "IPA 99%", (x, y - 0.17, z0 + 0.28), 0.085, MAT_WHITE, COL_PROPS)


def multimeter(x, y):
    z0 = BENCH_TOP
    box("MULTIMETER", (x, y, z0 + 0.07), (0.22, 0.38, 0.07), MAT_PL_YELLOW, COL_PROPS, 0.03)
    box("MULTIMETER_LCD", (x, y + 0.2, z0 + 0.145), (0.15, 0.1, 0.006), MAT_LCD, COL_PROPS, 0)
    cyl("MULTIMETER_DIAL", (x, y - 0.05, z0 + 0.15), 0.1, 0.02, MAT_PL_BLACK, COL_PROPS, seg=24)
    for k in range(3):
        cyl("MULTIMETER_JACK", (x - 0.12 + k * 0.12, y - 0.34, z0 + 0.15), 0.025, 0.012, MAT_STEEL, COL_PROPS, seg=12)


def esd_strap(x, y):
    z0 = BENCH_TOP
    torus("ESD_STRAP", (x, y, z0 + 0.03), 0.22, 0.03, MAT_PL_BLUE, COL_PROPS)
    box("ESD_CLIP", (x + 0.3, y, z0 + 0.03), (0.06, 0.04, 0.02), MAT_STEEL, COL_PROPS, 0.01)
    cable("ESD_CABLE", [(x + 0.35, y, z0 + 0.03), (x + 0.6, y + 0.12, z0 + 0.03), (x + 0.8, y - 0.05, z0 + 0.03)],
          0.02, MAT_PL_GREEN, COL_PROPS)


def bench_station(x0, s, label):
    """s = +1 mesa izquierda, -1 mesa derecha (espejo)."""
    y = -7.4
    workbench(x0, y, s)
    box("ANTI_STATIC_MAT", (x0, y - 0.15, BENCH_TOP + 0.0125), (1.5, 0.62, 0.0125), MAT_GREEN if False else MAT_PL_GREEN,
        COL_PROPS, 0.01)
    mat_top = BENCH_TOP + 0.025
    monitor(x0, y + 0.4, label)
    # teclado y mouse
    box("KEYBOARD", (x0, y - 0.3, mat_top + 0.025), (0.55, 0.2, 0.025), MAT_KEYS, COL_PROPS, 0.015)
    sphere("MOUSE", (x0 + s * 0.85, y - 0.3, mat_top + 0.04), 0.1, MAT_PL_BLACK, COL_PROPS, scale=(1.0, 1.6, 0.6))
    # osciloscopio con perillas y pantalla
    ox = x0 + s * 2.5
    box("OSCILLOSCOPE", (ox, y, BENCH_TOP + 0.45), (0.8, 0.5, 0.45), MAT_STEEL, COL_PROPS, 0.06)
    box("OSCILLOSCOPE_FACE", (ox, y - 0.505, BENCH_TOP + 0.45), (0.76, 0.01, 0.41), MAT_PL_BLACK, COL_PROPS, 0.02)
    box("OSCILLOSCOPE_SCREEN", (ox, y - 0.52, BENCH_TOP + 0.58), (0.48, 0.012, 0.28), MAT_SCREEN, COL_PROPS, 0.015)
    cable("SCOPE_SIGNAL",
          [(ox - 0.32, y - 0.54, BENCH_TOP + 0.58), (ox - 0.12, y - 0.54, BENCH_TOP + 0.76),
           (ox + 0.08, y - 0.54, BENCH_TOP + 0.46), (ox + 0.28, y - 0.54, BENCH_TOP + 0.72),
           (ox + 0.42, y - 0.54, BENCH_TOP + 0.58)], 0.012, MAT_GREEN, COL_PROPS)
    for k in range(4):
        cyl("SCOPE_KNOB", (ox - 0.45 + k * 0.3, y - 0.53, BENCH_TOP + 0.2), 0.07, 0.05, MAT_ALUMINUM, COL_PROPS,
            rot=(R90, 0, 0), seg=20)
        cyl("SCOPE_BNC", (ox - 0.45 + k * 0.3, y - 0.53, BENCH_TOP + 0.08), 0.035, 0.05, MAT_GOLD, COL_PROPS,
            rot=(R90, 0, 0), seg=12)
    # bandeja con tornillos y RAM suelta
    tx = x0 - s * 2.4
    box("COMPONENT_TRAY", (tx, y - 0.1, BENCH_TOP + 0.055), (0.72, 0.48, 0.055), MAT_ALUMINUM, COL_PROPS, 0.035)
    for i in range(4):
        cyl("SCREW", (tx - 0.35 + i * 0.23, y - 0.25, BENCH_TOP + 0.122), 0.025, 0.025, MAT_GOLD, COL_PROPS, seg=16)
    for k in range(2):
        box("LOOSE_SODIMM", (tx + 0.1, y + 0.05 - k * 0.0, BENCH_TOP + 0.13 + k * 0.025),
            (0.28, 0.1, 0.012), MAT_PCB, COL_PROPS, 0.004)
        for c in range(3):
            box("LOOSE_SODIMM_CHIP", (tx - 0.1 + c * 0.17, y + 0.05, BENCH_TOP + 0.155 + k * 0.025),
                (0.055, 0.06, 0.012), MAT_BLACK, COL_PROPS, 0.003)
    # destornilladores con punta, acostados sobre la alfombrilla
    cols = (MAT_PL_RED, MAT_PL_BLUE, MAT_PL_ORANGE)
    for i in range(3):
        sx = x0 - s * (1.5 - i * 0.3)
        cyl("TOOL_HANDLE", (sx, y - 0.55, mat_top + 0.065), 0.065, 0.42, cols[i], COL_PROPS, rot=(R90, 0, 0), seg=20)
        for g in range(3):
            torus("TOOL_GRIP", (sx, y - 0.55 - 0.12 + g * 0.12, mat_top + 0.065), 0.066, 0.008, MAT_RUBBER,
                  COL_PROPS, rot=(R90, 0, 0), seg=20)
        cyl("TOOL_SHAFT", (sx, y - 0.55 + 0.36, mat_top + 0.065), 0.018, 0.30, MAT_STEEL, COL_PROPS,
            rot=(R90, 0, 0), seg=16)
        box("TOOL_TIP", (sx, y - 0.55 + 0.53, mat_top + 0.065), (0.012, 0.02, 0.022), MAT_STEEL, COL_PROPS, 0)
    # accesorios de mantenimiento
    air_duster(x0 + s * 1.25, y - 0.35)
    paste_syringe(x0 - s * 1.9, y + 0.78)
    ipa_bottle(x0 - s * 1.0, y + 0.6)
    multimeter(x0 + s * 1.15, y + 0.42)
    esd_strap(x0 - s * 3.0, y + 0.55)
    # cable del monitor hasta el piso
    cable("BENCH_CABLE", [(x0, y + 0.5, BENCH_TOP + 0.1), (x0, y + 0.95, BENCH_TOP - 0.1),
                          (x0, y + 1.0, 1.0), (x0 + 0.2, y + 1.3, 0.06)], 0.05, MAT_PL_BLACK, COL_PROPS)
    # lineas de seguridad amarillas/negras en el piso
    for fy in (-8.75, -6.1):
        box("FLOOR_SAFETY_LINE", (x0, fy, 0.054), (3.9, 0.07, 0.004), MAT_HAZARD, COL_PROPS, 0)
    for fx in (-3.9, 3.9):
        box("FLOOR_SAFETY_LINE", (x0 + fx, -7.43, 0.054), (0.07, 1.35, 0.004), MAT_HAZARD, COL_PROPS, 0)


def stool(x, y):
    for k in range(5):
        a = 2 * math.pi * k / 5
        box("STOOL_LEG", (x + 0.33 * math.cos(a), y + 0.33 * math.sin(a), 0.22), (0.35, 0.045, 0.03),
            MAT_BLACK, COL_PROPS, 0.01, rot=(0, 0, a))
        sphere("STOOL_WHEEL", (x + 0.62 * math.cos(a), y + 0.62 * math.sin(a), 0.12), 0.07, MAT_RUBBER, COL_PROPS)
    cyl("STOOL_COLUMN", (x, y, 0.9), 0.05, 1.3, MAT_ALUMINUM, COL_PROPS, seg=20)
    cyl("STOOL_PLATE", (x, y, 1.54), 0.3, 0.04, MAT_STEEL, COL_PROPS, seg=32)
    cyl("STOOL_SEAT", (x, y, 1.62), 0.45, 0.14, MAT_FABRIC, COL_PROPS, seg=40)


bench_station(-8.8, 1, "STATION A")
bench_station(8.8, -1, "STATION B")
stool(-8.8, -9.3)
stool(8.8, -9.3)


# ============================================================
# 8. HP COMPAQ 8200 ELITE USDT  (protagonista, escala exagerada)
# ============================================================

PED = (0.0, 7.2, 0.0)
O = (0.0, 7.2, 1.4)
H = 1.1


def L(x, y, z):
    return (O[0] + x, O[1] + y, O[2] + z)


box("PEDESTAL", (PED[0], PED[1], 0.7), (3.0, 2.7, 0.7), MAT_BLACK, COL_PC, 0.05)
box("PEDESTAL_TOP_PLATE", (PED[0], PED[1], 1.38), (2.95, 2.65, 0.02), MAT_STEEL, COL_PC, 0.01)
box("PEDESTAL_GLOW_FRONT", (0, PED[1] - 2.71, 1.25), (2.9, 0.012, 0.03), MAT_CYAN, COL_PC, 0)
box("PEDESTAL_GLOW_LEFT", (-3.01, PED[1], 1.25), (0.012, 2.6, 0.03), MAT_CYAN, COL_PC, 0)
box("PEDESTAL_GLOW_RIGHT", (3.01, PED[1], 1.25), (0.012, 2.6, 0.03), MAT_CYAN, COL_PC, 0)
box("PEDESTAL_PLATE", (0, PED[1] - 2.71, 0.6), (1.2, 0.01, 0.2), MAT_BLACK, COL_PC, 0.01)
text("PEDESTAL_TEXT", "HP COMPAQ 8200 ELITE USDT", (0, PED[1] - 2.725, 0.6), 0.2, MAT_WHITE, COL_PC)

box("HP_PC_FLOOR", L(0, 0, 0.06), (2.5, 2.3, 0.06), MAT_STEEL, COL_PC, 0.02)
box("HP_PC_WALL_LEFT", L(-2.44, 0, H / 2), (0.06, 2.3, H / 2), MAT_HP, COL_PC, 0.02)
box("HP_PC_WALL_RIGHT", L(2.44, 0, H / 2), (0.06, 2.3, H / 2), MAT_HP, COL_PC, 0.02)
box("HP_PC_WALL_BACK", L(0, 2.24, H / 2), (2.38, 0.06, H / 2), MAT_HP, COL_PC, 0.02)
box("HP_PC_FRONT_PANEL", L(0, -2.23, H / 2), (2.38, 0.07, H / 2), MAT_HP, COL_PC, 0.03)
for wx in (-2.51, 2.51):                                 # ranuras de ventilacion laterales
    for k in range(9):
        box("HP_SIDE_VENT", L(wx, -1.6 + k * 0.4, 0.55), (0.012, 0.1, 0.32), MAT_BLACK, COL_PC, 0)
for sx, sy in ((-2.4, -2.2), (2.4, -2.2), (-2.4, 2.2), (2.4, 2.2)):   # tornillos de la tapa
    cyl("HP_CHASSIS_SCREW", L(sx, sy, H + 0.005), 0.07, 0.03, MAT_ALUMINUM, COL_PC, seg=16)
    box("HP_CHASSIS_SCREW_SLOT", L(sx, sy, H + 0.022), (0.05, 0.008, 0.004), MAT_BLACK, COL_PC, 0)

# frente
text("HP_LOGO", "hp", L(-1.0, -2.32, 0.80), 0.55, MAT_WHITE, COL_PC)
torus("HP_LOGO_RING", L(-1.0, -2.31, 0.80), 0.34, 0.012, MAT_WHITE, COL_PC, rot=(R90, 0, 0))
text("HP_MODEL", "COMPAQ 8200 ELITE", L(-1.0, -2.32, 0.42), 0.15, MAT_WHITE, COL_PC)
cyl("HP_POWER_BUTTON", L(-2.0, -2.31, 0.80), 0.12, 0.05, MAT_CYAN, COL_PC, rot=(R90, 0, 0), seg=32)
torus("HP_POWER_RING", L(-2.0, -2.30, 0.80), 0.15, 0.012, MAT_ALUMINUM, COL_PC, rot=(R90, 0, 0))
for ux in (-1.9, -1.55):
    box("HP_USB_FRONT", L(ux, -2.31, 0.15), (0.12, 0.02, 0.045), MAT_RUBBER, COL_PC, 0.005)
    box("HP_USB_TONGUE", L(ux, -2.325, 0.15), (0.09, 0.008, 0.012), MAT_PL_BLUE, COL_PC, 0)
for ax, ac in ((-1.1, MAT_PL_GREEN), (-0.85, MAT_PL_RED)):
    cyl("HP_AUDIO_JACK", L(ax, -2.31, 0.15), 0.05, 0.03, ac, COL_PC, rot=(R90, 0, 0), seg=20)
box("HP_ODD_FACEPLATE", L(1.425, -2.325, 0.55), (0.975, 0.02, 0.22), MAT_STEEL, COL_PC, 0.01)
box("HP_ODD_SLOT", L(1.425, -2.35, 0.60), (0.8, 0.01, 0.02), MAT_RUBBER, COL_PC, 0)
box("HP_ODD_BUTTON", L(2.2, -2.35, 0.42), (0.08, 0.01, 0.03), MAT_CYAN, COL_PC, 0)
box("HP_ODD_LED", L(0.7, -2.35, 0.42), (0.03, 0.01, 0.02), MAT_GREEN, COL_PC, 0)

# trasera
cyl("HP_DC_JACK", L(1.9, 2.33, 0.55), 0.12, 0.10, MAT_STEEL, COL_PC, rot=(R90, 0, 0), seg=24)
cyl("HP_DC_JACK_PIN", L(1.9, 2.39, 0.55), 0.04, 0.04, MAT_GOLD, COL_PC, rot=(R90, 0, 0), seg=12)
for dx in (0.7, 1.1):
    box("HP_DISPLAYPORT", L(dx, 2.31, 0.55), (0.14, 0.03, 0.07), MAT_RUBBER, COL_PC, 0.005)
for ux in (-2.0, -1.55, -1.1, -0.65):
    box("HP_USB_REAR", L(ux, 2.31, 0.30), (0.16, 0.03, 0.07), MAT_RUBBER, COL_PC, 0.005)
    box("HP_USB_REAR_TONGUE", L(ux, 2.335, 0.30), (0.12, 0.008, 0.012), MAT_PL_BLUE, COL_PC, 0)
box("HP_ETHERNET", L(-0.1, 2.31, 0.30), (0.17, 0.03, 0.14), MAT_STEEL, COL_PC, 0.005)
box("HP_ETHERNET_LED", L(-0.2, 2.345, 0.40), (0.02, 0.008, 0.02), MAT_GREEN, COL_PC, 0)
box("HP_ETHERNET_LED", L(0.0, 2.345, 0.40), (0.02, 0.008, 0.02), MAT_AMBER, COL_PC, 0)

# placa madre con componentes
box("HP_MOTHERBOARD", L(-0.975, 0.05, 0.17), (1.325, 1.95, 0.04), MAT_PCB, COL_PC, 0.02)
for sx, sy in ((-2.15, -1.75), (0.2, -1.75), (-2.15, 1.85), (0.2, 1.85)):
    cyl("HP_MB_SCREW", L(sx, sy, 0.225), 0.06, 0.03, MAT_GOLD, COL_PC, seg=16)
cap_cols = (MAT_PL_BLACK, MAT_PL_BLUE, MAT_PL_BLACK, MAT_PL_GREEN)
for k in range(8):
    cyl("HP_CAPACITOR", L(-2.15, -0.4 + k * 0.3, 0.29), 0.07, 0.16, cap_cols[k % 4], COL_PC, seg=16)
    cyl("HP_CAPACITOR_TOP", L(-2.15, -0.4 + k * 0.3, 0.375), 0.055, 0.01, MAT_ALUMINUM, COL_PC, seg=16)
cyl("HP_CMOS_BATTERY", L(-1.95, -1.0, 0.27), 0.22, 0.10, MAT_STEEL, COL_PC, seg=32)
for k in range(3):                                       # inductores y chips
    box("HP_INDUCTOR", L(-2.05, -1.75 + k * 0.17, 0.26), (0.07, 0.07, 0.05), MAT_BLACK, COL_PC, 0.01)
box("HP_BIOS_CHIP", L(-2.1, 1.3, 0.25), (0.14, 0.10, 0.03), MAT_BLACK, COL_PC, 0.005)
box("HP_IC_FRONT", L(0.1, -1.7, 0.25), (0.18, 0.14, 0.03), MAT_BLACK, COL_PC, 0.005)
box("HP_MB_STICKER", L(-0.15, -1.62, 0.222), (0.3, 0.12, 0.003), MAT_STICKER, COL_PC, 0)

# CPU, pasta, chipset
box("HP_CPU_SOCKET", L(-1.0, 0.35, 0.24), (0.42, 0.42, 0.03), MAT_STEEL, COL_PC, 0.015)
box("HP_CPU", L(-1.0, 0.35, 0.30), (0.33, 0.33, 0.03), MAT_ALUMINUM, COL_PC, 0.015)
paste_dry = box("HP_PASTE_DRY", L(-1.0, 0.35, 0.337), (0.26, 0.26, 0.006), MAT_PASTE_DRY, COL_PC, 0)
paste_new = sphere("HP_PASTE_NEW", L(-1.0, 0.35, 0.335), 0.13, MAT_PASTE_NEW, COL_PC, scale=(1, 1, 0.3))
box("HP_CHIPSET", L(0.03, 0.55, 0.28), (0.28, 0.28, 0.07), MAT_ALUMINUM, COL_PC, 0.02)
for k in range(5):
    box("HP_CHIPSET_FIN", L(0.03, 0.34 + k * 0.105, 0.37), (0.26, 0.02, 0.03), MAT_ALUMINUM, COL_PC, 0.005)

# RAM 4 GB (SO-DIMM)
box("HP_SODIMM_SLOT", L(0.03, -1.0, 0.25), (0.30, 0.70, 0.04), MAT_BLACK, COL_PC, 0.01)
box("HP_SODIMM_4GB", L(0.03, -1.0, 0.31), (0.28, 0.675, 0.015), MAT_PCB, COL_PC, 0.005)
for cy_ in (-0.45, -0.15, 0.15, 0.45):
    box("HP_SODIMM_CHIP", L(0.03, -1.0 + cy_, 0.345), (0.12, 0.10, 0.02), MAT_BLACK, COL_PC, 0.005)
box("HP_SODIMM_LABEL", L(0.03, -1.0, 0.368), (0.2, 0.3, 0.003), MAT_STICKER, COL_PC, 0)
for cy_ in (-0.5, 0.5):
    box("HP_SODIMM_CLIP", L(0.36, -1.0 + cy_, 0.29), (0.03, 0.05, 0.07), MAT_STEEL, COL_PC, 0.005)

# almacenamiento 2.5" y unidad optica
box("HP_STORAGE_2_5", L(1.45, 0.75, 0.22), (0.7, 1.0, 0.10), MAT_STEEL, COL_PC, 0.03)
box("HP_STORAGE_LABEL", L(1.45, 0.75, 0.325), (0.5, 0.7, 0.005), MAT_STICKER, COL_PC, 0, rot=(0, 0, R90))
for k in range(4):
    cyl("HP_STORAGE_SCREW", L(0.85 + (k % 2) * 1.2, -0.1 + (k // 2) * 1.7, 0.32), 0.035, 0.012,
        MAT_GOLD, COL_PC, seg=12)
box("HP_SATA_CONNECTOR", L(1.45, 1.8, 0.20), (0.35, 0.10, 0.06), MAT_BLACK, COL_PC, 0.01)
box("HP_ODD", L(1.425, -1.25, 0.27), (0.975, 0.9, 0.15), MAT_STEEL, COL_PC, 0.03)
box("HP_ODD_LABEL", L(1.425, -1.25, 0.425), (0.6, 0.5, 0.005), MAT_RUBBER, COL_PC, 0)
torus("HP_ODD_HUB", L(1.425, -1.25, 0.43), 0.18, 0.015, MAT_ALUMINUM, COL_PC)

# fuente de energia DC y cables de colores conectados
box("HP_DC_BOARD", L(1.45, 2.0, 0.20), (0.8, 0.14, 0.07), MAT_BLACK, COL_PC, 0.02)
for k in range(4):
    cyl("HP_DC_CAP", L(1.0 + k * 0.28, 2.0, 0.31), 0.06, 0.13, MAT_PL_BLACK, COL_PC, seg=16)
cable("HP_SATA_CABLE", [L(0.2, 1.3, 0.22), L(0.55, 1.5, 0.36), L(1.1, 1.8, 0.20)], 0.045, MAT_PL_RED, COL_PC)
cable("HP_POWER_CABLE", [L(0.65, 1.95, 0.20), L(0.35, 1.75, 0.40), L(0.15, 1.5, 0.23)], 0.05,
      MAT_PL_YELLOW, COL_PC)
cable("HP_ODD_CABLE", [L(0.2, -0.2, 0.22), L(0.5, -0.45, 0.34), L(1.0, -0.33, 0.30)], 0.04, MAT_PL_BLUE, COL_PC)

# DISIPADOR + VENTILADOR (conjunto que se levanta)
cooler = empty("HP_COOLER_ASSEMBLY", L(-1.0, 0.35, 0.0), COL_PC, 0.5)
parts = []
parts.append(box("HP_COOLER_PLATE", L(-1.0, 0.35, 0.42), (0.55, 0.55, 0.08), MAT_ALUMINUM, COL_PC, 0.03))
for hx in (-1.25, -0.75):
    parts.append(cyl("HP_HEATPIPE", L(hx, 1.0, 0.44), 0.055, 1.3, MAT_COPPER, COL_PC, rot=(R90, 0, 0), seg=20))
parts.append(box("HP_FIN_BASE", L(-1.0, 1.45, 0.22), (0.95, 0.45, 0.02), MAT_ALUMINUM, COL_PC, 0.01))
for i in range(14):
    parts.append(box("HP_FIN", L(-1.85 + i * 0.13, 1.45, 0.41), (0.02, 0.43, 0.20), MAT_ALUMINUM, COL_PC, 0.004))
for sx, sy in ((-0.6, -0.1), (-1.4, -0.1), (-0.6, 0.8), (-1.4, 0.8)):
    parts.append(cyl("HP_COOLER_SCREW", L(sx, sy, 0.52), 0.04, 0.03, MAT_GOLD, COL_PC, seg=12))
FAN_C = (-1.0, -0.95)
parts.append(cyl("HP_FAN_BASE", L(FAN_C[0], FAN_C[1], 0.23), 0.66, 0.04, MAT_BLACK, COL_PC))
parts.append(torus("HP_FAN_RIM", L(FAN_C[0], FAN_C[1], 0.33), 0.66, 0.05, MAT_PL_BLACK, COL_PC))
for sx, sy in ((0.5, 0.5), (-0.5, 0.5), (0.5, -0.5), (-0.5, -0.5)):
    parts.append(cyl("HP_FAN_SCREW", L(FAN_C[0] + sx, FAN_C[1] + sy, 0.255), 0.035, 0.02, MAT_GOLD, COL_PC, seg=10))
for p in parts:
    adopt(p, cooler)

rotor = empty("HP_FAN_ROTOR", L(FAN_C[0], FAN_C[1], 0.31), COL_PC, 0.4)
adopt(rotor, cooler)
bpy.context.view_layer.update()
blade_objs = [
    cyl("HP_FAN_HUB", L(FAN_C[0], FAN_C[1], 0.31), 0.16, 0.14, MAT_BLACK, COL_PC, seg=32),
    cyl("HP_FAN_CAP", L(FAN_C[0], FAN_C[1], 0.385), 0.08, 0.02, MAT_CYAN, COL_PC, seg=24),
]
NB = 11
for i in range(NB):
    a = 2 * math.pi * i / NB
    blade_objs.append(box("HP_FAN_BLADE",
                          L(FAN_C[0] + 0.40 * math.cos(a), FAN_C[1] + 0.40 * math.sin(a), 0.31),
                          (0.24, 0.045, 0.07), MAT_PL_BLUE if i == 0 else MAT_PL_BLACK, COL_PC, 0.01,
                          rot=(0, 0, a + 0.35)))
for b in blade_objs:
    adopt(b, rotor)

# TAPA abierta
hinge = empty("HP_LID_HINGE", L(0, 2.3, H), COL_PC, 0.4)
lid = box("HP_LID", L(0, 0, H + 0.04), (2.5, 2.3, 0.04), MAT_HP, COL_PC, 0.04)
adopt(lid, hinge)
for rx in (-2.1, -1.5, -0.9, -0.3, 0.3, 0.9, 1.5, 2.1):
    adopt(box("HP_LID_RIB", L(rx, 0, H - 0.04), (0.025, 2.1, 0.03), MAT_STEEL, COL_PC, 0.005), hinge)
for ry in (-1.6, 0.0, 1.6):
    adopt(box("HP_LID_CROSS", L(0, ry, H - 0.04), (2.1, 0.025, 0.03), MAT_STEEL, COL_PC, 0.005), hinge)
adopt(text("HP_LID_TEXT", "HP COMPAQ 8200 ELITE USDT", L(0, -0.6, H - 0.075), 0.2, MAT_WHITE, COL_PC,
           rot=(math.pi, 0, 0)), hinge)
adopt(box("HP_LID_STICKER", L(1.4, -1.4, H - 0.052), (0.5, 0.3, 0.003), MAT_STICKER, COL_PC, 0), hinge)

# V7: tapa fija y abierta para inspeccion del hardware.
hinge.rotation_euler = (math.radians(-100), 0, 0)

# POLVO
random.seed(8200)
dust_mesh = mesh_sphere("DUST_MESH", 0.09, 8, 6)
dust_mesh.materials.append(MAT_DUST)
dust_items = []


def add_dust(pos, parent, s):
    o = bpy.data.objects.new("HP_DUST", dust_mesh)
    o.location = pos
    o.rotation_euler = (random.uniform(0, 3), random.uniform(0, 3), random.uniform(0, 6))
    base = (s * random.uniform(0.9, 1.6), s * random.uniform(0.9, 1.6), s * random.uniform(0.45, 0.8))
    o.scale = base
    COL_PC.objects.link(o)
    if parent is not None:
        adopt(o, parent)
    dust_items.append((o, base))


for i in range(NB):
    a = 2 * math.pi * i / NB + 0.2
    add_dust(L(FAN_C[0] + 0.55 * math.cos(a), FAN_C[1] + 0.55 * math.sin(a), 0.38), rotor, 1.0)
    if i % 2 == 0:
        add_dust(L(FAN_C[0] + 0.33 * math.cos(a), FAN_C[1] + 0.33 * math.sin(a), 0.38), rotor, 0.8)
for i in range(12):
    add_dust(L(-1.8 + i * 0.14, 0.98, random.uniform(0.3, 0.58)), cooler, 1.0)
for i in range(8):
    add_dust(L(random.uniform(-1.8, -0.2), random.uniform(1.1, 1.8), 0.63), cooler, 1.0)
for i in range(14):
    dx, dy = random.uniform(-2.2, 0.2), random.uniform(-1.8, 1.9)
    if abs(dx + 1.0) < 0.75 and abs(dy + 0.95) < 0.75:
        continue
    add_dust(L(dx, dy, 0.23), None, 1.1)

for o, base in dust_items:
    o.scale = base

# V7: resultado estatico de mantenimiento; se conserva la pasta nueva
# como detalle visual y se oculta la capa de pasta seca.
paste_dry.hide_viewport = True
paste_dry.hide_render = True
paste_new.hide_viewport = False
paste_new.hide_render = False


rotor.rotation_euler = (0, 0, 0)

LABELS = [
    ("CPU", "INTEL CPU", (-1.0, 0.35, 0.52), (-3.5, 0.35, 2.7), 110),
    ("GFX", "INTEL HD GRAPHICS", (-1.0, 0.6, 0.34), (-3.5, 0.6, 2.2), 122),
    ("FAN", "COOLING FAN", (-1.0, -0.95, 0.42), (-3.5, -0.95, 1.7), 134),
    ("RAM", "4 GB RAM", (0.03, -1.0, 0.37), (0.0, -3.3, 1.9), 146),
    ("ODD", "SLIM DVD", (1.425, -1.25, 0.45), (3.5, -1.25, 1.5), 158),
    ("HDD", "STORAGE 2.5 IN", (1.45, 0.75, 0.33), (3.5, 0.75, 2.4), 170),
]
for key, body, anchor, pos, _frame_on in LABELS:
    t = text("HP_LABEL_" + key, body, L(*pos), 0.26, MAT_CYAN, COL_PC)
    end = (pos[0], pos[1], pos[2] - 0.18)
    c = cable("HP_LEADER_" + key, [L(*anchor), L(*end)], 0.012, MAT_CYAN, COL_PC)


# ============================================================
# 9. PANEL DE DIAGNOSTICO (monitor sobre pie)
# ============================================================

HX, HY = 6.9, 5.6
box("HUD_BASE", (HX, HY + 0.05, 0.05), (0.7, 0.45, 0.05), MAT_BLACK, COL_PROPS, 0.02)
box("HUD_POST", (HX, HY + 0.05, 0.95), (0.10, 0.08, 0.9), MAT_STEEL, COL_PROPS, 0.02)
box("HUD_PANEL", (HX, HY, 3.7), (2.0, 0.05, 1.8), MAT_SCREEN_HUD, COL_PROPS, 0.04)
for dz in (-1.78, 1.78):
    box("HUD_EDGE", (HX, HY - 0.055, 3.7 + dz), (2.0, 0.008, 0.02), MAT_CYAN, COL_PROPS, 0)
for dx in (-1.98, 1.98):
    box("HUD_EDGE", (HX + dx, HY - 0.055, 3.7), (0.02, 0.008, 1.8), MAT_CYAN, COL_PROPS, 0)
FY = HY - 0.07
text("HUD_TITLE", "HP COMPAQ 8200 ELITE USDT", (HX, FY, 5.05), 0.20, MAT_CYAN, COL_PROPS)
for i, line in enumerate(["WINDOWS 10 PRO", "RAM: 4 GB", "GPU: INTEL HD GRAPHICS",
                          "DISPLAY: 1280 x 1024", "DIRECTX: 12"]):
    text("HUD_LINE", line, (HX, FY, 4.55 - i * 0.35), 0.17, MAT_WHITE, COL_PROPS)

# Los numeros de temperatura son de EJEMPLO: reemplazalos por tus mediciones reales.
dirty_a = text("HUD_DIRTY_TEMP", "CPU TEMP: 78 C", (HX, FY, 2.65), 0.22, MAT_RED, COL_PROPS)
dirty_b = text("HUD_DIRTY_MSG", "! DUST DETECTED", (HX, FY, 2.25), 0.20, MAT_RED, COL_PROPS)
clean_a = text("HUD_CLEAN_TEMP", "CPU TEMP: 46 C", (HX, FY, 2.65), 0.22, MAT_GREEN, COL_PROPS)
clean_b = text("HUD_CLEAN_MSG", "SYSTEM HEALTH: OPTIMAL", (HX, FY, 2.25), 0.20, MAT_GREEN, COL_PROPS)
dirty_a.hide_viewport = True
dirty_a.hide_render = True
dirty_b.hide_viewport = True
dirty_b.hide_render = True
clean_a.hide_viewport = False
clean_a.hide_render = False
clean_b.hide_viewport = False
clean_b.hide_render = False



# ============================================================
# V7. DETALLE ESTATICO / REALISMO DEL LABORATORIO
# ============================================================
# Todo lo agregado aqui es estatico y de baja complejidad.
# Se prioriza detalle visual sobre geometria pesada.

# --- zocalos tecnicos y canales perimetrales ---
box("V7_SKIRT_BACK", (0, 10.48, 0.28), (14.45, 0.10, 0.28), MAT_BLACK, COL_ARCH, 0.02)
box("V7_SKIRT_LEFT", (-14.48, 0, 0.28), (0.10, 10.2, 0.28), MAT_BLACK, COL_ARCH, 0.02)
box("V7_SKIRT_RIGHT", (14.48, 0, 0.28), (0.10, 10.2, 0.28), MAT_BLACK, COL_ARCH, 0.02)
box("V7_TECH_CHANNEL_BACK", (0, 10.31, 0.72), (12.8, 0.035, 0.16), MAT_STEEL, COL_ARCH, 0.015)
box("V7_TECH_CHANNEL_LEFT", (-14.31, 1.0, 0.72), (0.035, 7.8, 0.16), MAT_STEEL, COL_ARCH, 0.015)
box("V7_TECH_CHANNEL_RIGHT", (14.31, 1.0, 0.72), (0.035, 7.8, 0.16), MAT_STEEL, COL_ARCH, 0.015)

# --- juntas de panel y tornilleria de mantenimiento ---
for x in (-12, -8, -4, 0, 4, 8, 12):
    box("V7_BACK_PANEL_SEAM", (x, 10.38, 4.0), (0.018, 0.012, 3.7), MAT_BLACK, COL_ARCH, 0)
    for z in (0.95, 3.9, 6.85):
        cyl("V7_BACK_PANEL_SCREW", (x, 10.35, z), 0.035, 0.018, MAT_ALUMINUM, COL_ARCH,
            rot=(R90, 0, 0), seg=12)

for y in (-7.5, -3.5, 0.5, 4.5, 8.5):
    box("V7_LEFT_PANEL_SEAM", (-14.36, y, 4.0), (0.012, 0.018, 3.7), MAT_BLACK, COL_ARCH, 0)
    box("V7_RIGHT_PANEL_SEAM", (14.36, y, 4.0), (0.012, 0.018, 3.7), MAT_BLACK, COL_ARCH, 0)

# --- pasamuros y conduits visibles ---
for y in (-5.8, -1.8, 2.2, 6.2):
    cable("V7_BACK_CONDUIT", [(13.7, y, 0.75), (13.7, y, 1.25), (13.7, y + 0.7, 1.25)],
          0.035, MAT_RUBBER, COL_ARCH)
    box("V7_CONDUIT_CLAMP", (13.7, y, 0.76), (0.08, 0.12, 0.035), MAT_STEEL, COL_ARCH, 0.01)

# --- cuatro posiciones reales de presentacion ---
for i, (x, y) in enumerate(((-2.4, -1.4), (2.4, -1.4), (-2.4, 1.7), (2.4, 1.7)), 1):
    torus("V7_PRESENTER_RING", (x, y, 0.10), 0.46, 0.018, MAT_CYAN, COL_STAGE, seg=32)
    cyl("V7_PRESENTER_CENTER", (x, y, 0.11), 0.10, 0.018, MAT_BLACK, COL_STAGE, seg=24)
    text("V7_PRESENTER_ID", "P%d" % i, (x, y - 0.50, 0.11), 0.12, MAT_WHITE, COL_STAGE)

# --- borde tecnico del escenario, sin bloquear a los presentadores ---
torus("V7_STAGE_TECH_RING", (0, -0.8, 0.16), 5.05, 0.025, MAT_STEEL, COL_STAGE, seg=64)
for a in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
    x, y = 5.05 * math.cos(a), -0.8 + 5.05 * math.sin(a)
    box("V7_STAGE_MARKER", (x, y, 0.18), (0.10, 0.10, 0.025), MAT_AMBER, COL_STAGE, 0.01)

# --- detalles funcionales en la pared de comando ---
text("V7_CMD_STATUS", "CORE / CPU 42 C   RAM 68%   STORAGE 74%   NET 1.2 Gb/s",
     (0, 10.16, 5.15), 0.18, MAT_WHITE, COL_ARCH)
text("V7_CMD_STATUS2", "RACKS 04 / ONLINE 48 NODES / ESD SAFE / BACKUP READY",
     (0, 10.16, 4.78), 0.15, MAT_GREEN, COL_ARCH)
for x in (-5.4, -1.8, 1.8, 5.4):
    box("V7_CMD_METRIC", (x, 10.13, 4.28), (1.35, 0.018, 0.025), MAT_CYAN, COL_ARCH, 0)

# --- numeracion visible de racks ---
for idx, x in enumerate((-11.5, -8.7, 8.7, 11.5), 1):
    text("V7_RACK_NUMBER", "RACK %02d" % idx, (x, 6.98, 6.65), 0.14, MAT_WHITE, COL_SERVER)
    for z in (1.15, 2.0, 2.85, 3.70, 4.55, 5.40):
        box("V7_RACK_UNIT_LED", (x - 0.82, 7.02, z), (0.018, 0.012, 0.018),
            MAT_GREEN if int(z * 10) % 2 else MAT_CYAN, COL_SERVER, 0)

# --- conectores de red extra en la zona de racks ---
for idx, x in enumerate((-11.5, -8.7, 8.7, 11.5)):
    for k in range(4):
        px = x - 0.48 + k * 0.32
        box("V7_ETH_PORT", (px, 7.01, 5.48), (0.055, 0.018, 0.045), MAT_RUBBER, COL_SERVER, 0.004)
        box("V7_ETH_LED", (px, 6.98, 5.57), (0.012, 0.008, 0.012),
            MAT_GREEN if k % 2 else MAT_AMBER, COL_SERVER, 0)

# --- microdetalle del HP 8200: pies, tornillos y etiquetas de servicio ---
for x in (-2.18, 2.18):
    for y in (-1.95, 1.95):
        cyl("V7_HP_FOOT", L(x, y, 0.10), 0.12, 0.06, MAT_RUBBER, COL_PC, seg=16)

for x in (-2.0, -0.8, 0.8, 2.0):
    box("V7_HP_SERVICE_SLOT", L(x, 1.98, 0.62), (0.035, 0.02, 0.16), MAT_BLACK, COL_PC, 0.004)

text("V7_HP_SERVICE_LABEL", "SERVICE / ESD / ASSET 8200-IT", L(0.8, -2.34, 0.22),
     0.12, MAT_CYAN, COL_PC)

# --- pequenas luces de trabajo bajo las mesas ---
for x, y in ((-8.8, 1), (8.8, -1)):
    box("V7_BENCH_UNDERLIGHT", (x, y - 0.76, 0.52), (2.5, 0.015, 0.018), MAT_CYAN, COL_PROPS, 0)


# ============================================================
# 10. LUCES (calibradas para NO quemar la imagen)
# ============================================================

area_light("KEY_LIGHT", (-4, -8, 7.2), 1100, 6, (0.80, 0.90, 1.0), (0, 0, 2.5))
area_light("FILL_LIGHT", (9, -2, 6), 650, 5, (0.20, 0.40, 1.0), (0, 0, 3))
area_light("BACK_LIGHT", (0, 3.5, 7.0), 900, 5, (0.10, 0.55, 1.0), (0, 7.2, 1.8))
area_light("HERO_KEY", (4, -1.5, 6.0), 1500, 3.5, (0.85, 0.92, 1.0), L(0, 0, 0.8))
area_light("HERO_TOP", L(0, -0.8, 4.2), 900, 2.5, (0.95, 0.97, 1.0), L(0, 0.3, 0.2))
area_light("HERO_RIM", (-6, 4.0, 5.0), 800, 3, (0.10, 0.30, 1.0), L(0, 0, 1.0))
area_light("ACCENT_AMBER", (12.5, -3, 5.0), 500, 4, (1.0, 0.45, 0.10), (7, -4, 1.5))
area_light("ACCENT_VIOLET", (0, 9.4, 3.5), 450, 4, (0.55, 0.15, 1.0), (0, 5.0, 0.5))
area_light("ACCENT_TEAL", (-12.5, -2, 5.0), 450, 4, (0.0, 0.8, 0.8), (-7, -4, 1.5))
for cy_ in (-6, 0, 6):
    area_light("CEILING_PRACTICAL", (0, cy_, 7.5), 250, 3, (0.55, 0.85, 1.0), (0, cy_, 0))
for px, py in ((-12, 7), (-9, 7), (9, 7), (12, 7)):
    point_light("SERVER_PRACTICAL", (px, py, 3.5), 65, (0.0, 0.25, 1.0))


# ============================================================
# 11. CAMARAS
# ============================================================

def static_camera(name, loc, target, lens):
    d = bpy.data.cameras.new(name)
    d.lens = lens
    o = add_obj(name, d, loc, (0, 0, 0), COL_CAMERA)
    point_at(o, target)
    return o


static_camera("CAMERA_MASTER", (17.5, -18.5, 8.5), (0, 0, 3), 28)
static_camera("CAMERA_HERO_PC", (4.5, 1.5, 4.6), L(-0.5, 0, 0.6), 40)
static_camera("CAMERA_WIDE", (0, -20, 8), (0, 1.5, 3.5), 24)

scene.camera = bpy.data.objects.get("CAMERA_MASTER") or bpy.data.objects.get("CAMERA_WIDE")


# ============================================================
# 12. MUNDO, RENDER, COLOR Y GLOW
# ============================================================

world = scene.world or bpy.data.worlds.new("LAB_WORLD")
scene.world = world
try:
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.004, 0.009, 0.020, 1)
        bg.inputs["Strength"].default_value = 0.35
except Exception as e:
    print("World:", e)

for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    try:
        scene.render.engine = engine
        break
    except Exception:
        continue

ev = scene.eevee
final = (QUALITY == "FINAL")
for attr, val in (("use_raytracing", True),
                  ("taa_render_samples", 128 if final else 32),
                  ("taa_samples", 16),
                  ("shadow_ray_count", 3 if final else 2),
                  ("shadow_step_count", 8 if final else 4)):
    try:
        setattr(ev, attr, val)
    except Exception:
        pass
try:
    ev.ray_tracing_options.resolution_scale = "1" if final else "2"
except Exception:
    pass

scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.resolution_percentage = 100 if final else 50
scene.render.image_settings.file_format = "PNG"
try:
    scene.render.image_settings.color_mode = "RGBA"
except Exception:
    pass
scene.frame_start = 1
scene.frame_end = 1

vs = scene.view_settings
try:
    vs.view_transform = VIEW_TRANSFORM
except Exception:
    pass
if VIEW_TRANSFORM == "AgX":
    for look in ("AgX - Punchy", "Punchy", "AgX - Medium High Contrast", "Medium High Contrast"):
        try:
            vs.look = look
            break
        except Exception:
            continue
try:
    vs.exposure = EXPOSURE
    vs.gamma = 1.0
except Exception:
    pass


def try_set(fn):
    try:
        fn()
        return True
    except Exception:
        return False


def setup_glow():
    """Glow suave y opcional. Si la API del compositor falla, el resto de la escena sigue igual."""
    try:
        if hasattr(scene, "compositing_node_group"):
            tree = bpy.data.node_groups.new("LAB_COMPOSITOR", "CompositorNodeTree")
            scene.compositing_node_group = tree
            tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            out = tree.nodes.new("NodeGroupOutput")
        else:
            scene.use_nodes = True
            tree = scene.node_tree
            tree.nodes.clear()
            out = tree.nodes.new("CompositorNodeComposite")
        rl = tree.nodes.new("CompositorNodeRLayers")
        gl = tree.nodes.new("CompositorNodeGlare")
        ok = try_set(lambda: setattr(gl, "glare_type", "FOG_GLOW")) or \
            try_set(lambda: setattr(gl.inputs["Type"], "default_value", "Fog Glow"))
        if ok:
            try_set(lambda: setattr(gl, "threshold", 1.2))
            try_set(lambda: setattr(gl, "mix", -0.85))                       # Blender 4.x
            try_set(lambda: setattr(gl.inputs["Strength"], "default_value", 0.25))   # Blender 5.x
            try_set(lambda: setattr(gl.inputs["Threshold"], "default_value", 1.2))
            tree.links.new(rl.outputs[0], gl.inputs[0])
            tree.links.new(gl.outputs[0], out.inputs[0])
        else:
            tree.nodes.remove(gl)
            tree.links.new(rl.outputs[0], out.inputs[0])
            print("Glow: no se pudo configurar el nodo Glare (opcional).")
    except Exception as e:
        print("Glow no aplicado (es opcional):", e)


setup_glow()


# ============================================================
# 13. ESCENA ESTATICA
# ============================================================

scene.timeline_markers.clear()
scene.frame_start = 1
scene.frame_end = 1
scene.frame_set(1)
# ============================================================
# 14. VALIDACION

# ============================================================

print("")
print("=" * 60)
print(" IT SUPPORT - THE LAB V7 STATIC  |  Blender", bpy.app.version_string)
print("=" * 60)
underground = [o.name for o in scene.objects if o.type == "MESH" and o.location.z < -0.5]
print("Objetos bajo el piso:", underground if underground else "ninguno")
required = ["HP_PC_FLOOR", "HP_MOTHERBOARD", "HP_CPU", "HP_COOLER_PLATE", "HP_SODIMM_4GB",
            "HP_STORAGE_2_5", "HP_ODD", "HP_LID", "HP_FAN_ROTOR", "HP_LID_HINGE"]
for n in required:
    print("   %-18s %s" % (n, "OK" if bpy.data.objects.get(n) else "FALTA"))
print("Objetos en escena:", len(scene.objects), "| motas de polvo:", len(dust_items))
print("Calidad:", QUALITY, "| exposicion:", EXPOSURE, "| escala de luces:", LIGHT_SCALE)
print("Camara activa:", scene.camera.name if scene.camera else "NINGUNA")
print("Animacion: DESACTIVADA | frame unico:", scene.frame_start, "-", scene.frame_end)


# ============================================================
# 15. GUARDADO (solo si el .blend ya esta guardado)
# ============================================================

try:
    if bpy.data.is_saved:
        out_path = os.path.join(os.path.dirname(bpy.data.filepath), "IT_SUPPORT_THE_LAB_V7_STATIC.blend")
        bpy.ops.wm.save_as_mainfile(filepath=out_path, copy=True)
        print("Copia guardada en:", out_path)
    else:
        print("Aviso: guarda tu .blend (Ctrl+S) para conservar la escena.")
except Exception as e:
    print("No se pudo guardar copia:", e)

print("LISTO. V7 STATIC: cambia el viewport a Rendered y usa CAMERA_MASTER / CAMERA_WIDE.")