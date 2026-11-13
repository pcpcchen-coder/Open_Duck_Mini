const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class FakeElement {
  constructor(id='') {
    this.id=id;
    this.value='';
    this.checked=id==='options';
    this.dataset={};
    this.hidden=false;
    this.open=false;
    this.scrollTop=0;
    this.clientWidth=870;
    this.clientHeight=520;
    this.listeners={};
    this.attributes={};
  }
  setAttribute(k,v){ this.attributes[k]=String(v); }
  addEventListener(n,f){ this.listeners[n]=f; }
  click(extra={}){ this.listeners.click?.({target:this,...extra}); }
  closest(){ return this; }
  prepend(){ }
  showModal(){ this.open=true; }
  close(){ this.open=false; }
  querySelector(){ return null; }
  getBoundingClientRect(){ return {left:0,top:0,width:870,height:520}; }
}
const els=new Map();
const get=id=>{if(!els.has(id))els.set(id,new FakeElement(id));return els.get(id);};
get('category').value='all';
const modeButtons=['assembly','exploded','cut'].map(mode=>Object.assign(new FakeElement(),{dataset:{mode}}));
const viewButtons=['iso','front','back','side'].map(view=>Object.assign(new FakeElement(),{dataset:{view}}));
const document={
  getElementById:get, documentElement:{dataset:{}},
  querySelectorAll: q=>q==='[data-mode]'?modeButtons:viewButtons,
};
const saved={};
const queued=[];
class FakeRenderer {
  constructor(){ this.domElement=new FakeElement('canvas');this.frames=0; }
  setPixelRatio(){} setClearColor(){} setSize(){}
  render(scene,camera){scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);this.frames++;}
}
const context=vm.createContext({console:{...console,warn:()=>{}}, document,window:{devicePixelRatio:1},
  TextDecoder, TextEncoder, atob, btoa, Uint8Array, Float32Array, Int16Array, Uint16Array, Uint32Array, DataView, ArrayBuffer,
  localStorage:{getItem:key=>saved[key]??null,setItem:(k,v)=>{saved[k]=v;}},
  requestAnimationFrame:callback=>queued.push(callback), ResizeObserver:class{observe(){}}, FakeRenderer,
});
const html=fs.readFileSync('/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html','utf8');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length,5);
assert.equal((html.match(/<(?:script|link|img)[^>]+(?:src|href)="https?:/g)||[]).length,0);
for (const [i,[,source]] of scripts.entries()) {
  vm.runInContext(source,context,{filename:'embedded-'+i+'.js',timeout:18000});
  if(i===0)vm.runInContext('THREE.WebGLRenderer=FakeRenderer',context);
}
function frames(){while(queued.length)queued.shift()();}
function app(expr){return vm.runInContext(expr,context);}
frames();
assert.equal(document.documentElement.dataset.ready,'true');
assert.equal(app('objects.length'),131);
assert.equal(app('DATA.parts.filter(p=>p.cat==="print").length'),51);
assert.equal(app('DATA.bom.filter(p=>p.cat==="print").length'),36);
assert.equal(app('DATA.parts.filter(p=>p.motor).map(p=>p.motor).sort((a,b)=>a-b).join(",")'),'10,11,12,13,14,20,21,22,23,24,30,31,32,33');
assert(app('renderer.frames')>0);
assert.equal(app('geometryCache.size'),52);
assert(app('objects.every(o=>o.group.children.length>0 && o.center.toArray().every(Number.isFinite))'));
assert(app('objects.flatMap(o=>o.group.children).every(m=>m.geometry.boundingBox!==null)'));
const extent=app('new THREE.Box3().setFromObject(rig).getSize(new THREE.Vector3()).toArray().map(x=>Math.round(x)).join(",")');
console.log('CAD pose envelope (mm)',extent);
modeButtons[1].click();frames();
assert.equal(get('spread-value').value,'56%');
assert(app('objects.filter(o=>o.group.position.distanceTo(o.center)>3).length')>110);
get('search').value='ID 24';get('search').listeners.input();
assert.equal((get('bom-list').innerHTML.match(/data-bom=/g)||[]).length,1);
app('choosePart("sts")');frames();
assert.equal((get('bom-list').innerHTML.match(/data-instance=/g)||[]).length,14);
app('choosePart("servo-24")');frames();
assert(get('selection').innerHTML.includes('ID 24 · 左腳踝舵機'));
get('only-focus').click();frames();
assert.equal(app('objects.filter(o=>o.group.visible).map(o=>o.part.id).join(",")'),'servo-24');
assert(app('camera.position.toArray().every(Number.isFinite)'));
get('only-focus').click();frames();
get('search').value='';get('search').listeners.input();
app('chooseStep(9)');frames();
assert(get('details').innerHTML.includes('2S 電池艙與供電'));
get('step-only').checked=true;get('step-only').listeners.change();
assert(get('bom-list').innerHTML.includes('data-bom="ubec"'));
get('details').listeners.click({target:new FakeElement('mark')});
assert(get('progress-text').textContent.includes('1／14'));
assert.equal(Object.values(saved)[0],'[9]');
get('wire-guide').click();
assert(get('dialog').open && get('dialog-content').innerHTML.includes('GPIO 27'));
get('close-dialog').click();
assert(!get('dialog').open);
app('showPhoto("assembled","驗證圖片")');
assert(get('dialog-content').innerHTML.includes('data:image/jpeg;base64,'));
app('chooseStep(12)');frames();
assert(get('wires').checked);
assert(app('objects.filter(o=>o.part.cat==="wire"&&o.group.visible).length')>=10);
app('chooseStep(13)');frames();
assert(get('details').innerHTML.includes('首次動作測試'));
console.log('Offline embedding, decoded geometries, IDs, assembly state, explosion, filters, isolation, photos, pin tables and saved progress passed. WebGL draw is stubbed.');
