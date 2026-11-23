// Exercise the shipped script with a small DOM adapter, without a browser.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = {}; }
  appendChild(child) { this.children.push(child); }
  prepend(child) { this.children.unshift(child); }
  replaceChildren() { this.children = []; this.textContent = ''; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(k, v) { this.events[k] = v; }
  set innerHTML(_) { throw Error('Untrusted metadata must never use innerHTML'); }
}
function setup() {
  const photo = new Element('div'), fields = new Element('div');
  const body = {querySelector: s => s === '.view-photo-panel' ? photo : fields};
  const T = Object.fromEntries(['information','source','unknown','product_page','rights','verified',
    'unverified','unverified_note','evidence','attribution','loading','unavailable'].map(k => ['photo_'+k,k]));
  const context = vm.createContext({URL, T, INGRESS: '/ingress',
    document: {createElement: tag => new Element(tag), getElementById: () => body},
    fetch: () => { throw Error('Unexpected fetch'); }});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/photo-info.js'),'utf8'),context);
  return {context,photo,fields};
}
const text = el => [el.textContent || '', ...el.children.map(text)].join(' ');
test('unverified info is hidden until clicked, toggles accessibly and does not open lightbox', () => {
  const {context,photo,fields} = setup();
  context.addPhotoInformation(1,{image:'photo.jpg',image_info:{source:{source_name:'Independent merchant',
    page_url:'https://example.org/product',rights:{status:'unverified'}}}});
  const button = photo.children[0], panel = fields.children[0];
  assert.equal(panel.hidden,true);
  assert.equal(button.attrs['aria-expanded'],'false');
  let stopped = false;
  button.events.click({stopPropagation(){stopped=true;}});
  assert.ok(stopped);
  assert.equal(panel.hidden,false);
  assert.equal(button.attrs['aria-expanded'],'true');
  assert.match(text(panel),/Independent merchant/);
  assert.match(text(panel),/unverified_note/);
  const link = panel.children.flatMap(e=>e.children).find(e=>e.tag==='a');
  assert.equal(link.href,'https://example.org/product');
  assert.equal(link.rel,'noopener noreferrer');
  button.events.click({stopPropagation(){}});
  assert.equal(panel.hidden,true);
});
test('verified evidence and credits are text; hostile links are never clickable', () => {
  const {context} = setup(), panel = new Element('section');
  context.renderPhotoInformation(panel,{source:{source_name:'<img onerror=alert(1)>',
    page_url:'javascript:alert(1)',rights:{status:'verified',reference:'<script>evidence</script>'},
    attribution:'Photographer'}});
  assert.match(text(panel),/<img onerror=alert\(1\)>/);
  assert.match(text(panel),/<script>evidence<\/script>/);
  assert.match(text(panel),/Photographer/);
  assert.doesNotMatch(text(panel),/unverified_note/);
  assert.equal(panel.children.flatMap(e=>e.children).filter(e=>e.tag==='a').length,0);
  for (const value of ['data:text/html,hi','//example.org','http://example.org','https://user:pass@example.org',{},null])
    assert.equal(context.photoSourceLink(value),null);
});
test('legacy photos have unknown source and unverified rights; image URL supplies fallback name', () => {
  const {context} = setup(), panel = new Element('section');
  context.renderPhotoInformation(panel,{source:null});
  assert.match(text(panel),/unknown/);
  assert.match(text(panel),/unverified_note/);
  context.renderPhotoInformation(panel,{source:{url:'https://images.example.org/a.jpg'}});
  assert.match(text(panel),/images.example.org/);
  assert.doesNotMatch(text(panel),/unknown/);
});
test('no photo means no information control', () => {
  const {context,photo,fields} = setup();
  context.addPhotoInformation(1,{});
  assert.equal(photo.children.length,0);
  assert.equal(fields.children.length,0);
});
test('fallback card data reads current metadata through ingress; errors do not invent rights', async () => {
  const {context,photo,fields} = setup();
  context.fetch = async url => {
    assert.equal(url,'/ingress/api/wine/7');
    return {ok:true,json:async()=>({ok:true,wine:{image:'a.jpg',image_info:{source:{source_name:'Source'}}}})};
  };
  context.addPhotoInformation(7,{image:'a.jpg'});
  photo.children[0].events.click({stopPropagation(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(text(fields.children[0]),/Source/);
  const failed = setup();
  failed.context.fetch = async()=>({ok:false});
  failed.context.addPhotoInformation(7,{image:'a.jpg'});
  failed.photo.children[0].events.click({stopPropagation(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(failed.fields.children[0].textContent,'unavailable');
});
