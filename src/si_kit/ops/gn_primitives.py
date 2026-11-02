# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Live Softimage primitives as Geometry Nodes (spec model.get-primitive, user decision 2026-11-01).

Each kind has one shared node group "SI <Kind>" whose inputs are the Softimage operator parameters. An object gets an
empty mesh + a Geometry Nodes modifier named like the Softimage operator ("Cube", ...). Parameters stay editable;
Freeze = apply the modifier. Topology matches Softimage 2015 (same point / polygon counts as the bmesh builders).
"""

import bpy

GROUP_PREFIX = "SI "
# Bumped when a group's wiring changes; an older group is renamed "_old" and rebuilt on next use.
# 2: cube subdivisions V / Base on Softimage's axes (V up = Blender Z).
GROUP_VERSION = 2
OP_NAMES = {"CUBE": "Cube", "SPHERE": "Sphere", "GRID": "Grid", "CYLINDER": "Cylinder", "CONE": "Cone",
            "TORUS": "Torus"}
LIVE = tuple(OP_NAMES)

# kind -> [(name, socket type, default, min, max)] = the Softimage parameters
PARAMS = {
    "CUBE": [("Length", 'NodeSocketFloat', 8.0, 0.0, 1e6), ("Subdivisions U", 'NodeSocketInt', 1, 1, 1000),
             ("Subdivisions V", 'NodeSocketInt', 1, 1, 1000), ("Subdivisions Base", 'NodeSocketInt', 1, 1, 1000)],
    "SPHERE": [("Radius", 'NodeSocketFloat', 4.0, 0.0, 1e6), ("Subdivisions U", 'NodeSocketInt', 8, 3, 1000),
               ("Subdivisions V", 'NodeSocketInt', 8, 2, 1000)],
    "GRID": [("Length U", 'NodeSocketFloat', 8.0, 0.0, 1e6), ("Length V", 'NodeSocketFloat', 8.0, 0.0, 1e6),
             ("Subdivisions U", 'NodeSocketInt', 8, 1, 1000), ("Subdivisions V", 'NodeSocketInt', 8, 1, 1000)],
    "CYLINDER": [("Radius", 'NodeSocketFloat', 1.0, 0.0, 1e6), ("Height", 'NodeSocketFloat', 4.0, 0.0, 1e6),
                 ("Subdivisions U", 'NodeSocketInt', 8, 3, 1000), ("Subdivisions V", 'NodeSocketInt', 2, 1, 1000),
                 ("Subdivisions Base", 'NodeSocketInt', 2, 1, 1000)],
    "CONE": [("Radius", 'NodeSocketFloat', 1.0, 0.0, 1e6), ("Height", 'NodeSocketFloat', 4.0, 0.0, 1e6),
             ("Subdivisions U", 'NodeSocketInt', 8, 3, 1000), ("Subdivisions V", 'NodeSocketInt', 2, 1, 1000),
             ("Subdivisions Base", 'NodeSocketInt', 2, 1, 1000)],
    "TORUS": [("Radius", 'NodeSocketFloat', 3.0, 0.0, 1e6), ("Section Radius", 'NodeSocketFloat', 1.0, 0.0, 1e6),
              ("Subdivisions U", 'NodeSocketInt', 8, 3, 1000), ("Subdivisions V", 'NodeSocketInt', 8, 3, 1000)],
}


def _new_group(kind):
    ng = bpy.data.node_groups.new(GROUP_PREFIX + OP_NAMES[kind], 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    for name, st, default, lo, hi in PARAMS[kind]:
        sk = ng.interface.new_socket(name, in_out='INPUT', socket_type=st)
        sk.default_value = default
        sk.min_value = lo
        sk.max_value = hi
    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")
    gin.location, gout.location = (-600, 0), (400, 0)
    I = gin.outputs

    def add1(sock):                       # subdivisions -> vertex count (subdivisions + 1)
        m = nodes.new("ShaderNodeMath")
        m.operation = 'ADD'
        m.inputs[1].default_value = 1.0
        links.new(sock, m.inputs[0])
        return m.outputs[0]

    if kind == "CUBE":
        n = nodes.new("GeometryNodeMeshCube")
        xyz = nodes.new("ShaderNodeCombineXYZ")
        for i in range(3):
            links.new(I["Length"], xyz.inputs[i])
        links.new(xyz.outputs[0], n.inputs["Size"])
        # Softimage: V runs along its up axis (Y = Blender Z), Base along its depth (Z = Blender Y)
        links.new(add1(I["Subdivisions U"]), n.inputs["Vertices X"])
        links.new(add1(I["Subdivisions Base"]), n.inputs["Vertices Y"])
        links.new(add1(I["Subdivisions V"]), n.inputs["Vertices Z"])
        out = n.outputs["Mesh"]
    elif kind == "SPHERE":
        n = nodes.new("GeometryNodeMeshUVSphere")
        links.new(I["Subdivisions U"], n.inputs["Segments"])
        links.new(I["Subdivisions V"], n.inputs["Rings"])
        links.new(I["Radius"], n.inputs["Radius"])
        out = n.outputs["Mesh"]
    elif kind == "GRID":
        n = nodes.new("GeometryNodeMeshGrid")
        links.new(I["Length U"], n.inputs["Size X"])
        links.new(I["Length V"], n.inputs["Size Y"])
        links.new(add1(I["Subdivisions U"]), n.inputs["Vertices X"])
        links.new(add1(I["Subdivisions V"]), n.inputs["Vertices Y"])
        out = n.outputs["Mesh"]
    elif kind == "CYLINDER":
        n = nodes.new("GeometryNodeMeshCylinder")
        n.fill_type = 'TRIANGLE_FAN'
        links.new(I["Subdivisions U"], n.inputs["Vertices"])
        links.new(I["Subdivisions V"], n.inputs["Side Segments"])
        links.new(I["Subdivisions Base"], n.inputs["Fill Segments"])
        links.new(I["Radius"], n.inputs["Radius"])
        links.new(I["Height"], n.inputs["Depth"])
        out = n.outputs["Mesh"]
    elif kind == "CONE":
        n = nodes.new("GeometryNodeMeshCone")
        n.fill_type = 'TRIANGLE_FAN'
        links.new(I["Subdivisions U"], n.inputs["Vertices"])
        links.new(I["Subdivisions V"], n.inputs["Side Segments"])
        links.new(I["Subdivisions Base"], n.inputs["Fill Segments"])
        n.inputs["Radius Top"].default_value = 0.0
        links.new(I["Radius"], n.inputs["Radius Bottom"])
        links.new(I["Height"], n.inputs["Depth"])
        # Blender's cone node starts at its base (z = 0 .. height); Softimage puts the base at -height/3
        m = nodes.new("ShaderNodeMath")
        m.operation = 'DIVIDE'
        m.inputs[1].default_value = -3.0
        links.new(I["Height"], m.inputs[0])
        xyz = nodes.new("ShaderNodeCombineXYZ")
        links.new(m.outputs[0], xyz.inputs[2])
        t = nodes.new("GeometryNodeTransform")
        links.new(n.outputs["Mesh"], t.inputs["Geometry"])
        links.new(xyz.outputs[0], t.inputs["Translation"])
        out = t.outputs["Geometry"]
    elif kind == "TORUS":
        ring = nodes.new("GeometryNodeCurvePrimitiveCircle")
        ring.mode = 'RADIUS'
        links.new(I["Subdivisions U"], ring.inputs["Resolution"])
        links.new(I["Radius"], ring.inputs["Radius"])
        sec = nodes.new("GeometryNodeCurvePrimitiveCircle")
        sec.mode = 'RADIUS'
        links.new(I["Subdivisions V"], sec.inputs["Resolution"])
        links.new(I["Section Radius"], sec.inputs["Radius"])
        c2m = nodes.new("GeometryNodeCurveToMesh")
        links.new(ring.outputs["Curve"], c2m.inputs["Curve"])
        links.new(sec.outputs["Curve"], c2m.inputs["Profile Curve"])
        out = c2m.outputs["Mesh"]
    links.new(out, gout.inputs["Geometry"])
    return ng


def group(kind):
    """The shared node group for this kind (created if missing or broken)."""
    ng = bpy.data.node_groups.get(GROUP_PREFIX + OP_NAMES[kind])
    if (ng is None or ng.bl_idname != 'GeometryNodeTree' or ng.get("si_kit_kind") != kind
            or ng.get("si_kit_version", 1) != GROUP_VERSION):
        if ng is not None:
            ng.name = ng.name + "_old"
        ng = _new_group(kind)
        ng["si_kit_kind"] = kind
        ng["si_kit_version"] = GROUP_VERSION
    return ng


def socket_id(ng, name):
    for it in ng.interface.items_tree:
        if getattr(it, "in_out", None) == 'INPUT' and it.name == name:
            return it.identifier
    raise KeyError(name)


def add_modifier(ob, kind):
    ng = group(kind)
    mod = ob.modifiers.new(OP_NAMES[kind], 'NODES')
    mod.node_group = ng
    return mod


def live_modifier(ob):
    """The live Softimage primitive modifier on this object, or None."""
    if ob is None or ob.type != 'MESH':
        return None
    for m in ob.modifiers:
        if m.type == 'NODES' and m.node_group is not None and m.node_group.get("si_kit_kind") in LIVE:
            return m
    return None


def _inputs(mod):
    # Blender 5.2: modifier.properties.inputs.<Socket_N>.value; older: modifier["Socket_N"]
    props = getattr(mod, "properties", None)
    return getattr(props, "inputs", None)


def get_param(mod, name):
    sid = socket_id(mod.node_group, name)
    ins = _inputs(mod)
    return getattr(ins, sid).value if ins is not None else mod[sid]


def set_param(mod, name, value):
    sid = socket_id(mod.node_group, name)
    ins = _inputs(mod)
    if ins is not None:
        getattr(ins, sid).value = value          # 5.2: each input is a struct with .value
    else:
        mod[sid] = value
    mod.id_data.update_tag()


def freeze(context, ob):
    """Apply the live primitive modifier (Softimage Freeze). Returns True if something was frozen."""
    mod = live_modifier(ob)
    if mod is None:
        return False
    with context.temp_override(object=ob, active_object=ob):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return True


def freeze_for_edit(context, ob):
    """Component editing needs a real mesh: freeze a live primitive first (user decision 2026-11-01).
    Returns the frozen operator name, or None. An undo step is pushed so the live primitive can come back."""
    mod = live_modifier(ob)
    if mod is None or context.mode != 'OBJECT':
        return None
    name = mod.name
    bpy.ops.ed.undo_push(message="Before Freeze for component editing")
    freeze(context, ob)
    bpy.ops.ed.undo_push(message="Freeze %s for component editing" % name)
    return name
