// Offline checks for the shipped adapter. Never attach or call Arena APIs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function runtime(findModule=()=>({getExportByName:name=>name})) {
  const calls=[];
  const context={rpc:{}, handlers:{}, Process:{findModuleByName:findModule},
    nativeOptions:{},
    NativeFunction:function(name,returns,args,options){if(options)context.nativeOptions[name]=options;return (...args)=>{calls.push(name);if(context.handlers[name])return context.handlers[name](...args);if(name==='il2cpp_gchandle_get_target')return context.manager;throw new Error('Unexpected native call: '+name);};}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/mtga_tracker/assets/arena_decks.js'),'utf8'),context);
  context.manager={equals:other=>other===context.manager};
  vm.runInContext("connection={account:'fixture',managerHandle:'held'};root=()=>globalThis.manager;accountId=()=> 'fixture';deckScreenOpen=()=>true;",context);
  return {context,calls};
}

test('the native account/service guard rejects an account switch',()=>{
  const {context,calls}=runtime();
  vm.runInContext("accountId=()=> 'another-account'",context);
  assert.throws(()=>vm.runInContext("guard('fixture',true)",context),/account or session changed/);
  assert.deepEqual(calls,[]);
});

test('an inactive Decks screen blocks writes before any service request',()=>{
  const {context,calls}=runtime();
  vm.runInContext('deckScreenOpen=()=>false',context);
  assert.throws(()=>vm.runInContext("guard('fixture',true)",context),/outside a match/);
  assert.deepEqual(calls,['il2cpp_gchandle_get_target']);
});

test('read polling survives a native UI rebuild while preserving account/service identity',()=>{
  const {context}=runtime();
  vm.runInContext('deckScreenOpen=()=>false',context);
  assert.equal(vm.runInContext("guard('fixture')",context),context.manager);
});

test('Arena-owned attached threads are never detached',()=>{
  const {context,calls}=runtime();
  context.handlers.il2cpp_thread_current=()=>({isNull:()=>false});
  assert.equal(vm.runInContext('attached(()=>42)',context),42);
  assert.deepEqual(calls,['il2cpp_thread_current']);
});

test('native removal refuses a changed snapshot before a delete call',async()=>{
  const {context,calls}=runtime();
  context.old={arena_id:'original',is_net_deck:false,summary:{Description:''},piles:[{quantity:60}],skins:[]};
  context.current=structuredClone(context.old);context.current.piles[0].quantity=59;
  vm.runInContext(`
    promiseCall=async(account,start,extract,write)=>{guard(account,write);return start();};
    cachedDecks=()=>[{}];ref=()=>({});fieldAt=()=>({});guidText=()=>'original';deckSnapshot=()=>globalThis.current;
  `,context);
  await assert.rejects(vm.runInContext("removeDeck('fixture',old)",context),/changed after backup/);
  assert.deepEqual(calls,['il2cpp_gchandle_get_target']);
});

test('full Arena slots block native construction and creation',async()=>{
  const {context,calls}=runtime();
  vm.runInContext(`
    onUnityThread=async run=>run();
    findMethod=()=>({});invoke=()=>({});
  `,context);
  context.handlers.il2cpp_object_unbox=()=>({readU8:()=>1});
  await assert.rejects(vm.runInContext("createDeck('fixture',{},'new')",context),/slots are full/);
  assert.deepEqual(calls,['il2cpp_gchandle_get_target','il2cpp_object_unbox']);
});

test('native text preparation requires Decks before touching import providers',async()=>{
  const {context,calls}=runtime();
  vm.runInContext('deckScreenOpen=()=>false;onUnityThread=async run=>run()',context);
  await assert.rejects(vm.runInContext("prepareImport('fixture','Deck\\n4 Forest','Test','12345678-1234-1234-1234-123456789abc')",context),/outside a match/);
  assert.deepEqual(calls,['il2cpp_gchandle_get_target']);
});

test('snapshot verification survives sorted persisted keys and still rejects changed cards',()=>{
  const {context}=runtime();
  context.original={name:'Offline fixture',arena_id:'id',summary:{Name:'Offline fixture',Description:null},piles:[{pile:1,entries:[{id:123,quantity:60}]}],skins:[]};
  const sorted=item=>Array.isArray(item)?item.map(sorted):item&&typeof item==='object'?Object.fromEntries(Object.keys(item).sort().map(key=>[key,sorted(item[key])])):item;
  context.saved=sorted(context.original);context.saved.summary.Description='';
  assert.notEqual(JSON.stringify(context.original),JSON.stringify(context.saved));
  assert.equal(vm.runInContext('sameSourceSnapshot(original,saved)',context),true);
  context.saved.piles[0].entries[0].quantity=59;
  assert.equal(vm.runInContext('sameSourceSnapshot(original,saved)',context),false);
});

function decksScreen(context,{screens=1,loading=false,finishedAtOnce=true}={}) {
  context.NULL=null;context.written=[];
  context.Memory={alloc:()=>({writeU8:v=>context.written.push(['hasValue',v]),writeS32(){},add:n=>['at',n]}),
    copy:(to,from,size)=>context.written.push(['guid',to,from,size])};
  context.handlers.il2cpp_class_get_type=()=>'type';
  context.handlers.il2cpp_type_get_object=()=>'type-object';
  context.invoked=[];
  context.screens=screens;context.loading=loading;context.finishedAtOnce=finishedAtOnce;
  vm.runInContext(`
    findMethod=(key,name)=>name;objectMethod=(object,name)=>name;
    array=()=>({length:globalThis.screens,data:{readPointer:()=>'controller'}});
    selectorObjects=()=>Array.from({length:globalThis.screens});
    ref=(object,name)=>({isNull:()=>name!=='_loadDecksCoroutine' || !globalThis.loading});
    fieldAt=()=>({readS32:()=>2});
    invoke=(method)=>{globalThis.invoked.push(method);
      return {isNull:()=>method==='StartCoroutine' && globalThis.finishedAtOnce};};
  `,context);
}

test('the Decks redraw starts Arena’s own list load on the open screen',()=>{
  const {context}=runtime();
  decksScreen(context);
  assert.equal(vm.runInContext('reloadDecksScreen()',context),true);
  assert.deepEqual(context.invoked,['FindObjectsOfType','Coroutine_LoadDecks','StartCoroutine']);
});

test('the Decks redraw leaves an Arena load already in progress alone',()=>{
  const {context}=runtime();
  decksScreen(context,{loading:true});
  assert.equal(vm.runInContext('reloadDecksScreen()',context),true);
  assert.deepEqual(context.invoked,['FindObjectsOfType']);
});

test('the Decks redraw calls nothing when the Decks screen is closed',()=>{
  const {context}=runtime();
  decksScreen(context,{screens:0});
  assert.equal(vm.runInContext('reloadDecksScreen()',context),false);
  assert.deepEqual(context.invoked,['FindObjectsOfType']);
});

test('the Decks redraw waits while an Arena request is pending',async()=>{
  const {context}=runtime();
  decksScreen(context);
  context.setTimeout=resolve=>resolve();
  vm.runInContext("onUnityThread=async run=>run();pending='request';",context);
  assert.equal(await vm.runInContext("refreshScreen('fixture')",context),false);
  assert.deepEqual(context.invoked,[]);
});

test('the Decks redraw selects the deck a job created',()=>{
  const {context}=runtime();
  decksScreen(context);
  context.handlers.il2cpp_gchandle_new=()=>'held';
  context.handlers.il2cpp_gchandle_free=()=>undefined;
  context.handlers.il2cpp_object_unbox=()=>'guid-bytes';
  vm.runInContext("parseGuid=()=>'guid'",context);
  assert.equal(vm.runInContext("reloadDecksScreen('12345678-1234-1234-1234-123456789abc')",context),true);
  // The first byte written is FindObjectsOfType's includeInactive flag.
  assert.deepEqual(context.written.slice(1),[['hasValue',1],['guid',['at',4],'guid-bytes',16]]);
  assert.deepEqual(context.invoked,['FindObjectsOfType','Coroutine_LoadDecks','StartCoroutine']);
});

test('the Decks redraw rejects a malformed deck to select before touching Arena',async()=>{
  const {context}=runtime();
  decksScreen(context);
  await assert.rejects(vm.runInContext("refreshScreen('fixture','not-a-deck')",context),/Invalid deck/);
  assert.deepEqual(context.invoked,[]);
});

function scrollGrid(context,{tileId='made',active=1}={}) {
  // Grid content 5600 tall pinned at the top, 1000 visible, tile 2800 down.
  const reader=values=>({readFloat:()=>values[0],readU8:()=>values[0],add:n=>reader(values.slice(n/4))});
  context.scrolled=[];context.invoked=[];
  context.Memory={alloc:()=>{const written=[];context.scrolled.push(written);
    return {writeFloat:v=>written.push(v),add:()=>({writeFloat:v=>written.push(v)})};}};
  context.handlers.il2cpp_object_unbox=boxed=>boxed.box;
  context.handlers.il2cpp_class_get_type=()=>'type';
  context.handlers.il2cpp_type_get_object=()=>'type-object';
  const object={isNull:()=>false};
  context.results={
    get_gameObject:()=>object, get_activeInHierarchy:()=>({box:reader([active])}), GetComponent:()=>object,
    get_content:()=>({isNull:()=>false,kind:'content'}), get_viewport:()=>({isNull:()=>false,kind:'viewport'}),
    get_rect:target=>({box:target.kind==='content'?reader([0,-5600,1880,5600]):reader([0,-1000,1880,1000])}),
    get_transform:()=>object, get_position:()=>({box:'position'}), InverseTransformPoint:()=>({box:reader([-940,-2800])}),
    get_normalizedPosition:()=>({box:reader([0,0])}), StopMovement:()=>null, set_normalizedPosition:()=>null,
  };
  context.tileId=tileId;
  vm.runInContext(`
    selectorObjects=()=>['selector'];objectMethod=(object,name)=>name;
    ref=()=>({isNull:()=>false});fieldAt=()=>({readU8:()=>1});guidText=()=>globalThis.tileId;
    invoke=(method,object)=>{globalThis.invoked.push(method);return globalThis.results[method](object);};
  `,context);
}

test('the Decks redraw centers the new deck in Arena’s scrolling grid',()=>{
  const {context}=runtime();
  scrollGrid(context);
  assert.equal(vm.runInContext("scrollToSelectedDeck('made')",context),true);
  // Offset 2800 - 500 = 2300 of a 4600 scroll range: halfway down.
  assert.deepEqual(context.scrolled.at(-1),[0,0.5]);
  assert.deepEqual(context.invoked.slice(-2),['StopMovement','set_normalizedPosition']);
});

test('the Decks redraw waits for the rebuilt tile before scrolling',()=>{
  const {context}=runtime();
  scrollGrid(context,{tileId:'older'});
  assert.equal(vm.runInContext("scrollToSelectedDeck('made')",context),false);
  assert.ok(!context.invoked.includes('set_normalizedPosition'));
});

test('the Decks redraw does not scroll to a deck in a closed folder',()=>{
  const {context}=runtime();
  scrollGrid(context,{active:0});
  assert.equal(vm.runInContext("scrollToSelectedDeck('made')",context),true);
  assert.ok(!context.invoked.includes('set_normalizedPosition'));
});

function connecting(context,{platform,arch,version='6000.3.14f1'}) {
  context.Process.platform=platform;context.Process.arch=arch;context.version=version;
  context.handlers.il2cpp_thread_current=()=>({isNull:()=>false});
  vm.runInContext(`
    connection=null;discover=()=>{};onUnityThread=async run=>run();checkedHandleABI=()=>{};
    findMethod=()=>'method';invoke=()=>'version';text=()=>globalThis.version;deckScreenOpen=()=>false;
  `,context);
}

test('the adapter accepts x64 Windows Arena on the supported Unity build',async()=>{
  const {context}=runtime();
  connecting(context,{platform:'windows',arch:'x64'});
  // Past the build check, it stops only because Arena is not on Decks.
  await assert.rejects(vm.runInContext('openConnection()',context),/Decks screen/);
});

test('the adapter names an unsupported Arena build instead of attaching to it',async()=>{
  for (const build of [{platform:'windows',arch:'ia32'},{platform:'darwin',arch:'x64'},{platform:'windows',arch:'x64',version:'6000.4.0f1'}]) {
    const {context}=runtime();
    connecting(context,build);
    await assert.rejects(vm.runInContext('openConnection()',context),/not supported by the native deck adapter yet \(Unity/);
  }
});

// Windows Arena embeds Mono rather than IL2CPP.
function monoRuntime() {
  const result=runtime(name=>name==='mono-2.0-bdwgc.dll' ? {getExportByName:name=>name} : null);
  const pointer=name=>({name,isNull:()=>false});
  result.context.NULL={isNull:()=>true};
  result.context.Memory={alloc:()=>{let value=null;return {writePointer(v){value=v;return this;},readPointer:()=>value};}};
  result.context.handlers.mono_domain_get=()=>pointer('domain');
  result.pointer=pointer;
  return result;
}

test('without IL2CPP the adapter uses Arena’s Mono runtime',()=>{
  const {context}=monoRuntime();
  assert.equal(vm.runInContext('RUNTIME',context),'Mono');
  assert.equal(vm.runInContext('RUNTIME',runtime().context),'IL2CPP');
});

test('an Arena build with neither runtime refuses to load',()=>{
  assert.throws(()=>runtime(()=>null),/IL2CPP or Mono/);
});

test('Mono: an Arena-owned attached thread is never detached',()=>{
  const {context,calls}=monoRuntime();
  assert.equal(vm.runInContext('attached(()=>42)',context),42);
  assert.deepEqual(calls,['mono_domain_get']);
});

test('Mono: the probe attaches to the root domain and detaches only its own thread',()=>{
  const {context,calls,pointer}=monoRuntime();
  context.handlers.mono_domain_get=()=>context.NULL;
  context.handlers.mono_get_root_domain=()=>pointer('root');
  const attachedTo=[];
  context.handlers.mono_thread_attach=domain=>{attachedTo.push(domain.name);return pointer('thread');};
  context.handlers.mono_thread_detach=thread=>{attachedTo.push('detach:'+thread.name);};
  assert.equal(vm.runInContext('attached(()=>7)',context),7);
  assert.deepEqual(attachedTo,['root','detach:thread']);
  assert.ok(calls.includes('mono_thread_detach'));
});

test('Mono: reference fields take the reference itself; value fields a pointer to the value',()=>{
  // mono_field_set_value dereferences only pointer-typed fields. Passing a
  // pointer to a reference stores the pointer (seen live as a garbage deck name).
  const {context}=monoRuntime();
  const written=[];
  context.handlers.mono_field_set_value=(object,field,value)=>{written.push({object,field,value});};
  vm.runInContext("fieldSetObject('summary','Name','title-string')",context);
  vm.runInContext("fieldSet('summary','DeckId','unboxed-guid-data')",context);
  assert.deepEqual(written,[
    {object:'summary',field:'Name',value:'title-string'},
    {object:'summary',field:'DeckId',value:'unboxed-guid-data'},
  ]);
});

test('Mono: static and constant fields are read through their class vtable',()=>{
  const {context}=monoRuntime();
  context.handlers.mono_field_get_parent=field=>'parent-of-'+field;
  context.handlers.mono_class_vtable=(domain,klass)=>`vtable(${domain.name},${klass})`;
  let read=null;
  context.handlers.mono_field_static_get_value=(vtable,field,out)=>{read=[vtable,field,out];};
  vm.runInContext("staticValue('Pile','out')",context);
  assert.deepEqual(read,['vtable(domain,parent-of-Pile)','Pile','out']);
});

test('Mono: method parameters come from the method signature',()=>{
  const {context}=monoRuntime();
  context.handlers.mono_method_signature=method=>'sig:'+method;
  context.handlers.mono_signature_get_param_count=sig=>sig==='sig:Parse' ? 2 : 0;
  const types=['System.String','System.Type'];
  let next=0;
  context.handlers.mono_signature_get_params=()=>types[next++];
  assert.equal(vm.runInContext("methodCount('Parse')",context),2);
  assert.equal(vm.runInContext("methodParam('Parse',1)",context),'System.Type');
});

test('Mono: managed objects are created in the current domain',()=>{
  const {context}=monoRuntime();
  context.handlers.mono_string_new=(domain,text)=>`${domain.name}:${text}`;
  context.handlers.mono_type_get_object=(domain,type)=>`${domain.name}:${type}`;
  assert.equal(vm.runInContext("stringNew('Forest')",context),'domain:Forest');
  assert.equal(vm.runInContext("typeObject('Guid')",context),'domain:Guid');
});

test('pile names include only the enum’s own members, not System.Enum’s string constant',()=>{
  const {context,calls}=runtime();
  let stored=0;
  context.Memory={alloc:()=>({readS32:()=>stored})};
  const values={Main:1,Sideboard:2};
  context.handlers.il2cpp_field_static_get_value=field=>{stored=values[field];};
  vm.runInContext(`checkCardLayouts=()=>{};
    fields=()=>new Map([['Main','Main'],['Sideboard','Sideboard'],['enumSeperator','enumSeperator'],['value__','value__']]);
    meta=f=>f==='enumSeperator' ? {flags:0x56,type:'System.String'}
      : f==='value__' ? {flags:0x6,type:'System.Int32'} : {flags:0x56,type:'Wizards.Mtga.Decks.EDeckPile'};`,context);
  assert.deepEqual({...vm.runInContext('pileNames()',context)},{1:'Main',2:'Sideboard'});
  assert.deepEqual(calls,['il2cpp_field_static_get_value','il2cpp_field_static_get_value']);
});

test('Mono: managed calls let Mono handle its own null-reference faults',()=>{
  const {context}=monoRuntime();
  assert.deepEqual({...context.nativeOptions.mono_runtime_invoke},{exceptions:'propagate'});
  assert.equal(runtime().context.nativeOptions.il2cpp_runtime_invoke,undefined);
});

test('a rejected managed call names the exception type and nothing else',()=>{
  const {context}=monoRuntime();
  const name=text=>({readUtf8String:()=>text});
  context.Memory={alloc:()=>{let value=context.NULL;return {writePointer(v){value=v;return this;},readPointer:()=>value};}};
  context.handlers.mono_runtime_invoke=(method,object,params,error)=>{error.writePointer({isNull:()=>false});return context.NULL;};
  context.handlers.mono_object_get_class=()=>'exception-class';
  context.handlers.mono_class_get_namespace=()=>name('System');
  context.handlers.mono_class_get_name=()=>name('NullReferenceException');
  assert.throws(()=>vm.runInContext("invoke('TryImportDeck')",context),
    /^Error: Arena rejected the managed call \(System\.NullReferenceException\); no further calls made\.$/);
});

test('Nullable<Guid> arguments: a boxed Guid or null on Mono, the raw struct on IL2CPP',()=>{
  const mono=monoRuntime().context;
  assert.equal(vm.runInContext("nullableGuidArgument('boxed-guid')",mono),'boxed-guid');
  assert.equal(vm.runInContext('nullableGuidArgument(null)',mono),mono.NULL);

  const {context}=runtime();
  const bytes=new Uint8Array(32);
  const at=offset=>({writeU8:v=>{bytes[offset]=v;},add:n=>at(offset+n),offset});
  context.Memory={alloc:()=>at(0),copy:(to,from,size)=>{for(let i=0;i<size;i++)bytes[to.offset+i]=from[i];}};
  context.handlers.il2cpp_object_unbox=()=>Array.from({length:16},(_,i)=>i+1);
  vm.runInContext("nullableGuidArgument('boxed-guid')",context);
  assert.deepEqual(Array.from(bytes.slice(0,20)),[1,0,0,0,...Array.from({length:16},(_,i)=>i+1)]);
});
