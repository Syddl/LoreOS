"""The free part of `npm run paid:eval`: every check that can fail before the first paid call, then the plan.

Spec behaviour 4: the checks run in order and the first failure stops with its fix. Nothing here embeds, answers
or judges; listing models is free. Every `dataset.<NAME>` is read at call time, so a test can patch the paths.
"""

import collections
from typing import NoReturn

import openai

from loreos import answering, chunking, ingest, llm, parsing, settings, smoke
from loreos.evaluation import dataset, fetch, labels, run

CALL_ALLOWANCE = 1000  # tokens per answer or judge call beside the passages: instructions, question, source labels, answer


async def preflight(limit: int | None) -> str:
    """Run the checks, print the planned calls and tokens, and return the commit the run must still be at when it writes."""
    questions, calibration = _evaluation_set()
    manifest = _read(dataset.read_manifest, dataset.MANIFEST)
    if problems := dataset.manifest_problems(manifest):
        _refuse(f"{dataset.MANIFEST.name} is not valid", problems)
    if problems := fetch.corpus_problems(manifest, dataset.CORPUS_DIR):
        _refuse(f"the corpus in {dataset.CORPUS_DIR} is not the one {dataset.MANIFEST.name} pins", problems)
    files_by_hash = collections.defaultdict(list)
    for item in manifest["files"]:
        files_by_hash[item["sha256"]].append(item["file"])
    if same := [" and ".join(files) for files in files_by_hash.values() if len(files) > 1]:
        _refuse("corpus files with identical bytes, which ingest would store as one document",
                [f"{files}: keep one of them in {dataset.MANIFEST.name}" for files in same])
    corpus = run.load_corpus(manifest)
    entries, problems = fetch.corpus_outline(corpus)
    if problems:
        _refuse("corpus files that cannot be parsed", problems)
    if problems := labels.label_problems(questions, entries):
        _refuse("labels that match no section of the corpus", problems)
    await smoke.preflight()  # the database, the migration head, and the key
    await _check_models()
    if limit is None and not run.tree_clean():
        raise SystemExit("preflight: the git tree is not clean; commit or remove the changes, "
                         "since a committed result must name the code that produced it")
    await _print_plan(questions[:limit], len(questions), calibration if limit is None else None, manifest, corpus)
    for warning in labels.broad_labels(questions, entries):
        print(f"warning: {warning}")
    return run.git_sha()


def _evaluation_set() -> tuple[list[dict], list[dict] | None]:
    """The questions and, when the file exists, the calibration rows; every problem in either stops the run."""
    if not dataset.QUESTIONS.is_file():
        raise SystemExit(f"preflight: {dataset.QUESTIONS.as_posix()} is missing; write the evaluation set as eval/README.md describes")
    questions = _read(dataset.read_jsonl, dataset.QUESTIONS)
    calibration = _read(dataset.read_jsonl, dataset.CALIBRATION) if dataset.CALIBRATION.is_file() else None
    if problems := dataset.question_problems(questions):
        _refuse(f"{dataset.QUESTIONS.name} is not valid", problems)
    if calibration is not None and (problems := dataset.calibration_problems(calibration)):
        _refuse(f"{dataset.CALIBRATION.name} is not valid", problems)
    return questions, calibration


async def _check_models() -> None:
    """Each configured model is in the API's model list; a server without a model list leaves them unverified."""
    try:
        async with llm.client() as client:
            listed = {model.id for model in (await client.models.list()).data}
    except openai.APIStatusError as e:  # a compatible server without /models: ambiguous, so go on, as paid:smoke does
        print(f"preflight: listing models returned {e.status_code}; the model names are unverified, continuing")
        return
    except openai.OpenAIError as e:
        raise SystemExit(f"preflight: cannot list the models ({type(e).__name__}: {e}); check the network and OPENAI_BASE_URL") from e
    models = {"EMBEDDING_MODEL": settings.embedding_model(), "ANSWER_MODEL": settings.answer_model(), "JUDGE_MODEL": settings.judge_model()}
    if missing := [f"{env}={model}" for env, model in models.items() if model not in listed]:
        raise SystemExit(f"preflight: the API lists no model {', '.join(missing)}; set each in .env to a model your key can use")


async def _print_plan(asked: list[dict], total: int, calibration: list[dict] | None, manifest: dict, corpus: dict[str, bytes]) -> None:
    """The calls and tokens the run will spend: corpus embedding exactly, answers and judging as an upper estimate."""
    answerable = sum(q["answerable"] for q in asked)
    name = run.workspace_name(manifest)
    _, reused = await run.workspace_status(name, corpus)
    tokens = calls = 0
    if not reused:  # what ingest embeds: each file's chunks, in batches of EMBED_BATCH per file
        for file, data in corpus.items():
            chunks = chunking.chunk(parsing.parse(file, data))
            tokens += sum(chunking.count_tokens(ingest.embedding_input(c)) for c in chunks)
            calls += -(-len(chunks) // llm.EMBED_BATCH)
    rows = len(calibration) if calibration is not None else 0
    judged = len(asked) + rows
    per_call = answering.TOP_K * chunking.CHUNK_TOKENS + CALL_ALLOWANCE
    print(f"plan: {len(asked)} of {total} questions ({answerable} answerable, {len(asked) - answerable} unanswerable)")
    print(f"plan: workspace {name} {'reused' if reused else 'to build'}; corpus embedding {tokens} tokens in {calls} embed calls")
    print(f"plan: embed calls {calls + len(asked)} ({calls} for the corpus, one per question)")
    print(f"plan: answer calls up to {len(asked)}; judge calls up to {judged} ({len(asked)} answers, {rows} calibration rows)")
    print(f"plan: input tokens up to about {per_call} per answer or judge call ({answering.TOP_K} passages of up to "
          f"{chunking.CHUNK_TOKENS} tokens, plus {CALL_ALLOWANCE}), {per_call * (len(asked) + judged)} in all; "
          "output tokens are not capped")


def _read(reader, path):
    """reader(path), with an unreadable file stopping the preflight; a DatasetError names the line and the fix."""
    try:
        return reader(path)
    except dataset.DatasetError as e:
        raise SystemExit(f"preflight: {e}") from e


def _refuse(what: str, problems: list[str]) -> NoReturn:
    """Stop with every problem on its own line; each problem carries its own fix."""
    listed = "".join(f"\n  {problem}" for problem in problems)
    raise SystemExit(f"preflight: {what}; fix each, then run again:{listed}")
