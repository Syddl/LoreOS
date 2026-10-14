// check-readme: README.md's results table is exactly what scripts/readme-table.mjs builds from the committed result
// files and retrieval.DEFAULT_MODE; its prose uses no word the glossary avoids; its relative links resolve. First it
// replays fixture cases through the same functions, so a generator that stops refusing or formats a cell wrongly fails
// here even while the real README happens to agree with it.
//
// Does NOT exercise: numbers in the README's prose (a review item, decision 0011), synonyms the glossary does not
// list, links to other sites, or whether the result files themselves are honest (check:backend's result check).
import fs from 'node:fs';
import path from 'node:path';
import {
  END, MODES, ROOT, START, blockDifference, buildBlock, currentBlock, defaultMode, findGroup, glossaryProblems, linkProblems,
  replaceBlock,
} from './readme-table.mjs';

const failures = [];
let passed = 0;

function check(name, ok, detail = '') {
  if (ok) passed += 1;
  else failures.push(`${name}${detail ? `: ${detail}` : ''}`);
}

function refuses(name, run, fragment) {
  try {
    run();
    check(name, false, 'did not refuse');
  } catch (e) {
    check(name, e.message.includes(fragment), `refused with "${e.message}", not one naming "${fragment}"`);
  }
}

// A result file as paid:eval writes it, with distinct values per metric and per mode, so a cell read from the wrong
// key, or a row filled from another mode's file, shows. Judge agreement is the same in every mode unless set.
function result(mode, { sha = 'a'.repeat(40), created = '2026-10-14T10:00:00Z', destination = 'results', calibration = 'h', k = 5 } = {}) {
  const step = MODES.indexOf(mode) / 10;
  const at = (value) => Math.round((value + step) * 1000) / 1000;
  return {
    file: `${created.replace(/[-:]/g, '')}-${mode}-${sha.slice(0, 8)}.json`,
    data: {
      schema: 1, git_sha: sha, created_at: created, mode, destination,
      settings: { embedding_model: 'e', answer_model: 'a', judge_model: 'j', chunk_tokens: 500, chunk_overlap: 50, k, rerank_model: 'r' },
      corpus_hash: 'c', questions_hash: 'q', calibration_hash: calibration,
      counts: { questions: 81, answerable: 66, calibration_rows: 30 },
      metrics: {
        recall_at_5: at(0.111), mrr_at_10: at(0.222), citation_accuracy: at(0.333), unanswerable_refused: at(0.444),
        answerable_refused: at(0.555), faithfulness: at(0.666), judge_agreement: 0.777,
      },
      latency_ms: { search_p50: 1234.4 + step * 10000, search_p95: 5678.5 + step * 10000 },
    },
  };
}
const group = (options) => MODES.map((mode) => result(mode, options));
const README = `# LoreOS\n\n${START}\n${END}\n`;

// The golden row: every cell from its own key, formatted as the files have it, nothing else.
const golden = buildBlock(group(), 'hybrid_rerank').split('\n');
for (const line of [
  '| Vector search only | 0.111 | 0.222 | 0.333 | 0.444 | 0.555 | 0.666 | 1234 ms | 5679 ms |',
  '| + keyword search, fused with RRF | 0.211 | 0.322 | 0.433 | 0.544 | 0.655 | 0.766 | 2234 ms | 6679 ms |',
  '| **+ local reranker (served by default)** | 0.311 | 0.422 | 0.533 | 0.644 | 0.755 | 0.866 | 3234 ms | 7679 ms |',
]) {
  check(`golden row: ${line.slice(2, 30)}`, golden.includes(line), golden.find((row) => row.startsWith(line.slice(0, 12))));
}
check('judge agreement is one value when the files agree', golden.some((line) => line.includes("Claude's grades of 30 calibration answers: 0.777.")));
const split = group();
split[1].data.metrics.judge_agreement = 0.9;
check('judge agreement per mode when the files differ',
  buildBlock(split, 'vector').includes('0.777 (vector), 0.900 (hybrid), 0.777 (hybrid_rerank)'));
const withNull = group();
withNull[0].data.metrics.faithfulness = null;
check('a null metric is n/a, never 0', buildBlock(withNull, 'vector').includes('| 0.555 | n/a | 1234 ms |'));

// Group selection.
const filled = replaceBlock(README, buildBlock(group(), 'vector'));
check('an unchanged README has no difference', blockDifference(filled, buildBlock(group(), 'vector')) === null);
const edited = filled.replace('| 0.222 |', '| 0.223 |');
const difference = blockDifference(edited, buildBlock(group(), 'vector'));
check('an edited cell is a difference that names it', difference?.includes('0.223') && difference.includes('0.222'), difference ?? 'none');
refuses('mixed commits make no complete group', () => findGroup([result('vector'), result('hybrid'), result('hybrid_rerank', { sha: 'b'.repeat(40) })]),
  'no complete group');
refuses('a missing mode', () => findGroup([result('vector'), result('hybrid')]), 'no complete group');
refuses('mixed calibration rows make no complete group',
  () => findGroup([result('vector'), result('hybrid'), result('hybrid_rerank', { calibration: 'other' })]), 'no complete group');
refuses('mixed settings make no complete group', () => findGroup([result('vector'), result('hybrid'), result('hybrid_rerank', { k: 10 })]),
  'no complete group');
refuses('two results of one mode in the newest group', () => findGroup([...group(), result('hybrid', { created: '2026-10-14T11:00:00Z' })]),
  '2 hybrid results');
const oldDuplicate = [...group({ sha: 'd'.repeat(40), created: '2026-10-13T09:00:00Z' }), result('vector', { sha: 'd'.repeat(40), created: '2026-10-13T10:00:00Z' })];
check('a duplicate in an older group does not block the newest', findGroup([...oldDuplicate, ...group()])[0].data.git_sha === 'a'.repeat(40));
const older = group({ created: '2026-10-14T09:00:00Z' });
const picked = findGroup([...older, result('vector', { sha: 'b'.repeat(40), created: '2026-10-15T09:00:00Z' })]);
check('a newer lone file at another commit does not displace a complete group', picked[0].data.git_sha === 'a'.repeat(40));
const newerGroup = group({ sha: 'c'.repeat(40), created: '2026-10-16T09:00:00Z' });
check('the newest complete group wins', findGroup([...older, ...newerGroup])[0].data.git_sha === 'c'.repeat(40));
refuses('a scratch result is never published', () => findGroup([result('vector'), result('hybrid'), result('hybrid_rerank', { destination: 'scratch' })]),
  'no complete group');
refuses('an unreadable DEFAULT_MODE', () => defaultMode('DEFAULT_MODE = MODES[0]\n'), 'cannot read DEFAULT_MODE');
check('DEFAULT_MODE read from its line', defaultMode('x = 1\nDEFAULT_MODE = "hybrid"  # decision 0010\n') === 'hybrid');
refuses('a README without the markers', () => replaceBlock('# LoreOS\n', 'x'), 'lacks');

// The glossary governs prose, not URLs or code.
const glossary = { _why: 'note', workspace: { avoid: ['tenant', 'organization', 'org'] }, 'keyword search': { avoid: ['BM25'] } };
check('"Organization" in prose fails', glossaryProblems('Answers for your Organization.\n', glossary).length === 1);
check('"org" as a word fails', glossaryProblems('Every org gets one.\n', glossary).length === 1);
check('a URL with .org passes', glossaryProblems('CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)\n', glossary).length === 0);
check('a link target with .org passes', glossaryProblems('[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)\n', glossary).length === 0);
check('"forget" passes', glossaryProblems('Do not forget the key.\n', glossary).length === 0);
check('a word inside a code span passes', glossaryProblems('The column is `BM25`.\n', glossary).length === 0);
check('a plural fails', glossaryProblems('Several organizations use it.\n', glossary).length === 1);
const phrases = { 'evaluation set': { avoid: ['test set'] } };
check('a phrase split across a line fails', glossaryProblems('the test\nset was hand written\n', phrases).length === 1);
refuses('a glossary with nothing to avoid', () => glossaryProblems('anything\n', { _why: 'note' }), 'no word to avoid');

// Relative links resolve.
const missing = linkProblems('See [the plan](docs/no-such-file.md) and [the site](https://example.com).\n', ROOT);
check('a missing link target is named', missing.length === 1 && missing[0].includes('docs/no-such-file.md'), missing.join('; '));
check('an existing link target passes', linkProblems('[License](LICENSE)\n', ROOT).length === 0);

// The real README.
const readme = fs.readFileSync(path.join(ROOT, 'README.md'), 'utf8').replace(/\r\n/g, '\n');
try {
  const realDifference = blockDifference(readme, currentBlock());
  check('README.md results block is what npm run readme:table builds', realDifference === null,
    `${realDifference}\nrun npm run readme:table and commit README.md`);
} catch (e) {
  check('README.md results block can be built', false, e.message);
}
const harness = JSON.parse(fs.readFileSync(path.join(ROOT, '.claude', 'harness.json'), 'utf8'));
for (const problem of glossaryProblems(readme, harness.glossary)) check('README.md glossary', false, problem);
for (const problem of linkProblems(readme, ROOT)) check('README.md links', false, problem);

for (const failure of failures) console.error(`  FAIL ${failure}`);
console.log(`check:readme: ${passed}/${passed + failures.length} checks passed`);
process.exit(failures.length ? 1 : 0);
