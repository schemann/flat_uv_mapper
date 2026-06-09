import bpy
import bmesh
import math
from mathutils import Vector, Matrix


# ---------------------------------------------------------------------------
# Core projection
# ---------------------------------------------------------------------------

def _axis_basis_from_normal(normal):
    """Hammer-style: pick the dominant world axis of the normal and return
    a (u_axis, v_axis) basis on that world plane."""
    n = normal
    ax, ay, az = abs(n.x), abs(n.y), abs(n.z)

    # Dominant axis -> choose U/V like classic CSG editors
    if az >= ax and az >= ay:
        # facing up/down  -> XY plane
        u_axis = Vector((1.0, 0.0, 0.0))
        v_axis = Vector((0.0, 1.0, 0.0))
    elif ax >= ay:
        # facing +/-X     -> YZ plane
        u_axis = Vector((0.0, 1.0, 0.0))
        v_axis = Vector((0.0, 0.0, 1.0))
    else:
        # facing +/-Y     -> XZ plane
        u_axis = Vector((1.0, 0.0, 0.0))
        v_axis = Vector((0.0, 0.0, 1.0))
    return u_axis, v_axis


def _face_basis_from_normal(normal):
    """Face-aligned: build a tangent basis perpendicular to the face normal."""
    n = normal.normalized()
    # pick a reference that is not parallel to the normal
    ref = Vector((0.0, 0.0, 1.0))
    if abs(n.z) > 0.999:
        ref = Vector((0.0, 1.0, 0.0))
    u_axis = n.cross(ref).normalized()
    v_axis = n.cross(u_axis).normalized()
    return u_axis, v_axis


def _basis_for_face(world_n, mode):
    if mode == 'AXIS':
        return _axis_basis_from_normal(world_n)
    return _face_basis_from_normal(world_n)


def project_faces(obj, settings):
    me = obj.data
    bm = bmesh.from_edit_mesh(me)

    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.new("UVMap")

    tile_x = settings.tile_x
    tile_y = settings.tile_y
    off_x = settings.offset_x
    off_y = settings.offset_y
    rot = math.radians(settings.rotation)
    cos_r = math.cos(rot)
    sin_r = math.sin(rot)

    mw = obj.matrix_world
    # normal transform = inverse-transpose of the 3x3
    nmat = mw.to_3x3().inverted_safe().transposed()

    sel_faces = [f for f in bm.faces if f.select]
    for f in sel_faces:
        world_n = (nmat @ f.normal).normalized()
        u_axis, v_axis = _basis_for_face(world_n, settings.mode)

        for loop in f.loops:
            world_co = mw @ loop.vert.co
            u = world_co.dot(u_axis)
            v = world_co.dot(v_axis)

            # rotation around origin in UV space
            ru = u * cos_r - v * sin_r
            rv = u * sin_r + v * cos_r

            # tile (texels per unit) + offset
            final_u = ru / tile_x + off_x
            final_v = rv / tile_y + off_y

            if settings.flip_u:
                final_u = -final_u
            if settings.flip_v:
                final_v = -final_v

            loop[uv_layer].uv = (final_u, final_v)

    bmesh.update_edit_mesh(me)
    return len(sel_faces)


def fit_faces(obj, settings):
    """Normalize projected UVs of the selection into the 0..1 range based on
    the combined bounding box, then reproject offset/tile to match."""
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.new("UVMap")

    sel_faces = [f for f in bm.faces if f.select]
    if not sel_faces:
        return 0

    mw = obj.matrix_world
    nmat = mw.to_3x3().inverted_safe().transposed()
    rot = math.radians(settings.rotation)
    cos_r, sin_r = math.cos(rot), math.sin(rot)

    # First pass: gather raw (rotated, untiled) coords to find bounds.
    raw = []  # (loop, u, v)
    min_u = min_v = float('inf')
    max_u = max_v = float('-inf')
    for f in sel_faces:
        world_n = (nmat @ f.normal).normalized()
        u_axis, v_axis = _basis_for_face(world_n, settings.mode)
        for loop in f.loops:
            wc = mw @ loop.vert.co
            u = wc.dot(u_axis)
            v = wc.dot(v_axis)
            ru = u * cos_r - v * sin_r
            rv = u * sin_r + v * cos_r
            raw.append((loop, ru, rv))
            min_u, max_u = min(min_u, ru), max(max_u, ru)
            min_v, max_v = min(min_v, rv), max(max_v, rv)

    span_u = max(max_u - min_u, 1e-9)
    span_v = max(max_v - min_v, 1e-9)
    for loop, ru, rv in raw:
        loop[uv_layer].uv = ((ru - min_u) / span_u, (rv - min_v) / span_v)

    bmesh.update_edit_mesh(me)
    return len(sel_faces)


def read_from_face(obj, settings):
    """Reconstruct tile/offset/rotation from the active face's existing UVs,
    relative to the current projection mode's basis. Periodicity of tiling
    means offset is recovered modulo 1."""
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        return False

    f = bm.faces.active
    if f is None or not f.select or len(f.loops) < 3:
        # fall back to first selected face
        f = next((x for x in bm.faces if x.select and len(x.loops) >= 3), None)
    if f is None:
        return False

    mw = obj.matrix_world
    nmat = mw.to_3x3().inverted_safe().transposed()
    world_n = (nmat @ f.normal).normalized()
    u_axis, v_axis = _basis_for_face(world_n, settings.mode)

    loops = list(f.loops)
    p0 = loops[0]
    # world-space planar coords for first 3 loops
    def planar(loop):
        wc = mw @ loop.vert.co
        return Vector((wc.dot(u_axis), wc.dot(v_axis)))

    w0, w1, w2 = planar(loops[0]), planar(loops[1]), planar(loops[2])
    uv0 = Vector(loops[0][uv_layer].uv)
    uv1 = Vector(loops[1][uv_layer].uv)
    uv2 = Vector(loops[2][uv_layer].uv)

    dw1, dw2 = w1 - w0, w2 - w0
    duv1, duv2 = uv1 - uv0, uv2 - uv0

    # Solve linear map M (2x2) with M @ dw = duv  -> [dw1 dw2] columns
    det = dw1.x * dw2.y - dw1.y * dw2.x
    if abs(det) < 1e-12:
        return False
    inv = Matrix(((dw2.y, -dw2.x), (-dw1.y, dw1.x))) * (1.0 / det)
    # columns of M = duv * inv (mapping world-delta -> uv-delta)
    m00 = duv1.x * inv[0][0] + duv2.x * inv[1][0]
    m01 = duv1.x * inv[0][1] + duv2.x * inv[1][1]
    m10 = duv1.y * inv[0][0] + duv2.y * inv[1][0]
    m11 = duv1.y * inv[0][1] + duv2.y * inv[1][1]

    # M = diag(1/Tx, 1/Ty) @ R(rot)
    #   row0 = (cos/Tx, -sin/Tx)  -> |row0| = 1/Tx
    #   row1 = (sin/Ty,  cos/Ty)  -> |row1| = 1/Ty
    scale_u = math.hypot(m00, m01)   # = 1/Tx
    scale_v = math.hypot(m10, m11)   # = 1/Ty
    if scale_u < 1e-12 or scale_v < 1e-12:
        return False
    tile_x = 1.0 / scale_u
    tile_y = 1.0 / scale_v
    # recover rotation from row0: (cos, -sin) = row0 * Tx
    rot = math.atan2(-m01 * tile_x, m00 * tile_x)

    cos_r, sin_r = math.cos(rot), math.sin(rot)
    ru = w0.x * cos_r - w0.y * sin_r
    rv = w0.x * sin_r + w0.y * cos_r
    off_x = uv0.x - ru / tile_x
    off_y = uv0.y - rv / tile_y

    settings.tile_x = tile_x
    settings.tile_y = tile_y
    settings.rotation = math.degrees(rot)
    settings.offset_x = off_x % 1.0
    settings.offset_y = off_y % 1.0
    settings.flip_u = False
    settings.flip_v = False
    return True
# ---------------------------------------------------------------------------

def _live_update(self, context):
    if not self.live_apply:
        return
    obj = context.edit_object
    if obj and obj.type == 'MESH':
        project_faces(obj, self)


class FlatUVSettings(bpy.types.PropertyGroup):
    mode: bpy.props.EnumProperty(
        name="Projection",
        items=[
            ('AXIS', "Axis Aligned", "World-axis planar projection (Hammer/CSG style)"),
            ('FACE', "Face Aligned", "Project along the face normal"),
        ],
        default='AXIS',
        update=_live_update,
    )
    tile_x: bpy.props.FloatProperty(
        name="Tile X", default=1.0, min=0.0001, soft_min=0.01, soft_max=10.0,
        update=_live_update)
    tile_y: bpy.props.FloatProperty(
        name="Tile Y", default=1.0, min=0.0001, soft_min=0.01, soft_max=10.0,
        update=_live_update)
    offset_x: bpy.props.FloatProperty(
        name="Offset X", default=0.0, soft_min=-10.0, soft_max=10.0,
        update=_live_update)
    offset_y: bpy.props.FloatProperty(
        name="Offset Y", default=0.0, soft_min=-10.0, soft_max=10.0,
        update=_live_update)
    rotation: bpy.props.FloatProperty(
        name="Rotation", default=0.0, soft_min=-360.0, soft_max=360.0,
        subtype='ANGLE' if False else 'NONE', unit='NONE',
        update=_live_update)
    flip_u: bpy.props.BoolProperty(
        name="Flip U", default=False,
        update=_live_update)
    flip_v: bpy.props.BoolProperty(
        name="Flip V", default=False,
        update=_live_update)
    live_apply: bpy.props.BoolProperty(
        name="Live Apply", default=True,
        description="Reproject automatically when values change")


# ---------------------------------------------------------------------------
# Clipboard for Copy/Paste
# ---------------------------------------------------------------------------
_uv_clipboard = {
    'mode': 'AXIS',
    'tile_x': 1.0,
    'tile_y': 1.0,
    'offset_x': 0.0,
    'offset_y': 0.0,
    'rotation': 0.0,
    'flip_u': False,
    'flip_v': False,
}


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class FLATUV_OT_apply(bpy.types.Operator):
    bl_idname = "flatuv.apply"
    bl_label = "Apply Flat UV"
    bl_description = "Project the current settings onto the selected faces"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def execute(self, context):
        s = context.scene.flat_uv_settings
        n = project_faces(context.edit_object, s)
        if n == 0:
            self.report({'WARNING'}, "No faces selected")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Projected {n} face(s)")
        return {'FINISHED'}


class FLATUV_OT_reset(bpy.types.Operator):
    bl_idname = "flatuv.reset"
    bl_label = "Reset"
    bl_description = "Reset offset and rotation to defaults"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.flat_uv_settings
        s.offset_x = 0.0
        s.offset_y = 0.0
        s.rotation = 0.0
        s.tile_x = 1.0
        s.tile_y = 1.0
        s.flip_u = False
        s.flip_v = False
        return {'FINISHED'}


class FLATUV_OT_fit(bpy.types.Operator):
    bl_idname = "flatuv.fit"
    bl_label = "Fit to Face"
    bl_description = "Normalize the projected UVs of the selection into 0..1"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def execute(self, context):
        s = context.scene.flat_uv_settings
        n = fit_faces(context.edit_object, s)
        if n == 0:
            self.report({'WARNING'}, "No faces selected")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Fitted {n} face(s) to 0..1")
        return {'FINISHED'}


class FLATUV_OT_pick(bpy.types.Operator):
    bl_idname = "flatuv.pick"
    bl_label = "Pick From Face"
    bl_description = ("Read tile, offset and rotation from the active face's "
                      "current UVs (offset recovered modulo 1)")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def execute(self, context):
        s = context.scene.flat_uv_settings
        # avoid live-apply firing mid-read
        was_live = s.live_apply
        s["live_apply"] = False
        ok = read_from_face(context.edit_object, s)
        s["live_apply"] = was_live
        if not ok:
            self.report({'WARNING'}, "Could not read UVs from active face")
            return {'CANCELLED'}
        self.report({'INFO'}, "Picked UV parameters from active face")
        return {'FINISHED'}


class FLATUV_OT_copy(bpy.types.Operator):
    bl_idname = "flatuv.copy"
    bl_label = "Copy UVs"
    bl_description = "Copy UV settings from the active face (or current settings)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def execute(self, context):
        s = context.scene.flat_uv_settings
        was_live = s.live_apply
        s["live_apply"] = False
        # Try to pick from face first
        read_from_face(context.edit_object, s)
        s["live_apply"] = was_live

        _uv_clipboard['mode'] = s.mode
        _uv_clipboard['tile_x'] = s.tile_x
        _uv_clipboard['tile_y'] = s.tile_y
        _uv_clipboard['offset_x'] = s.offset_x
        _uv_clipboard['offset_y'] = s.offset_y
        _uv_clipboard['rotation'] = s.rotation
        _uv_clipboard['flip_u'] = s.flip_u
        _uv_clipboard['flip_v'] = s.flip_v

        self.report({'INFO'}, "Copied UV settings to clipboard")
        return {'FINISHED'}


class FLATUV_OT_paste(bpy.types.Operator):
    bl_idname = "flatuv.paste"
    bl_label = "Paste UVs"
    bl_description = "Paste copied UV settings to selected faces"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def execute(self, context):
        s = context.scene.flat_uv_settings
        was_live = s.live_apply
        s["live_apply"] = False

        s.mode = _uv_clipboard['mode']
        s.tile_x = _uv_clipboard['tile_x']
        s.tile_y = _uv_clipboard['tile_y']
        s.offset_x = _uv_clipboard['offset_x']
        s.offset_y = _uv_clipboard['offset_y']
        s.rotation = _uv_clipboard['rotation']
        s.flip_u = _uv_clipboard['flip_u']
        s.flip_v = _uv_clipboard['flip_v']

        s["live_apply"] = was_live

        # Apply immediately
        n = project_faces(context.edit_object, s)
        self.report({'INFO'}, f"Pasted UV settings to {n} face(s)")
        return {'FINISHED'}


class FLATUV_OT_aspect(bpy.types.Operator):
    bl_idname = "flatuv.aspect"
    bl_label = "Aspect Ratio"
    bl_description = "Adjust Tile Y to match the aspect ratio of the active material's texture"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def execute(self, context):
        obj = context.edit_object
        if not obj.active_material or not obj.active_material.node_tree:
            self.report({'WARNING'}, "No active material with nodes found")
            return {'CANCELLED'}

        img_node = None
        for node in obj.active_material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                img_node = node
                break

        if not img_node:
            self.report({'WARNING'}, "No Image Texture node found in the active material")
            return {'CANCELLED'}

        width, height = img_node.image.size
        if width == 0 or height == 0:
            self.report({'WARNING'}, "Image has invalid size")
            return {'CANCELLED'}

        s = context.scene.flat_uv_settings
        ratio = width / height
        s.tile_y = s.tile_x / ratio

        self.report({'INFO'}, f"Adjusted Aspect Ratio ({width}x{height})")
        return {'FINISHED'}


class FLATUV_OT_justify(bpy.types.Operator):
    bl_idname = "flatuv.justify"
    bl_label = "Justify UVs"
    bl_description = "Align UV bounds to boundaries (Top, Bottom, Left, Right, Center)"
    bl_options = {'REGISTER', 'UNDO'}

    align: bpy.props.EnumProperty(
        items=[
            ('TOP', "Top", "Align to top edge"),
            ('BOTTOM', "Bottom", "Align to bottom edge"),
            ('LEFT', "Left", "Align to left edge"),
            ('RIGHT', "Right", "Align to right edge"),
            ('CENTER', "Center", "Center UVs"),
            ('FIT_X', "Fit X", "Fit horizontally"),
            ('FIT_Y', "Fit Y", "Fit vertically"),
        ]
    )

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def execute(self, context):
        obj = context.edit_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        sel_faces = [f for f in bm.faces if f.select]
        if not sel_faces:
            return {'CANCELLED'}

        s = context.scene.flat_uv_settings
        mw = obj.matrix_world
        nmat = mw.to_3x3().inverted_safe().transposed()
        rot = math.radians(s.rotation)
        cos_r, sin_r = math.cos(rot), math.sin(rot)

        min_ru = min_rv = float('inf')
        max_ru = max_rv = float('-inf')

        for f in sel_faces:
            world_n = (nmat @ f.normal).normalized()
            u_axis, v_axis = _basis_for_face(world_n, s.mode)
            for loop in f.loops:
                wc = mw @ loop.vert.co
                u = wc.dot(u_axis)
                v = wc.dot(v_axis)
                ru = u * cos_r - v * sin_r
                rv = u * sin_r + v * cos_r
                min_ru, max_ru = min(min_ru, ru), max(max_ru, ru)
                min_rv, max_rv = min(min_rv, rv), max(max_rv, rv)

        span_ru = max(max_ru - min_ru, 1e-9)
        span_rv = max(max_rv - min_rv, 1e-9)

        was_live = s.live_apply
        s["live_apply"] = False

        if self.align == 'LEFT':
            s.offset_x = -min_ru / s.tile_x
        elif self.align == 'RIGHT':
            s.offset_x = 1.0 - max_ru / s.tile_x
        elif self.align == 'BOTTOM':
            s.offset_y = -min_rv / s.tile_y
        elif self.align == 'TOP':
            s.offset_y = 1.0 - max_rv / s.tile_y
        elif self.align == 'CENTER':
            s.offset_x = 0.5 - (max_ru + min_ru) / (2.0 * s.tile_x)
            s.offset_y = 0.5 - (max_rv + min_rv) / (2.0 * s.tile_y)
        elif self.align == 'FIT_X':
            s.tile_x = span_ru
            s.offset_x = -min_ru / s.tile_x
        elif self.align == 'FIT_Y':
            s.tile_y = span_rv
            s.offset_y = -min_rv / s.tile_y

        s["live_apply"] = was_live
        project_faces(obj, s)

        return {'FINISHED'}


class FLATUV_OT_align_edge(bpy.types.Operator):
    bl_idname = "flatuv.align_edge"
    bl_label = "Align Rotation to Edge"
    bl_description = "Align UV rotation to the selected edge"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def execute(self, context):
        obj = context.edit_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)

        edges = [e for e in bm.edges if e.select]
        if not edges:
            self.report({'WARNING'}, "No edge selected")
            return {'CANCELLED'}

        e = edges[0]
        s = context.scene.flat_uv_settings
        mw = obj.matrix_world
        nmat = mw.to_3x3().inverted_safe().transposed()

        faces = [f for f in e.link_faces if f.select]
        if not faces:
            faces = e.link_faces
        if not faces:
            return {'CANCELLED'}
        f = faces[0]

        world_n = (nmat @ f.normal).normalized()
        u_axis, v_axis = _basis_for_face(world_n, s.mode)

        wc1 = mw @ e.verts[0].co
        wc2 = mw @ e.verts[1].co
        vec = (wc2 - wc1).normalized()

        du = vec.dot(u_axis)
        dv = vec.dot(v_axis)

        angle = math.atan2(dv, du)

        was_live = s.live_apply
        s["live_apply"] = False

        s.rotation = math.degrees(angle)

        s["live_apply"] = was_live
        project_faces(obj, s)

        self.report({'INFO'}, "Aligned rotation to edge")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class FLATUV_PT_panel(bpy.types.Panel):
    bl_label = "Flat UV Mapper"
    bl_idname = "FLATUV_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Flat UV"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        s = context.scene.flat_uv_settings

        layout.prop(s, "mode", expand=True)

        col = layout.column(align=True)
        col.label(text="Tile (units per repeat):")
        row = col.row(align=True)
        row.prop(s, "tile_x", text="X")
        row.prop(s, "tile_y", text="Y")
        
        layout.operator("flatuv.aspect", icon='IMAGE_DATA')

        col = layout.column(align=True)
        col.label(text="Offset:")
        row = col.row(align=True)
        row.prop(s, "offset_x", text="X")
        row.prop(s, "offset_y", text="Y")

        row = layout.row(align=True)
        row.prop(s, "rotation", text="Rotation (deg)")
        row.operator("flatuv.align_edge", text="", icon='EDGESEL')

        col = layout.column(align=True)
        col.label(text="Justify:")
        row = col.row(align=True)
        row.operator("flatuv.justify", text="L").align = 'LEFT'
        row.operator("flatuv.justify", text="C").align = 'CENTER'
        row.operator("flatuv.justify", text="R").align = 'RIGHT'
        row.operator("flatuv.justify", text="T").align = 'TOP'
        row.operator("flatuv.justify", text="B").align = 'BOTTOM'
        row = col.row(align=True)
        row.operator("flatuv.justify", text="Fit X").align = 'FIT_X'
        row.operator("flatuv.justify", text="Fit Y").align = 'FIT_Y'

        col = layout.column(align=True)
        col.label(text="Flip:")
        row = col.row(align=True)
        row.prop(s, "flip_u", toggle=True)
        row.prop(s, "flip_v", toggle=True)

        layout.separator()
        layout.prop(s, "live_apply")
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("flatuv.apply", icon='UV')

        row = layout.row(align=True)
        row.operator("flatuv.fit", icon='FULLSCREEN_ENTER')
        row.operator("flatuv.pick", icon='EYEDROPPER')

        row = layout.row(align=True)
        row.operator("flatuv.copy", icon='COPYDOWN')
        row.operator("flatuv.paste", icon='PASTEDOWN')
        
        layout.operator("flatuv.reset", icon='LOOP_BACK')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    FlatUVSettings,
    FLATUV_OT_apply,
    FLATUV_OT_fit,
    FLATUV_OT_pick,
    FLATUV_OT_copy,
    FLATUV_OT_paste,
    FLATUV_OT_aspect,
    FLATUV_OT_justify,
    FLATUV_OT_align_edge,
    FLATUV_OT_reset,
    FLATUV_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.flat_uv_settings = bpy.props.PointerProperty(type=FlatUVSettings)


def unregister():
    del bpy.types.Scene.flat_uv_settings
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
