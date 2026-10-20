// Pure Node fixtures: no browser process, GUI, screenshot, input simulation or clipboard.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {pathToFileURL} = require('node:url');
const base = path.resolve(__dirname, '..');
const descriptor = '54321.' + 'a'.repeat(43);
const flush = async () => { for (let n = 0; n < 15; n++) await new Promise(setImmediate); };

async function contentFixture({draft = '', drop = false, editable = false, files = true} = {}) {
  const sent = [], chips = [], messages = [], intervals = [], listeners = [], elements = [];
  class Element {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.attributes = {}; this._text = ''; this.isConnected = true; elements.push(this); }
    set textContent(value) { this._text = value; this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent || '').join('\n'); }
    get innerText() { return this.textContent; }
    getClientRects() { return [{width: 300, height: 40}]; }
    get isContentEditable() { return this.tagName === 'DIV'; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this._text = ''; this.children = nodes; }
    attachShadow() { return new Element('shadow'); }
    getAttribute(name) { return this.attributes[name] || null; }
    contains(other) { return this === other || this.children.some(child => child.contains?.(other)); }
    closest(selector) { return selector === 'form' ? area : null; }
    addEventListener(type, callback) { (this.events ||= {})[type] = callback; }
    removeEventListener(type) { delete this.events?.[type]; }
    dispatchEvent(event) {
      this.events?.[event.type]?.(event);
      if (event.type === 'change') {
        for (const file of this.files) chip(file.name);
      }
      if (event.type === 'drop') for (const file of event.dataTransfer.files) chip(file.name);
      return true;
    }
  }
  class Textarea extends Element {
    constructor() { super('textarea'); this._value = draft; }
    get value() { return this._value; }
    set value(value) { this._value = value; }
  }
  const area = new Element('form');
  const editor = editable ? new Element('div') : new Textarea();
  if (editable) editor.textContent = draft;
  const input = new Element('input'); input.accept = '.pdf,.png,.txt';
  function chip(name) { const element = new Element('div'); element.textContent = name; chips.push(element); }
  area.querySelector = () => null;
  area.querySelectorAll = () => chips;
  const location = {origin: 'https://chatgpt.com', pathname: '/', search: '', hash: '#paperquick=' + descriptor};
  const payload = {key: 'library:paper', url: '', prompt: '文献：测试\n第 2 页\n\nSelected quotation', files: files ? [
    {name: 'paper.pdf', size: 4, primary: true, chunks: 1}, {name: '图表.png', size: 4, primary: false, chunks: 1}
  ] : []};
  const document = {
    documentElement: new Element('html'),
    createElement: tag => new Element(tag),
    querySelector: selector => selector.includes('input[type=') ? (drop ? null : input) : selector.includes('prompt-textarea') ? editor : null,
    querySelectorAll: selector => selector.includes('data-message-author-role') ? messages : selector.includes('prompt-textarea') ? [editor] : selector.includes('input[type=') ? (drop ? [] : [input]) : [],
    getSelection: () => ({removeAllRanges(){},addRange(){}}),createRange: () => ({selectNodeContents(){}}),execCommand: () => false
  };
  const chrome = {runtime: {
    id: 'fixture', onMessage: {addListener: callback => listeners.push(callback)},
    sendMessage: async message => {
      sent.push(message);
      if (message.type.endsWith('Route') || message.type.endsWith('Payload')) return {ok: true, payload};
      if (message.type.endsWith('Chunk')) return {ok: true, data: Buffer.from('data').toString('base64')};
      return {ok: true};
    }
  }};
  class Event { constructor(type, args = {}) { this.type = type; Object.assign(this, args); } }
  class DataTransfer { constructor() { this.files = []; this.items = {add: file => this.files.push(file)}; } }
  const context = vm.createContext({document, location, chrome, history: {state: {}, replaceState: () => { location.hash = ''; }},
    Event, InputEvent: Event, DragEvent: Event, HTMLTextAreaElement: Textarea, DataTransfer, File,
    atob: value => Buffer.from(value, 'base64').toString('binary'), Uint8Array,
    setTimeout: callback => { queueMicrotask(callback); }, setInterval: callback => { intervals.push(callback); return callback; },
    clearInterval: callback => { const index = intervals.indexOf(callback); if (index >= 0) intervals.splice(index, 1); },
    getComputedStyle: () => ({display:'block',visibility:'visible'}),addEventListener: () => {}, console});
  vm.runInContext(fs.readFileSync(path.join(base, 'browser-extension/chat-content.js'), 'utf8'), context);
  await flush();
  return {editor, input, chips, sent, messages, intervals, listeners, payload, location, Element, elements};
}

async function contentChecks() {
  for (const editable of [false, true]) {
    const f = await contentFixture({editable});
    assert.match(editable ? f.editor.textContent : f.editor.value, /Selected quotation/);
    assert.deepEqual(f.chips.map(chip => chip.textContent), ['paper.pdf', '图表.png']);
    assert.equal(f.sent.filter(m => m.type.endsWith('Bind')).length, 0, 'Never bind before user sends');
    assert.equal(f.location.hash, '', 'Remove token from URL after handoff');
    if (editable) f.editor.textContent = 'Edited question by user'; else f.editor.value = 'Edited question by user';
    f.editor.dispatchEvent({type: 'input'});
    if (editable) f.editor.textContent = ''; else f.editor.value = '';
    const turn = new f.Element('div'); turn.textContent = 'Edited question by user\npaper.pdf\n图表.png';
    f.messages.push(turn); f.location.pathname = '/c/12345678-abcd';
    await f.intervals[0](); await flush();
    const bind = f.sent.find(m => m.type.endsWith('Bind'));
    assert.equal(bind.primaryAttached, true);
    assert.equal(f.intervals.length, 0);
  }
  const draft = await contentFixture({draft: 'My existing draft'});
  assert.equal(draft.editor.value, 'My existing draft');
  assert.equal(draft.chips.length, 0);
  assert(draft.elements.some(element => element.textContent.includes('已有未发送文字')));
  const drop = await contentFixture({drop: true});
  assert.equal(drop.chips.length, 2, 'Drop fallback stages files without opening an OS picker');
  const noFiles = await contentFixture({files: false});
  assert.match(noFiles.editor.value, /Selected quotation/);
  assert.equal(noFiles.sent.filter(m => m.type.endsWith('Chunk')).length, 0);
  const removed = await contentFixture();
  removed.editor.value = '';
  const turn = new removed.Element('div'); turn.textContent = removed.payload.prompt;
  removed.messages.push(turn); removed.location.pathname = '/c/12345678-abcd';
  await removed.intervals[0](); await flush();
  assert.equal(removed.sent.find(m => m.type.endsWith('Bind')).primaryAttached, false);
}

async function backgroundChecks() {
  const {descriptor: parse, chatRoute, installChatBridge} = await import(pathToFileURL(path.join(base, 'browser-extension/chat-background.js')));
  assert.equal(parse(descriptor).port, 54321);
  for (const value of ['80.' + 'a'.repeat(43), '65536.' + 'a'.repeat(43), 'http://evil.test', descriptor + '/file']) assert.throws(() => parse(value));
  assert.equal(chatRoute('https://chatgpt.com/c/12345678-abcd#secret'), 'https://chatgpt.com/c/12345678-abcd');
  assert.equal(chatRoute('https://chatgpt.com.evil.test/c/12345678'), '');
  const state = {}, listeners = [], calls = [];
  global.chrome = {runtime: {id: 'fixture', onMessage: {addListener: fn => listeners.push(fn)}}, storage: {session: {
    get: async key => ({[key]: state[key]}), set: async changes => Object.assign(state, changes), remove: async key => { delete state[key]; }
  }}, tabs: {
    get: async id => ({id, url: 'https://chatgpt.com/c/12345678-abcd'}),
    sendMessage: async (...args) => { calls.push(['deliver', ...args]); return {ok: true}; },
    update: async (...args) => calls.push(['update', ...args]), remove: async (...args) => calls.push(['remove', ...args])
  }};
  global.fetch = async (url, options) => {
    calls.push(['fetch', url, options]);
    return {ok: true, json: async () => ({key: 'library:paper', url: 'https://chatgpt.com/c/12345678-abcd', prompt: 'text', files: []})};
  };
  installChatBridge();
  const sender = {id: 'fixture', frameId: 0, tab: {id: 2}, url: 'https://chatgpt.com/c/12345678-abcd#paperquick=' + descriptor};
  const send = message => new Promise(resolve => listeners[0](message, sender, resolve));
  let result = await send({type: 'paperQuickChatRoute', descriptor});
  assert(result.ok && result.payload);
  assert.equal(state['chat-tab:library:paper'].tabId, 2);
  assert.equal(calls[0][1], 'http://127.0.0.1:54321/handoff/' + 'a'.repeat(43));
  state['chat-tab:library:paper'] = {tabId: 1};
  result = await send({type: 'paperQuickChatRoute', descriptor});
  assert(result.redirected);
  assert(calls.some(call => call[0] === 'remove' && call[1] === 2));
  const count = calls.length;
  result = await send({type: 'paperQuickChatChunk', descriptor, index: -1, part: 0});
  assert.equal(result.ok, false);
  assert.equal(calls.length, count, 'Invalid chunk never reaches network');
  let responded = false;
  assert.equal(listeners[0]({type: 'paperQuickChatRoute', descriptor}, {...sender, url: 'https://evil.test/'}, () => { responded = true; }), false);
  assert.equal(responded, false);
  delete global.chrome; delete global.fetch;
}

(async () => {
  await contentChecks();
  await backgroundChecks();
  console.log('PASS: draft protection, textarea/contenteditable, file input/drop, per-paper tab reuse, send/bind lifecycle and restricted bridge requests (no browser launched).');
})().catch(error => { console.error(error); process.exitCode = 1; });
