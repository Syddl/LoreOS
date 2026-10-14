// readme-table: the README's results table, generated from the committed result files of one commit (spec P5,
// behaviours 1 and 2). `npm run readme:table` rewrites README.md between the markers; `npm run check:readme`
// (scripts/check-readme.mjs) fails when the README differs from what this builds. No number is typed by hand or
// filled by default: a group that is not complete, or not unique, is refused with the reason.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const MODES = ['vector', 'hybrid', 'hybrid_rerank'];
export const START = '<!-- results:start -->';
export const END = '<!-- results:end -->';
const LABELS = {
  vector: 'Vector search only',
  hybrid: '+ keyword search, fused with RRF',
  hybrid_rerank: '+ local reranker',
};
const RATIOS = [
  ['Recall@5', 'recall_at_5'],
  ['MRR@10', 'mrr_at_10'],
  ['Citation accuracy', 'citation_accuracy'],
  ['Unanswerable refused', 'unanswerable_refused'],
  ['Answerable wrongly refused', 'answerable_refused'],
  ['Faithfulness', 'faithfulness'],
];
const LATENCIES = [['Search p50', 'search_p50'], ['Search p95', 'search_p95']];

/** JSON with sorted keys at every level, so two settings objects compare equal exactly when their contents do. */
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

/**
 * The newest complete group among `results` ([{file, data}]): a committed result for every mode, sharing schema,
 * commit, corpus, questions and calibration hashes and settings. A group is as new as its newest file. When that
 * newest group holds two results of one mode, either could be the one published, so it is refused; a duplicate in an
 * older group never matters, since result files are never edited by hand.
 */
export function findGroup(results) {
  const tuples = new Map();
  for (const result of results) {
    const d = result.data;
    if (d.destination !== 'results' || !MODES.includes(d.mode)) continue;
    const key = canonical([d.schema, d.git_sha, d.corpus_hash, d.questions_hash, d.calibration_hash, d.settings]);
    if (!tuples.has(key)) tuples.set(key, new Map(MODES.map((mode) => [mode, []])));
    tuples.get(key).get(d.mode).push(result);
  }
  const newest = (byMode) => [...byMode.values()].flat().map((result) => result.data.created_at).sort().at(-1);
  const [chosen] = [...tuples.values()]
    .filter((byMode) => [...byMode.values()].every((files) => files.length > 0))
    .sort((a, b) => newest(b).localeCompare(newest(a)));
  if (!chosen) {
    throw new Error(`no complete group in eval/results/: one committed result per mode (${MODES.join(', ')}) sharing the commit, `
      + 'the hashes and the settings; run npm run paid:eval -- --mode all from a clean tree and commit its files');
  }
  for (const [mode, files] of chosen) {
    if (files.length > 1) {
      throw new Error(`the newest complete group has ${files.length} ${mode} results: ${files.map((r) => r.file).join(' and ')}; `
        + 'remove the one that should not be published');
    }
  }
  return MODES.map((mode) => chosen.get(mode)[0]);
}

/** The mode the api serves, read from backend/loreos/retrieval.py, the one owner of that fact. */
export function defaultMode(retrievalSource) {
  const found = /^DEFAULT_MODE = "([a-z_]+)"/m.exec(retrievalSource)?.[1];
  if (!MODES.includes(found)) throw new Error(`cannot read DEFAULT_MODE from backend/loreos/retrieval.py (found ${found ?? 'nothing'})`);
  return found;
}

function cell(source, key, format, file) {
  if (!(key in source)) throw new Error(`${file} has no ${key}; it is not a result file this table can read`);
  return source[key] === null ? 'n/a' : format(source[key]);
}

/** The Markdown between the markers: the table, then its caption. Every value comes from the group's files. */
export function buildBlock(group, served) {
  const [first] = group;
  const s = first.data.settings;
  const header = ['Retrieval', ...RATIOS.map(([name]) => name), ...LATENCIES.map(([name]) => name)];
  const rows = group.map(({ file, data }) => {
    const label = data.mode === served ? `**${LABELS[data.mode]} (served by default)**` : LABELS[data.mode];
    return [
      label,
      ...RATIOS.map(([, key]) => cell(data.metrics, key, (v) => v.toFixed(3), file)),
      ...LATENCIES.map(([, key]) => cell(data.latency_ms, key, (v) => `${Math.round(v)} ms`, file)),
    ];
  });
  const agreements = group.map(({ file, data }) => cell(data.metrics, 'judge_agreement', (v) => v.toFixed(3), file));
  const agreement = new Set(agreements).size === 1
    ? agreements[0]
    : group.map(({ data }, i) => `${agreements[i]} (${data.mode})`).join(', ');
  const links = group.map(({ file, data }) => `[${data.mode}](eval/results/${file})`).join(', ');
  const c = first.data.counts;
  return [
    '<!-- Generated by npm run readme:table from eval/results/. Do not edit by hand: npm run check:readme compares it. -->',
    '',
    `| ${header.join(' | ')} |`,
    `|${header.map(() => '---').join('|')}|`,
    ...rows.map((row) => `| ${row.join(' | ')} |`),
    '',
    `Measured at commit \`${first.data.git_sha.slice(0, 7)}\` (${links}): ${c.questions} questions, ${c.answerable} of them answerable, `
      + 'over the [evaluation corpus](eval/corpus.json).',
    `Embeddings \`${s.embedding_model}\`, answers \`${s.answer_model}\`, faithfulness judged by \`${s.judge_model}\`, `
      + `reranker \`${s.rerank_model}\`. Chunks of ${s.chunk_tokens} tokens with ${s.chunk_overlap} of overlap; the answer model reads the top ${s.k}.`,
    `Judge agreement with Claude's grades of ${c.calibration_rows} calibration answers: ${agreement}. `
      + 'Search time is one question at a time on the machine that ran the evaluation, and includes the question\'s embedding call.',
  ].join('\n');
}

/** readme with everything between the markers replaced by block. */
export function replaceBlock(readme, block) {
  const start = readme.indexOf(START);
  const end = readme.indexOf(END);
  if (start < 0 || end < start) throw new Error(`README.md lacks ${START} followed by ${END}; add both where the results table goes`);
  return `${readme.slice(0, start + START.length)}\n${block}\n${readme.slice(end)}`;
}

/** The first line where the README's block differs from block, as "line n: has ... / expected ..."; null when equal. */
export function blockDifference(readme, block) {
  const expected = replaceBlock(readme, block).split('\n');
  const actual = readme.split('\n');
  for (let i = 0; i < Math.max(expected.length, actual.length); i += 1) {
    if (expected[i] !== actual[i]) return `line ${i + 1}: has\n  ${actual[i] ?? '(nothing)'}\nexpected\n  ${expected[i] ?? '(nothing)'}`;
  }
  return null;
}

/** Text with code, link targets and URLs removed: the prose a reader sees, which is what the glossary governs. */
function prose(readme) {
  return readme
    .replace(/^```[\s\S]*?^```/gm, ' ')
    .replace(/`[^`\n]*`/g, ' ')
    .replace(/\]\([^)\s]*(?:\s+"[^"]*")?\)/g, '] ')
    .replace(/<https?:[^>\s]*>/g, ' ')
    .replace(/https?:\/\/\S+/g, ' ');
}

/**
 * Each glossary word the README's prose uses, with the term to say instead: whole words in any case, plurals and line
 * breaks inside a phrase included. A glossary with no word to avoid is refused, so a check reading the wrong file
 * fails rather than passing every README.
 */
export function glossaryProblems(readme, glossary) {
  const entries = Object.entries(glossary ?? {}).filter(([term]) => term !== '_why');
  if (!entries.some(([, entry]) => entry?.avoid?.length)) throw new Error('the glossary lists no word to avoid; check .claude/harness.json');
  const text = prose(readme);
  const problems = [];
  for (const [term, entry] of entries) {
    for (const word of entry.avoid ?? []) {
      const phrase = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/ /g, '\\s+');
      if (new RegExp(`\\b${phrase}(?:s|es)?\\b`, 'i').test(text)) {
        problems.push(`README.md says "${word}"; say "${term}" (glossary in .claude/harness.json)`);
      }
    }
  }
  return problems;
}

/** Each relative link or image whose target does not exist under root. */
export function linkProblems(readme, root) {
  const problems = [];
  const withoutCode = readme.replace(/^```[\s\S]*?^```/gm, ' ').replace(/`[^`\n]*`/g, ' ');
  for (const [, target] of withoutCode.matchAll(/\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g)) {
    if (/^(?:[a-z]+:|#)/i.test(target)) continue;
    const file = decodeURIComponent(target.split('#')[0]);
    if (!fs.existsSync(path.join(root, file))) problems.push(`README.md links ${target}, which does not exist`);
  }
  return problems;
}

/** Every result file under dir, as {file, data}. */
export function readResults(dir) {
  return fs.readdirSync(dir).filter((name) => name.endsWith('.json')).sort()
    .map((file) => ({ file, data: JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8')) }));
}

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** The block the committed files and code give today. */
export function currentBlock(root = ROOT) {
  const group = findGroup(readResults(path.join(root, 'eval', 'results')));
  return buildBlock(group, defaultMode(fs.readFileSync(path.join(root, 'backend', 'loreos', 'retrieval.py'), 'utf8')));
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  try {
    const readmePath = path.join(ROOT, 'README.md');
    const readme = fs.readFileSync(readmePath, 'utf8').replace(/\r\n/g, '\n');
    fs.writeFileSync(readmePath, replaceBlock(readme, currentBlock()));
    console.log('readme:table: README.md results block rewritten from eval/results/');
  } catch (e) {
    console.error(`readme:table: ${e.message}`);
    process.exit(1);
  }
}
