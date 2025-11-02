from pathlib import Path

if "bpy" in locals():
    import importlib
else:
    from .rose.zms import *

import bpy
from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper


class ImportZMS(bpy.types.Operator, ImportHelper):
    bl_idname = "rose.import_zms"
    bl_label = "ROSE Mesh (.zms)"
    bl_options = {"PRESET"}

    filename_ext = ".ZMS"
    filter_glob = StringProperty(default="*.ZMS", options={"HIDDEN"})
    load_texture = BoolProperty(
        name = "Load texture",
        description = ( "Automatically detect and load a texture if "
                        "one can be found (uses file name)"),
        default=True,
    )

    texture_extensions = [".DDS", ".dds", ".PNG", ".png"]

    def execute(self, context):
        filepath = Path(self.filepath)
        filename = filepath.stem
        
        # Create a report function wrapper
        def report_wrapper(level, message):
            self.report({level}, message)
        
        try:
            zms = ZMS(str(filepath), report_func=report_wrapper)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load ZMS file: {str(e)}")
            return {'CANCELLED'}

        # Debug logging
        self.report({'INFO'}, f"=== ZMS Import Debug ===")
        self.report({'INFO'}, f"Identifier: {zms.identifier}")
        self.report({'INFO'}, f"Version: {zms.version}")
        self.report({'INFO'}, f"Flags: {zms.flags}")
        self.report({'INFO'}, f"Vertices: {len(zms.vertices)}")
        self.report({'INFO'}, f"Indices: {len(zms.indices)}")
        self.report({'INFO'}, f"Bones: {zms.bones}")
        self.report({'INFO'}, f"Materials: {zms.materials}")
        self.report({'INFO'}, f"Strips: {zms.strips}")
        self.report({'INFO'}, f"Pool: {zms.pool}")
        self.report({'INFO'}, f"Bounding Box Min: {zms.bounding_box_min}")
        self.report({'INFO'}, f"Bounding Box Max: {zms.bounding_box_max}")
        self.report({'INFO'}, f"=======================")

        mesh = self.mesh_from_zms(zms, filename)

        obj = bpy.data.objects.new(filename, mesh)

        # --- Create vertex groups and assign weights so exporter can detect bone data ---
        # Create one Blender vertex group per ZMS bone entry (order matters)
        # bone_indices in C++ is std::vector<uint16> - each entry is a bone ID
        if len(zms.bones) > 0:
            for i, bone_id in enumerate(zms.bones):
                # name groups deterministically; exporter relies on obj["zms_bones"] to restore mapping
                # The group index corresponds to the index in the bones array
                obj.vertex_groups.new(name=f"zms_bone_{i}")

            # Assign weights per vertex. mesh.from_pydata created vertices in same order as zms.vertices
            for vi, v in enumerate(zms.vertices):
                # bone_weights is vec4 (4x float)
                # bone_indices now contain the actual bone IDs (uint16 values after mapping)
                for gi in range(4):
                    try:
                        weight = v.bone_weights[gi]
                        bone_id = int(v.bone_indices[gi])
                    except (IndexError, ValueError):
                        continue

                    if weight and weight > 0.0:
                        # Find which group index corresponds to this bone_id
                        # The bone_id should match zms.bones[group_index]
                        try:
                            group_index = zms.bones.index(bone_id)
                            if 0 <= group_index < len(obj.vertex_groups):
                                obj.vertex_groups[group_index].add([vi], weight, 'REPLACE')
                        except ValueError:
                            # bone_id not in bones list, skip
                            pass

        # Store ZMS metadata on the object for later export
        # These need to be stored so the exporter can recreate the exact file
        obj["zms_version"] = zms.version
        obj["zms_identifier"] = zms.identifier
        obj["zms_materials"] = str(zms.materials)  # uint16 array (matid_numfaces)
        obj["zms_strips"] = str(zms.strips)  # uint16 array (ibuf_strip)
        obj["zms_pool"] = zms.pool  # uint16 pool type
        obj["zms_bones"] = str(zms.bones)  # std::vector<uint16> bone_indices

        scene = context.scene
        context.collection.objects.link(obj)

        self.report({'INFO'}, f"Imported {filename} (v{zms.version}, {len(zms.vertices)} verts, {len(zms.indices)} tris)")
        return {"FINISHED"}

    def mesh_from_zms(self, zms, filename):
        mesh = bpy.data.meshes.new(filename)

        #-- Vertices (vec3 positions)
        verts = []
        for v in zms.vertices:
            verts.append((v.position.x, v.position.y, v.position.z))

        #-- Faces (usvec3 = 3x uint16 indices)
        faces = []
        for i in zms.indices:
            faces.append((int(i.x), int(i.y), int(i.z)))

        #-- Mesh
        mesh.from_pydata(verts, [], faces)

        #-- UV (vec2 coordinates, up to 4 channels)
        if zms.uv1_enabled():
            mesh.uv_layers.new(name="uv1")
        if zms.uv2_enabled():
            mesh.uv_layers.new(name="uv2")
        if zms.uv3_enabled():
            mesh.uv_layers.new(name="uv3")
        if zms.uv4_enabled():
            mesh.uv_layers.new(name="uv4")

        for loop_idx, loop in enumerate(mesh.loops):
            vi = loop.vertex_index

            if zms.uv1_enabled():
                u = zms.vertices[vi].uv1.x
                v = zms.vertices[vi].uv1.y
                mesh.uv_layers["uv1"].data[loop_idx].uv = (u, 1-v)  # Flip V
            
            if zms.uv2_enabled():
                u = zms.vertices[vi].uv2.x
                v = zms.vertices[vi].uv2.y
                mesh.uv_layers["uv2"].data[loop_idx].uv = (u, 1-v)  # Flip V
            
            if zms.uv3_enabled():
                u = zms.vertices[vi].uv3.x
                v = zms.vertices[vi].uv3.y
                mesh.uv_layers["uv3"].data[loop_idx].uv = (u, 1-v)  # Flip V
            
            if zms.uv4_enabled():
                u = zms.vertices[vi].uv4.x
                v = zms.vertices[vi].uv4.y
                mesh.uv_layers["uv4"].data[loop_idx].uv = (u, 1-v)  # Flip V

        #-- Material
        mat = bpy.data.materials.new(filename)
        mat.use_nodes = True

        nodes = mat.node_tree.nodes
        mat_node = nodes["Principled BSDF"]
        tex_node = nodes.new(type="ShaderNodeTexImage")

        if self.load_texture:
            # Check if DDS or PNG exists
            for ext in self.texture_extensions:
                filepath = Path(self.filepath)
                p = filepath.with_suffix(ext)
                if not p.is_file():
                    continue

                image = bpy.data.images.load(str(p))
                tex_node.image = image
                break

        links = mat.node_tree.links
        links.new(tex_node.outputs["Color"], mat_node.inputs["Base Color"])
        mesh.materials.append(mat)

        mesh.update(calc_edges=True)
        return mesh
