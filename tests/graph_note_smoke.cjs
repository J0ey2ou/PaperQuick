// Run the exported graph against a tiny DOM to catch new relation-kind crashes.
const fs=require('fs'),vm=require('vm');
const blocks=[...fs.readFileSync('graph_template.html','utf8').matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)];
const draw=new Proxy({},{get:()=>()=>{}});
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{value:'',checked:true,style:{},classList:{toggle(){}},textContent:'',innerHTML:'',append(){},addEventListener(){},setPointerCapture(){},getBoundingClientRect(){return{left:0,top:0,width:1000,height:560}},getContext(){return draw}});return elements.get(id)}
const node=(id,title,extra={})=>({id,title,year:'2026',doi:'',status:'未读',projects:['Demo'],in_library:true,pdf:true,...extra});
element('data').textContent=JSON.stringify({nodes:[node('paper','Main paper'),node('related','Another paper'),node('note','Note <script>',{kind:'note',paper_id:'paper',pdf:false,status:'笔记'})],edges:[{source:'paper',target:'related',kind:'related',weight:1},{source:'paper',target:'note',kind:'note',weight:1}]});
const context={document:{getElementById:element,createElement:()=>element('option')},window:{devicePixelRatio:1},devicePixelRatio:1,console};
vm.runInNewContext(blocks.at(-1)[1]+`
tab('relationships');
if(!document.getElementById('stats').innerHTML.includes('<b>2</b>'))throw Error('Notes counted as papers');
if(!document.getElementById('list').innerHTML.includes('Note &lt;script&gt;'))throw Error('Note labels not escaped');
const notePoint=positions.get('note');canvas.onpointerdown({clientX:notePoint.x,clientY:notePoint.y,pointerId:1});
if(!document.getElementById('detail').innerHTML.includes('笔记关联'))throw Error('Missing note relation detail');
document.getElementById('candidate').checked=false;refresh();
`,context);
console.log('Offline graph passed: note and manual edges / counts / escaping / selection / candidate toggle');
