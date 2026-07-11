import os
import io
import time
import struct
import chunk
import operator
import codecs
from math import radians
from math import sqrt
import json
import math

import bpy
import mathutils
from bpy.props import *
from mathutils.geometry import tessellate_polygon
from mathutils import Matrix, Vector

from .pm_convert import convertToPM, ObjectOutput, Transform, exportTextures, setTextureFormat, clearCaches

def ShowMessageBox(message = "", title = "RPG-Cobo", icon = 'INFO'):
	def draw( self, context):
		self.layout.label( text=message)

	bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)


################################################################################
#
#
# PLUGIN CODE
#
#
################################################################################

bl_info= {
    "name": "RPG-Cobo Exporter Addon",
    "author": "djkotori",
    "version": (0, 1),
    "blender": (4, 30, 0),
    "api": 31847,
    "location": "File > Export > Sakana PolygonMesh (.pm)",
    "description": "Exports a pm file including any UV, Morph and Color maps. "\
        "Can convert Skelegons to an Armature.",
    "warning": "",
    "category": "Import-Export"}

def write( context, scn, obj, params):
	frame = scn.frame_current
	dirpath = os.path.dirname( params["filename"])
	fpath = dirpath+"\\"+obj.name
	mdlname = obj.name
	motname = None
	pm = convertToPM( scn, obj, params)
	os.makedirs( dirpath, exist_ok=True)
	#
	#	convert & save mdl file!!!!
	#
	if params["export_mesh"]:
		saveModelData( pm, fpath+".mdl")
	#
	#	convert & save mot file!!!!
	#
	if pm.mot and params["export_anime"] and not pm.mot.exported :
		motname = pm.mot.name
		mpath = dirpath+"\\"+motname
		saveMotionData( pm.mot, mpath+".mot")
		pm.mot.exported = True
		print( 'MotionData exported "%s"' % ( mpath+".mot"))
	#
	# SAVE pm!!!!!!!
	#
	if params["export_mesh"]:
		savePolygonMesh( pm, fpath+".pm", mdlname, motname)
		print( 'PolygonMesh exported "%s"' % ( fpath+".pm"))
	frame = scn.frame_set( frame)

def collectionof( obj):
    for collection in bpy.data.collections:
        if obj.name in collection.objects:
            return collection
    return None

def doexport( path, context, params): 
	clearCaches()
	scn = context.scene
	for o in context.visible_objects:
		col = collectionof( o)
		if not o.visible_get():
			continue
		if o.type!='MESH':
			continue
		if o.name.startswith("_"):
			continue
		if col.name.startswith("_"):
			continue
		write( context, scn, o, params)

class sakana_pm_exporter(bpy.types.Operator):
	'''Export SakanaGL PolygonMesh Operator.'''
	bl_idname = "export.pm"
	bl_label = "Export SakanaGL .pm"
	
	#getter/setter
	def getscale( self):
		return bpy.context.scene.get( "sakanapm_scale", 0.1)

	def setscale( self, val):
		bpy.context.scene["sakanapm_scale"] = val
	
	def getmaskmesh( self):
		return bpy.context.scene.get( "sakanapm_export_mesh", True)

	def setmaskmesh( self, val):
		bpy.context.scene["sakanapm_export_mesh"] = val
	
	def getmaskanime( self):
		return bpy.context.scene.get( "sakanapm_export_anime", True)

	def setmaskanime( self, val):
		bpy.context.scene["sakanapm_export_anime"] = val
	
	def getmasktree( self):
		return bpy.context.scene.get( "sakanapm_export_tree", False)

	def setmasktree( self, val):
		bpy.context.scene["sakanapm_export_tree"] = val
	
	filepath : StringProperty(subtype='FILE_PATH')
	
	SCALE : FloatProperty(name="Scale", description="", get=getscale, set=setscale)
	MASKMESH : BoolProperty(name="Export Mesh", description="", get=getmaskmesh, set=setmaskmesh)
	MASKANIME : BoolProperty(name="Export Anime", description="", get=getmaskanime, set=setmaskanime)
	MASKTREE : BoolProperty(name="Export Model Tree", description="", get=getmasktree, set=setmasktree)
	TEXFORMAT: EnumProperty(
		name="Texture Format", 
		items=(('nochange', "NoChange", ""), 
			('webp100', "WebpLossless", ""), 
			('webp90', "WebpLossy", "")), 
			description="",
			default='webp100'
		)

	#
	def execute(self, context):
		params = { 'filename':self.filepath, 'scale':self.SCALE, 'export_mesh':self.MASKMESH, 'export_anime':self.MASKANIME, 'export_tree':self.MASKTREE, 'tex_format':self.TEXFORMAT}
		setTextureFormat( params["tex_format"])
		doexport( self.filepath, context, params )
		exportTextures( os.path.dirname(context.blend_data.filepath), os.path.dirname( params["filename"])+"\\tex")
		return {'FINISHED'}
	
	def invoke(self, context, event):
		wm= context.window_manager
		wm.fileselect_add(self)
		return {'RUNNING_MODAL'}

def menu_func(self, context):
    self.layout.operator( sakana_pm_exporter.bl_idname, text="SakanaGL PolygonMesh (.pm)")

############################################################################################################
############# RPG-Cobo utility menus



############# Export mot to resource dir

class EXPORT_RPGCOBO_mot( bpy.types.Operator):
	bl_idname = "export_scene.rpgcobo_mot"
	bl_label = "Export OBJ (UV + Normals + Materials)"

	def invoke( self, context, event):
		clearCaches()
		scn = context.scene
		filepath = context.blend_data.filepath
		workdir = os.path.dirname( os.path.dirname( os.path.dirname( filepath)))
		mottype = os.path.basename( os.path.dirname( filepath))
		motname = os.path.splitext( os.path.basename(filepath))[0]
		expdir = os.path.dirname( workdir) + "\\project\\resource\\mot\\" + mottype
		print( 'motname %s mottype %s  workdir %s export %s' % (motname, mottype, workdir, expdir))
		params = { 'filename':filepath, 'scale':1.0, 'export_mesh':False, 'export_anime':True, 'export_tree':False, 'tex_format':'nochange' }
		setTextureFormat( params["tex_format"])
		obj = bpy.data.collections["chara"].objects[0]
		frame = scn.frame_current
		pm = convertToPM( scn, obj, params)
		#	
		os.makedirs( expdir, exist_ok=True)
		mpath = expdir+"\\"+motname+".mot"
		saveMotionData( pm.mot, mpath)
		pm.mot.exported = True
		print( 'MotionData exported "%s"' % ( mpath))
		frame = scn.frame_set( frame)
		ShowMessageBox( 'MotionData exported "%s"' % ( mpath))
		return {'FINISHED'}


############# Load and replace chara vox

def _parseparts( name):
	for i in range( len(name)) :
		if name[i] >= "0" and name[i] <= "9" :
			return (name[:i], int( name[i]))

def _fillweight( obj, wname, w=1.0) :
	vg = obj.vertex_groups.get( wname)
	obj.vertex_groups.active = vg
	bpy.context.view_layer.objects.active = obj
	bpy.ops.object.mode_set(mode='EDIT')
	bpy.ops.mesh.select_all(action='SELECT')
	bpy.context.tool_settings.vertex_group_weight = w
	bpy.ops.object.vertex_group_assign()
	bpy.ops.object.mode_set(mode='OBJECT')

def addHideDriver( obj, arma, pname, pidx):
	fcurve = obj.driver_add( "hide_viewport")
	driver = fcurve.driver
	driver.type = 'SCRIPTED'
	var = driver.variables.new()
	var.name = "var"
	var.targets[0].id = arma
	var.targets[0].data_path = '["' + pname + '"]'
	driver.expression = "var != "+str(pidx)

def replaceCharaVox( colname):
	cols = bpy.data.collections[colname]
	arma = bpy.data.objects["motion"]
	# Ensure Object Mode
	if bpy.context.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
	bpy.ops.object.select_all(action='DESELECT')
	bpy.context.view_layer.objects.active = arma
	# 1: 基本位置を退避
	posmap = {}
	for n in ["leg_L","leg_R","arm_L","arm_R","face","head","tail","wing_L","wing_R"]:
		obj = cols.objects.get( n+"0")
		if obj: posmap[n] = [obj.location[0], obj.location[1], obj.location[2]] # copy
	# 2: バインド
	for obj in cols.all_objects:
		pname, pidx = _parseparts( obj.name)
		if pname not in arma.pose.bones: continue
		bone = arma.pose.bones[pname]
		print( "object %s(%s,%i) bone %s" % ( obj, pname, pidx, bone))
		# reset origin
		if pname in posmap : obj.location = posmap[pname]
		bpy.context.view_layer.objects.active = obj
		# select and bind!
		bpy.ops.object.select_all(action='DESELECT')
		obj.select_set( True)
		bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
		arma.select_set( True)
		bpy.context.view_layer.objects.active = arma
		bpy.ops.object.parent_set(type='ARMATURE_NAME')
		# weight!
		_fillweight( obj, pname, 1.0)
		# driver!!
		addHideDriver( obj, arma, pname, pidx)
	# 3: 仮アニメパターン。1~2
	nnn = 0
	for obj in cols.all_objects:
		print( 'cols.all_objectscols.all_objectscols.all_objects "%s"' % ( obj))
		if not obj or not obj.name : continue
		pname, pidx = _parseparts( obj.name)
		if pidx == 0 and nnn == 0:
			for lidx in range( 1, 3):
				lname = pname + str( lidx)
				if not cols.objects.get( lname):
					lobj = obj.copy()
					lobj.name = lname
					cols.objects.link( lobj)
					addHideDriver( lobj, arma, pname, lidx)
	# 4: finish
	oldcols = bpy.data.collections["chara"]
	#for obj in oldcols.all_objects:
	#	bpy.data.objects.remove( obj, do_unlink=True)
	bpy.data.collections.remove( oldcols, do_unlink=True)
	cols.name = "chara"
	for obj in cols.all_objects:
		if bpy.data.objects.get( obj.name+"_") : obj.name = obj.name + "_a"
		else : obj.name = obj.name + "_"


class EXPORT_RPGCOBO_loadvox( bpy.types.Operator):
	bl_idname = "op.rpgcobo_loadvox"
	bl_label = "RPGCobo Load Chara .vox"

	filepath: bpy.props.StringProperty( subtype='FILE_PATH')

	def execute(self, context):
		filepath = bpy.path.abspath( self.filepath)
		ret = bpy.ops.import_scene.vox( filepath=filepath, voxel_size=0.0625)
		self.report({'INFO'}, f"Imported vox from {filepath}")
		replaceCharaVox( os.path.basename( filepath))
		return {'FINISHED'}

	def invoke(self, context, event):
		x = bpy.context.view_layer.layer_collection
		bpy.context.view_layer.active_layer_collection = x
		# vox addon check.....
		context.window_manager.fileselect_add(self)
		return {'RUNNING_MODAL'}

############# RPGCobo menu

class RPGCOBO_MT_menu(bpy.types.Menu):
	bl_label = "RPGCobo"
	bl_idname = "RPGCOBO_MT_menu_export"

	def draw(self, context):
		layout = self.layout
		layout.operator( EXPORT_RPGCOBO_mot.bl_idname, text="Export Chara Motion")
		layout.operator( EXPORT_RPGCOBO_loadvox.bl_idname, text="Load Chara .vox")

def draw_rpgcobo_menu(self, context):
    self.layout.menu(RPGCOBO_MT_menu.bl_idname)

############# REGISTER / UNREGISTER

def register():
    bpy.utils.register_class( sakana_pm_exporter)
    bpy.types.TOPBAR_MT_file_export.append( menu_func)
	#	menu
    bpy.utils.register_class(EXPORT_RPGCOBO_mot)
    bpy.utils.register_class(RPGCOBO_MT_menu)
    bpy.utils.register_class(EXPORT_RPGCOBO_loadvox)
    bpy.types.TOPBAR_MT_editor_menus.append(draw_rpgcobo_menu)

def unregister():
    bpy.utils.unregister_class( sakana_pm_exporter)
    bpy.types.TOPBAR_MT_file_export.remove( menu_func)
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_rpgcobo_menu)
    bpy.utils.unregister_class(RPGCOBO_MT_menu)
    bpy.utils.unregister_class(EXPORT_RPGCOBO_mot)
    bpy.utils.unregister_class(EXPORT_RPGCOBO_loadvox)

if __name__ == "__main__":
    register()


################################################################################
#
#
# .pm WRITER FUNCTIONs
#
#
################################################################################

def saveModelData( pm, filename):
	print( 'saveModelData "%s"' % filename)
	file = open( filename, "wb")
	out = ObjectOutput()
	out.file = file
	#	write vertex list
	out.put4c("SMDL")
	out.putb( 0)
	out.putb( 1)
	writeVertexBuffer( pm, out)
	out.puti( 0)
	#	write face list
	out.putb( len( pm.face))
	for f in pm.face :
		writePolygonFace( f, out)
	out.puti( 0)
	#	write weight map name
	out.putb( len( pm.wmapname))
	for n in pm.wmapname :
		out.putt( n)
	out.puti( 0)
	#	write face list
	if pm.shapekey != None:
		out.putb( 1)
		writeShapeKeyList( pm.shapekey, out)
	else:
		out.putb( 0)
	out.puti( 0)
	file.close()

def savePolygonMesh( pm, pmfilename, mdlname, motname):
	global filename
	file = codecs.open( pmfilename, "w", "utf_8")
	file.write("///  PolygonMesh converted by Blender.\n/// \n")
	file.write("return {\n")
	file.write("modeldata = \"%s.mdl\"\n" % mdlname)
	if motname : file.write("motiondata = \"%s.mot\"\n" % motname)
	b = pm.aabb
	file.write("bnd = [%f,%f,%f,%f,%f,%f]\n" % ( (b[0]+b[3])*0.5, (b[1]+b[4])*0.5, (b[2]+b[5])*0.5, (b[3]-b[0])*0.5, (b[4]-b[1])*0.5, (b[5]-b[2])*0.5))
	if pm.customdata:
		file.write("customdata = %s\n" % json.dumps(pm.customdata))
	file.write("\nmaterial = [\n")
	for l in range( len( pm.face)):
		writeMaterial( pm.face[l].mate, file)
	file.write("]\n}\n")

def saveMotionData( mot, filename):
	file = open( filename, "wb")
	out = ObjectOutput()
	out.file = file
	out.put4c("SMOT")
	out.putb( 0)
	out.putb( len( mot.parts))
	for p in mot.parts :
		writeBoneParts( p, out)
	if mot.customs:
		out.putb( len( mot.customs))
		for c in mot.customs :
			out.putt( c["name"])
			out.puts( len( c["vals"]))
			for v in c["vals"] :
				out.putf( v)
	else :
		out.putb(0)
	out.putb(0)
	file.close()


################################################################################
#
#
# .pm WRITER INTERNAL
#
#
################################################################################

class VertexBufferStream:
	attr = 0
	type = 0
	normalize = 0
	elems = 1
	offset = 0
	#stride = 0		#※VertexBufferが持ってれば良い
	data = None		# [ [val,...] ]
	
	def write( self, out, stride):
		out.putb( self.attr)
		out.putb( self.type)
		out.putb( self.normalize)
		out.putb( self.elems)
		out.putb( stride)			# strideは引数で渡される
		out.putb( 0)				# align
		out.puti( self.offset)
		out.puti( len( self.data))
		t = self.type
		if t == 1 :
			for a in self.data : 
				for v in a: out.putf( v)
		elif t == 2 :
			for a in self.data :
				for v in a: out.puth( v)
		elif t == 3 :
			for a in self.data :
				for v in a: out.puts( v)
		elif t == 4 :
			for a in self.data :
				for v in a: out.puts( v)
		elif t == 5 :
			for a in self.data :
				for v in a: out.putb( v)
		elif t == 6 :
			for a in self.data :
				for v in a: out.putb( v)
		elif t == 7 :
			for a in self.data :
				for v in a: out.puti( v)
		else :
			for a in self.data :
				for v in a: out.puti( v)

def align( i, tb):
	return int( max( int((i+tb*2-1) / (tb*2)) * (tb*2), int((i+3)/4)*4))

class VertexBuffer:
	typebytes = [ 0, 4, 2, 2, 2, 1, 1, 4, 4]
	stream = None
	flags = 0
	stride = 0			#全てのstreamのstrideはこれと同じ数値
	
	def __init__( self):
		self.stream = []
	
	def newstream( self, attr, type, normalize, elems):
		tb = self.typebytes[type]
		s = VertexBufferStream()
		s.attr = attr
		s.type = type
		s.normalize = normalize
		s.elems = elems
		s.offset = align( self.stride, tb)
		s.data = []
		self.stride = align( s.offset + tb*elems, tb)
		#print( "stream offset %i  _ %i" % ( s.offset, self.stride))
		self.stream.append( s)
		return s
	
	def write( self, out):
		num = len( self.stream[0].data)
		out.putb( 0)
		out.putb( self.flags)
		out.putb( 0)
		out.putb( len( self.stream))
		out.puti( num * self.stride)
		for s in self.stream:
			s.write( out, self.stride)


#	SK_FLOAT	 = 1,
#	SK_HALF		 = 2,
#	SK_USHORT	 = 3,
#	SK_SHORT	 = 4,
#	SK_UBYTE	 = 5,
#	SK_BYTE		 = 6,
#	SK_UINT		 = 7,
#	SK_INT		 = 8,

def uvpack( uv):
	return int( math.floor( uv[0])) + int( math.floor( uv[1])) * 16

def uvpackcheck( vtxlist, id):
	packid = uvpack( getattr( vtxlist[0],id))
	for v in vtxlist :
		if packid != uvpack( getattr( v, id)) :
			return 0
	return 1

def writeVertexBuffer( pm, out):
	vb = VertexBuffer()
	#	SK_POSITION
	s = vb.newstream( 0, 1, 0, 3)
	for p in pm.vtx : s.data.append( p.pos)
	#	SK_NORMAL
	if pm.vtxmask & 1:
		if pm.shapekey :
			s = vb.newstream( 1, 1, 0, 3)
			for p in pm.vtx : s.data.append( p.nml)
		else :
			s = vb.newstream( 1, 4, 1, 3)
			for p in pm.vtx : s.data.append( (p.nml[0]*32767, p.nml[1]*32767, p.nml[2]*32767) )
	#	SK_COLOR1
	if pm.vtxmask & 2:
		s = vb.newstream( 2, 5, 1, 4)
		for p in pm.vtx : s.data.append( p.col)
	#	SK_UV1
	if pm.vtxmask & 4:
		if pm.vtxmask & 8:
			packed = uvpackcheck( pm.vtx, "uv0") and uvpackcheck( pm.vtx, "uv1")
			if packed :
				s = vb.newstream( 4, 3, 1, 4)
				for p in pm.vtx : s.data.append( [ int( (p.uv0[0]%1.0)*65535.0), int( (p.uv0[1]%1.0)*65535.0), int( (p.uv1[0]%1.0)*65535.0), int( (p.uv1[1]%1.0)*65535.0) ] )
			else : 
				s = vb.newstream( 4, 1, 0, 4)
				for p in pm.vtx : s.data.append( [p.uv0[0],p.uv0[1],p.uv1[0],p.uv1[1]])
		else:
			packed = uvpackcheck( pm.vtx, "uv0")
			if packed :
				s = vb.newstream( 4, 3, 1, 2)
				for p in pm.vtx : s.data.append( [ int( (p.uv0[0]%1.0)*65535.0), int( (p.uv0[1]%1.0)*65535.0) ] )
			else : 
				s = vb.newstream( 4, 1, 0, 2)
				for p in pm.vtx : s.data.append( p.uv0)
	#	SK_WEIGHTIDX+SK_WEIGHT
	if pm.vtxmask & 16:
		s = vb.newstream( 6, 5, 0, 4)
		for p in pm.vtx : s.data.append( p.widx)
		s = vb.newstream( 7, 5, 1, 4)
		for p in pm.vtx : s.data.append( p.w)
	#	SK_UV5 = TANGENT
	if pm.vtxmask & 32:
		s = vb.newstream( 8, 4, 1, 4)
		for p in pm.vtx : s.data.append( (p.tan[0]*32767, p.tan[1]*32767, p.tan[2]*32767, p.tan[3]*32767) )
	vb.write( out)

def writePolygonFace( f, out):
	out.putb( 4) # SK_TRIANGLES
	out.putb( 0) # align
	# write IndexBuffer
	out.putb( 0) # version = 0
	ilen = len( f.idx)
	if ilen > 65535 :
		out.putb( 7) # SK_UINT
		out.puti( 4 * len( f.idx))
		out.puti( len( f.idx))
		for i in f.idx: out.puti( i)
	else :
		out.putb( 3) # SK_USHORT
		out.puti( 2 * len( f.idx))
		out.puti( len( f.idx))
		for i in f.idx: out.puts( i)
	out.puti(0)

def writeShapeKeyList( list, out):
	out.putb( len(list.attr))
	for _a in list.attr :
		out.putb( _a)
	out.puti(0)
	out.putb( len(list.k))
	out.putb( 0)
	for l in range( len( list.k)):
		out.putt( list.name[l])
		out.puti(0)
		for _k in list.k[l]:
			#	ShapeKey elems == 3!!!!
			out.puts( len(_k.v))
			out.putb( _k.elems)
			out.puti(0)
			for _v in _k.v :
				out.puts( _v[0])
				out.puth( _v[1])
				out.puth( _v[2])
				out.puth( _v[3])
			#
			out.puti(0)

def _strornull( s):
	if s : return "\"" + s + "\""
	return "null"

def writeMaterial( m, file):
	#	basic param
	file.write("\t{\n")
	file.write("\t\tname = \"%s\"\n" % m.name)
	file.write("\t\ttec = \"%s\"\n" % m.tec)
	file.write("\t\tmtype = %i\n" % m.mtype)
	file.write("\t\tbasecol = 0x%08x\n" % m.basecol)
	file.write("\t\trough = %f\n" % m.rough)
	file.write("\t\tmetal = %f\n" % m.metal)
	file.write("\t\tmparam = 0x%08x\n" % m.mparam)
	file.write("\t\ttexmap = 0x%08x\n" % m.texmap)
	if m.alphatest != 0:
		file.write("\t\talphatest = %i\n" % m.alphatest)
		file.write("\t\talpharef = %f\n" % m.alpharef)
	#	texture
	file.write("\t\ttexture%i = %s\n" % ( 0, _strornull( m.colortex1)))
	file.write("\t\ttexture%i = %s\n" % ( 1, _strornull( m.normaltex)))
	file.write("\t\ttexture%i = %s\n" % ( 2, _strornull( m.paramtex)))
	#	uvbits
	if m.uvbits : file.write("\t\tuvbits = %d\n" % m.uvbits)
	file.write("\t}\n")

def writeTransformTimeline( tt, out):
	out.puts( tt.start)
	out.puts( tt.end)
	prev = Transform()
	for kf in tt.list:
		flag = 0
		if kf.px==prev.px and kf.py==prev.py and kf.pz==prev.pz: flag |= 1
		if kf.sx==prev.sx and kf.sy==prev.sy and kf.sz==prev.sz: flag |= 2
		if kf.rw==prev.rw and kf.rx==prev.rx and kf.ry==prev.ry and kf.rz==prev.rz : flag |= 4
		out.putb( flag)
		if (flag&1) == 0 :
			out.puth(kf.px)
			out.puth(kf.py)
			out.puth(kf.pz)
		if (flag&2) == 0 :
			out.puth(kf.sx)
			out.puth(kf.sy)
			out.puth(kf.sz)
		if (flag&4) == 0 :
			out.puth(kf.rw)
			out.puth(kf.rx)
			out.puth(kf.ry)
			out.puth(kf.rz)
		prev = kf

def writeBoneParts( p, out):
	out.putt( p.name)
	out.putb( p.id)
	out.putb( ( p.parentid&0xff)+1)
	if p.pivot:
		out.putb(1)
		out.putf( p.pivot.x)
		out.putf( p.pivot.y)
		out.putf( p.pivot.z)
	else:
		out.putb(0)
	for l in range(0,4):
		out.putf( p.bindpose[0][l])
		out.putf( p.bindpose[1][l])
		out.putf( p.bindpose[2][l])
		out.putf( p.bindpose[3][l])
	out.putf( p.length)
	writeTransformTimeline( p.timeline, out)
	out.puti(0)
