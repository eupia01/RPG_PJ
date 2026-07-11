import os
import io
import time
import struct
import chunk
import operator
import codecs
import subprocess
from math import radians
from math import sqrt

import bpy
import mathutils
from bpy.props import *
from mathutils.geometry import tessellate_polygon
from mathutils import Matrix, Vector
from bpy_extras import io_utils, node_shader_utils

import numpy as np

################################################################################
#
#
# OBJECT SERIALIZER
#
#
################################################################################

class ObjectOutput:
	file = None
	
	def putbuffer( self, b, len):
		for l in range(len): self.file.write( struct.pack("B",b[l]&0xff))
	
	def putb( self, v):
		self.file.write( struct.pack("B",int(v)&0xff))
	
	def put4c( self, code):
		self.putb( ord( code[0]))
		self.putb( ord( code[1]))
		self.putb( ord( code[2]))
		self.putb( ord( code[3]))
	
	def putc( self, v):
		self.file.write( struct.pack(">H",int(v)))
	
	def puts( self, v):
		self.file.write( struct.pack(">H",int(v)&0xffff))
	
	def puti( self, v):
		self.file.write( struct.pack(">i",int(v)))
	
	def putf( self, v):
		self.file.write( struct.pack(">f",v))
	
	def putl( self, v):
		self.file.write( struct.pack(">q",v))
	
	def putd( self, v):
		self.file.write( struct.pack(">d",v))
	
	def putbtext( self, s):
		for l in s : self.file.write( struct.pack("B",ord(l)&0xff))
	
	def putt( self, s):
		self.puts( len( s))
		self.putbtext( s)
	
	def puth( self, v):
		self.file.write( struct.pack(">H",toFP16(v)))
	
	def close( self):
		self.file.close()

def toFP16( fp32) :
	i = struct.unpack("I",struct.pack("f",fp32))[0]
	if i==0:
		return 0
	e=((i & 0x7f800000)>>23) - 127 + 15
	if e<0:
		return 0
	elif e>31:
		e=31
	s=  i&0x80000000
	f=  i&0x007fffff
	return  ((s>>16)&0x8000) | ((e<<10) & 0x7c00) | ((f>>13) & 0x03ff)

def toFP32( i) :
	if i==0:
		return 0
	s=  i & 0x8000;
	e=((i & 0x7c00) >>10) - 15 + 127
	f=  i & 0x03ff
	fval= (s<<16) | ((e <<23)&0x7f800000) | (f<<13)
	return struct.unpack("f",struct.pack("I",fval))[0]

################################################################################
#
#
# Material
#
#
################################################################################

def parseName( f) :
	i1 = f.rfind("\\")
	f = f[i1+1:]
	i1 = f.rfind("//")
	if i1 >= 0:
		f = f[i1+2:]
	i2 = f.rfind(".")
	if i2 >= 0 : return [f[:i2],f[i2+1:]]
	return [f,""]

def eq( a, b, w=0.001):
	return abs(a-b)<=w

def eq2( a1, a2, w=0.001):
	return abs(a1[0]-a2[0])+abs(a1[1]-a2[1])<=w

def eq3( a1, a2, w=0.001):
	return abs(a1[0]-a2[0])+abs(a1[1]-a2[1])+abs(a1[2]-a2[2])<=w

def eq4( a1, a2, w=0.001):
	return abs(a1[0]-a2[0])+abs(a1[1]-a2[1])+abs(a1[2]-a2[2])+abs(a1[3]-a2[3])<=w

class Material:
	name = ""
	tec = "pbr.basic"
	
	alphatest = 0
	alpharef = 0.7
	blend = 0
	depthtest = 0
	depthmask = 0
	cullface = 0
	
	colortex1 = None
	normaltex = None
	paramtex = None
	uvbits = 0			# color, mix, normal

	# pbr parameters
	mtype = 0			# standard
	basecol = 0xffffffff
	rough = 0.5
	metal = 0.1
	mparam = 0
	texmap = 0			# rgba to pbr parameter
	
	def __init__( self):
		pass

class PolygonFace:
	strip = False
	idx = None			# int[]
	mate = None
	
	id = 0
	
	def __init__(self):
		self.idx = []
		self.mate = Material()
	
	def num(self):
		if self.strip: return len( idx)-2
		else: return len( idx) / 3

class VertexPoint:
	pos = None
	nml = None
	uv0 = None
	uv1 = None
	col = None
	widx = None
	w = None
	tan = None
	
	def __init__( self, p=None):
		if( p):
			self.pos = p.pos[:]
			self.nml = p.nml[:]
			self.uv0 = p.uv0[:]
			self.uv1 = p.uv1[:]
			self.col = p.col[:]
			self.widx = p.widx[:]
			self.w = p.w[:]
			self.tan = p.tan[:]
		else:
			self.pos = [0,0,0]
			self.nml = [0,0,0]
			self.uv0 = [0,0]
			self.uv1 = [0,0]
			self.col = [255,255,255,255]
			self.widx = [0,0,0,0]
			self.w = [0,0,0,0]
			self.tan = [0,0,0,0]
	
	def clear( self):	# posとnmlはクリアしないでいいや
		self.uv0[0]=self.uv0[1]=0
		self.uv1[0]=self.uv1[1]=0
		self.w[2]=self.w[3]=self.w[0]=self.w[1]=0
		self.widx[0]=self.widx[1]=self.widx[2]=self.widx[3]=0
		self.col[0]=self.col[1]=self.col[2]=self.col[3]=255
		self.tan[0]=self.tan[1]=self.tan[2]=self.tan[3]=0
	
	def normalizenml( self):
		div = sqrt( self.nml[0]*self.nml[0] + self.nml[1]*self.nml[1] + self.nml[2]*self.nml[2])
		if div > 0.1:
			ns = 1.0 / div
			self.nml[0] *= ns
			self.nml[1] *= ns
			self.nml[2] *= ns

class ShapeKey:
	elems = 3
	v = None
	
	def __init__(self):
		self.v = []
	
	def append( self, i, x, y, z):
		self.v.append( [i,x,y,z])

class ShapeKeyList:
	attr = None
	name = None
	k = None
	
	def __init__(self):
		self.attr = []
		self.k = []
		self.name = []

class PolygonMesh:
	vtx = None			#	VertexBuffer
	vtxmask = 0			#	
	stream = None		#	VertexBufferStream vtx.streamのエイリアス
	face = None			#	list of PolygonFace
	wmapname = None		#	weight map
	shapekey = None		#	
	vgroup = {}			#	for optimizing vertex search
	aabb = None			#	[xmin,ymin,zmin,xmax,ymax,zmax] AABB Box
	mot = None			#	MotionData
	customdata = None	#	object
	uvname0 = None
	uvname1 = None
	
	def __init__(self):
		self.vtx = []
		self.face = []
		self.shapekey = None
		self.wmapname = []
		self.vgroup = {}
		self.aabb = [1000,1000,1000,-1000,-1000,-1000]
	
	def getFace( self, id):
		for f in self.face:
			if f.id==id : return f
	
	def vtxid( self, p):
		pos = p.pos
		nml = p.nml
		uv = p.uv0
		return int((pos[0]+pos[1]+pos[2]+nml[0]+nml[1]+nml[2]+uv[0]*10+uv[1]*3)*100)
	
	def getVertex( self, p):
		n   = self.vtxmask & 1
		c   = self.vtxmask & 2
		uv0 = self.vtxmask & 4
		uv1 = self.vtxmask & 8
		w  = self.vtxmask & 16
		tan = self.vtxmask & 32
		vid = self.vtxid( p)
		if vid in self.vgroup :
			g = self.vgroup[vid]
			for l in g:
				_p = self.vtx[l]
				if not eq3( p.pos, _p.pos) : continue
				if n and not eq3( p.nml, _p.nml) : continue
				if c and not eq4( p.col, _p.col, 4) : continue
				if uv0 and not eq2( p.uv0, _p.uv0) : continue
				if uv1 and not eq2( p.uv1, _p.uv1) : continue
				if tan and not eq4( p.tan, _p.tan) : continue
				if w and not eq4( p.widx, _p.widx) and not eq4( p.w, _p.w) : continue
				return l
		else:
			self.vgroup[vid] = []
		#	add
		idx = len( self.vtx)
		self.vgroup[vid].append( idx)
		self.vtx.append( VertexPoint( p))
		#	aabb
		x,y,z = p.pos[0], p.pos[1], p.pos[2]
		if self.aabb[0] > x : self.aabb[0] = x
		if self.aabb[3] < x : self.aabb[3] = x
		if self.aabb[1] > y : self.aabb[1] = y
		if self.aabb[4] < y : self.aabb[4] = y
		if self.aabb[2] > z : self.aabb[2] = z
		if self.aabb[5] < z : self.aabb[5] = z
		return idx
	
	def getWeightID( self, name):
		for l in range( len(self.wmapname)):
			if self.wmapname[l]==name:
				return l
		self.wmapname.append(name)
		return len(self.wmapname)-1
	
	def addCustomData( self, id, val):
		if not self.customdata: self.customdata = {}
		self.customdata[id] = val

################################################################################
#
#
# MOT DATASET
#
#
################################################################################

class Transform:
	px = 0
	py = 0
	pz = 0
	sx = 1
	sy = 1
	sz = 1
	rw = 1
	rx = 0
	ry = 0
	rz = 0
	
	def set( self, t, s, r) :
		k = self
		k.px, k.py, k.pz = t.x, t.y, t.z
		k.sx, k.sy, k.sz = s.x, s.y, s.z
		k.rw, k.rx, k.ry, k.rz = r.w, r.x, r.y, r.z

class TransformTimeline:
	start=0
	end=0
	list=[]
	
	def __init__(self):
		self.list = []
	
	def append( self, k) :
		self.list.append(k)

class BoneParts:
	id = -1
	parentid = -1
	name = ""
	pivot = None
	actor = None
	bindpose = None
	timeline = None
	length = 0.0
	
	depth = 0
	bone = None
	
	def __init__(self):
		self.timeline = TransformTimeline()

class MotionData:
	name = None
	parts = None
	customs = None

	exported = False
	
	def __init__(self):
		self.parts = []
	
	def findParts( self, bone):
		if not bone:
			return None
		for p in self.parts:
			if p.bone == bone:
				return p
		return None

rgbname = ["R","G","B","A"]

class ParamTexture:
	maplist = None		# { ( path, uvname, node.image), ei, pi }
	texmap = 0
	orgtex = True
	
	def __init__(self):
		self.maplist = []

	def addParam( self, ti, ei, pi):
		ei = 3-ei	# change ei from ABGR => RGBA
		i = len( self.maplist)
		self.maplist.append({ "ti":ti, "ei":ei, "pi":pi})
		if (self.texmap & (255<<((3-ei)*8))): self.orgtex = False
		self.texmap = self.texmap | (pi<<((3-ei)*8))
		print( "Add Texture Parameter map PID=%i, img=%s, ch=%s" % (pi, ti["path"], rgbname[ei]))
		if i==0: return
		ti0 = self.maplist[0]["ti"]
		if i>0 and ti["path"] != ti0["path"]:
			self.orgtex = False
			s0 = ti0["img"].size
			s1 = ti["img"].size
			if s0[0]!=s1[0] or s0[1]!=s1[1]: raise ValueError( "Parameter Texture size mismatch!!!")

	def buildImage( self, m):
		ti0 = self.maplist[0]["ti"]
		if self.orgtex:
			return ti0
		else:
			# need to compose image!!!!!!!!!!!!!!!!!!!!!!!
			print( "Material %s's parameter maps need to be composed to single image!" % ( m.name))
			self.texmap = 0
			w = ti0["img"].size[0]
			h = ti0["img"].size[1]
			wh = w*h
			genimg = bpy.data.images.new( "_tmp_"+m.name, w, h, alpha=True)
			print( "Target image = %s, size=(%i,%i)" % (genimg, w, h, ))
			pix = np.ones( (4, wh)) # numy!
			pi = 0
			for v in self.maplist:
				img = v["ti"]["img"]
				ei = v["ei"]
				ch = img.channels
				print( "%s : src=%s, ch=%s" % (rgbname[pi], img.name, ei))
				pix[pi] = np.array( img.pixels).reshape( wh, ch).transpose()[ei]
				self.texmap |= v["pi"]<<(8*(3-pi))
				pi += 1
			genimg.pixels = pix.transpose().flatten().tolist()
			genimg.update()
			ti = { "path":"//"+m.name+"_param.png", "uv":ti0["uv"], "img":genimg, "srgb":False }
			print( "Done! texinfo=", ti)
			return ti

	def used( self):
		return len(self.maplist) > 0

################################################################################
#
#
# TEXTURE EXPORT
#
#
################################################################################

exportimage = []
texformat = "nochange"

def setTextureFormat( f) :
	global texformat
	texformat = f
	print( "Texture Format: %s" % f)

def writeTempImage( img, dir, fn):
	newpath = dir+"\\" + "_tmp_" + fn[0]+"."+fn[1]
	img.save( filepath=newpath)
	return newpath

def exportTextures( scenedir, dir) :
	global exportimage
	global texformat
	if len( exportimage) == 0 : return
	try: os.mkdir(dir)
	except: pass
	if texformat == "nochange" :
		for ti in exportimage :
			f = ti["path"]
			img = ti["img"]
			if f[0:2] == "//" : f = scenedir + "\\" + f[2:]
			if img.filepath == "": f = writeTempImage( img, dir, parseName( f))
			cmd = "cmd.exe /C copy"
			cmd += " \""+f+"\""
			cmd += " \""+dir+"\""
			print(cmd)
			info = subprocess.run( cmd)
	else:
		exepath = __file__ + "\\..\\cwebp.exe"
		for ti in exportimage :
			f = ti["path"]
			img = ti["img"]
			if f[0:2] == "//" : f = scenedir + "\\" + f[2:]
			if img.filepath == "": f = writeTempImage( img, dir, parseName( f))
			cmd = exepath + " \""+f+"\""
			if texformat == "webp100" : cmd += " -lossless"
			else: cmd += " -q 82"
			cmd += " -o \""+dir+"\\"+parseTextureName( ti, "")
			print(cmd)
			info = subprocess.run( cmd)
	# finalize temporal resources
	subprocess.run( "cmd.exe /C del /Q \""+dir+"\\_tmp_*\"")
	for img in bpy.data.images:
		if img.name[0:5]=="_tmp_":
			print( "delete temporal image", img)
			bpy.data.images.remove( img)

def addExportImage( ti) :
	global exportimage
	for i in exportimage :
		print( "exportimage? ", i, ti)
		if i["path"] == ti["path"] : return
	exportimage.append( ti)

def parseTextureName( ti, prefix="tex/") :
	global texformat
	n = None
	a = parseName( ti["path"])
	if texformat != "nochange":
		a[1] = "webp"
	n = prefix+a[0]
	if ti["srgb"]: n += "_srgb"
	n += "." + a[1]
	return n

################################################################################


################################################################################
#
#
# POLYGONMESH CONVERT
#
#
################################################################################

def getlinknode( sock):
	if sock.is_linked:
		return sock.links[0].from_socket.node
	return None

linkelemmap = { "Red":3, "Green":2, "Blue":1, "Alpha":0, "Color":2}

# sock : Roughness, Metallic, Emission Strength, ...
# @ret : [ "node":ShaderNodeTexImage, "ei":elemidx ]
# 入力ソケットにマップされているテクスチャのノードと、テクスチャのRGBA要素のどれを使ってるかのインデックスを返す
# 
def getlinktexelem( sock):
	n = getlinknode( sock)
	if not n: return None
	name = sock.links[0].from_socket.name
	if type( n) == bpy.types.ShaderNodeTexImage:
		ei = linkelemmap[name]
		return { "node":n, "ei":ei}
	if type( n) == bpy.types.ShaderNodeSeparateColor:
		texn = getlinknode( n.inputs[0])
		ei = linkelemmap[name]
		return { "node":texn, "ei":ei}
	return None

# sock : ShaderNodeTexImage
# @ret { "path":image path, "uv":uvmap name, "img":Image, "srgb":sRGB or not }
# テクスチャノードの情報を集めて返す
# 
def gettexinfo( node):
	if type( node) != bpy.types.ShaderNodeTexImage: return None
	if node.image == None: return None
	path = node.image.filepath
	# get subuv
	uvnode = getlinknode( node.inputs["Vector"])
	uvname = uvnode.uv_map if uvnode else None
	srgb = (node.image.colorspace_settings.name=='sRGB')
	return { "path":path, "uv":uvname, "img":node.image, "srgb":srgb }

# ti : texinfo
# pm : PolygonMesh
# m : Material
# i : UV selector index
# テクスチャ情報をマテリアルに設定する
#
def _setimguv( ti, pm, m, i):
	addExportImage( ti)
	if ti["uv"] and ti["uv"]!=pm.uvname0:
		pm.uvname1 = ti["uv"]
		m.uvbits |= (1<<i)

# (f,f,f) -> uint に変換
def vec3col( v):
	return (int(v[0]*255)<<24) | (int(v[1]*255)<<16) | (int(v[2]*255)<<8) | int(255)

# mesh : Mesh
# pm : PolygonMesh
# ポリゴンメッシュのマテリアル毎にフェイスリストとして設定する。
# 
def buildPolygonFaceList( mesh, pm) : 
	if len(mesh.materials) == 0:
		f = PolygonFace()
		m = Material()
		f.id = 0
		f.mate = m
		pm.face.append(f)
		return
	#	uvmap.....
	pm.uvname0 = mesh.uv_layers[0].name		#	default uvmap. *** korega seikai?
	#print( "------------------------------------------ %s" % pm.uvname0)
	#
	for i in range( len(mesh.materials)) :
		mat = mesh.materials[i]
		if not mat : continue
		f = PolygonFace()
		m = Material()
		m.name = mat.name
		f.id = i
		f.mate = m
		pm.face.append(f)
		#	material parameters
		bsdfwrap = node_shader_utils.PrincipledBSDFWrapper( mat)
		###### check node_principled_bsdf
		if not bsdfwrap.node_principled_bsdf:
			#	texture image.....
			image_map = {
				"colortex1": "base_color_texture",
				"normaltex": "normalmap_texture",
			}
			for key, mat_wrap_key in sorted( image_map.items()):
				tex_wrap = getattr( bsdfwrap, mat_wrap_key, None)
				print( "tex_wrap", mat_wrap_key, tex_wrap, bsdfwrap, bsdfwrap.base_color)
				if tex_wrap is None:
					continue
				image = tex_wrap.image
				if image is None:
					continue
				ti = gettexinfo( tex_wrap)
				addExportImage( ti)
				setattr( m, key, parseTextureName( ti))
			print( "Legacy Material[%s]: colortex=%s normaltex=%s" % (m.name, m.colortex1, m.normaltex))
		else:
			#	normal texture
			nnode = getlinknode( bsdfwrap.node_principled_bsdf.inputs["Normal"])
			if type( nnode) == bpy.types.ShaderNodeNormalMap:
				ti = gettexinfo( getlinknode( nnode.inputs["Color"]))
				m.normaltex = parseTextureName( ti)
				_setimguv( ti, pm, m, 1)
			#	detect pbr material type
			buildStandardPbrMaterial( pm, m, bsdfwrap)
			print( "BSDF Material[%s]: colortex=%s normaltex=%s paramtex=%s" % (m.name, m.colortex1, m.normaltex, m.paramtex))
	print( "Mesh[%s]: uv0=%s uv1=%s" % (mesh.name, pm.uvname0, pm.uvname1))

# param id
# 1:RGB, 2:rough, 3:metal, 4:param0, 5:param1, 6:param2, 7:param3, 8:param012

# BlenderのPBRマテリアルの情報を取り出してマテリアルに設定する。
# Standard PBR用。rough, metal, emitのパラメータを持つ。
def buildStandardPbrMaterial( pm, m, bsdfwrap) :
	bc = bsdfwrap.node_principled_bsdf.inputs["Base Color"]
	ro = bsdfwrap.node_principled_bsdf.inputs["Roughness"]
	mt = bsdfwrap.node_principled_bsdf.inputs["Metallic"]
	em = bsdfwrap.node_principled_bsdf.inputs.get( "Emission", None)
	ep = bsdfwrap.node_principled_bsdf.inputs.get( "Emission Strength", None)  # texture ha kotti
	bcnode = getlinknode( bc)
	rote = getlinktexelem( ro)
	mtte = getlinktexelem( mt)
	epte = ep!=None and getlinktexelem( ep)
	epval = ep.default_value if em != None else 0.0
	e = em.default_value if em != None else [0,0,0]
	m.mtype = 0 # 0:standard
	m.basecol = vec3col( bc.default_value)
	m.rough = ro.default_value
	m.metal = mt.default_value
	m.mparam = 0xff000000 | (int(min((e[0]*0.3+e[1]*0.59+e[2]*0.11)*ep.default_value*3.9999,255))<<16)	# 0-63 emission, AO=ff000000
	# base color
	if type( bcnode) == bpy.types.ShaderNodeTexImage:
		ti = gettexinfo( bcnode)
		m.colortex1 = parseTextureName( ti)
		m.basecol = 0xffffffff
		_setimguv( ti, pm, m, 0)
	# param textures ... rough, metal, emit
	pt = ParamTexture()
	# roughness
	if rote:
		m.rough = 1.0
		pt.addParam( gettexinfo( rote["node"]), rote["ei"], 2)
	# metallic
	if mtte:
		m.metal = 1.0
		pt.addParam( gettexinfo( mtte["node"]), mtte["ei"], 3)
	# emit
	if epte:
		m.mparam |= 0xff0000
		pt.addParam( gettexinfo( epte["node"]), epte["ei"], 5)
	# composite param texture
	if pt.used():
		ti = pt.buildImage( m)
		m.texmap = pt.texmap
		m.paramtex = parseTextureName( ti)
		_setimguv( ti, pm, m, 2)

def getVertexInfluences( mesh, vidx, bonekeys) :
	vert = mesh.vertices[vidx]
	w = []
	for i in range(len(vert.groups)):
		if vert.groups[i].weight > 0 : 
			w.append( [bonekeys[vert.groups[i].group], vert.groups[i].weight] )
	return w

def getTangents( mesh) :
	t = {}
	for loop in mesh.loops:
		key = loop.index
		vv = (loop.tangent[0], loop.tangent[1], loop.tangent[2], loop.bitangent_sign)
		t[key] = vv
	return t

def buildPolygonMesh( mobj, mesh, pm, bonekeys) :
	#	initialize vertex buffers
	haswmap = 0
	shapeanime = 0
	bump = 0
	tanloops = None
	oldpinshape = mobj.show_only_shape_key
	oldactiveshape = mobj.active_shape_key_index
	bmesh = mesh
	if mesh.shape_keys and len(mesh.shape_keys.key_blocks)>1:
		shapeanime = 1
		mobj.show_only_shape_key = True
		mobj.active_shape_key_index = 0
		bpy.context.scene.frame_set( 0)
		mesh = mesh.copy()
		bmesh = mobj.to_mesh( preserve_all_data_layers=True)
	if len( mobj.vertex_groups)>0:
		if not shapeanime or bonekeys:
			haswmap = 1
	# mesh.calc_normals_split() < 4.0
	mesh.calc_loop_triangles()
	buildPolygonFaceList( mesh, pm)
	for f in pm.face :
		if f.mate.normaltex :
			bump = 1
			mesh.calc_tangents()
			break
	uv0loops = getattr( mesh.uv_layers.get( pm.uvname0), "data", None) if pm.uvname0 else None
	uv1loops = getattr( mesh.uv_layers.get( pm.uvname1), "data", None) if pm.uvname1 else None
	colloops = mesh.vertex_colors.active.data if mesh.vertex_colors else None
	verts = bmesh.vertices
	
	#	append all faces
	pt = VertexPoint()
	
	pm.vtxmask = 0
	pm.vtxmask = pm.vtxmask | 1							# SK_NORMAL
	if colloops : pm.vtxmask = pm.vtxmask | 2			# SK_COLOR1
	if uv0loops : pm.vtxmask = pm.vtxmask | 4			# SK_UV1
	if uv1loops : pm.vtxmask = pm.vtxmask | 8			# SK_UV1
	if haswmap : pm.vtxmask = pm.vtxmask | 16			# SK_WEIGHTIDX+SK_WEIGHT
	if bump : 
		pm.vtxmask = pm.vtxmask | 32					# SK_UV5 = TANGENT
		tanloops = getTangents( mesh)
	facevertidx = []
	facevert = []
	maxwnum = 0
	
	if not bonekeys:
		bonekeys = ["","","","","","","","","","","","","","","","","","","","","","","","","","","","","",""]
	
	for tri in mesh.loop_triangles :
		mf = pm.getFace( tri.material_index)
		if not mf:
			print("FACE NOT FOUND???? %s . %i" % (mobj.name, tri.material_index))
			continue
		vidx = []
		for v in range( len( tri.vertices)) : # == 3
			vi = tri.vertices[v]
			li = tri.loops[v]
			#	make a VertexPoint of each face point
			pt.clear()
			pt.pos[0] = verts[vi].co[0]
			pt.pos[1] = verts[vi].co[2]
			pt.pos[2] = verts[vi].co[1]
			vn = tri.split_normals
			pt.nml[0] = vn[v][0]
			pt.nml[1] = vn[v][2]
			pt.nml[2] = vn[v][1]
			if shapeanime == 0 : pt.normalizenml()
			if uv0loops:
				pt.uv0[0] = uv0loops[li].uv[0]
				pt.uv0[1] = 1.0-uv0loops[li].uv[1]
			if uv1loops:
				pt.uv1[0] = uv1loops[li].uv[0]
				pt.uv1[1] = 1.0-uv1loops[li].uv[1]
			if colloops:
				vc = colloops[li].color
				pt.col[0] = vc[0] * 255
				pt.col[1] = vc[1] * 255
				pt.col[2] = vc[2] * 255
				pt.col[3] = vc[3] * 255
			if tanloops:
				vv = tanloops[li]
				pt.tan[0] = vv[0]
				pt.tan[1] = vv[2]
				pt.tan[2] = vv[1]
				pt.tan[3] = vv[3]
			#	make weight palette array ( ima code ga kimoi )
			if haswmap:
				wlist = getVertexInfluences( bmesh, vi, bonekeys)
				wnum = wtotal = wscale = 0
				for w in wlist :
					wscale += w[1]
				if wscale > 0:
					wscale = 1/wscale
				wlistnum = len(wlist)
				wlist.sort( key=lambda x:x[1], reverse=True )
				for w in wlist :
					wid = pm.getWeightID(w[0])
					if w[1]<=0 :
						continue
					else:
						pt.widx[wnum] = wid
						pt.w[wnum] = int( w[1]*wscale * 255)
						wtotal += pt.w[wnum]
						wnum += 1
					if wnum>=4 or wtotal>=255 :
						break
				if wtotal < 255 :
					pt.w[0] += 255-wtotal
				maxwnum = max(maxwnum,wnum)
			ptidx = pm.getVertex( pt)
			facevertidx.append( ptidx)
			facevert.append( [pt.pos[0], pt.pos[1], pt.pos[2], pt.nml[0], pt.nml[1], pt.nml[2]])
			vidx.append( ptidx)
		#	ngon to triangle(s)
		for v in range( 2, len(vidx)) : 
			mf.idx.append(vidx[0])
			mf.idx.append(vidx[v])
			mf.idx.append(vidx[v-1])
	#
	#	morph...
	if shapeanime:
		scn = bpy.data.scenes[0]
		frame = scn.frame_current
		sklist = ShapeKeyList()
		sklist.attr.append( 0)	# SK_POSITION
		sklist.attr.append( 1)	# SK_NORMAL
		pm.shapekey = sklist
		for l in range( 1, len(mesh.shape_keys.key_blocks)):
			b = mesh.shape_keys.key_blocks[l]
			mobj.active_shape_key_index = l
			mobj_eval = mobj.evaluated_get( bpy.context.evaluated_depsgraph_get())
			smesh = mobj_eval.to_mesh().copy()
			sklist.name.append( b.name)
			pntsk = ShapeKey()
			nmlsk = ShapeKey()
			sklist.k.append( [pntsk, nmlsk])
			verts = smesh.vertices
			j = 0
			ptmark = {}
			mesh.calc_loop_triangles()
			for tri in mesh.loop_triangles :
				for v in range( len(tri.vertices)) : 
					vi = tri.vertices[v]
					ptidx = facevertidx[j]
					if not (ptidx in ptmark) : 
						ptmark[ptidx] = 1
						vt = facevert[j]
						dx = verts[vi].co[0] - vt[0]
						dy = verts[vi].co[2] - vt[1]
						dz = verts[vi].co[1] - vt[2]
						if dx*dx+dy*dy+dz*dz >= 0.0000001:
							pntsk.append( ptidx, dx, dy, dz)
							if tri.use_smooth:
								dx = verts[vi].normal[0] - vt[3]
								dy = verts[vi].normal[2] - vt[4]
								dz = verts[vi].normal[1] - vt[5]
							else:
								dx = tri.normal[0] - vt[3]
								dy = tri.normal[2] - vt[4]
								dz = tri.normal[1] - vt[5]
							nmlsk.append( ptidx, dx, dy, dz)
					j = j + 1
			print( "shape %s = %i" % ( b.name, len( pntsk.v) ))
		mobj.show_only_shape_key = oldpinshape
		mobj.active_shape_key_index = oldactiveshape
	
	pm.face = list( filter( lambda x: False if len(x.idx)==0  else True, pm.face))
	#done!!!!!!

def bbox_to_aabb( bbox, mat) :
	aabb = [1000,1000,1000,-1000,-1000,-1000]
	for p in bbox :
		v = mat @ Vector( (p[0], p[1], p[2], 1.0))
		x,y,z = v.x, v.y, v.z
		if aabb[0] > x : aabb[0] = x
		if aabb[3] < x : aabb[3] = x
		if aabb[1] > y : aabb[1] = y
		if aabb[4] < y : aabb[4] = y
		if aabb[2] > z : aabb[2] = z
		if aabb[5] < z : aabb[5] = z
	return aabb

def expand_aabb( a, b) :
	if a[0] > b[0] : a[0] = b[0]
	if a[3] < b[3] : a[3] = b[3]
	if a[1] > b[1] : a[1] = b[1]
	if a[4] < b[4] : a[4] = b[4]
	if a[2] > b[2] : a[2] = b[2]
	if a[5] < b[5] : a[5] = b[5]

################################################################################
#
#
# MOTION EXPORT
#
#
################################################################################

mtx_xm90		= (  Matrix.Rotation( radians(-90), 3, 'X') @ Matrix.Scale( -1.0, 3, Vector((0.0, 1.0, 0.0)) )) .to_4x4() # used
motcache = {}

def buildMotionData( scn, mobj, aobj):
	global motcache
	
	arma = aobj.data
	bones = arma.bones
	start = scn.frame_start
	end = scn.frame_end
	mtoamat = mtx_xm90.copy() @ aobj.matrix_world.copy().inverted() @ mobj.matrix_world.copy()
	aabb = [1000,1000,1000,-1000,-1000,-1000]
	#	check cached
	if motcache.get( aobj.name) :
	#	print ( "MOTCACHED!!!!!! ", aobj.name)
		mot = motcache[aobj.name]
		for f in range( start, end) : 
			scn.frame_set(f)
			r = bbox_to_aabb( mobj.bound_box, mtoamat)
			expand_aabb( aabb, r)
		return (mot, aabb)
	#	
	#	NEW MOTION
	#	
	mot = MotionData()
	mot.name = aobj.name
	list = mot.parts
	
	# sort , set id, bind matrix
	for b in bones:
		if b.name.find("ctrl") >= 0: continue
		if b.name.startswith("_"): continue
		p = BoneParts()
		p.bone = b
		p.name = b.name
		p.timeline.start = start
		p.timeline.end = end
		p.bindpose = mtx_xm90.copy() @ mobj.matrix_world.copy().inverted() @ aobj.matrix_world.copy() @ b.matrix_local.copy()
		p.length = b.length
		list.append(p)
		_b = b
		while _b.parent :
			p.depth += 1
			_b = _b.parent
	list.sort( key=lambda w: w.depth)
	for i in range(len(list)):
		p = list[i]
		p.id = i
		pp = mot.findParts( p.bone.parent)
		p.parentid = pp.id if pp else -1
		print("PARTS[%i] %s  :: %i(%s)" % (i,p.name,p.parentid,list[p.parentid].name))
	# 
	print("ANIMATION FRAME %i - %i" % (start,end))
	curfrm = scn.frame_current
	customs = None
	for key in aobj.keys():
		prop_ui = aobj.id_properties_ui( key)
		if prop_ui != None :
			if not customs: customs = mot.customs = []
			customs.append( {"name":key, "vals":[], "len":0})
	for f in range( start, end+1) : 
		scn.frame_set(f)
		pose = aobj.pose
		for i in range(len(list)):
			p = list[i]
			posemat = pose.bones[p.name].matrix.copy()
			if p.parentid >= 0 :
				pp = list[p.parentid]
				posemat = pose.bones[pp.name].matrix.copy().inverted() @ posemat
			else :
				posemat = mtx_xm90.copy() @ posemat
			#
			k = Transform()
			t, r, s = posemat.decompose()
			k.set( t, s, r)
			p.timeline.append(k)
#			print("%s %i (%f %f %f)(%f %f %f)(%f %f %f %f)" % (p.name,f,t.x,t.y,t.z,s.x,s.y,s.z,k.rw, k.rx, k.ry, k.rz))
		r = bbox_to_aabb( mobj.bound_box, mtoamat)
#		print("%i (%f %f %f)(%f %f %f)" % (f,r[0],r[1],r[2],r[3],r[4],r[5]))
		expand_aabb( aabb, r)
		if customs != None :
			for c in customs :
				v = aobj[c["name"]]
				i = len( c["vals"])-1
				v0 = c["vals"][i] if i>=0 else 0.0
				if v != v0: c["len"] = i+1
				c["vals"].append( v)
#				print("custom %s %d = %f" % (c["name"], f, aobj[c["name"]]))
	motcache[aobj.name] = mot
	return (mot, aabb)

def printmat( m):
	print("%f %f %f %f" % (m[0][0], m[0][1], m[0][2], m[0][3]))
	print("%f %f %f %f" % (m[1][0], m[1][1], m[1][2], m[1][3]))
	print("%f %f %f %f" % (m[2][0], m[2][1], m[2][2], m[2][3]))
#	print("%f %f %f %f" % (m[3][0], m[3][1], m[3][2], m[3][3]))



################################################################################
#
#
# CONVERT
#
#
################################################################################

def convertToPM( scn, obj, params):
	print("Convert to PolygonMesh : %s" % obj.name)
	mesh = obj.to_mesh( preserve_all_data_layers=False)
	if not mesh:
		Draw.PupMenu('Error%t|Could not get mesh data from active object')
		return None
	aobj = None
	bonekeys = None
	if params["export_anime"] and len(obj.modifiers) == 1 and obj.modifiers[0].type == 'ARMATURE' :
		aobj = obj.modifiers[0].object
		if not aobj:
			aobj = obj.parent
		if aobj:
			groups = obj.vertex_groups
			bonekeys = [""] * len(groups)
			for g in groups:
				bonekeys[ g.index] = g.name
	pm = PolygonMesh()
	#
	#	convert & save mdl file!!!!
	#
	if params["export_mesh"]:
		buildPolygonMesh(obj,mesh,pm,bonekeys)
		print("Vertices : %i" % len( pm.vtx))
	#
	#	convert & save mot file!!!!
	#
	mot = None
	if aobj and aobj.data :
		mot, aabb = buildMotionData( scn, obj, aobj)
		pm.mot = mot
		pm.aabb = aabb
	#
	#	customdata
	#
	#print("Object",obj.name,"custom wavetype:", obj.get( "wavetype", None), obj.get( "_RNA_UI", None))
	for key in obj.keys():
		prop_ui = obj.id_properties_ui( key)
		if prop_ui != None :
			print( "customdata %s = %f" % (key, obj[key]))
			pm.addCustomData( key, obj[key])
	obj.to_mesh_clear()
	return pm

def clearCaches():
	global exportimage
	global motcache
	exportimage = []
	motcache = {}

