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
        zms = ZMS(str(filepath))

        # Debug logging
        print(f"=== ZMS Import Debug ===")
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

        mesh = self.mesh_from_zms(zms, filename)

        obj = bpy.data.objects.new(filename, mesh)

        # --- Create vertex groups and assign weights so exporter can detect bone data ---
        # Create one Blender vertex group per ZMS bone entry (order matters)
        if len(zms.bones) > 0:
            for i, bone in enumerate(zms.bones):
                # name groups deterministically; exporter relies on obj["zms_bones"] to restore mapping
                obj.vertex_groups.new(name=f"zms_bone_{i}")

            # Assign weights per vertex. mesh.from_pydata created vertices in same order as zms.vertices
            for vi, v in enumerate(zms.vertices):
                # bone_weights and bone_indices are lists of length 4
                for gi in range(4):
                    try:
                        weight = v.bone_weights[gi]
                        group_index = int(v.bone_indices[gi])
                    except Exception:
                        continue

                    if weight and weight > 0.0 and 0 <= group_index < len(zms.bones):
                        # Add weight to that group for this vertex
                        obj.vertex_groups[group_index].add([vi], weight, 'REPLACE')

        # Store ZMS metadata on the object for later export
        obj["zms_materials"] = str(zms.materials)
        obj["zms_strips"] = str(zms.strips)
        obj["zms_pool"] = zms.pool
        obj["zms_bones"] = str(zms.bones)

        scene = context.scene
        context.collection.objects.link(obj)
        #scene.update()

        return {"FINISHED"}

    def mesh_from_zms(self, zms, filename):
        mesh = bpy.data.meshes.new(filename)

        #-- Vertices
        verts = []
        for v in zms.vertices:
            verts.append((v.position.x, v.position.y, v.position.z))

        #-- Faces
        faces = []
        for i in zms.indices:
            faces.append((i.x, i.y, i.z))

        #-- Mesh
        mesh.from_pydata(verts, [], faces)

        #-- UV
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
                mesh.uv_layers["uv1"].data[loop_idx].uv = (u,1-v)

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

        links = mat.node_tree.links
        #links.new(mat_node.inputs["Base Color"], tex_node.outputs["Color"])
        links.new(tex_node.outputs["Color"], mat_node.inputs["Base Color"])
        mesh.materials.append(mat)

        mesh.update(calc_edges=True)
        return mesh
