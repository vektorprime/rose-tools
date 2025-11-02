from enum import IntEnum
from .utils import *

class VertexFlags(IntEnum):
    POSITION = 2      # (1 << 1)
    NORMAL = 4        # (1 << 2)
    COLOR = 8         # (1 << 3)
    BONE_WEIGHT = 16  # (1 << 4) - FIXED ORDER
    BONE_INDEX = 32   # (1 << 5) - FIXED ORDER
    TANGENT = 64      # (1 << 6)
    UV1 = 128         # (1 << 7)
    UV2 = 256         # (1 << 8)
    UV3 = 512         # (1 << 9)
    UV4 = 1024        # (1 << 10)

class Vertex:
    def __init__(self):
        self.position = Vector3()
        self.normal = Vector3()
        self.color = Color4()
        self.bone_weights = [0.0, 0.0, 0.0, 0.0]  # vec4 (4x float)
        self.bone_indices = [0, 0, 0, 0]  # vec4 (4x float in C++, but stored as indices)
        self.tangent = Vector3()
        self.uv1 = Vector2()
        self.uv2 = Vector2()
        self.uv3 = Vector2()
        self.uv4 = Vector2()

class ZMS:
    def __init__(self, filepath=None, report_func=None):
        self.identifier = ""
        self.version = 0
        self.flags = 0  # int (vertex_format in C++)
        self.bounding_box_min = Vector3(0, 0, 0)  # vec3
        self.bounding_box_max = Vector3(0, 0, 0)  # vec3
        self.vertices = []
        self.indices = []  # stored as usvec3 (3x uint16) per face
        self.bones = []  # std::vector<uint16> bone_indices in C++
        self.materials = []  # uint16 array (matid_numfaces)
        self.strips = []  # uint16 array (ibuf_strip)
        self.pool = 0  # pool setting
        self.report_func = report_func  # Optional callback for reporting

        if filepath:
            with open(filepath, "rb") as f:
                self.read(f)
    
    def report(self, level, message):
        """Helper method to report messages either via callback or print"""
        if self.report_func:
            self.report_func(level, message)
        else:
            # Fallback to print if no report function provided
            print(f"[{level}] {message}")

    def positions_enabled(self):
        return (self.flags & VertexFlags.POSITION) != 0

    def normals_enabled(self):
        return (self.flags & VertexFlags.NORMAL) != 0

    def colors_enabled(self):
        return (self.flags & VertexFlags.COLOR) != 0

    def bones_enabled(self):
        bone_weights = (self.flags & VertexFlags.BONE_WEIGHT) != 0
        bone_indices = (self.flags & VertexFlags.BONE_INDEX) != 0
        return (bone_weights and bone_indices)

    def tangents_enabled(self):
        return (self.flags & VertexFlags.TANGENT) != 0

    def uv1_enabled(self):
        return (self.flags & VertexFlags.UV1) != 0

    def uv2_enabled(self):
        return (self.flags & VertexFlags.UV2) != 0

    def uv3_enabled(self):
        return (self.flags & VertexFlags.UV3) != 0

    def uv4_enabled(self):
        return (self.flags & VertexFlags.UV4) != 0

    def read(self, f):
        self.identifier = read_str(f)
        
        # Determine version from identifier
        if self.identifier == "ZMS0005":
            self.version = 5
            self._read_version6(f, 5)
        elif self.identifier == "ZMS0006":
            self.version = 6
            self._read_version6(f, 6)
        elif self.identifier == "ZMS0007":
            self.version = 7
            self._read_version8(f, 7)
        elif self.identifier == "ZMS0008":
            self.version = 8
            self._read_version8(f, 8)
        else:
            raise ValueError(f"Unsupported ZMS version: {self.identifier}")

    def _read_version6(self, f, version):
        """Read ZMS version 5 or 6 format
        
        Version 5/6 use uint32 for counts and indices
        """
        self.flags = read_u32(f)  # int vertex_format
        self.bounding_box_min = read_vector3_f32(f)  # vec3
        self.bounding_box_max = read_vector3_f32(f)  # vec3

        # Read bone lookup table
        bone_count = read_u32(f)  # uint32 in v5/6
        bone_table = []
        for i in range(bone_count):
            _ = read_u32(f)  # Skip first u32 (dummy index)
            bone_table.append(read_u32(f))  # uint32 bone index

        vert_count = read_u32(f)  # uint32 in v5/6 (but stored as uint16 in C++)
        for i in range(vert_count):
            self.vertices.append(Vertex())

        # Read positions (scaled by 100.0 in version 5/6)
        if self.positions_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                pos = read_vector3_f32(f)  # vec3
                # Divide by 100.0 to unscale
                self.vertices[i].position = Vector3(pos.x / 100.0, pos.y / 100.0, pos.z / 100.0)

        # Read normals
        if self.normals_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                self.vertices[i].normal = read_vector3_f32(f)  # vec3

        # Read colors
        if self.colors_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                self.vertices[i].color = read_color4(f)  # zz_color (4x float)

        # Read bone weights and indices
        if self.bones_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                self.vertices[i].bone_weights = read_list_f32(f, 4)  # vec4 (4x float)
                bone_indices_raw = read_list_u32(f, 4)  # vec4 stored as uint32 in file
                # Map through bone table (indices into bone_table)
                self.vertices[i].bone_indices = [
                    bone_table[idx] if idx < len(bone_table) else 0
                    for idx in bone_indices_raw
                ]

        # Read tangents
        if self.tangents_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                self.vertices[i].tangent = read_vector3_f32(f)  # vec3

        # Read UV coordinates
        if self.uv1_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                self.vertices[i].uv1 = read_vector2_f32(f)  # vec2

        if self.uv2_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                self.vertices[i].uv2 = read_vector2_f32(f)  # vec2

        if self.uv3_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                self.vertices[i].uv3 = read_vector2_f32(f)  # vec2

        if self.uv4_enabled():
            for i in range(vert_count):
                _ = read_u32(f)  # vertex_id (uint32)
                self.vertices[i].uv4 = read_vector2_f32(f)  # vec2

        # Read triangle indices (usvec3 = 3x uint16, but stored as uint32 in v5/6 file format)
        triangle_count = read_u32(f)  # uint32 in v5/6
        for i in range(triangle_count):
            _ = read_u32(f)  # triangle_id (uint32)
            idx1 = read_u32(f)  # uint32 in file
            idx2 = read_u32(f)  # uint32 in file
            idx3 = read_u32(f)  # uint32 in file
            self.indices.append(Vector3(idx1, idx2, idx3))

        # Read materials (version 6 only) - uint16 * num_matids
        if version >= 6:
            material_count = read_u32(f)  # uint32 count in file
            for i in range(material_count):
                _ = read_u32(f)  # index (uint32)
                self.materials.append(read_u32(f))  # uint32 in file (but uint16 in C++)

        # Populate bones list from bone_table (std::vector<uint16>)
        self.bones = bone_table

    def _read_version8(self, f, version):
        """Read ZMS version 7 or 8 format
        
        Version 7/8 use uint16 for counts and indices (matches C++ uint16)
        """
        self.flags = read_u32(f)  # int vertex_format (still u32 in file)
        self.bounding_box_min = read_vector3_f32(f)  # vec3
        self.bounding_box_max = read_vector3_f32(f)  # vec3

        # Read bones (direct list, no lookup table) - std::vector<uint16>
        bone_count = read_u16(f)  # uint16 (matches C++ num_bones)
        for i in range(bone_count):
            self.bones.append(read_u16(f))  # uint16 bone_indices[i]

        vert_count = read_u16(f)  # uint16 (matches C++ num_verts)
        for i in range(vert_count):
            self.vertices.append(Vertex())

        # Read vertex data (no vertex_id prefix in version 7/8)
        if self.positions_enabled():
            for i in range(vert_count):
                self.vertices[i].position = read_vector3_f32(f)  # vec3

        if self.normals_enabled():
            for i in range(vert_count):
                self.vertices[i].normal = read_vector3_f32(f)  # vec3

        if self.colors_enabled():
            for i in range(vert_count):
                self.vertices[i].color = read_color4(f)  # zz_color (4x float)

        if self.bones_enabled():
            for i in range(vert_count):
                self.vertices[i].bone_weights = read_list_f32(f, 4)  # vec4 (4x float)
                bone_indices_raw = read_list_u16(f, 4)  # vec4 stored as uint16 in file
                # Map through bones list - indices are into bones array
                self.vertices[i].bone_indices = [
                    self.bones[idx] if idx < len(self.bones) else 0
                    for idx in bone_indices_raw
                ]

        if self.tangents_enabled():
            for i in range(vert_count):
                self.vertices[i].tangent = read_vector3_f32(f)  # vec3

        if self.uv1_enabled():
            for i in range(vert_count):
                self.vertices[i].uv1 = read_vector2_f32(f)  # vec2

        if self.uv2_enabled():
            for i in range(vert_count):
                self.vertices[i].uv2 = read_vector2_f32(f)  # vec2

        if self.uv3_enabled():
            for i in range(vert_count):
                self.vertices[i].uv3 = read_vector2_f32(f)  # vec2

        if self.uv4_enabled():
            for i in range(vert_count):
                self.vertices[i].uv4 = read_vector2_f32(f)  # vec2

        # Read indices - flat array (usvec3 = 3x uint16)
        index_count = read_u16(f)  # uint16 num_faces (matches C++)
        indices_flat = read_list_u16(f, index_count * 3)  # uint16 indices
        for i in range(0, len(indices_flat), 3):
            self.indices.append(Vector3(indices_flat[i], indices_flat[i+1], indices_flat[i+2]))

        # Read materials (uint16 * num_matids)
        material_count = read_u16(f)  # uint16 num_matids
        self.materials = read_list_u16(f, material_count)  # uint16 array

        # Read strips (uint16 * num_indices for strips)
        strip_count = read_u16(f)  # uint16 count
        self.strips = read_list_u16(f, strip_count)  # uint16 array (ibuf_strip)

        # Read pool (version 8 only)
        if version >= 8:
            self.pool = read_u16(f)  # uint16
