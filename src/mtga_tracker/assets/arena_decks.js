'use strict';

// Native deck adapter. Checked IL2CPP helpers carried forward from the live POC.
// macOS Arena is an IL2CPP build; Windows Arena embeds Mono. Both run the same
// managed code with the same 64-bit object layouts (object header, arrays,
// strings, structs), so only the runtime API below differs between them.
const targets = new Set([
  'DecksManager', 'WrapperController', 'DeckManagerController', 'DeckViewSelector',
  'DeckFolderView', 'Client_Deck', 'Client_DeckSummary', 'WrapperDeckUtilities',
  'DeckServiceWrapperHelpers',
  'UnitySynchronizationContext',
  'Object', 'Resources', 'Component', 'Transform', 'Localize', 'Client_DeckContents',
  'Client_DeckCard', 'Client_CardSkin', 'EDeckPile',
  'TMP_Text', 'Application', 'GameObject',
  'Guid',
  'JsonConvert', 'DeckInfo', 'Languages', 'MTGALocalizedString', 'ScrollRect',
]);
const game = Process.findModuleByName('GameAssembly.dylib')
  ?? Process.findModuleByName('GameAssembly.dll');
const mono = game ? null : Process.findModuleByName('mono-2.0-bdwgc.dll');
if (!game && !mono) throw new Error('Arena’s scripting runtime (IL2CPP or Mono) was not found.');
const RUNTIME = game ? 'IL2CPP' : 'Mono';
const {
  isAttached, domainGet, threadAttach, threadDetach, images, imageCount, imageClass,
  className, classFromName, classNamespace, classMethods, classFields, fieldName, fieldType,
  fieldOffset, methodName, methodCount, methodParam, methodCode, typeName, free, objectClass,
  classParent, staticValue, fieldFlags, arrayLength, arrayElementSize, elementClass, stringLength,
  stringChars, runtimeInvoke, objectUnbox, classType, classValueSize, classIsValueType, typeObject,
  stringNew, fieldSet, fieldSetObject, handleNew, handleTarget, handleFree, nullableGuidArgument,
} = game ? il2cppRuntime() : monoRuntime();

function il2cppRuntime() {
  const api = (name, returns, args) =>
    new NativeFunction(game.getExportByName(`il2cpp_${name}`), returns, args);
  const domainGet = api('domain_get', 'pointer', []);
  const threadCurrent = api('thread_current', 'pointer', []);
  const assembliesGet = api('domain_get_assemblies', 'pointer', ['pointer', 'pointer']);
  const assemblyImage = api('assembly_get_image', 'pointer', ['pointer']);
  return {
    isAttached: () => !threadCurrent().isNull(),
    domainGet,
    threadAttach: api('thread_attach', 'pointer', ['pointer']),
    threadDetach: api('thread_detach', 'void', ['pointer']),
    images() {
      const count = Memory.alloc(Process.pointerSize);
      const assemblies = assembliesGet(domainGet(), count);
      const length = Process.pointerSize === 8 ? number(count.readU64()) : count.readU32();
      if (length > 1000) throw new Error('Unexpected assembly count.');
      return Array.from({length}, (_, i) => assemblyImage(assemblies.add(i * Process.pointerSize).readPointer()));
    },
    imageCount: api('image_get_class_count', 'size_t', ['pointer']),
    imageClass: api('image_get_class', 'pointer', ['pointer', 'size_t']),
    className: api('class_get_name', 'pointer', ['pointer']),
    classFromName: api('class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']),
    classNamespace: api('class_get_namespace', 'pointer', ['pointer']),
    classMethods: api('class_get_methods', 'pointer', ['pointer', 'pointer']),
    classFields: api('class_get_fields', 'pointer', ['pointer', 'pointer']),
    fieldName: api('field_get_name', 'pointer', ['pointer']),
    fieldType: api('field_get_type', 'pointer', ['pointer']),
    fieldOffset: api('field_get_offset', 'size_t', ['pointer']),
    methodName: api('method_get_name', 'pointer', ['pointer']),
    methodCount: api('method_get_param_count', 'uint', ['pointer']),
    methodParam: api('method_get_param', 'pointer', ['pointer', 'uint']),
    // MethodInfo starts with its compiled code pointer.
    methodCode: method => method.readPointer(),
    typeName: api('type_get_name', 'pointer', ['pointer']),
    free: api('free', 'void', ['pointer']),
    objectClass: api('object_get_class', 'pointer', ['pointer']),
    classParent: api('class_get_parent', 'pointer', ['pointer']),
    staticValue: api('field_static_get_value', 'void', ['pointer', 'pointer']),
    fieldFlags: api('field_get_flags', 'int', ['pointer']),
    arrayLength: api('array_length', 'uint', ['pointer']),
    arrayElementSize: api('array_element_size', 'int', ['pointer']),
    elementClass: api('class_get_element_class', 'pointer', ['pointer']),
    stringLength: api('string_length', 'int', ['pointer']),
    stringChars: api('string_chars', 'pointer', ['pointer']),
    runtimeInvoke: api('runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']),
    objectUnbox: api('object_unbox', 'pointer', ['pointer']),
    classType: api('class_get_type', 'pointer', ['pointer']),
    classValueSize: api('class_value_size', 'int', ['pointer', 'pointer']),
    classIsValueType: api('class_is_valuetype', 'bool', ['pointer']),
    typeObject: api('type_get_object', 'pointer', ['pointer']),
    stringNew: api('string_new', 'pointer', ['pointer']),
    fieldSet: api('field_set_value', 'void', ['pointer', 'pointer', 'pointer']),
    fieldSetObject: api('field_set_value_object', 'void', ['pointer', 'pointer', 'pointer']),
    // Unity 6 uses Il2CppGCHandle = void*, not the older uint32_t ABI.
    handleNew: api('gchandle_new', 'pointer', ['pointer', 'bool']),
    handleTarget: api('gchandle_get_target', 'pointer', ['pointer']),
    handleFree: api('gchandle_free', 'void', ['pointer']),
    // A Nullable<Guid> argument is the struct itself: HasValue byte, then the
    // Guid at +4 (Arena's 20-byte layout).
    nullableGuidArgument(boxedGuid) {
      const value = Memory.alloc(32);
      if (boxedGuid) { value.writeU8(1); Memory.copy(value.add(4), objectUnbox(boxedGuid), 16); }
      return value;
    },
  };
}

// The same helpers over Mono's embedding API. Mono takes an explicit domain
// where IL2CPP has one global domain, and reads method parameters through the
// method signature.
function monoRuntime() {
  const api = (name, returns, args, options) =>
    new NativeFunction(mono.getExportByName(`mono_${name}`), returns, args, options);
  const rootDomain = api('get_root_domain', 'pointer', []);
  // The calling thread's domain; null on a thread Mono has never attached.
  const currentDomain = api('domain_get', 'pointer', []);
  const domain = () => { const value = currentDomain(); return value.isNull() ? rootDomain() : value; };
  const assemblyForeach = api('assembly_foreach', 'void', ['pointer', 'pointer']);
  const assemblyImage = api('assembly_get_image', 'pointer', ['pointer']);
  const tableRows = api('image_get_table_rows', 'int', ['pointer', 'int']);
  const classGet = api('class_get', 'pointer', ['pointer', 'uint32']);
  const signature = api('method_signature', 'pointer', ['pointer']);
  const paramCount = api('signature_get_param_count', 'uint32', ['pointer']);
  const params = api('signature_get_params', 'pointer', ['pointer', 'pointer']);
  const fieldParent = api('field_get_parent', 'pointer', ['pointer']);
  const classVtable = api('class_vtable', 'pointer', ['pointer', 'pointer']);
  const staticGet = api('field_static_get_value', 'void', ['pointer', 'pointer', 'pointer']);
  const length = api('array_length', 'size_t', ['pointer']);
  const valueType = api('class_is_valuetype', 'int', ['pointer']);
  const typeObject = api('type_get_object', 'pointer', ['pointer', 'pointer']);
  const stringNew = api('string_new', 'pointer', ['pointer', 'pointer']);
  const fieldSet = api('field_set_value', 'void', ['pointer', 'pointer', 'pointer']);
  // Unity's Mono exposes pointer-sized GC handles through the _v2 calls.
  const handleNew = api('gchandle_new_v2', 'pointer', ['pointer', 'int']);
  return {
    isAttached: () => !currentDomain().isNull(),
    domainGet: domain,
    threadAttach: api('thread_attach', 'pointer', ['pointer']),
    threadDetach: api('thread_detach', 'void', ['pointer']),
    images() {
      const assemblies = [];
      const visit = new NativeCallback(assembly => { assemblies.push(assembly); }, 'void', ['pointer', 'pointer']);
      assemblyForeach(visit, NULL);
      if (assemblies.length > 1000) throw new Error('Unexpected assembly count.');
      // Mono lists the newest assembly first; scan in load order, as IL2CPP does.
      return assemblies.reverse().map(assembly => assemblyImage(assembly));
    },
    imageCount: image => tableRows(image, 2), // MONO_TABLE_TYPEDEF
    imageClass: (image, index) => classGet(image, 0x02000000 + index + 1), // TypeDef token
    className: api('class_get_name', 'pointer', ['pointer']),
    classFromName: api('class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']),
    classNamespace: api('class_get_namespace', 'pointer', ['pointer']),
    classMethods: api('class_get_methods', 'pointer', ['pointer', 'pointer']),
    classFields: api('class_get_fields', 'pointer', ['pointer', 'pointer']),
    fieldName: api('field_get_name', 'pointer', ['pointer']),
    fieldType: api('field_get_type', 'pointer', ['pointer']),
    fieldOffset: api('field_get_offset', 'uint32', ['pointer']),
    methodName: api('method_get_name', 'pointer', ['pointer']),
    methodCount: method => paramCount(signature(method)),
    methodParam(method, index) {
      const iterator = Memory.alloc(Process.pointerSize);
      iterator.writePointer(NULL);
      const sig = signature(method);
      let type = NULL;
      for (let i = 0; i <= index; i++) type = params(sig, iterator);
      return type;
    },
    // Mono compiles on first use; this returns the existing code once compiled.
    methodCode: api('compile_method', 'pointer', ['pointer']),
    typeName: api('type_get_name', 'pointer', ['pointer']),
    free: api('free', 'void', ['pointer']),
    objectClass: api('object_get_class', 'pointer', ['pointer']),
    classParent: api('class_get_parent', 'pointer', ['pointer']),
    // Reads constants (enum members) too.
    staticValue: (field, out) => staticGet(classVtable(domain(), fieldParent(field)), field, out),
    fieldFlags: api('field_get_flags', 'uint32', ['pointer']),
    arrayLength: array => number(length(array)),
    arrayElementSize: api('array_element_size', 'int', ['pointer']),
    elementClass: api('class_get_element_class', 'pointer', ['pointer']),
    stringLength: api('string_length', 'int', ['pointer']),
    stringChars: api('string_chars', 'pointer', ['pointer']),
    // Mono's JIT code finds null references through hardware faults that Mono
    // turns into NullReferenceException, which Arena's own code often catches.
    // Frida's default 'steal' would take those faults and abort the call
    // midway ("access violation accessing 0x0"), so let Mono see them.
    runtimeInvoke: api('runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer'],
      {exceptions: 'propagate'}),
    objectUnbox: api('object_unbox', 'pointer', ['pointer']),
    classType: api('class_get_type', 'pointer', ['pointer']),
    classValueSize: api('class_value_size', 'int', ['pointer', 'pointer']),
    classIsValueType: klass => valueType(klass) !== 0,
    typeObject: type => typeObject(domain(), type),
    stringNew: text => stringNew(domain(), text),
    // Value-type fields take a pointer to the value; reference fields take the
    // reference itself (mono_copy_value dereferences only MONO_TYPE_PTR fields).
    fieldSet,
    fieldSetObject: fieldSet,
    handleNew: (object, pinned) => handleNew(object, pinned ? 1 : 0),
    handleTarget: api('gchandle_get_target_v2', 'pointer', ['pointer']),
    handleFree: api('gchandle_free_v2', 'void', ['pointer']),
    // Mono's invoke wrapper unboxes Nullable<T> arguments: it takes a boxed T,
    // or null for no value, never the raw struct.
    nullableGuidArgument: boxedGuid => boxedGuid || NULL,
  };
}
const classes = new Map();
const fieldCache = new Map();
let connection = null;
let pending = null;
function number(value) { return Number(value.toString()); }
function typeLabel(type) {
  const text = typeName(type);
  try { return text.readUtf8String(); } finally { free(text); }
}
function iterate(fn, owner) {
  const iterator = Memory.alloc(Process.pointerSize);
  iterator.writePointer(NULL);
  const results = [];
  for (let i = 0; i < 10000; i++) {
    const item = fn(owner, iterator);
    if (item.isNull()) return results;
    results.push(item);
  }
  throw new Error('Metadata enumeration exceeded the bound.');
}
function attached(run) {
  // Promise continuations can execute on Unity's already-attached main thread.
  // Never detach a thread owned by Arena; only detach our own fresh attachment.
  if (isAttached()) return run();
  const thread = threadAttach(domainGet());
  if (thread.isNull()) throw new Error(`Could not attach the probe thread to ${RUNTIME}.`);
  try { return run(); } finally { threadDetach(thread); }
}
// Every class key the adapter reads. Discovery looks these up by name; the
// full class scan (every class in every assembly) is only the fallback.
const required = [
  '.DecksManager', '.WrapperController', '.DeckManagerController', '.WrapperDeckUtilities',
  '.MTGALocalizedString', 'Wizards.Mtga.Decks.DeckViewSelector', 'Wizards.Mtga.Decks.Client_DeckCard',
  'Wizards.Mtga.Decks.Client_CardSkin', 'Wizards.Mtga.Decks.EDeckPile',
  'Wizards.Mtga.Decks.DeckServiceWrapperHelpers', 'Wizards.Mtga.Decks.Client_DeckSummary',
  'Wizards.Mtga.FrontDoorModels.DeckInfo', 'UnityEngine.UnitySynchronizationContext',
  'UnityEngine.Object', 'UnityEngine.Application', 'System.Guid', 'Newtonsoft.Json.JsonConvert',
  'Wotc.Mtga.Loc.Languages', 'UnityEngine.UI.ScrollRect',
];
function discover() {
  if (required.every(key => classes.has(key))) return;
  const all = images();
  // Later images win, matching the scan's order.
  for (const image of all) {
    for (const key of required) {
      const dot = key.lastIndexOf('.');
      const klass = classFromName(image, Memory.allocUtf8String(key.slice(0, dot)), Memory.allocUtf8String(key.slice(dot + 1)));
      if (!klass.isNull()) classes.set(key, klass);
    }
  }
  if (required.every(key => classes.has(key))) return;
  for (const image of all) {
    const classCount = number(imageCount(image));
    if (classCount > 100000) throw new Error('Unexpected class count.');
    for (let j = 0; j < classCount; j++) {
      const klass = imageClass(image, j);
      if (klass.isNull()) continue;
      const name = className(klass).readUtf8String();
      if (!targets.has(name)) continue;
      classes.set(`${classNamespace(klass).readUtf8String()}.${name}`, klass);
    }
  }
}
function fields(klass) {
  const key=klass.toString();
  if (fieldCache.has(key)) return fieldCache.get(key);
  const found = new Map();
  for (let k = klass; !k.isNull(); k = classParent(k)) {
    for (const field of iterate(classFields, k)) {
      const name = fieldName(field).readUtf8String();
      if (!found.has(name)) found.set(name, field);
    }
  }
  fieldCache.set(key,found);
  return found;
}
// Field metadata never changes while Arena runs; reading it once per field
// instead of once per deck keeps roster and backup snapshots cheap.
const metaCache = new Map();
function meta(field) {
  const key=field.toString();
  let value=metaCache.get(key);
  if (!value) {
    value={offset:number(fieldOffset(field)), flags:fieldFlags(field), type:typeLabel(fieldType(field))};
    metaCache.set(key,value);
  }
  return value;
}
function fieldAt(object, name) {
  if (object.isNull()) throw new Error(`Null object for ${name}.`);
  const field = fields(objectClass(object)).get(name);
  if (!field || (meta(field).flags & 0x10)) throw new Error(`Missing instance field ${name}.`);
  return object.add(meta(field).offset);
}
function ref(object, name) { return fieldAt(object, name).readPointer(); }
function text(object) {
  if (object.isNull()) return null;
  const length = stringLength(object);
  if (length < 0 || length > 20000) throw new Error('String length exceeded the bound.');
  return stringChars(object).readUtf16String(length);
}
function array(object) {
  if (object.isNull()) return {length: 0, data: NULL, stride: 0, klass: NULL};
  const klass = objectClass(object);
  const length = arrayLength(object);
  const stride = arrayElementSize(klass);
  if (length > 10000 || stride < 1 || stride > 256) throw new Error('Unexpected array layout.');
  // IL2CPP 64-bit array header: object header, bounds pointer, max_length.
  if (Process.pointerSize !== 8) throw new Error('This experiment requires a 64-bit client.');
  return {length, data: object.add(4 * Process.pointerSize), stride, klass};
}
function dictionary(object) {
  if (object.isNull()) return [];
  const count = fieldAt(object, '_count').readS32();
  const entries = array(ref(object, '_entries'));
  if (count < 0 || count > entries.length) throw new Error('Invalid dictionary count.');
  if (!count) return [];
  const entryFields = fields(elementClass(entries.klass));
  if (meta(entryFields.get('hashCode')).type !== 'System.Int32') throw new Error('Unsupported dictionary entry layout.');
  const offset = name => {
    const field = entryFields.get(name);
    if (!field) throw new Error(`Missing dictionary entry ${name}.`);
    const value = meta(field).offset - 2 * Process.pointerSize;
    if (value < 0 || value >= entries.stride) throw new Error('Invalid dictionary entry offset.');
    return value;
  };
  const hash = offset('hashCode'), key = offset('key'), value = offset('value');
  const items = [];
  for (let i = 0; i < count; i++) {
    const base = entries.data.add(i * entries.stride);
    if (base.add(hash).readS32() < 0) continue;
    items.push({key: base.add(key), value: base.add(value)});
  }
  return items;
}
function list(object, expectedStride) {
  if (object.isNull()) return [];
  const count = fieldAt(object, '_size').readS32();
  const items = array(ref(object, '_items'));
  if (count < 0 || count > items.length) throw new Error('Invalid list count.');
  if (count && expectedStride && items.stride !== expectedStride) throw new Error('Unsupported list element layout.');
  return Array.from({length:count}, (_, i) => items.data.add(i * items.stride));
}
function root() {
  const klass = classes.get('.WrapperController');
  const field = klass && fields(klass).get('<Instance>k__BackingField');
  if (!field) throw new Error('Wrapper singleton metadata is unavailable.');
  const value = Memory.alloc(Process.pointerSize);
  staticValue(field, value);
  const wrapper = value.readPointer();
  if (wrapper.isNull()) throw new Error('Arena must be on its home/decks screen.');
  const manager = ref(wrapper, 'DecksManager');
  if (manager.isNull()) throw new Error('Deck service is not loaded.');
  return manager;
}
// Layout checks, pile names and service calls are cheap; walking every cached
// deck is not (Arena caches its own decks too), so only the roster does that.
function checkCardLayouts() {
  for (const [key,expected] of [
    ['Wizards.Mtga.Decks.Client_DeckCard',{Id:['System.UInt32',16],Quantity:['System.UInt32',20]}],
    ['Wizards.Mtga.Decks.Client_CardSkin',{GrpId:['System.Int64',16],CCV:['System.String',24],ArtId:['System.Int64',32]}],
  ]) {
    const metadata=fields(classes.get(key));
    for (const [name,[type,offset]] of Object.entries(expected)) {
      const field=metadata.get(name);
      if (!field || meta(field).type!==type || meta(field).offset!==offset) {
        throw new Error(`Unsupported ${key} layout; no partial capture returned.`);
      }
    }
  }
}
function pileNames() {
  checkCardLayouts();
  const names = {};
  for (const [name,field] of fields(classes.get('Wizards.Mtga.Decks.EDeckPile'))) {
    // Only the enum's own members: Mono's System.Enum also declares a string
    // constant (enumSeperator), which fields() reaches through the parent class.
    if (!(meta(field).flags & 0x40) || meta(field).type !== 'Wizards.Mtga.Decks.EDeckPile') continue;
    const value=Memory.alloc(4); staticValue(field,value); names[value.readS32()]=name;
  }
  return names;
}
function serviceCalls(manager) {
  const serviceLimit = invoke(findMethod('.DecksManager','GetDeckLimit',[]), manager);
  const serviceReached = invoke(findMethod('.DecksManager','get_DeckLimitReached',[]), manager);
  return {get_deck_limit:objectUnbox(serviceLimit).readS32(), limit_reached:Boolean(objectUnbox(serviceReached).readU8())};
}
function deckSnapshot(deck) {
    const summary = ref(deck, '_summary');
    const contents = ref(deck, '_contents');
    const result = {name: text(ref(summary, 'Name')), arena_id:guidText(fieldAt(summary,'DeckId')),
      summary:summarySnapshot(summary), is_net_deck: Boolean(fieldAt(summary, 'IsNetDeck').readU8()),
      contents_loaded: !contents.isNull()};
    if (!contents.isNull()) {
      const contentFields = [...fields(objectClass(contents))];
      result.contents_fields = contentFields.map(([name,f]) => ({name,type:meta(f).type}));
      const pileField = contentFields.find(([name]) => name.includes('Piles'));
      if (pileField) {
        result.piles = dictionary(contents.add(meta(pileField[1]).offset).readPointer()).map(pile => ({
          pile: pile.key.readS32(), entries: list(pile.value.readPointer(),8).map(card => ({
            id: card.readU32(), quantity: card.add(4).readU32(),
          })),
        }));
      }
      result.skins = list(ref(contents,'Skins'),24).map(skin => ({
        GrpId:skin.readS64().toString(), CCV:text(skin.add(8).readPointer()), ArtId:skin.add(16).readS64().toString(),
      }));
    }
    return result;
}
function guidText(address) {
  const hex = offset => address.add(offset).readU8().toString(16).padStart(2,'0');
  return [[3,2,1,0],[5,4],[7,6],[8,9],[10,11,12,13,14,15]].map(group => group.map(hex).join('')).join('-');
}
function summarySnapshot(summary) {
  const result = {};
  for (const [name,field] of fields(objectClass(summary))) {
    const {flags, type, offset} = meta(field);
    if (flags & 0x10) continue;
    const address = summary.add(offset);
    if (type === 'System.String') result[name] = text(address.readPointer());
    else if (type === 'System.UInt32') result[name] = address.readU32();
    else if (type === 'System.Boolean') result[name] = Boolean(address.readU8());
    else if (type === 'System.Guid') result[name] = guidText(address);
    else if (type === 'System.Nullable<System.Guid>') {
      // Preserve bytes as well as presence; do not guess the inline Guid offset.
      result[name] = {raw_bytes:Array.from(new Uint8Array(address.readByteArray(20)))};
    } else if (type === 'System.Collections.Generic.List<System.String>') result[name] = list(address.readPointer()).map(p=>text(p.readPointer()));
    else if (type === 'System.Collections.Generic.Dictionary<System.String,System.String>') result[name] = dictionary(address.readPointer()).map(e=>({key:text(e.key.readPointer()),value:text(e.value.readPointer())}));
    else throw new Error(`Unsupported deck-summary field ${name}: ${type}; refusing a partial snapshot.`);
  }
  return result;
}

// Method lookups walk every method of a class (Guid and JsonConvert have
// hundreds); each checked signature is resolved once per attachment.
const methodCache = new Map();
function findMethod(key, name, parameters) {
  const cacheKey = `${key}|${name}|${parameters.join(',')}`;
  if (methodCache.has(cacheKey)) return methodCache.get(cacheKey);
  const klass = classes.get(key);
  const found = klass && iterate(classMethods, klass).filter(m =>
    methodName(m).readUtf8String() === name && methodCount(m) === parameters.length
    && parameters.every((p,i) => typeLabel(methodParam(m,i)) === p));
  if (!found || found.length !== 1) throw new Error(`Expected one ${key}.${name} with the checked signature.`);
  methodCache.set(cacheKey, found[0]);
  return found[0];
}
function invoke(method, object = NULL, arguments_ = []) {
  const params = arguments_.length ? Memory.alloc(arguments_.length * Process.pointerSize) : NULL;
  arguments_.forEach((value,i) => params.add(i * Process.pointerSize).writePointer(value));
  const error = Memory.alloc(Process.pointerSize);
  error.writePointer(NULL);
  const result = runtimeInvoke(method, object, params, error);
  const exception = error.readPointer();
  if (!exception.isNull()) {
    let kind = '';
    try { kind = ` (${classNamespace(objectClass(exception)).readUtf8String()}.${className(objectClass(exception)).readUtf8String()})`; } catch (_) { /* name is diagnostic only */ }
    throw new Error(`Arena rejected the managed call${kind}; no further calls made.`);
  }
  return result;
}
function selectorObjects() {
  const type = typeObject(classType(classes.get('Wizards.Mtga.Decks.DeckViewSelector')));
  const includeInactive = Memory.alloc(1); includeInactive.writeU8(0);
  const method = findMethod('UnityEngine.Object','FindObjectsOfType',['System.Type','System.Boolean']);
  const result = array(invoke(method, NULL, [type,includeInactive]));
  return Array.from({length:result.length}, (_,i) => result.data.add(i * result.stride).readPointer());
}
function objectMethod(object, name, parameters) {
  const cacheKey = `${objectClass(object)}|${name}|${parameters.join(',')}`;
  if (methodCache.has(cacheKey)) return methodCache.get(cacheKey);
  for (let klass=objectClass(object);!klass.isNull();klass=classParent(klass)) {
    const key = `${classNamespace(klass).readUtf8String()}.${className(klass).readUtf8String()}`;
    classes.set(key,klass);
    const matches = iterate(classMethods,klass).filter(m=>methodName(m).readUtf8String()===name
      && methodCount(m)===parameters.length && parameters.every((p,i)=>typeLabel(methodParam(m,i))===p));
    if (matches.length===1) {methodCache.set(cacheKey,matches[0]); return matches[0];}
    if (matches.length>1) throw new Error(`Ambiguous ${key}.${name}.`);
  }
  throw new Error(`Missing checked method ${name}.`);
}

function checkedHandleABI() {
  const version = text(invoke(findMethod('UnityEngine.Application','get_unityVersion',[])));
  if (!/^6000\./.test(version)) throw new Error('This mutation experiment requires the verified Unity 6 GC-handle ABI.');
}

function cachedDecks(manager) {
  return dictionary(ref(ref(manager,'_deckDataProvider'),'_allDecks')).map(e=>e.value.readPointer());
}
function stringObject(value) { return stringNew(Memory.allocUtf8String(value)); }
function parseGuid(value) {
  const text=stringObject(value), handle=handleNew(text,0);
  try { return invoke(findMethod('System.Guid','Parse',['System.String']),NULL,[text]); }
  finally { handleFree(handle); }
}

function serializeModel(object) {
  const result=invoke(findMethod('Newtonsoft.Json.JsonConvert','SerializeObject',['System.Object']),NULL,[object]);
  if (result.isNull()) throw new Error('Native serializer returned no data.');
  const handle=handleNew(result,0);
  try { return text(result); } finally { handleFree(handle); }
}
function physicalSummaryJson(json,sourceSummary) {
  const serialized=JSON.parse(json), physical={};
  for (const key of Object.keys(sourceSummary)) {
    if (!(key in serialized)) throw new Error(`Serializer omitted summary field ${key}.`);
    physical[key]=serialized[key];
  }
  // Computed IsFavorite/Format/date property setters can rewrite Attributes.
  // Persist only verified physical fields, retaining the serializer's Guid codec.
  return JSON.stringify(physical);
}
function deserializeModel(json,key) {
  if (typeof json!=='string' || json.length>20000) throw new Error('Invalid bounded model archive.');
  const klass=classes.get(key);
  if (!klass) throw new Error('The required archive model type is unavailable.');
  const input=stringObject(json), handle=handleNew(input,0);
  try {
    const result=invoke(findMethod('Newtonsoft.Json.JsonConvert','DeserializeObject',['System.String','System.Type']),NULL,
      [input,typeObject(classType(klass))]);
    if (result.isNull() || !objectClass(result).equals(klass)) throw new Error('Archive did not deserialize into the checked type.');
    return result;
  } finally { handleFree(handle); }
}

function sameSourceSnapshot(left,right) {
  const normalized=deck=>{
    // A fresh summary represents an empty description as null, while a
    // previously loaded full-deck model can use "". Preserve all other fields.
    const value=JSON.parse(JSON.stringify(deck));
    if (value.summary.Description===null) value.summary.Description='';
    const canonical=item=>Array.isArray(item) ? item.map(canonical)
      : item && typeof item==='object' ? Object.fromEntries(Object.keys(item).sort().map(key=>[key,canonical(item[key])])) : item;
    return JSON.stringify(canonical(value));
  };
  return normalized(left)===normalized(right);
}

let execAddress = null;
function unityExec() {
  if (execAddress) return execAddress;
  // Mono only answers metadata and compile calls on an attached thread.
  return attached(() => {
    const klass = classes.get('UnityEngine.UnitySynchronizationContext');
    const exec = klass && iterate(classMethods, klass).find(m => methodName(m).readUtf8String() === 'Exec' && methodCount(m) === 0);
    if (!exec) throw new Error('Unity main-thread dispatcher is unavailable.');
    const address = methodCode(exec);
    if (address.isNull() || !Process.findRangeByAddress(address)?.protection.includes('x')) throw new Error('Invalid Unity method address.');
    execAddress = address;
    return address;
  });
}
// Each call waits for Arena's next frame, which can be 30-100 ms while Arena is
// in the background, so callers do as much as they can per frame.
function onUnityThread(run) {
  const address = unityExec();
  return new Promise((resolve, reject) => {
    let complete = false;
    const timer = setTimeout(() => {
      if (complete) return;
      complete = true; listener.detach(); reject(new Error('No Unity main-thread frame within 10 seconds.'));
    }, 10000);
    const listener = Interceptor.attach(address, {onEnter() {
      if (complete) return;
      complete = true; clearTimeout(timer); listener.detach();
      try { resolve(run()); } catch (error) { reject(error); }
    }});
  });
}

// Shown as-is wherever a job needs Arena on Decks (Deck Manager and Deck Finder).
const DECKS_SCREEN='Arena isn’t on its Decks screen. Go to Decks in Arena, outside a match, then try again.';
function wrapperObject() {
  const field=fields(classes.get('.WrapperController')).get('<Instance>k__BackingField');
  const value=Memory.alloc(Process.pointerSize); staticValue(field,value);
  const wrapper=value.readPointer();
  if (wrapper.isNull()) throw new Error(DECKS_SCREEN);
  return wrapper;
}
function accountId() {
  const client=ref(wrapperObject(),'<AccountClient>k__BackingField');
  if (client.isNull()) throw new Error('Arena is not signed in.');
  const info=invoke(objectMethod(client,'get_AccountInformation',[]),client);
  if (info.isNull()) throw new Error('Arena is not signed in.');
  const field=fields(objectClass(info)).get('AccountID');
  if (!field || meta(field).type!=='System.String') throw new Error('Unsupported account identity layout.');
  // Read only the stable account ID. Never read tokens, email or credentials.
  const id=text(ref(info,'AccountID'));
  if (!id || id.length>256) throw new Error('Arena account identity is unavailable.');
  return id;
}
function deckScreenOpen() {
  const klass=classes.get('.DeckManagerController');
  if (!klass) return false;
  const flag=Memory.alloc(1); flag.writeU8(0);
  const found=array(invoke(findMethod('UnityEngine.Object','FindObjectsOfType',['System.Type','System.Boolean']),NULL,
    [typeObject(classType(klass)),flag]));
  return found.length===1 && selectorObjects().length===1;
}
function guard(expectedAccount, requireDecks=false) {
  if (!connection || accountId()!==expectedAccount || connection.account!==expectedAccount
    || !root().equals(handleTarget(connection.managerHandle))) throw new Error('Arena account or session changed. Reconnect Deck Manager.');
  if (requireDecks && !deckScreenOpen()) throw new Error(DECKS_SCREEN);
  return root();
}
function releaseConnection() {
  if (pending) throw new Error('A native request is still pending.');
  if (preparedCreate) {handleFree(preparedCreate.handle);preparedCreate=null;}
  if (connection) handleFree(connection.managerHandle);
  connection=null;
  return true;
}
// The 64-bit Arena build each platform ships.
const ARENA_ARCH={darwin:'arm64',windows:'x64'};
async function openConnection() {
  attached(discover);
  return onUnityThread(()=>{
    if (connection) throw new Error('Deck Manager is already connected.');
    checkedHandleABI();
    const version=text(invoke(findMethod('UnityEngine.Application','get_unityVersion',[])));
    if (ARENA_ARCH[Process.platform]!==Process.arch || version!=='6000.3.14f1') {
      throw new Error(`This Arena build is not supported by the native deck adapter yet (Unity ${version}, ${Process.platform} ${Process.arch}).`);
    }
    if (!deckScreenOpen()) throw new Error(DECKS_SCREEN);
    const account=accountId(), manager=root();
    connection={account,managerHandle:handleNew(manager,0)};
    return {account_id:account,unity_version:version,deck_screen_open:deckScreenOpen()};
  });
}
// Polls a pending Arena request between frames; each poll is itself a frame.
const POLL_MS = 40;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
// Unity thread only: a finished request's {value}, or null while it runs.
function settled(promise, extract) {
  if (!objectUnbox(invoke(objectMethod(promise,'get_IsDone',[]),promise)).readU8()) return null;
  if (!objectUnbox(invoke(objectMethod(promise,'get_Successful',[]),promise)).readU8()) throw new Error('Arena request did not succeed. Refresh to reconcile its outcome.');
  return {value:extract(invoke(objectMethod(promise,'get_Result',[]),promise))};
}
async function promiseCall(account, start, extract, write=false) {
  if (pending) throw new Error('A native request is already pending.');
  let handle=null;
  try {
    // Arena answers cached reads at once, so check in the same frame that
    // started the request before holding it across frames.
    const first=await onUnityThread(()=>{
      guard(account,write);
      const promise=start();
      if (promise.isNull()) throw new Error('Arena returned no request. Outcome must be reconciled.');
      const done=settled(promise,extract);
      if (!done) handle=pending=handleNew(promise,0);
      return done;
    });
    if (first) return first.value;
    const deadline=Date.now()+45000;
    while (Date.now()<deadline) {
      await sleep(POLL_MS);
      const result=await onUnityThread(()=>{
        guard(account);
        const done=settled(handleTarget(handle),extract);
        if (done) {handleFree(handle);handle=pending=null;}
        return done;
      });
      if (result) return result.value;
    }
    throw new Error('Arena request timed out. Refresh to reconcile its outcome.');
  } finally {
    if (handle) await onUnityThread(()=>{handleFree(handle);pending=null;});
  }
}
async function refreshCache(account) {
  await promiseCall(account,()=>invoke(findMethod('.DecksManager','ForceRefreshCachedDecks',[]),root()),()=>true);
}
async function roster(account) {
  await refreshCache(account);
  return promiseCall(account,()=>invoke(findMethod('.DecksManager','GetAllDecks',[]),root()),result=>{
    if (result.isNull()) throw new Error('Arena returned no roster. No transfer can proceed.');
    const names=pileNames(),service=serviceCalls(root());
    const decks=list(result).map(p=>deckSnapshot(p.readPointer()));
    const ids=decks.filter(d=>!d.is_net_deck).map(d=>d.arena_id);
    if (new Set(ids).size!==ids.length) throw new Error('Arena returned duplicate deck identities.');
    return {account_id:account,deck_screen_open:deckScreenOpen(),limit:service.get_deck_limit,
      limit_reached:service.limit_reached,pile_names:names,
      decks:decks.filter(d=>!d.is_net_deck),roster_refreshed:true};
  });
}
function requestFullDeck(id) {
  const guid=parseGuid(id),handle=handleNew(guid,0);
  try { return invoke(findMethod('.DecksManager','GetFullDeck',['System.Guid']),root(),[objectUnbox(guid)]); }
  finally { handleFree(handle); }
}
function checkFullDeck(result,id) {
  if (guidText(fieldAt(ref(result,'_summary'),'DeckId'))!==id || fieldAt(ref(result,'_summary'),'IsNetDeck').readU8()) {
    throw new Error('Arena returned a different deck identity.');
  }
}
async function fullDeck(account,id) {
  return promiseCall(account,()=>requestFullDeck(id),result=>{
    const actual=deckSnapshot(result);
    if (actual.arena_id!==id || actual.is_net_deck) throw new Error('Arena returned a different deck identity.');
    return actual;
  });
}
// Unity thread only. Null until Arena has stored the loaded deck, unless strict.
function cachedArchive(id,names,strict) {
  const deck=cachedDecks(root()).find(d=>guidText(fieldAt(ref(d,'_summary'),'DeckId'))===id);
  if (!deck) throw new Error('Deck is no longer present in Arena.');
  const source=deckSnapshot(deck);
  if (source.is_net_deck || !source.contents_loaded || source.piles.length!==4) {
    if (!strict) return null;
    throw new Error('Arena has not loaded all deck piles.');
  }
  const model=invoke(findMethod('Wizards.Mtga.Decks.DeckServiceWrapperHelpers','ToAzureModel',['Wizards.Mtga.Decks.Client_Deck']),NULL,[deck]);
  const handle=handleNew(model,0);
  try { return {schema:1,archive_kind:'arena_typed_model_poc',model_json:serializeModel(model),
    summary_json:physicalSummaryJson(serializeModel(ref(deck,'_summary')),source.summary),source_snapshot:source,
    pile_names:names,runtime:RUNTIME,unity_thread_observed:true,unity_version:'6000.3.14f1'}; }
  finally { handleFree(handle); }
}
async function archiveDecks(account,ids) {
  if (!Array.isArray(ids) || ids.length>2000 || new Set(ids).size!==ids.length) throw new Error('Invalid deck selection.');
  if (pending) throw new Error('A native request is already pending.');
  // Request every deck in one frame and archive those Arena already has
  // loaded in that same frame; only the rest are held and polled.
  const archives=new Map(),waiting=new Map();
  const collect=(id,promise,names)=>{
    const done=settled(promise,result=>{checkFullDeck(result,id);return cachedArchive(id,names,false);});
    if (done && done.value) archives.set(id,done.value);
    return Boolean(done);
  };
  try {
    await onUnityThread(()=>{
      guard(account);
      const names=pileNames();
      for (const id of ids) {
        const promise=requestFullDeck(id);
        if (promise.isNull()) throw new Error('Arena returned no request. Outcome must be reconciled.');
        if (!collect(id,promise,names)) waiting.set(id,handleNew(promise,0));
      }
      if (waiting.size) pending=true;
    });
    const deadline=Date.now()+45000;
    while (waiting.size) {
      if (Date.now()>=deadline) throw new Error('Arena request timed out. Refresh to reconcile its outcome.');
      await sleep(POLL_MS);
      await onUnityThread(()=>{
        guard(account);
        const names=pileNames();
        for (const [id,handle] of [...waiting]) {
          if (collect(id,handleTarget(handle),names)) {handleFree(handle);waiting.delete(id);}
        }
      });
    }
    pending=null;
    // A request can finish a frame before Arena stores the loaded deck.
    if (archives.size<ids.length) {
      await onUnityThread(()=>{
        guard(account);
        const names=pileNames();
        for (const id of ids) if (!archives.has(id)) archives.set(id,cachedArchive(id,names,true));
      });
    }
    return ids.map(id=>archives.get(id));
  } finally {
    if (waiting.size) await onUnityThread(()=>{for (const handle of waiting.values()) handleFree(handle);waiting.clear();});
    pending=null;
  }
}
async function prepareImport(account,deckText,name,id) {
  if (typeof deckText!=='string' || !deckText.length || deckText.length>20000
      || typeof name!=='string' || !name.length || name.length>256 || !/^[0-9a-f-]{36}$/.test(id)) {
    throw new Error('Invalid bounded Arena import.');
  }
  return onUnityThread(()=>{
    guard(account,true);
    if (cachedDecks(root()).some(d=>guidText(fieldAt(ref(d,'_summary'),'DeckId'))===id)) {
      throw new Error('Import identity already exists. Reconcile before continuing.');
    }
    const includeInactive=Memory.alloc(1);includeInactive.writeU8(0);
    const controllers=array(invoke(findMethod('UnityEngine.Object','FindObjectsOfType',['System.Type','System.Boolean']),NULL,
      [typeObject(classType(classes.get('.DeckManagerController'))),includeInactive]));
    if (controllers.length!==1) throw new Error('The Decks import controller is unavailable.');
    const controller=controllers.data.readPointer();
    const cardDb=ref(controller,'_cardDatabase'),setMeta=ref(controller,'_setMetadataProvider');
    const inventory=ref(wrapperObject(),'<InventoryManager>k__BackingField');
    if (cardDb.isNull() || setMeta.isNull() || inventory.isNull()) throw new Error('Arena import providers are unavailable.');
    const cards=invoke(objectMethod(inventory,'get_Cards',[]),inventory);
    const locField=fields(classes.get('Wotc.Mtga.Loc.Languages')).get('ActiveLocProvider');
    if (!locField || !(meta(locField).flags&0x10) || meta(locField).type!=='Wotc.Mtga.Loc.IClientLocProvider') {
      throw new Error('Unsupported Arena localization provider.');
    }
    const locValue=Memory.alloc(Process.pointerSize);locValue.writePointer(NULL);staticValue(locField,locValue);
    const loc=locValue.readPointer();
    const language=invoke(findMethod('Wotc.Mtga.Loc.Languages','get_CurrentLanguage',[]));
    if (cards.isNull() || loc.isNull() || language.isNull()) throw new Error('Arena import providers are not ready.');
    const errorClass=classes.get('.MTGALocalizedString');
    if (!errorClass) throw new Error('Unsupported Arena import error type.');
    const alignment=Memory.alloc(4);
    const size=classIsValueType(errorClass) ? classValueSize(errorClass,alignment) : Process.pointerSize;
    if (size<1 || size>512) throw new Error('Unsupported Arena import error layout.');
    const errorOut=Memory.alloc(size),deckOut=Memory.alloc(Process.pointerSize);deckOut.writePointer(NULL);
    const input=stringObject(deckText),heldInput=handleNew(input,0);
    let heldDeck=null;
    try {
      const result=invoke(findMethod('.WrapperDeckUtilities','TryImportDeck',[
        'System.String','Wotc.Mtga.Cards.Database.ICardDatabaseAdapter',
        'SharedClientCore.SharedClientCore.Code.Providers.ISetMetadataProvider',
        'Wotc.Mtga.Loc.IClientLocProvider','System.Collections.Generic.Dictionary<System.UInt32,System.Int32>',
        'System.String','Wizards.Mtga.Decks.Client_Deck&','MTGALocalizedString&',
      ]),NULL,[input,cardDb,setMeta,loc,cards,language,deckOut,errorOut]);
      const draft=deckOut.readPointer();
      if (!objectUnbox(result).readU8() || draft.isNull()) throw new Error('Arena could not import this decklist. No deck was created.');
      heldDeck=handleNew(draft,0);
      const summary=ref(draft,'_summary'),guid=parseGuid(id),guidHandle=handleNew(guid,0);
      try {fieldSet(summary,fields(objectClass(summary)).get('DeckId'),objectUnbox(guid));}
      finally {handleFree(guidHandle);}
      const title=stringObject(name),heldTitle=handleNew(title,0);
      try {fieldSetObject(summary,fields(objectClass(summary)).get('Name'),title);}
      finally {handleFree(heldTitle);}
      const model=invoke(findMethod('Wizards.Mtga.Decks.DeckServiceWrapperHelpers','ToAzureModel',['Wizards.Mtga.Decks.Client_Deck']),NULL,[draft]);
      const heldModel=handleNew(model,0);
      const source=deckSnapshot(draft);
      try {return {schema:1,archive_kind:'arena_typed_model_poc',model_json:serializeModel(model),
        summary_json:physicalSummaryJson(serializeModel(summary),source.summary),source_snapshot:source,pile_names:pileNames()};}
      finally {handleFree(heldModel);}
    } finally {if(heldDeck)handleFree(heldDeck);handleFree(heldInput);}
  });
}
let preparedCreate=null;
async function prepareCreate(account,archive,id) {
  if (preparedCreate) throw new Error('A deck is already prepared for creation.');
    const draftHandle=await onUnityThread(()=>{
      const manager=guard(account,true);
      if (objectUnbox(invoke(findMethod('.DecksManager','get_DeckLimitReached',[]),manager)).readU8()) throw new Error('Arena’s deck slots are full. Move a deck to your collection first.');
      if (!/^[0-9a-f-]{36}$/.test(id) || cachedDecks(manager).some(d=>guidText(fieldAt(ref(d,'_summary'),'DeckId'))===id)) throw new Error('Restore identity already exists. Reconcile instead of creating again.');
      const model=deserializeModel(archive.model_json,'Wizards.Mtga.FrontDoorModels.DeckInfo'),modelHandle=handleNew(model,0);
      let draft;
      try {draft=invoke(findMethod('Wizards.Mtga.Decks.DeckServiceWrapperHelpers','ToClientModel',['Wizards.Mtga.FrontDoorModels.DeckInfo']),NULL,[model]);}
      finally {handleFree(modelHandle);}
      const held=handleNew(draft,0);
      try {
        const summary=deserializeModel(archive.summary_json,'Wizards.Mtga.Decks.Client_DeckSummary'),summaryHandle=handleNew(summary,0);
        try {fieldSetObject(draft,fields(objectClass(draft)).get('_summary'),summary);}
        finally {handleFree(summaryHandle);}
        if (!sameSourceSnapshot(deckSnapshot(draft),archive.source_snapshot)) throw new Error('The rebuilt deck differs from its saved backup.');
        const guid=parseGuid(id),guidHandle=handleNew(guid,0);
        try {fieldSet(summary,fields(objectClass(summary)).get('DeckId'),objectUnbox(guid));}
        finally {handleFree(guidHandle);}
        return held;
      } catch(error) {handleFree(held);throw error;}
    });
    preparedCreate={account,id,handle:draftHandle};
    return {id};
}
async function createPrepared(account,id) {
  if (!preparedCreate || preparedCreate.account!==account || preparedCreate.id!==id) throw new Error('No matching prepared deck.');
  const draftHandle=preparedCreate.handle;
  preparedCreate=null;
  try {
    const createdId=await promiseCall(account,()=>{
      const imported=stringObject('Imported'),held=handleNew(imported,0),flag=Memory.alloc(1);flag.writeU8(0);
      try {return invoke(findMethod('.DecksManager','CreateDeck',['Wizards.Mtga.Decks.Client_Deck','System.String','System.Boolean']),root(),[handleTarget(draftHandle),imported,flag]);}
      finally {handleFree(held);}
    },summary=>guidText(fieldAt(summary,'DeckId')),true);
    // A client returning a different identity is an unknown result, never retried.
    if (createdId!==id) throw new Error('Arena returned an unexpected restore identity. Refresh to reconcile.');
    // Refresh Arena's cache before reading the new deck back. The roster's
    // snapshot of every deck is not needed here; the caller verifies it.
    await refreshCache(account);
    await promiseCall(account,()=>invoke(findMethod('.DecksManager','GetAllDecks',[]),root()),result=>{
      if (result.isNull()) throw new Error('Arena returned no roster. No transfer can proceed.');
      return true;
    });
    return fullDeck(account,id);
  } finally {if(draftHandle) await onUnityThread(()=>handleFree(draftHandle));}
}
async function createDeck(account,archive,id) {
  await prepareCreate(account,archive,id);
  return createPrepared(account,id);
}
async function removeDeck(account,snapshot) {
  const id=snapshot.arena_id;
  return promiseCall(account,()=>{
    const current=cachedDecks(root()).find(d=>guidText(fieldAt(ref(d,'_summary'),'DeckId'))===id);
    if (!current || snapshot.is_net_deck || !sameSourceSnapshot(deckSnapshot(current),snapshot)) throw new Error('The deck changed after backup. Refresh before moving it.');
    const guid=parseGuid(id),held=handleNew(guid,0);
    try {return invoke(findMethod('.DecksManager','DeleteDeck',['System.Guid']),root(),[objectUnbox(guid)]);}
    finally {handleFree(held);}
  },result=>{
    if (result.isNull() || !objectUnbox(result).readU8()) throw new Error('Arena did not confirm removal. Refresh to reconcile.');
    return true;
  },true);
}
// Arena's Decks screen draws its grid once when it opens, so a deck created or
// removed through the service stays hidden until the screen is reopened. This
// starts the screen's own load routine, as Arena does after its own delete: it
// reads the refreshed cache and rebuilds the grid, selecting `selectId` when
// given (a deck this job created). Display only; no deck write.
function reloadDecksScreen(selectId) {
  const flag=Memory.alloc(1); flag.writeU8(0);
  const found=array(invoke(findMethod('UnityEngine.Object','FindObjectsOfType',['System.Type','System.Boolean']),NULL,
    [typeObject(classType(classes.get('.DeckManagerController'))),flag]));
  if (found.length!==1 || selectorObjects().length!==1) return false;
  const controller=found.data.readPointer();
  // Arena is already loading the list, and that load shows the change.
  if (!ref(controller,'_loadDecksCoroutine').isNull()) return true;
  const bucket=Memory.alloc(4); bucket.writeS32(fieldAt(controller,'_selectedBucket').readS32());
  const guid=selectId ? parseGuid(selectId) : null, held=guid && handleNew(guid,0);
  let routine;
  try {
    routine=invoke(findMethod('.DeckManagerController','Coroutine_LoadDecks',['System.Int32','System.Nullable<System.Guid>']),
      controller,[bucket,nullableGuidArgument(guid)]);
  } finally {if (held) handleFree(held);}
  if (routine.isNull()) return false;
  const started=invoke(objectMethod(controller,'StartCoroutine',['System.Collections.IEnumerator']),controller,[routine]);
  // Null when the cached list loaded at once; otherwise hold it as Arena does.
  if (!started.isNull()) fieldSetObject(controller,fields(objectClass(controller)).get('_loadDecksCoroutine'),started);
  return true;
}
// Arena's selection does not scroll, so center the selected tile in the grid's
// ScrollRect (on the selector itself). True once handled, including when the
// tile is in a closed folder; false while the rebuilt tile is not there yet.
function scrollToSelectedDeck(selectId) {
  const selectors=selectorObjects();
  if (selectors.length!==1) return false;
  const selector=selectors[0], view=ref(selector,'_selectedDeckView');
  if (view.isNull() || guidText(fieldAt(ref(view,'_deckViewInfo'),'deckId'))!==selectId) return false;
  const tile=invoke(objectMethod(view,'get_gameObject',[]),view);
  if (!objectUnbox(invoke(objectMethod(tile,'get_activeInHierarchy',[]),tile)).readU8()) return true;
  const scroll=invoke(objectMethod(selector,'GetComponent',['System.Type']),selector,
    [typeObject(classType(classes.get('UnityEngine.UI.ScrollRect')))]);
  if (scroll.isNull() || !fieldAt(scroll,'m_Vertical').readU8()) return true;
  const content=invoke(objectMethod(scroll,'get_content',[]),scroll), viewport=invoke(objectMethod(scroll,'get_viewport',[]),scroll);
  if (content.isNull() || viewport.isNull()) return true;
  const rect=transform=>objectUnbox(invoke(objectMethod(transform,'get_rect',[]),transform));
  const area=rect(content), height=area.add(12).readFloat(), top=area.add(4).readFloat()+height;
  const visible=rect(viewport).add(12).readFloat();
  const where=invoke(objectMethod(view,'get_transform',[]),view);
  const position=objectUnbox(invoke(objectMethod(where,'get_position',[]),where));
  const local=objectUnbox(invoke(objectMethod(content,'InverseTransformPoint',['UnityEngine.Vector3']),content,[position]));
  if (height<=visible) return true;
  const offset=Math.max(0,Math.min(height-visible,top-local.add(4).readFloat()-visible/2));
  const current=objectUnbox(invoke(objectMethod(scroll,'get_normalizedPosition',[]),scroll));
  const target=Memory.alloc(8); target.writeFloat(current.readFloat()); target.add(4).writeFloat(1-offset/(height-visible));
  invoke(objectMethod(scroll,'StopMovement',[]),scroll);
  invoke(objectMethod(scroll,'set_normalizedPosition',['UnityEngine.Vector2']),scroll,[target]);
  return true;
}
async function refreshScreen(account,selectId=null) {
  if (selectId!==null && !/^[0-9a-f-]{36}$/.test(selectId)) throw new Error('Invalid deck to select.');
  // A cache refresh can briefly rebuild the Decks selector; wait it out.
  let reloaded=false;
  for (let i=0;i<25 && !reloaded;i++) {
    reloaded=await onUnityThread(()=>{guard(account); return !pending && reloadDecksScreen(selectId);});
    if (!reloaded) await sleep(80);
  }
  if (!reloaded || !selectId) return reloaded;
  // New tiles are laid out on a later frame; scroll once they are in place.
  for (let i=0;i<20;i++) {
    await sleep(100);
    if (await onUnityThread(()=>{guard(account); return scrollToSelectedDeck(selectId);})) break;
  }
  return true;
}
rpc.exports={open:openConnection,roster,archive:archiveDecks,fetchdeck:fullDeck,create:createDeck,remove:removeDeck,prepareimport:prepareImport,preparecreate:prepareCreate,createprepared:createPrepared,
  refreshscreen:refreshScreen,close(){return onUnityThread(releaseConnection);}};
