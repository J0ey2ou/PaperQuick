'use strict';

// Offline stdin/stdout adapter. No HTTP, Word automation, or user-code evaluation.
const fs = require('fs');
const path = require('path');
const CSL = require('./vendor/citeproc.js');

const warnings = [];
CSL.debug = () => warnings.push('部分引用细节需要核对，请检查文献资料和所选格式。');
const localeCache = new Map();
function retrieveLocale(language) {
  const tag = String(language || 'en-US');
  if (!/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(tag)) return false;
  if (localeCache.has(tag)) return localeCache.get(tag);
  const filename = path.join(__dirname, 'locales', `locales-${tag}.xml`);
  const value = fs.existsSync(filename) ? fs.readFileSync(filename, 'utf8') : false;
  localeCache.set(tag, value);
  return value;
}

function unicodeRtf(text) {
  // The RTF specification uses signed UTF-16 code units (including surrogate pairs).
  return String(text).replace(/(?<!\\)\\u(\d+)(?=[^\d]|$)/g, (_, code) => {
    const n = Number(code);
    return `\\u${n >= 32768 ? n - 65536 : n}`;
  }).replace(/[^\x00-\x7f]/g, char => {
    const code = char.charCodeAt(0);
    return `\\uc0\\u${code >= 32768 ? code - 65536 : code}{}`;
  });
}

function rtfDocument(body) {
  return '{\\rtf1\\ansi\\ansicpg1252\\deff0\\uc0' +
    '{\\fonttbl{\\f0\\froman Times New Roman;}{\\f1\\fnil SimSun;}}' +
    '\\viewkind4\\pard\\f0\\fs22 ' + unicodeRtf(body) + '}';
}

function bibliographyRtf(parameters, entries) {
  if (!entries.length) return rtfDocument('');
  const hanging = Boolean(parameters.hangingindent);
  const aligned = Boolean(parameters['second-field-align']);
  const offset = Math.max(360, (Number(parameters.maxoffset) + 1) * 120);
  const indent = hanging ? 720 : (aligned ? offset : 0);
  const lines = Math.max(1, Number(parameters.linespacing) || 1);
  const spacing = Math.max(0, Number(parameters.entryspacing) || 0) * 220;
  const paragraph = '\\pard\\f0\\fs22' +
    `\\sl${Math.round(240 * lines)}\\slmult1\\sa${spacing}` +
    (indent ? `\\li${indent}\\fi-${indent}\\tx${indent}` : '\\li0\\fi0') + ' ';
  return rtfDocument(entries.map(entry => paragraph + entry.trim()).join('\\par\n'));
}

function render(input, format) {
  const items = JSON.parse(JSON.stringify(input.items));
  const processor = new CSL.Engine({
    retrieveLocale,
    retrieveItem(id) {
      const item = items[String(id)];
      if (!item) throw new Error(`Missing citation item: ${id}`);
      return item;
    }
  }, input.style_xml, input.locale || 'en-US', Boolean(input.force_locale));
  processor.setOutputFormat(format);
  const citations = {};
  const preceding = [];
  input.citations.forEach((citation, index) => {
    const cluster = {
      citationID: citation.id,
      citationItems: JSON.parse(JSON.stringify(citation.items)),
      properties: {noteIndex: citation.noteIndex || 0}
    };
    const result = processor.processCitationCluster(cluster, preceding.slice(), []);
    for (const [position, rendered] of result[1]) {
      const changedId = input.citations[position].id;
      citations[changedId] = rendered;
    }
    preceding.push([citation.id, cluster.properties.noteIndex]);
    if (result[0].citation_errors && result[0].citation_errors.length) {
      warnings.push('部分文献资料不完整，请核对作者、年份和标题。');
    }
  });
  const bibliography = processor.makeBibliography();
  const parameters = bibliography ? bibliography[0] : {};
  const entries = bibliography ? bibliography[1] : [];
  if (parameters.bibliography_errors && parameters.bibliography_errors.length) {
    warnings.push('部分参考文献信息不完整，请核对后再提交。');
  }
  return {citations, parameters, entries};
}

function main(input) {
  const rich = render(input, 'rtf');
  const plain = render(input, 'text');
  const result = {};
  for (const [id, value] of Object.entries(rich.citations)) result[id] = rtfDocument(value);
  return {
    citations: result,
    bibliography: bibliographyRtf(rich.parameters, rich.entries),
    bibliography_ids: (rich.parameters.entry_ids || []).flat().map(String),
    bibliography_parameters: {
      hangingindent: Boolean(rich.parameters.hangingindent),
      second_field_align: rich.parameters['second-field-align'] || false,
      linespacing: rich.parameters.linespacing || 1,
      entryspacing: rich.parameters.entryspacing || 0
    },
    plain_citations: plain.citations,
    plain_bibliography: plain.entries.map(entry => entry.trim()).join('\n'),
    warnings: [...new Set(warnings)].slice(0, 20)
  };
}

let incoming = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', part => {
  incoming += part;
  if (incoming.length > 32 * 1024 * 1024) {
    process.stderr.write('Citation request is too large.');
    process.exit(2);
  }
});
process.stdin.on('end', () => {
  try {
    process.stdout.write(JSON.stringify(main(JSON.parse(incoming))));
  } catch (error) {
    process.stdout.write(JSON.stringify({error: String(error.message || error)}));
    process.exitCode = 1;
  }
});
