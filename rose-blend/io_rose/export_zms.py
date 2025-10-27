from pathlib import Path
import struct
import ast

if "bpy" in locals():
    import importlib
else:
    from .rose.zms import *

import bpy
from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper


class ExportZMS(bpy.types.Operator, ExportHelper):
    bl_idname = "rose.export_zms"
    bl_label = "Export ROSE Mesh (.zms)"
    bl_options = {"PRESET"}

    filename_ext = ".ZMS"
    filter_glob = StringProperty(default="*.ZMS", options={"HIDDEN"})
    
    export_normals = BoolProperty(
        name="Export Normals",
        description="Export vertex normals",
        default=True,
    )
    
    export_colors = BoolProperty(
        name="Export Vertex Colors",
        description="Export vertex colors if available",
        default=True,
    )
    
    export_uv = BoolProperty(
        name="Export UV Coordinates",
        description="Export UV coordinates",
        default=True,
    )

    def execute(self, context):
        filepath = Path(self.filepath)
        obj = context.active_object
        
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "No mesh object selected")
            return {'CANCELLED'}
        
        # Check mesh size limits
        mesh = obj.data
        if len(mesh.vertices) > 32767:
            self.report({'ERROR'}, f"Mesh has {len(mesh.vertices)} vertices. ZMS format supports max 32,767 vertices.")
            return {'CANCELLED'}
        
        mesh.calc_loop_triangles()
        if len(mesh.loop_triangles) > 32767:
            self.report({'ERROR'}, f"Mesh has {len(mesh.loop_triangles)} triangles. ZMS format supports max 32,767 triangles.")
            return {'CANCELLED'}
        
        # Apply all transformations before export
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.transform(bm, matrix=obj.matrix_world, verts=bm.verts)
        
        # Create a temporary mesh with transformations applied
        temp_mesh = bpy.data.meshes.new("temp_export")
        bm.to_mesh(temp_mesh)
        bm.free()
        temp_mesh.calc_loop_triangles()
        
        # Restore ZMS metadata from the original object (if available)
        # NOTE: We read bones early so zms_from_mesh_data can use them if needed.
        orig_materials = None
        orig_strips = None
        orig_pool = None
        orig_bones = None

        if "zms_materials" in obj:
            try:
                orig_materials = ast.literal_eval(obj["zms_materials"])
            except Exception:
                orig_materials = None

        if "zms_strips" in obj:
            try:
                orig_strips = ast.literal_eval(obj["zms_strips"])
            except Exception:
                orig_strips = None

        if "zms_pool" in obj:
            try:
                orig_pool = obj["zms_pool"]
            except Exception:
                orig_pool = None

        if "zms_bones" in obj:
            try:
                orig_bones = ast.literal_eval(obj["zms_bones"])
            except Exception:
                orig_bones = None

        # Create ZMS from mesh (pass original object & original bones list so we can export weights/indices)
        zms = self.zms_from_mesh_data(temp_mesh, obj, orig_bones)
        
        # Apply restored metadata to the generated zms (materials/strips/pool/bones)
        if orig_materials is not None:
            try:
                zms.materials = orig_materials
            except Exception:
                pass

        if orig_strips is not None:
            try:
                zms.strips = orig_strips
            except Exception:
                pass

        if orig_pool is not None:
            try:
                zms.pool = orig_pool
            except Exception:
                pass

        if orig_bones is not None:
            try:
                zms.bones = orig_bones
            except Exception:
                pass
        
        # Clean up temp mesh
        bpy.data.meshes.remove(temp_mesh)
        
        # Validate before writing
        if len(zms.vertices) > 32767:
            self.report({'ERROR'}, f"After processing: {len(zms.vertices)} vertices (max 32,767). Mesh has UV seams that split vertices.")
            return {'CANCELLED'}
        
        # Debug logging
        print(f"=== ZMS Export Debug ===")
        print(f"Identifier: {zms.identifier}")
        print(f"Flags: {zms.flags}")
        print(f"Vertices: {len(zms.vertices)}")
        print(f"Indices: {len(zms.indices)}")
        print(f"Bones: {zms.bones}")
        print(f"Materials: {zms.materials}")
        print(f"Strips: {zms.strips}")
        print(f"Pool: {zms.pool}")
        print(f"Bounding Box Min: {zms.bounding_box_min}")
        print(f"Bounding Box Max: {zms.bounding_box_max}")
        print(f"=======================")
        
        # Write to file
        with open(str(filepath), "wb") as f:
            self.write_zms(f, zms)
        
        self.report({'INFO'}, f"Exported {filepath.name} ({len(zms.vertices)} verts, {len(zms.indices)} tris)")
        return {"FINISHED"}
    
    def zms_from_mesh_data(self, mesh, obj=None, orig_bones=None):
        """Extract ZMS data from mesh data"""
        zms = ZMS()
        zms.identifier = "ZMS0008"

        # If orig_bones provided, populate zms.bones early so consumers can map if needed
        if orig_bones is not None:
            zms.bones = list(orig_bones)
        else:
            zms.bones = []

        # Calculate flags
        zms.flags = VertexFlags.POSITION

        if self.export_normals and len(mesh.vertices) > 0:
            zms.flags |= VertexFlags.NORMAL

        if self.export_colors and len(mesh.vertex_colors) > 0:
            zms.flags |= VertexFlags.COLOR

        if self.export_uv:
            if len(mesh.uv_layers) >= 1 and len(mesh.uv_layers[0].data) > 0:
                zms.flags |= VertexFlags.UV1
            if len(mesh.uv_layers) >= 2 and len(mesh.uv_layers[1].data) > 0:
                zms.flags |= VertexFlags.UV2
            if len(mesh.uv_layers) >= 3 and len(mesh.uv_layers[2].data) > 0:
                zms.flags |= VertexFlags.UV3
            if len(mesh.uv_layers) >= 4 and len(mesh.uv_layers[3].data) > 0:
                zms.flags |= VertexFlags.UV4

        # Detect bone/weight presence on the original object (vertex groups)
        has_weights = False
        if obj is not None and hasattr(obj, "data"):
            try:
                # Any vertex with at least one group weight
                has_weights = any(len(v.groups) > 0 for v in obj.data.vertices)
            except Exception:
                has_weights = False

        if has_weights:
            zms.flags |= VertexFlags.BONE_WEIGHT
            zms.flags |= VertexFlags.BONE_INDEX

        # We need to split vertices by unique UV coordinates
        # because ZMS stores UV per vertex, not per loop
        vertex_map = {}  # Maps (vert_idx, uv1, uv2, ...) -> new_vert_idx

        # Process each triangle
        for tri in mesh.loop_triangles:
            tri_indices = []
            
            for loop_idx in tri.loops:
                loop = mesh.loops[loop_idx]
                vert_idx = loop.vertex_index
                vert = mesh.vertices[vert_idx]
                
                # Build a key with vertex index and UV coordinates
                uv_key = [vert_idx]
                
                for uv_idx in range(4):
                    if uv_idx < len(mesh.uv_layers) and len(mesh.uv_layers[uv_idx].data) > loop_idx:
                        uv = mesh.uv_layers[uv_idx].data[loop_idx].uv
                        uv_key.extend([round(uv[0], 6), round(uv[1], 6)])
                
                # Add vertex color to key if present
                if self.export_colors and len(mesh.vertex_colors) > 0:
                    color_layer = mesh.vertex_colors[0]
                    if loop_idx < len(color_layer.data):
                        color = color_layer.data[loop_idx].color
                        uv_key.extend([round(c, 6) for c in color])
                
                key = tuple(uv_key)
                
                # Check if we've seen this unique vertex before
                if key not in vertex_map:
                    # Create new vertex
                    v = Vertex()
                    v.position = Vector3(vert.co.x, vert.co.y, vert.co.z)
                    
                    if zms.normals_enabled():
                        v.normal = Vector3(vert.normal.x, vert.normal.y, vert.normal.z)
                    
                    if zms.colors_enabled():
                        if len(mesh.vertex_colors) > 0 and loop_idx < len(mesh.vertex_colors[0].data):
                            color = mesh.vertex_colors[0].data[loop_idx].color
                            v.color = Color4(color[0], color[1], color[2], 
                                           color[3] if len(color) > 3 else 1.0)
                        else:
                            v.color = Color4(1.0, 1.0, 1.0, 1.0)
                    
                    # Set UV coordinates (flip V)
                    for uv_idx in range(4):
                        if uv_idx < len(mesh.uv_layers) and len(mesh.uv_layers[uv_idx].data) > loop_idx:
                            uv = mesh.uv_layers[uv_idx].data[loop_idx].uv
                            v_coord = 1.0 - uv[1]  # Flip V coordinate
                            
                            if uv_idx == 0:
                                v.uv1 = Vector2(uv[0], v_coord)
                            elif uv_idx == 1:
                                v.uv2 = Vector2(uv[0], v_coord)
                            elif uv_idx == 2:
                                v.uv3 = Vector2(uv[0], v_coord)
                            elif uv_idx == 3:
                                v.uv4 = Vector2(uv[0], v_coord)

                    # Populate bone weights + indices from original object vertex groups (if available)
                    if zms.bones_enabled() and obj is not None:
                        groups = []
                        try:
                            orig_v = obj.data.vertices[vert_idx]
                            groups = [(g.group, g.weight) for g in orig_v.groups]
                        except Exception:
                            groups = []

                        # sort by weight desc, take top 4
                        groups.sort(key=lambda x: x[1], reverse=True)
                        top = groups[:4]
                        total = sum(w for _, w in top) or 1.0

                        # normalized weights and group indices (pad to 4)
                        weights = [w / total for _, w in top] + [0.0] * (4 - len(top))
                        indices = [int(gi) for gi, _ in top] + [0] * (4 - len(top))

                        # If orig_bones is provided and represents a direct mapping from
                        # Blender group index -> ZMS bone index, you might want to remap here.
                        # For now we keep the Blender group index as the bone index.
                        v.bone_weights = weights[:4]
                        v.bone_indices = indices[:4]

                    # Add to vertices list
                    new_idx = len(zms.vertices)
                    zms.vertices.append(v)
                    vertex_map[key] = new_idx
                
                tri_indices.append(vertex_map[key])
            
            # Add triangle indices (ensure they're valid)
            if len(tri_indices) == 3:
                zms.indices.append(Vector3(tri_indices[0], tri_indices[1], tri_indices[2]))
        
        # Calculate bounding box
        if len(zms.vertices) > 0:
            min_x = min(v.position.x for v in zms.vertices)
            min_y = min(v.position.y for v in zms.vertices)
            min_z = min(v.position.z for v in zms.vertices)
            max_x = max(v.position.x for v in zms.vertices)
            max_y = max(v.position.y for v in zms.vertices)
            max_z = max(v.position.z for v in zms.vertices)
            
            zms.bounding_box_min = Vector3(min_x, min_y, min_z)
            zms.bounding_box_max = Vector3(max_x, max_y, max_z)
        
        return zms

    def write_zms(self, f, zms):
        # Write identifier (null-terminated string)
        f.write(zms.identifier.encode('ascii') + b'\x00')
        
        # Write flags
        f.write(struct.pack("<i", zms.flags))
        
        # Write bounding box
        self.write_vector3_f32(f, zms.bounding_box_min)
        self.write_vector3_f32(f, zms.bounding_box_max)
        
        # Write bone count
        f.write(struct.pack("<h", len(zms.bones)))
        for bone in zms.bones:
            f.write(struct.pack("<h", bone))
        
        # Write vertex count
        vert_count = len(zms.vertices)
        f.write(struct.pack("<h", vert_count))
        
        # Write vertex data (each component separately)
        if zms.positions_enabled():
            for v in zms.vertices:
                self.write_vector3_f32(f, v.position)
        
        if zms.normals_enabled():
            for v in zms.vertices:
                self.write_vector3_f32(f, v.normal)
        
        if zms.colors_enabled():
            for v in zms.vertices:
                self.write_color4(f, v.color)
        
        if zms.bones_enabled():
            for v in zms.vertices:
                for w in v.bone_weights[:4]:
                    f.write(struct.pack("<f", w))
                for idx in v.bone_indices[:4]:
                    f.write(struct.pack("<h", idx))
        
        if zms.tangents_enabled():
            for v in zms.vertices:
                self.write_vector3_f32(f, v.tangent)
        
        if zms.uv1_enabled():
            for v in zms.vertices:
                self.write_vector2_f32(f, v.uv1)
        
        if zms.uv2_enabled():
            for v in zms.vertices:
                self.write_vector2_f32(f, v.uv2)
        
        if zms.uv3_enabled():
            for v in zms.vertices:
                self.write_vector2_f32(f, v.uv3)
        
        if zms.uv4_enabled():
            for v in zms.vertices:
                self.write_vector2_f32(f, v.uv4)
        
        # Write indices
        f.write(struct.pack("<h", len(zms.indices)))
        for idx in zms.indices:
            self.write_vector3_i16(f, idx)
        
        # Write materials
        f.write(struct.pack("<h", len(zms.materials)))
        for mat in zms.materials:
            f.write(struct.pack("<h", mat))
        
        # Write strips
        f.write(struct.pack("<h", len(zms.strips)))
        for strip in zms.strips:
            f.write(struct.pack("<h", strip))
        
        # Write pool (for ZMS0008)
        if zms.identifier == "ZMS0008":
            f.write(struct.pack("<h", zms.pool))
    
    def write_vector2_f32(self, f, vec):
        f.write(struct.pack("<f", vec.x))
        f.write(struct.pack("<f", vec.y))
    
    def write_vector3_f32(self, f, vec):
        f.write(struct.pack("<f", vec.x))
        f.write(struct.pack("<f", vec.y))
        f.write(struct.pack("<f", vec.z))
    
    def write_vector3_i16(self, f, vec):
        # Ensure values are within int16 range
        x = max(-32768, min(32767, int(vec.x)))
        y = max(-32768, min(32767, int(vec.y)))
        z = max(-32768, min(32767, int(vec.z)))
        f.write(struct.pack("<hhh", x, y, z))
    
    def write_color4(self, f, color):
        f.write(struct.pack("<f", color.r))
        f.write(struct.pack("<f", color.g))
        f.write(struct.pack("<f", color.b))
        f.write(struct.pack("<f", color.a))
