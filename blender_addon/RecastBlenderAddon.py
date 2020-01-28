# ***** BEGIN GPL LICENSE BLOCK *****
#
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ***** END GPL LICENCE BLOCK *****

bl_info = {
    "name":         "RecastBlenderAddon",
    "author":       "Przemysław Bągard",
    "blender":      (2,80,0),
    "version":      (0,0,1),
    "location":     "Scene",
    "description":  "Recast blender navmesh generator.",
    "category":     "Navmesh"
}

import os, sys, logging
import bpy, mathutils, subprocess, pickle
from bpy_extras.io_utils import ExportHelper

import bpy
from bpy.props import IntProperty, CollectionProperty, BoolProperty, FloatProperty, StringProperty, EnumProperty, PointerProperty
from bpy.types import Panel, UIList, PropertyGroup, AddonPreferences
from mathutils import Vector, Quaternion, Euler, Matrix
from bpy.app.handlers import persistent

import platform, ctypes, ctypes.util
from ctypes import c_char_p, c_int, c_float

import bmesh


# x -> x'
# y -> -z'
# z -> y'

def swap(vec):
    return mathutils.Vector( [vec.x, vec.z, -vec.y] )

def reswap(vec):
    return mathutils.Vector( [vec.x, -vec.z, vec.y] )

class RecastData(ctypes.Structure):
    _fields_ = [("cellsize", c_float),
                ("cellheight", c_float),
                ("agentmaxslope", c_float),
                ("agentmaxclimb", c_float),
                ("agentheight", c_float),
                ("agentradius", c_float),
                ("edgemaxlen", c_float),
                ("edgemaxerror", c_float),
                ("regionminsize", c_float),
                ("regionmergesize", c_float),
                ("vertsperpoly", c_int),
                ("detailsampledist", c_float),
                ("detailsamplemaxerror", c_float),
                ("partitioning", ctypes.c_short),
                ("pad1", ctypes.c_short)]

class recast_polyMesh(ctypes.Structure):
    _fields_ = [("verts", ctypes.POINTER(ctypes.c_ushort)), # The mesh vertices. [Form: (x, y, z) * #nverts]
                ("polys", ctypes.POINTER(ctypes.c_ushort)), # Polygon and neighbor data. [Length: #maxpolys * 2 * #nvp]
                ("regs", ctypes.POINTER(ctypes.c_ushort)),  # The region id assigned to each polygon. [Length: #maxpolys]
                ("flags", ctypes.POINTER(ctypes.c_ushort)), # The user defined flags for each polygon. [Length: #maxpolys]
                ("areas", ctypes.POINTER(ctypes.c_ubyte)),  # The area id assigned to each polygon. [Length: #maxpolys]
                ("nverts", c_int),                          # The number of vertices.
                ("npolys", c_int),                          # The number of polygons.
                ("maxpolys", c_int),                        # The number of allocated polygons.
                ("nvp", c_int),                             # The maximum number of vertices per polygon.
                ("bmin", c_float*3),                        # The minimum bounds in world space. [(x, y, z)]
                ("bmax", c_float*3),                        # The maximum bounds in world space. [(x, y, z)]
                ("cs", c_float),                            # The size of each cell. (On the xz-plane.)
                ("ch", c_float),                            # The height of each cell. (The minimum increment along the y-axis.)
                ("borderSize", c_int),                      # The AABB border size used to generate the source data from which the mesh was derived.
                ("maxEdgeError", c_float) ]                 # The max error of the polygon edges in the mesh.

class recast_polyMeshDetail(ctypes.Structure):
    _fields_ = [("meshes", ctypes.POINTER(ctypes.c_uint)), # The sub-mesh data. [Size: 4*#nmeshes]  
                ("verts", ctypes.POINTER(ctypes.c_float)), # The mesh vertices. [Size: 3*#nverts]
                ("tris", ctypes.POINTER(ctypes.c_ubyte)),  # The mesh triangles. [Size: 4*#ntris]
                ("nmeshes", c_int),                        # The number of sub-meshes defined by #meshes.
                ("nverts", c_int),                         # The number of vertices in #verts.
                ("ntris", c_int) ]                         # The number of triangles in #tris.

class recast_polyMesh_holder(ctypes.Structure):
    _fields_ = [("pmesh", ctypes.POINTER(recast_polyMesh))]

class recast_polyMeshDetail_holder(ctypes.Structure):
    _fields_ = [("dmesh", ctypes.POINTER(recast_polyMeshDetail))]

def recastDataFromBlender(scene):
    recastData = RecastData()
    recastData.cellsize = scene.recast_navmesh.cell_size
    recastData.cellheight = scene.recast_navmesh.cell_height
    recastData.agentmaxslope = scene.recast_navmesh.slope_max
    recastData.agentmaxclimb = scene.recast_navmesh.climb_max
    recastData.agentheight = scene.recast_navmesh.agent_height
    recastData.agentradius = scene.recast_navmesh.agent_radius
    recastData.edgemaxlen = scene.recast_navmesh.edge_max_len
    recastData.edgemaxerror = scene.recast_navmesh.edge_max_error
    recastData.regionminsize = scene.recast_navmesh.region_min_size
    recastData.regionmergesize = scene.recast_navmesh.region_merge_size
    recastData.vertsperpoly = scene.recast_navmesh.verts_per_poly
    recastData.detailsampledist = scene.recast_navmesh.sample_dist
    recastData.detailsamplemaxerror = scene.recast_navmesh.sample_max_error
    recastData.partitioning = 0
    if scene.recast_navmesh.partitioning == "WATERSHED":
        recastData.partitioning = 0
    if scene.recast_navmesh.partitioning == "MONOTONE":
        recastData.partitioning = 1
    if scene.recast_navmesh.partitioning == "LAYERS":
        recastData.partitioning = 2
    recastData.pad1 = 0
    return recastData

def addon_preferences(context):
    try:
        preferences = context.preferences
    except AttributeError:
        # Old (<2.80) location of user preferences
        preferences = context.user_preferences

    return preferences.addons[__name__].preferences


def object_has_collection(ob, groupName):
    for group in ob.users_collection:
        if group.name == groupName:
            return True
    return False

def objects_from_collection(allObjects, collectionName):
    objects = []
    for ob in allObjects:
        if object_has_collection(ob, collectionName):
            objects.append(ob)
    return objects

# take care of applying modiffiers and triangulation
def extractTriangulatedInputMeshList(objects, matrix, verts_offset, verts, tris, depsgraph):
    for ob in objects:
        if ob.instance_type == 'COLLECTION':
            subobjects = objects_from_collection(bpy.data.objects, ob.name)
            parent_matrix = matrix@ob.matrix_world
            verts_offset = extractTriangulatedInputMeshList(subobjects, parent_matrix, verts_offset, verts, tris, depsgraph)
        
        if ob.type != 'MESH':
            continue

        bm = bmesh.new()
        bm.from_object( ob, depsgraph )
        real_matrix_world = matrix@ob.matrix_world
        bmesh.ops.transform(bm, matrix=real_matrix_world, verts=bm.verts)
        
        tm = bmesh.ops.triangulate(bm, faces=bm.faces[:])
        # tm['faces']   # but it seems that it modify bmesh anyway
        
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        for v in bm.verts:
            vp = swap(v.co) # swap from blender coordinates to recast coordinates
            verts.append(vp.x)
            verts.append(vp.y)
            verts.append(vp.z)
        
        for f in bm.faces:
            for i in f.verts: # After triangulation it will always be 3 vertexes
                tris.append(i.index + verts_offset)

        verts_offset += len(bm.verts)
        bm.free()
    return verts_offset

# take care of applying modiffiers and triangulation
def extractTriangulatedInputMesh():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    verts = []
    tris = []
    list = bpy.context.selected_objects
    extractTriangulatedInputMeshList(list, Matrix(), 0, verts, tris, depsgraph)
    return (verts, tris)

def createMesh(dmesh_holder):
    mesh = bpy.data.meshes.new("navmesh")  # add a new mesh
    obj = bpy.data.objects.new("navmesh", mesh)  # add a new object using the mesh
    scene = bpy.context.scene
    bpy.context.scene.collection.objects.link(obj)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = obj  # set as the active object in the scene
    obj.select_set(True)  # select object
    #mesh = obj.data
    bm = bmesh.new()

    nverts = (int)(dmesh_holder.dmesh.contents.nverts)
    for i in range(nverts):
        x = dmesh_holder.dmesh.contents.verts[i*3+0]
        y = dmesh_holder.dmesh.contents.verts[i*3+1]
        z = dmesh_holder.dmesh.contents.verts[i*3+2]
        v = reswap(mathutils.Vector( [x, y, z] ))
        bm.verts.new(v)  # add a new vert
    bm.verts.ensure_lookup_table()

    nmeshes = (int)(dmesh_holder.dmesh.contents.nmeshes)
    for j in range(nmeshes):
        baseVerts = dmesh_holder.dmesh.contents.meshes[j*4+0]
        meshNVerts = dmesh_holder.dmesh.contents.meshes[j*4+1]
        baseTri = dmesh_holder.dmesh.contents.meshes[j*4+2]
        meshNTris = dmesh_holder.dmesh.contents.meshes[j*4+3]
        meshVertsList = []
        #if len(meshVertsList) >= 3:
        #    bm.faces.new(meshVertsList)
        
        for i in range(meshNTris):
            i1 = dmesh_holder.dmesh.contents.tris[(baseTri+i)*4+0] + baseVerts
            i2 = dmesh_holder.dmesh.contents.tris[(baseTri+i)*4+1] + baseVerts
            i3 = dmesh_holder.dmesh.contents.tris[(baseTri+i)*4+2] + baseVerts
            flags = dmesh_holder.dmesh.contents.tris[(baseTri+i)*4+3]
            #print("face = (%i, %i, %i)" % (i1, i2, i3))
            bm.faces.new((bm.verts[i1], bm.verts[i2], bm.verts[i3]))  # add a new vert

    ## Recast: The vertex indices in the triangle array are local to the sub-mesh, not global. To translate into an global index in the vertices array, the values must be offset by the sub-mesh's base vertex index.
    #ntris = (int)(dmesh_holder.dmesh.contents.ntris)
    #for i in range(ntris):
    #    i1 = dmesh_holder.dmesh.contents.tris[i*3+0]
    #    i2 = dmesh_holder.dmesh.contents.tris[i*3+1]
    #    i3 = dmesh_holder.dmesh.contents.tris[i*3+2]
    #    print("face[%i] = (%i, %i, %i)" % (i, i1, i2, i3))
    #    bm.faces.new((bm.verts[i1], bm.verts[i2], bm.verts[i3]))  # add a new vert
    
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.00001)
        
    # make the bmesh the object's mesh
    bm.to_mesh(mesh)  
    bm.free()  # always do this when finished


class ReacastNavmeshGenerateOperator(bpy.types.Operator):
    bl_idname = "recast.build_navigation_mesh"
    bl_label = "Build Navigation Mesh"
    bl_description = "Build navigation mesh using recast."

    def execute(self, context):
        #bpy.ops.wm.call_menu(name="ADDITIVE_ANIMATION_insert_keyframe_menu")
        
        addon_prefs = addon_preferences(context)
        dllpath = os.path.abspath(addon_prefs.dllpath)
        dllpathr = dllpath.replace("\\", "/")
        
        verts, tris = extractTriangulatedInputMesh()
        vertsCount = len(verts)
        trisCount = len(tris)
        nverts = (int)(len(verts)/3)
        ntris = (int)(len(tris)/3)
        recastData = recastDataFromBlender(bpy.context.scene)
        
        print("Path to shared library: %s" % dllpathr)
        try:
            l = ctypes.CDLL(dllpathr)
        except OSError as e:
            self.report({'ERROR'}, 'Failed to load shared library: %s\nPath to shared library: %s' % (str(e), dllpathr))
            return{'FINISHED'}
        
        print("nverts %i" % nverts)
        print("ntris %i" % ntris)
        print("cell size %f" % recastData.cellsize)
        
        #print("verts: %s" % str(verts))
        #print("tris: %s" % str(tris))
        
        pmesh = recast_polyMesh_holder()
        dmesh = recast_polyMeshDetail_holder()
        nreportMsg = 128
        reportMsg = ctypes.create_string_buffer(b'\000' * nreportMsg)     # 128 chars mutable text
        l.buildNavMesh.argtypes  = [ctypes.POINTER(RecastData), c_int, c_float*vertsCount, c_int, c_int*trisCount, ctypes.POINTER(recast_polyMesh_holder), ctypes.POINTER(recast_polyMeshDetail_holder), ctypes.c_char_p, c_int]
        l.buildNavMesh.restype = c_int
        l.freeNavMesh.argtypes  = [ctypes.POINTER(recast_polyMesh_holder), ctypes.POINTER(recast_polyMeshDetail_holder), ctypes.c_char_p, c_int]
        l.freeNavMesh.restype = c_int
        
        ok = l.buildNavMesh(recastData, nverts, (c_float*vertsCount)(*verts), ntris, (c_int*trisCount)(*tris), pmesh, dmesh, reportMsg, nreportMsg)
        print("Report msg: %s" % reportMsg.raw)
        if not ok:
            self.report({'ERROR'}, 'buildNavMesh C++ error: %s' % reportMsg.value)

        if not dmesh.dmesh:
            self.report({'ERROR'}, 'buildNavMesh C++ error: %s' % 'No recast_polyMeshDetail')
        else:
            #print("ABC %i" % pmesh.pmesh.contents.nverts)
            #dmeshv1 = dmesh.dmesh.contents.verts[0]
            #print("dmeshv1 %f" % dmeshv1)
            
            createMesh(dmesh)
        
        # what was allocated in C/C++ should be also deallocated there
        l.freeNavMesh(pmesh, dmesh, reportMsg, nreportMsg)
        
        return{'FINISHED'}
        

class ReacastNavmeshPropertyGroup(PropertyGroup):
    # based on https://docs.blender.org/api/2.79/bpy.types.SceneGameRecastData.html
    cell_size : FloatProperty(
        name="cell_size",
        #description="A float property",
        default=0.3,
        min=0.0,
        max=30.0)
        
    cell_height : FloatProperty(
        name="cell_height",
        #description="A float property",
        default=0.2,
        min=0.0,
        max=30.0)

    agent_height : FloatProperty(
        name="agent_height",
        #description="A float property",
        default=2.0,
        min=0.0,
        max=30.0)

    agent_radius : FloatProperty(
        name="agent_radius",
        #description="A float property",
        default=0.6,
        min=0.0,
        max=30.0)

    slope_max : FloatProperty(
        name="slope_max",
        #description="A float property",
        default=0.785398,
        min=0.0,
        max=1.5708)

    climb_max : FloatProperty(
        name="climb_max",
        #description="A float property",
        default=0.9,
        min=0.0,
        max=30.0)

    region_min_size : FloatProperty(
        name="region_min_size",
        #description="A float property",
        default=8.0,
        min=0.0,
        max=30.0)

    region_merge_size : FloatProperty(
        name="region_merge_size",
        #description="A float property",
        default=20.0,
        min=0.0,
        max=30.0)
        
    edge_max_error : FloatProperty(
        name="edge_max_error",
        #description="A float property",
        default=1.3,
        min=0.0,
        max=30.0)
    
    edge_max_len : FloatProperty(
        name="edge_max_len",
        #description="A float property",
        default=12.0,
        min=0.0,
        max=30.0)
    
    verts_per_poly : IntProperty(
        name = "verts_per_poly",
        #description="A integer property",
        default = 6,
        min = 3,
        max = 10
        )
    
    sample_dist : FloatProperty(
        name="sample_dist",
        #description="A float property",
        default=6.0,
        min=0.0,
        max=30.0)
        
    sample_max_error : FloatProperty(
        name="sample_max_error",
        #description="A float property",
        default=1.0,
        min=0.0,
        max=30.0)
    
    partitioning : EnumProperty(
        name="partitioning",
        items = [("WATERSHED", "WATERSHED", "WATERSHED"),
                 ("MONOTONE", "MONOTONE", "MONOTONE"),
                 ("LAYERS", "LAYERS", "LAYERS") ],
        default = "WATERSHED")


class ReacastNavmeshPanel(Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = "Recast navmesh"
    bl_idname = "SCENE_PT_blendcast"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):
        layout = self.layout
        object = context.object
        recastPropertyGroup = context.scene.recast_navmesh
        
        layout.operator("recast.build_navigation_mesh")
        
        layout.label(text="Rasterization:")
        flow = layout.grid_flow()
        col = flow.column()
        col.prop(recastPropertyGroup, "cell_size", text="Cell size")
        col = flow.column()
        col.prop(recastPropertyGroup, "cell_height", text="Cell height")
        
        
        layout.label(text="Agent:")
        flow = layout.grid_flow()
        col = flow.column()
        col.prop(recastPropertyGroup, "agent_height", text="Height")
        col.prop(recastPropertyGroup, "agent_radius", text="Radius")
        col = flow.column()
        col.prop(recastPropertyGroup, "slope_max", text="Max slope")
        col.prop(recastPropertyGroup, "climb_max", text="Max climb")
        #col.separator()
        
        layout.label(text="Region:")
        flow = layout.grid_flow()
        col = flow.column()
        col.prop(recastPropertyGroup, "region_min_size", text="Min region size")
        col = flow.column()
        col.prop(recastPropertyGroup, "region_merge_size", text="Merged region size")
        
        layout.prop(recastPropertyGroup, "partitioning", text="Partitioning")
        
        layout.label(text="Polygonization:")
        flow = layout.grid_flow()
        col = flow.column()
        col.prop(recastPropertyGroup, "edge_max_len", text="Max edge length")
        col.prop(recastPropertyGroup, "edge_max_error", text="Max edge error")
        col = flow.column()
        col.prop(recastPropertyGroup, "verts_per_poly", text="Verts per poly")
        
        layout.label(text="Detail mesh:")
        flow = layout.grid_flow()
        col = flow.column()
        col.prop(recastPropertyGroup, "sample_dist", text="Sample distance")
        col = flow.column()
        col.prop(recastPropertyGroup, "sample_max_error", text="Max sample error")

#@convert_properties
class BlendcastAddonPreferences(AddonPreferences):
    # this must match the addon name, use '__package__'
    # when defining this in a submodule of a python package.
    bl_idname = __name__

    dllpath : StringProperty(
        name='Path of the shared library',
        subtype='FILE_PATH',
        default='.dll'
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'dllpath')
        layout.label(text='Make sure you select shared library')

classes = [
    ReacastNavmeshPanel,
    ReacastNavmeshGenerateOperator
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.utils.register_class(ReacastNavmeshPropertyGroup)
    bpy.types.Scene.recast_navmesh = PointerProperty(type=ReacastNavmeshPropertyGroup)
    bpy.utils.register_class(BlendcastAddonPreferences)


def unregister():
    bpy.utils.unregister_class(BlendcastAddonPreferences)
    bpy.utils.unregister_class(ReacastNavmeshPropertyGroup)
    del bpy.types.Scene.recast_navmesh
    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
