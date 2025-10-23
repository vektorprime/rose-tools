from pathlib import Path
import bpy
import mathutils as bmath
from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper

# if "bpy" in locals():
#     import importlib
# else:
from .rose.zmd import ZMD


class ImportZMD(bpy.types.Operator, ImportHelper):
    bl_idname = "rose.import_zmd"
    bl_label = "ROSE Armature (.zmd)"
    bl_options = {"PRESET"}

    filename_ext = ".zmd"
    # filter_glob = StringProperty(default="*.zmd", options={"HIDDEN"})
    filter_glob: StringProperty(default="*.zmd", options={"HIDDEN"})

    # find_animations = BoolProperty(
    #     name = "Find Animations",
    #     description = ( "Recursively load any animations (ZMOs) from current "
    #                     "directory with this armature"),
    #     default = True,
    # )
    find_animations: BoolProperty(
        name="Find Animations",
        description=(
            "Recursively load any animations (ZMOs) from current "
            "directory with this armature"
        ),
        default=True,
    )

    # keep_root_bone = BoolProperty(
    #     name = "Keep Root bone",
    #     description = ( "Prevent blender from automatically removing the root "
    #                     "bone" ),
    #     default = True,
    # )
    keep_root_bone: BoolProperty(
        name="Keep Root bone",
        description=(
            "Prevent Blender from automatically removing the root bone"
        ),
        default=True,
    )

    animation_extensions = [".ZMO", ".zmo"]

    def execute(self, context):
        filepath = Path(self.filepath)
        filename = filepath.stem
        zmd = ZMD(str(filepath))

        armature = bpy.data.armatures.new(filename)
        obj = bpy.data.objects.new(filename, armature)

        # --- Blender 2.7 ---
        # scene = context.scene
        # scene.objects.link(obj)
        # scene.objects.active = obj
        # --- Blender 2.8+ / 4.5 ---
        context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Bones can only be added to armature after it is added to scene
        # self.bones_from_zmd(zmd, armature)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        self.bones_from_zmd(zmd, armature)

        # --- Blender 2.7 ---
        # scene.update()
        # --- Blender 2.8+ ---
        bpy.ops.object.mode_set(mode='OBJECT')

        return {"FINISHED"}

    def bones_from_zmd(self, zmd, armature):
        # bpy.ops.object.mode_set(mode='EDIT')  # Moved earlier

        # Create all bones first so parenting can be done later
        for rose_bone in zmd.bones:
            bone = armature.edit_bones.new(rose_bone.name)
            bone.use_connect = True

        for idx, rose_bone in enumerate(zmd.bones):
            bone = armature.edit_bones[idx]

            pos = bmath.Vector(rose_bone.position.as_tuple())
            rot = bmath.Quaternion(rose_bone.rotation.as_tuple(w_first=True))

            if rose_bone.parent_id == -1:
                bone.head = pos
                bone.tail = pos

                if self.keep_root_bone:
                    bone.head.z += 0.00001  # Blender removes 0-length bones
            else:
                bone.parent = armature.edit_bones[rose_bone.parent_id]

                # --- Old Blender 2.7 logic (kept for reference) -
