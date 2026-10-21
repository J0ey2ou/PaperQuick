/* Shared strict routes. Content scripts and the service worker use the same allowlist. */
globalThis.PaperQuickAISites = {
  chatgpt: {name:'ChatGPT',home:'https://chatgpt.com/', conversation:/^\/c\/[A-Za-z0-9-]{8,100}$/},
  doubao: {name:'豆包',home:'https://www.doubao.com/chat/',conversation:/^\/chat\/[A-Za-z0-9_-]{4,150}$/},
  deepseek: {name:'DeepSeek',home:'https://chat.deepseek.com/',conversation:/^\/a\/chat\/s\/[A-Za-z0-9_-]{4,150}$/},
  gemini: {name:'Gemini',home:'https://gemini.google.com/app',conversation:/^\/app\/[A-Za-z0-9_-]{4,150}$/},
  qwen: {name:'千问 / Qwen',home:'https://chat.qwen.ai/',conversation:/^\/c\/[A-Za-z0-9_-]{4,150}$/},
  kimi: {name:'Kimi',home:'https://www.kimi.com/',conversation:/^\/chat\/[A-Za-z0-9_-]{4,150}$/}
};
