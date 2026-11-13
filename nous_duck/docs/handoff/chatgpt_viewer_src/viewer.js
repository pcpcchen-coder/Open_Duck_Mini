'use strict';
const byId = id => document.getElementById(id);
const cats = {print:'列印件', motor:'馬達', electronic:'電子', power:'電源', wire:'線材', hardware:'五金'};
const precision = {cad:'上游 CAD 網格', 'print-placement':'原版列印網格 · 依頭殼座標定位', proxy:'位置或外形示意', route:'配線路徑示意'};
const rowMap = new Map(DATA.bom.map(row => [row.k,row]));
const instances = new Map(DATA.bom.map(row => [row.k,DATA.parts.filter(p => p.k === row.k)]));
const partMap = new Map(DATA.parts.map(p => [p.id,p]));
const state = {step:0, mode:'assembly', amount:0, selection:null, only:false, camera:'iso'};
const progressKey = 'open-duck-mini-v2-assembly-b23317a-progress';
let completed = new Set();
try {
  const saved = JSON.parse(localStorage.getItem(progressKey) || '[]');
  if (Array.isArray(saved)) completed = new Set(saved.filter(i => Number.isInteger(i) && i >= 0 && i < steps.length));
} catch (error) { /* File URLs can have storage disabled. */ }
const htmlEscape = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const e = htmlEscape;
function isStepPart(part, step=state.step) {
  if (step === 0) return part.k === 'sts';
  const guide = steps[step];
  return part.stage === step || guide.include?.includes(part.id) || guide.includeKeys?.includes(part.k) || false;
}
function selectedParts() {
  return partMap.has(state.selection) ? [partMap.get(state.selection)] : instances.get(state.selection) || [];
}
function selectedRow() {
  return rowMap.get(partMap.get(state.selection)?.k || state.selection);
}
function renderSteps() {
  byId('progress').value = completed.size;
  byId('progress-text').textContent = completed.size+'／'+steps.length+' 步完成';
  byId('steps').innerHTML = steps.map((s,i) => '<button class="step" data-step="'+i+'" aria-current="'+(i===state.step?'step':'false')+'"><span class="number">'+String(i+1).padStart(2,'0')+'</span><span>'+e(s.title)+'</span>'+(completed.has(i)?'<span class="done" aria-label="已完成">✓</span>':'')+'</button>').join('');
}
function renderDetails() {
  const step = steps[state.step];
  const marked = completed.has(state.step);
  const gallery = step.pics.map(([key,label]) => DATA.photos[key] ? '<button class="thumb" data-photo="'+e(key)+'" data-label="'+e(label)+'"><img alt="" src="'+DATA.photos[key]+'"><span>'+e(label)+'</span></button>' : '').join('');
  byId('details').innerHTML = '<h2>'+String(state.step+1).padStart(2,'0')+'　'+e(step.title)+'</h2><p class="intro">'+e(step.summary)+'</p><ol>'+step.tasks.map(t=>'<li>'+e(t)+'</li>').join('')+'</ol><p class="checkline"><strong>驗收</strong>　'+e(step.check)+'</p>'+(gallery?'<div class="gallery" aria-label="原版組裝圖">'+gallery+'</div>':'')+'<p class="reference"><a target="_blank" rel="noopener" href="'+e(step.src)+'">原作者說明 ↗</a><a target="_blank" rel="noopener" href="'+e(RUNTIME)+'">Runtime v2 ↗</a></p><div class="step-bottom"><button id="mark" class="complete" aria-pressed="'+marked+'">'+(marked?'✓ 已完成（點一下取消）':'標記這步已完成')+'</button><div><button id="prev" '+(state.step===0?'disabled':'')+'>上一步</button><button id="next" '+(state.step===steps.length-1?'disabled':'')+'>下一步</button></div></div>';
}
function rowStage(row) {
  const list=instances.get(row.k);
  if(list.length) return list.some(p => isStepPart(p));
  const table={horns:[0,1,2,3,4,5,6,7],screws:[1,2,3,4,5,6,7,10,11],lock:[1,2,3,4,5,6,7],sheath:[9,10,12],controller:[13]};
  return table[row.k]?.includes(state.step) || false;
}
function searchText(row) {
  const ps=instances.get(row.k);
  return [row.name,row.spec,row.note,row.k,cats[row.cat],...ps.flatMap(p=>[p.name,p.zone,p.detail,p.motor && ('ID '+p.motor)])].filter(Boolean).join(' ').toLowerCase();
}
function renderBom() {
  const oldScroll=byId('bom-list').scrollTop;
  const keywords=byId('search').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const filter=byId('category').value;
  const onlyStep=byId('step-only').checked;
  const match=DATA.bom.filter(r => (filter==='all'||r.cat===filter) && (!onlyStep||rowStage(r)) && keywords.every(word=>searchText(r).includes(word)));
  const active=selectedRow()?.k;
  byId('bom-count').textContent = match.length+'／'+DATA.bom.length+' 類 · 51 件列印件';
  byId('bom-list').innerHTML=match.length?match.map(r=>{
    const list=instances.get(r.k);
    const selected=r.k===active;
    const qty=typeof r.qty==='number'?'×'+r.qty:r.qty;
    const description=r.spec+(r.opt?' · 選配':'');
    const children=selected && list.length>1 ? '<div class="instance-list" aria-label="個別安裝位置">'+list.map(p=>'<button class="instance" data-instance="'+e(p.id)+'" aria-pressed="'+(p.id===state.selection)+'">'+e(p.motor?'ID '+p.motor+' · '+p.name:p.zone+' · '+(p.name===r.name?'位置 '+(list.indexOf(p)+1):p.name))+'</button>').join('')+'</div>' : '';
    return '<button class="bom-row" data-bom="'+e(r.k)+'" aria-pressed="'+selected+'"><span class="dot '+r.cat+'"></span><span><strong>'+e(r.name)+'</strong><small>'+e(description)+'</small></span><span class="qty">'+e(qty)+'</span></button>'+children;
  }).join(''):'<p class="empty">沒有符合條件的零件。</p>';
  byId('bom-list').scrollTop=oldScroll;
}
function renderSelection() {
  const row=selectedRow(), parts=selectedParts(), el=byId('selection');
  if (!row) {el.hidden=true;el.innerHTML='';return;}
  const picked=partMap.get(state.selection);
  const title=picked ? (picked.motor?'ID '+picked.motor+' · ':'')+picked.name : row.name;
  const caption=picked ? picked.zone+' · '+precision[picked.src] : (parts.length?'3D 中有 '+parts.length+' 個位置或組件':'採購項／外部耗材');
  el.innerHTML='<strong>'+e(title)+'</strong><p>'+e(caption)+'</p><p>'+e(row.spec)+(row.note?' · '+e(row.note):'')+'</p><p><button id="clear-pick">清除選取</button>'+(row.link?' <a href="'+e(row.link)+'" target="_blank" rel="noopener">原資料 ↗</a>':'')+'</p>';
  el.hidden=false;
}
function refreshControls() {
  document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.mode===state.mode));
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.view===state.camera));
  byId('only-focus').setAttribute('aria-pressed',String(state.only));
  byId('spread').value=Math.round(state.amount*100);
  byId('spread-value').value=Math.round(state.amount*100)+'%';
}
function chooseStep(index) {
  if(index<0||index>=steps.length)return;
  state.step=index;state.selection=null;
  if(index===12) byId('wires').checked=true;
  renderSteps();renderDetails();renderBom();renderSelection();
  if (state.only) fit(true);
  requestRender();
}
function choosePart(id, fromCanvas=false) {
  const priorId=state.selection;
  state.selection=priorId===id?null:id;
  const row=selectedRow(), list=selectedParts();
  if(row && list.some(p=>p.cat==='wire')) byId('wires').checked=true;
  if(row && list.some(p=>p.opt)) byId('options').checked=true;
  if(row && list.length && (row.cat!=='print'||list.some(p=>p.opt)) && state.mode==='assembly'){
    state.mode='cut';
  }
  if (state.only && row && list.length===0) state.only=false;
  renderBom();renderSelection();refreshControls();requestRender();
  if(state.only) fit(true);
  if(fromCanvas && row){
    const b=byId('bom-list').querySelector('[data-bom="'+row.k+'"]');
    if(b) b.scrollIntoView({block:'nearest'});
  }
}
function setMode(mode) {
  state.mode=mode;
  state.amount=mode==='exploded'?(state.amount||.56):0;
  refreshControls();requestRender();fit(true);
}
function showDialog(title,content) {
  byId('dialog-title').textContent=title;
  byId('dialog-content').innerHTML=content;
  const d=byId('dialog');
  if(!d.open) d.showModal();
  d.scrollTop=0;
}
function showPhoto(key,label) {
  const src=DATA.photos[key];
  if(src) showDialog(label,'<img class="full" src="'+src+'" alt="'+e(label)+'"><p>圖源　Open Duck Mini v2／Antoine Pirrone 與貢獻者</p>');
}
function showWiring() {
  const map=pinGroups.map(([title,rows])=>'<section><h3>'+e(title)+'</h3><table><thead><tr><th>訊號</th><th>Pi 實體腳位</th><th>功能</th></tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(cell=>'<td>'+e(cell)+'</td>').join('')+'</tr>').join('')+'</tbody></table></section>').join('');
  showDialog('接線圖與 GPIO 腳位','<p>舵機支路使用 2S 原電壓，Pi 使用 UBEC 穩壓 5 V。原作者的接線圖與所用模組的腳位標示優先。</p><img class="full" alt="Open Duck Mini v2 系統接線圖" src="'+DATA.photos['system-wiring']+'"><div class="pin-grid">'+map+'</div><p><a href="'+UP+'assembly_guide.md#electronics" target="_blank" rel="noopener">原作者接線與腳位 ↗</a></p>');
}
function showSources() {
  showDialog('來源與模型精度','<ul><li><strong>原版網格</strong>　列印結構與 14 顆 STS3215 使用上游 CAD／MJCF。51 件列印件中有 7 件表情相關印件以原版 STL 的頭殼座標合併顯示。標準姿勢沿用原模型零位。</li><li><strong>位置或外形示意</strong>　部分 PCB、天線舵機、microSD、排針、足底開關、接頭、選配電子、緊固件與線束。請用原作者照片、接線圖及實物確認孔位、方向與線長。</li><li><strong>BOM 數量</strong>　以原 BOM 與列印指南為準。供應商變體、安裝零件的尺寸、公差和逐孔螺絲清單需依實物確認。用料與工具保留在 BOM 供查找。</li><li><strong>爆炸距離</strong>　供辨識與點選，滑桿不表示實際拆裝路徑或間隙。</li><li><strong>離線使用</strong>　模型和照片已內嵌。組裝進度存於瀏覽器，若瀏覽器限制本機檔案儲存，進度只保留在當次開啟。</li></ul><p><a href="'+REPO+'/tree/'+DATA.commit+'" target="_blank" rel="noopener">固定上游版本 ↗</a> · <a href="'+UP+'print_guide.md" target="_blank" rel="noopener">原列印清單 ↗</a> · <a href="'+BOM_URL+'" target="_blank" rel="noopener">原 BOM ↗</a></p><details><summary>模型及程式授權</summary><pre>'+e(LICENSES)+'</pre></details>');
}

byId('steps').addEventListener('click',event=>{
 const b=event.target.closest('[data-step]');
 if(b) chooseStep(Number(b.dataset.step));
});
byId('details').addEventListener('click',event=>{
 const b=event.target.closest('button');if(!b)return;
 if(b.id==='prev') chooseStep(state.step-1);
 else if(b.id==='next') chooseStep(state.step+1);
 else if(b.dataset.photo) showPhoto(b.dataset.photo,b.dataset.label);
 else if(b.id==='mark'){
   if(completed.has(state.step)) completed.delete(state.step); else completed.add(state.step);
   try{localStorage.setItem(progressKey,JSON.stringify([...completed]));}catch(error){/* Optional persistence. */}
   renderSteps();renderDetails();
 }
});
byId('bom-list').addEventListener('click',event=>{
 const b=event.target.closest('button');if(b) choosePart(b.dataset.instance||b.dataset.bom);
});
byId('selection').addEventListener('click',event=>{if(event.target.id==='clear-pick') choosePart(state.selection);});
byId('search').addEventListener('input',renderBom);
byId('category').addEventListener('change',renderBom);
byId('step-only').addEventListener('change',renderBom);
byId('wire-guide').addEventListener('click',showWiring);
byId('sources').addEventListener('click',showSources);
byId('close-dialog').addEventListener('click',()=>byId('dialog').close());
byId('dialog').addEventListener('click',event=>{if(event.target===byId('dialog')) byId('dialog').close();});
byId('spread').addEventListener('input',event=>{
 state.amount=Number(event.target.value)/100;
 if(state.amount>0) state.mode='exploded';
 refreshControls();requestRender();
});
byId('wires').addEventListener('change',requestRender);
byId('options').addEventListener('change',requestRender);
document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
byId('only-focus').addEventListener('click',()=>{
 const row=selectedRow();
 if(row && !selectedParts().length) choosePart(state.selection);
 state.only=!state.only;
 refreshControls();fit(true);
});
byId('fit').addEventListener('click',()=>fit(true));
renderSteps();renderDetails();renderBom();refreshControls();

let viewport, renderer, camera, scene, rig;
let ready=false, pending=false;
let spherical, target, raycaster, mouse;
const objects=[], geometryCache=new Map(), primitiveCache=new Map();
const stageMaterial=new Map(), scratchMaterials=new Map(), poses={iso:[.65,1.35],front:[0,1.54],back:[Math.PI,1.54],side:[Math.PI/2,1.54]};
function bytes(encoded) {
 const raw=atob(encoded);
 const result=new Uint8Array(raw.length);
 for(let i=0;i<raw.length;i++) result[i]=raw.charCodeAt(i);
 return result;
}
function decodeGeometry(key) {
 if(geometryCache.has(key)) return geometryCache.get(key);
 const [nv,ni,width,packed]=DATA.geometry[key];
 const data=fflate.gunzipSync(bytes(packed));
 const coordinates=new Int16Array(data.buffer,data.byteOffset,nv*3);
 const vertices=new Float32Array(nv*3);
 for(let i=0;i<vertices.length;i++)vertices[i]=coordinates[i]/100;
 const rawIndices=new DataView(data.buffer,data.byteOffset+nv*6,ni*width);
 const index=width===2?new Uint16Array(ni):new Uint32Array(ni);
 for(let i=0;i<ni;i++) index[i]=width===2?rawIndices.getUint16(i*2,true):rawIndices.getUint32(i*4,true);
 const geometry=new THREE.BufferGeometry();
 geometry.setAttribute('position',new THREE.BufferAttribute(vertices,3));
 geometry.setIndex(new THREE.BufferAttribute(index,1));
 geometry.computeBoundingBox();
 geometry.computeBoundingSphere();
 geometryCache.set(key,geometry);
 return geometry;
}
function primitive(shape) {
 const key=JSON.stringify(shape.box||shape.cyl||shape.ring);
 if(primitiveCache.has(key)) return primitiveCache.get(key);
 let g;
 if(shape.box) g=new THREE.BoxGeometry(...shape.box);
 else if(shape.cyl){
   const [radius,length,axis]=shape.cyl;
   g=new THREE.CylinderGeometry(radius,radius,length,18);
   if(axis==='x') g.rotateZ(-Math.PI/2); else if(axis==='z') g.rotateX(Math.PI/2);
 } else {
   const [outer,inner,h]=shape.ring;
   const s=new THREE.Shape();s.absarc(0,0,outer,0,2*Math.PI,false);
   const hole=new THREE.Path();hole.absarc(0,0,inner,0,2*Math.PI,true);
   s.holes.push(hole);
   g=new THREE.ExtrudeGeometry(s,{depth:h,steps:1,bevelEnabled:false,curveSegments:12});
   g.translate(0,0,-h/2);g.rotateX(Math.PI/2);
 }
 g.computeBoundingBox();
 primitiveCache.set(key,g);
 return g;
}
function material(color,variant) {
 const cacheKey=color+'|'+variant;
 if(stageMaterial.has(cacheKey)) return stageMaterial.get(cacheKey);
 const tint=new THREE.Color(color);
 const targetColor=variant==='selected'?new THREE.Color('#88f3d2'):
   variant==='active'?tint.clone().lerp(new THREE.Color('#76c9c7'),.31):
   variant==='dim'?tint.clone().lerp(new THREE.Color('#203143'),.63):tint;
 const translucent=variant==='ghost';
 const m=new THREE.MeshStandardMaterial({color:targetColor,flatShading:true,roughness:.73,
   metalness:0.04,side:THREE.DoubleSide,transparent:translucent,opacity:translucent?.13:1,depthWrite:!translucent});
 if(variant==='selected'){m.emissive.set('#4aa385');m.emissiveIntensity=.37;}
 if(translucent){m.color.lerp(new THREE.Color('#9aafd0'),.45);}
 stageMaterial.set(cacheKey,m);
 return m;
}
function makePart(part,index) {
 const group=new THREE.Group();
 group.userData.part=part;
 const center=new THREE.Vector3(...part.c);
 for(const s of part.sh){
   let geometry, relative;
   if(s.tube){
     const curve=new THREE.CatmullRomCurve3(s.tube.map(p=>new THREE.Vector3(...p).sub(center)));
     geometry=new THREE.TubeGeometry(curve,Math.max(9,s.tube.length*5),1.45,7,false);
     geometry.computeBoundingBox();
     relative=new THREE.Vector3();
   } else {
     geometry=s.m?decodeGeometry(s.m):primitive(s);
     relative=new THREE.Vector3(...s.p).sub(center);
   }
   const color=s.color||part.color;
   const mesh=new THREE.Mesh(geometry,material(color,'base'));
   mesh.userData.part=part;mesh.userData.color=color;
   mesh.position.copy(relative);
   if(s.q) mesh.quaternion.fromArray(s.q);
   group.add(mesh);
 }
 group.position.copy(center);
 rig.add(group);
 const delta=explosion(part,index);
 return {part,group,center,delta};
}
function explosion(part,index) {
 const [x,y,z]=part.c;
 const side=Math.abs(x)>8?Math.sign(x):(index%2?1:-1);
 const signZ=Math.abs(z)>9?Math.sign(z):(index%3?1:-1);
 const bump=(index%7-3)*9;
 const strength=part.cover?1.25:1;
 if(part.cat==='wire')return new THREE.Vector3(0,0,0);
 if(part.stage===9)return new THREE.Vector3(x*.84+side*(24+Math.abs(bump)),(y-236)*.55+bump*.7,-100-(index%5)*13);
 if(part.stage===2)return new THREE.Vector3(side*(45+Math.abs(bump)),-23+(y-13)*1.36+bump*.53,z*.55+signZ*(24+Math.abs(bump)));
 if(part.stage>=3 && part.stage<=5)return new THREE.Vector3(side*(47+Math.abs(bump)+Math.abs(x)*.51),(y-188)*.52+bump,z*.53+signZ*(31+Math.abs(bump)));
 if(part.stage>=6 && part.stage<=7 || y>320)return new THREE.Vector3((x*.80+side*(24+Math.abs(bump)))*strength,(y-286)*.62+bump+38,(z*.72+signZ*(27+Math.abs(bump)))*strength);
 return new THREE.Vector3((x*.75+side*(25+Math.abs(bump)))*strength,(y-205)*.6+bump,(z*.72+signZ*(26+Math.abs(bump)))*strength);
}
function updateScene() {
 if(!ready) return;
 const selected=new Set(selectedParts().map(p=>p.id));
 const hasSelection=selected.size>0;
 const stepOnly=state.only&&!hasSelection;
 const allowOptional=byId('options').checked;
 const allowWires=byId('wires').checked;
 for(const {part,group,center,delta} of objects){
   const inStep=isStepPart(part);
   const hit=selected.has(part.id);
   group.visible=(allowOptional||!part.opt||hit) && (allowWires||part.cat!=='wire'||hit) &&
     (!state.only||(hasSelection?hit:inStep));
   group.position.copy(center).addScaledVector(delta,state.amount);
   if(!group.visible)continue;
   const ghost=state.mode==='cut'&&part.cover&&!hit;
   const variant=hit?'selected':ghost?'ghost':hasSelection?'dim':state.only||state.step>0?(inStep?'active':'base'):'base';
   for(const m of group.children){
     m.material=material(m.userData.color,variant);
     m.renderOrder=ghost?4:0;
   }
 }
}
function cameraUpdate() {
 const offset=new THREE.Vector3().setFromSpherical(spherical);
 camera.position.copy(target).add(offset);
 camera.lookAt(target);
}
function requestRender() {
 if(!ready||pending)return;
 pending=true;
 requestAnimationFrame(()=>{
   pending=false;
   updateScene();cameraUpdate();renderer.render(scene,camera);
 });
}
function fit(moveTarget) {
 if(!ready)return;
 updateScene();
 const box=new THREE.Box3();
 for(const {group} of objects){
   if(!group.visible)continue;
   if(group.userData.part.cat==='wire'&&!state.only)continue;
   box.expandByObject(group);
 }
 if(box.isEmpty())return;
 if(moveTarget)box.getCenter(target);
 const size=box.getSize(new THREE.Vector3());
 const perspective=THREE.MathUtils.degToRad(camera.fov/2);
 const depth=size.z*.39;
 const vertical=size.y*.57/Math.tan(perspective);
 const horizontal=(size.x*.6+size.z*.18)/(Math.tan(perspective)*camera.aspect);
 spherical.radius=Math.max(43,(Math.max(vertical,horizontal)+depth)*1.06);
 requestRender();
}
function setView(view) {
 state.camera=view;
 if(!ready){refreshControls();return;}
 [spherical.theta,spherical.phi]=poses[view];
 refreshControls();fit(true);
}
function resize() {
 if(!ready)return;
 const width=viewport.clientWidth,height=viewport.clientHeight;
 if(!width||!height)return;
 renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();
 requestRender();
}
function selectFromCanvas(event) {
 const rect=renderer.domElement.getBoundingClientRect();
 mouse.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
 scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);
 raycaster.setFromCamera(mouse,camera);
 const candidates=objects.filter(o=>o.group.visible).flatMap(o=>o.group.children)
   .filter(m=>m.material.opacity>.2);
 const found=raycaster.intersectObjects(candidates,false)[0];
 if(found)choosePart(found.object.userData.part.id,true);
 else if(state.selection)choosePart(state.selection);
}
function cameraGestures(canvas) {
 const points=new Map();
 let moved=false, pinch=null;
 canvas.addEventListener('contextmenu',event=>event.preventDefault());
 canvas.addEventListener('pointerdown',event=>{
   canvas.setPointerCapture(event.pointerId);
   points.set(event.pointerId,{x:event.clientX,y:event.clientY,button:event.button});
   if(points.size===1){moved=false;pinch=null;}
   if(points.size===2){moved=true;pinch=distance();}
 });
 function distance() {
   const [a,b]=points.values();
   return Math.hypot(a.x-b.x,a.y-b.y);
 }
 canvas.addEventListener('pointermove',event=>{
   const prev=points.get(event.pointerId);
   if(!prev)return;
   const dx=event.clientX-prev.x,dy=event.clientY-prev.y;
   if(Math.abs(dx)+Math.abs(dy)>2)moved=true;
   points.set(event.pointerId,{x:event.clientX,y:event.clientY,button:prev.button});
   if(points.size>=2){
     const d=distance();
     if(pinch&&d>5)spherical.radius=THREE.MathUtils.clamp(spherical.radius*pinch/d,25,3200);
     pinch=d;
   } else if(prev.button===2||prev.button===1||event.shiftKey){
     const scale=spherical.radius/viewport.clientHeight*.68;
     const right=new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,0);
     const up=new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,1);
     target.addScaledVector(right,-dx*scale).addScaledVector(up,dy*scale);
   } else {
     spherical.theta-=dx*.008;
     spherical.phi=THREE.MathUtils.clamp(spherical.phi-dy*.008,.07,Math.PI-.07);
   }
   requestRender();
 });
 canvas.addEventListener('pointerup',event=>{
   if(points.size===1&&!moved&&event.button===0)selectFromCanvas(event);
   points.delete(event.pointerId);pinch=null;
 });
 canvas.addEventListener('pointercancel',event=>{points.delete(event.pointerId);pinch=null;});
 canvas.addEventListener('wheel',event=>{
   event.preventDefault();
   spherical.radius=THREE.MathUtils.clamp(spherical.radius*Math.exp(event.deltaY*.001),25,3200);
   requestRender();
 },{passive:false});
 canvas.addEventListener('keydown',event=>{
   if(event.key==='Escape'){if(state.selection)choosePart(state.selection);return;}
   if(event.key==='ArrowLeft')spherical.theta-=.1;
   else if(event.key==='ArrowRight')spherical.theta+=.1;
   else if(event.key==='ArrowUp')spherical.phi=Math.max(.07,spherical.phi-.1);
   else if(event.key==='ArrowDown')spherical.phi=Math.min(Math.PI-.07,spherical.phi+.1);
   else if(event.key==='+'||event.key==='=')spherical.radius=Math.max(25,spherical.radius*.9);
   else if(event.key==='-')spherical.radius=Math.min(3200,spherical.radius*1.1);
   else return;
   event.preventDefault();requestRender();
 });
}
function showStaticOverview(message) {
 const status=byId('scene-status'), img=byId('static-overview');
 status.textContent=message;
 status.hidden=false;
 if(DATA.photos.overview){
   img.src=DATA.photos.overview;
   img.hidden=false;
   viewport.classList.add('fallback');
 }
}
function boot() {
 try {
   viewport=byId('viewport');
   renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'high-performance'});
   renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.8));
   renderer.setClearColor(0,0);
   renderer.outputColorSpace=THREE.SRGBColorSpace;
   renderer.toneMapping=THREE.ACESFilmicToneMapping;
   renderer.toneMappingExposure=1.28;
   const canvas=renderer.domElement;
   canvas.tabIndex=0;canvas.setAttribute('aria-label','互動 3D 模型。方向鍵旋轉，加減鍵縮放。');
   viewport.prepend(canvas);
   scene=new THREE.Scene();
   camera=new THREE.PerspectiveCamera(35,1,.5,5000);
   target=new THREE.Vector3(0,220,0);
   spherical=new THREE.Spherical(860,poses.iso[1],poses.iso[0]);
   raycaster=new THREE.Raycaster();mouse=new THREE.Vector2();
   rig=new THREE.Group();scene.add(rig);
   scene.add(new THREE.HemisphereLight('#e7f1ff','#6f8193',2.05));
   const key=new THREE.DirectionalLight('#fff1de',2.1);key.position.set(180,400,330);scene.add(key);
   const rim=new THREE.DirectionalLight('#8ab5e8',1.6);rim.position.set(-280,270,-250);scene.add(rim);
   const grid=new THREE.GridHelper(900,36,0x42617b,0x294156);grid.position.y=-2;scene.add(grid);
   DATA.parts.forEach((part,i)=>objects.push(makePart(part,i)));
   ready=true;
   resize();fit(true);cameraGestures(canvas);
   new ResizeObserver(resize).observe(viewport);
   byId('scene-status').hidden=true;
   canvas.addEventListener('webglcontextlost',event=>{
     event.preventDefault();ready=false;
     showStaticOverview('3D 圖形連線已中斷，重新開啟檔案可再載入模型。');
   });
   document.documentElement.dataset.ready='true';
 } catch(error){
   console.error(error);
   showStaticOverview('這個瀏覽器目前無法繪製 3D 模型。BOM、組裝步驟和接線圖仍可使用。');
   document.documentElement.dataset.ready='false';
 }
}
requestAnimationFrame(boot);
