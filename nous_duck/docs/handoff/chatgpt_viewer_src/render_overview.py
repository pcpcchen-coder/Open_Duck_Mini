from pathlib import Path
import bpy
import json
import gzip
import base64
from mathutils import Quaternion, Vector
from array import array

html=Path('/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html').read_text()
i=html.index('const DATA=')+len('const DATA=')
data=json.JSONDecoder().raw_decode(html,i)[0]
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene
mats={}
def material(hexcol):
 if hexcol not in mats:
  c=[int(hexcol[i:i+2],16)/255 for i in (1,3,5)]
  rgb=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in c]
  mat=bpy.data.materials.new(hexcol)
  mat.diffuse_color=(*rgb,1)
  mats[hexcol]=mat
 return mats[hexcol]
cache={}
def geometry(key,color):
 token=[REDACTED_SECRET]
 if token not in cache:
  nv,ni,width,compressed=data['geometry'][key]
  raw=gzip.decompress(base64.b64decode(compressed))
  v=array('h');v.frombytes(raw[:nv*6])
  indices=array('H' if width==2 else 'I');indices.frombytes(raw[nv*6:])
  pts=[tuple(c*.00001 for c in v[i:i+3]) for i in range(0,len(v),3)]
  faces=[tuple(indices[i:i+3]) for i in range(0,len(indices),3)]
  mesh=bpy.data.meshes.new(key)
  mesh.from_pydata(pts,[],faces)
  mesh.update()
  mesh.materials.append(material(color))
  cache[token]=mesh
 return cache[token]
for item in data['parts']:
 if item['cat']=='wire':continue
 for s in item['sh']:
  if 'm' not in s:continue
  mesh=geometry(s['m'],s.get('color',item['color']))
  obj=bpy.data.objects.new(item['name'],mesh)
  scene.collection.objects.link(obj)
  x,y,z=s['p']
  obj.location=(x*.001,-z*.001,y*.001)
  rx,ry,rz,rw=s['q']
  adjust=Quaternion((1,0,0),1.57079632679)
  obj.rotation_mode='QUATERNION'
  obj.rotation_quaternion=adjust@Quaternion((rw,rx,ry,rz))
bpy.ops.mesh.primitive_plane_add(size=4,location=(0,0,-.002))
bpy.context.object.data.materials.append(material('#172739'))
camdat=bpy.data.cameras.new('Overview')
cam=bpy.data.objects.new('Overview',camdat)
scene.collection.objects.link(cam)
cam.location=(.55,-.85,.48)
target=Vector((0,0,.254))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
camdat.type='ORTHO'
camdat.ortho_scale=.66
scene.camera=cam
def light(name,loc,power,diameter,tint):
 dat=bpy.data.lights.new(name,'AREA');dat.energy=power;dat.shape='DISK';dat.size=diameter;dat.color=tint
 ob=bpy.data.objects.new(name,dat);scene.collection.objects.link(ob);ob.location=loc
 ob.rotation_euler=(target-ob.location).to_track_quat('-Z','Y').to_euler()
light('Key',(.45,-.45,.84),80,.6,(1,.92,.83))
light('Fill',(-.62,-.35,.6),48,.7,(.68,.84,1))
light('Rim',(.1,.58,.75),100,.45,(.70,.85,1))
scene.world=bpy.data.worlds.new('Backdrop')
scene.world.color=(.16,.18,.22)
scene.render.engine='CYCLES'
scene.cycles.device='CPU';scene.cycles.samples=8
scene.render.threads_mode='FIXED';scene.render.threads=4
scene.render.resolution_x=710;scene.render.resolution_y=640;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='JPEG';scene.render.image_settings.quality=88
scene.render.filepath='/tmp/duck-viewer/photos/overview.jpg'
bpy.ops.render.render(write_still=True)
