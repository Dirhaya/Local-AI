// Isolated rendering checks. No DOM layout, real browser or live backend is simulated as verified.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.join(__dirname,'..'),nodes=new Map();
function node(key){if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',hidden:false,tagName:'DIV',isConnected:true,classList:{toggle(){},remove(){}},addEventListener(){},replaceChildren(){this.innerHTML='';},focus(){},close(){this.open=false;},showModal(){this.open=true;}});return nodes.get(key);}
const ctx=vm.createContext({console,Date,URL,FormData,document:{querySelector:node,querySelectorAll:()=>[]},location:{hash:'#study'},setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},window:{},navigator:{}});
vm.runInContext(fs.readFileSync(path.join(root,'app/static/study.js'),'utf8'),ctx);
vm.runInContext(fs.readFileSync(path.join(root,'app/static/app.js'),'utf8').replace(/\nboot\(\);\s*$/,''),ctx);
function run(code){return vm.runInContext(code,ctx);}
run(`state.unlocked=true;state.view='study';state.health={models:[]};study.courses=[{id:'c',title:'Algebra'}];study.courseId='c';study.topics=[{id:'t',chapter:'3',section:'3.2',title:'<img src=x onerror=bad>',start_page:1,end_page:5}];study.topicId='t';study.progress={player_level:1,xp:0,next_level_xp:50,readiness_level:0,readiness_label:'Unassessed',practice_readiness:null,coverage:0,evidence_count:0,topics:[],evidence_window_days:30};`);
for(const tab of ['ask','practice','progress','materials']){
 run(`study.tab='${tab}';renderStudy();`);
 assert(nodes.get('#content').innerHTML.includes('YOU ARE HERE'));
 assert(nodes.get('#content').innerHTML.includes('&lt;img'));
 assert(!nodes.get('#content').innerHTML.includes('<img src=x'));
 assert(nodes.get('#study-panel').innerHTML.length>30);
}
run(`study.tab='practice';study.session={id:'s',mode:'exam',minutes:15,started_at:new Date().toISOString(),finished:false,questions:[{prompt:'Choose a valid result',options:['<script>bad</script>','B','C','D'],difficulty:2}]};renderStudy();`);
assert(!nodes.get('#study-panel').innerHTML.includes('<script>'));
assert(nodes.get('#study-panel').innerHTML.includes('&lt;script&gt;'));
assert(!nodes.get('#study-panel').innerHTML.includes('answer-correct'));
run(`study.session.questions[0].selected=1;renderStudy();`);
assert(nodes.get('#study-panel').innerHTML.includes('Solutions remain hidden'));
run(`state.view='updates';study.updates={version:'0.2.0',configured:false,automatic:false};renderUpdates();`);
assert(nodes.get('#content').innerHTML.includes('Release publisher not connected'));
assert(nodes.get('#content').innerHTML.includes('id="check-updates" disabled'));
const previous=nodes.get('#content').innerHTML;
run(`state.unlocked=false;renderStudy();`);
assert.strictEqual(nodes.get('#content').innerHTML,previous);
run(`clearStudy();`);
assert.strictEqual(run('study.courses.length'),0);
assert.strictEqual(run('study.session'),null);
(async()=>{
 const select={tagName:'SELECT',disabled:false,isConnected:true,textContent:'existing options'};
 ctx.testSelect=select;
 await run(`action(testSelect,async()=>{if(testSelect.textContent!=='existing options')throw new Error('select was overwritten')});`);
 assert.strictEqual(select.textContent,'existing options');
 console.log('26 isolated study/update rendering and state assertions passed. Browser layout and backend integration are not covered.');
})().catch(e=>{console.error(e);process.exitCode=1});
