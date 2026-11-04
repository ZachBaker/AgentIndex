# Prompts

Every step of the benchmark that needed judgement was done by coding agents in the Claude Code
harness, each starting with a fresh context and only the prompt below. They are kept here,
word for word, so the method can be checked and repeated. Only local paths are shortened:
`<root>` is the corpus checkout in `bench/.cache/<corpus>`, and `<work>` a scratch folder
outside the repository holding the drafts and the PR title lists. How the steps fit together:
[knowledge/development/benchmarks.md](../knowledge/development/benchmarks.md).

1. [Writing questions](#1-writing-questions), without seeing the docs
2. [Labeling answers](#2-labeling-answers), by two labelers and a reconciler
3. [Judging pooled results](#3-judging-pooled-results) that no labeler had judged
4. [Real agents answering](#4-real-agents-answering), with and without AgentIndex
5. [Grading their answers](#5-grading-their-answers)

## 1. Writing questions

One agent per corpus, given 300 recently merged PR (or MR) titles from the project and a
paragraph on what the docs cover, and told not to open the docs. The prompt for the Rust
compiler dev guide:

````text
You are helping build a benchmark that measures how well a documentation search tool (AgentIndex: lexical search over a folder of markdown docs) helps coding agents find project knowledge. This is phase 1 of 2: you write realistic questions that a coding agent would need answered while doing real tasks. You must NOT look at the documentation being searched — that is deliberate. A different person will later find which doc answers each question. Writing blind keeps the questions phrased the way an agent asks *before* it has read the docs, so they don't copy the docs' wording (which would make the benchmark too easy and unconvincing).

## Project and knowledge base
Project: the Rust compiler and standard library (github.com/rust-lang/rust). The agent is working on a task in that repository.
Knowledge base to be searched: the rustc-dev-guide, the compiler's contributor guide. Scope, in general terms: getting the source and building the compiler and standard library with the `x` tool, running and writing the different test suites, debugging and profiling the compiler, the compiler's architecture and internals (from parsing and macro expansion through name resolution, type checking, trait solving, borrow checking, MIR and its optimizations, monomorphization and code generation), diagnostics and lints, how language and library features go from unstable to stable, and contribution procedures (PRs, reviews, CI, backports, working with submodules/subtrees).

## Inputs
Real tasks: `<work>/tasks/rust-lang_rust.txt` holds 300 recently merged PR titles (`#number<TAB>title`). Base your questions on these.

## Rules
1. Do NOT open, read, list, grep or search any documentation of this project, local or on the web. In particular never look inside `<work>/corpora/` or `<work>/agentfiles/`, and don't fetch rustc-dev-guide pages. Use only the PR titles file and your own general knowledge of the project.
2. Write 40 questions. For each, pick a PR title representing a task during which an agent would realistically need to look something up in the contributor guide, and write the question that agent would ask. At most 8 questions may come from general knowledge of common contributor tasks instead of a specific PR (then `"pr": null` and `"task"` describes the task).
3. Questions must be about project-specific knowledge that the guide plausibly covers given its scope — procedures, commands, where things live, conventions and rules, how a subsystem works, what to do when something fails — not general Rust programming knowledge.
4. Mix of kinds, roughly: how-to/procedure (~35%), how-it-works/architecture (~25%), convention/rule (~15%), where-is (~10%), troubleshooting (~15%). Spread across different areas; no near-duplicates (no two questions answerable by the same paragraph).
5. Two phrasings per question:
   - `"question"`: natural language, as the agent would ask a teammate, 8–25 words.
   - `"keywords"`: the 2–6 words the agent would type into a docs search box. Use words the agent knows from the task, the code or tool output — don't try to guess doc titles.
6. Realism over cleverness: write what an agent that knows Rust and has the repo open, but has not read the guide, would really ask.

## Output
Write valid JSON (UTF-8) to `<work>/cases-draft/rustc-dev-guide.json`:
```json
{"corpus": "rustc-dev-guide", "questions": [
  {"id": "rustc-01", "pr": "#164686", "task": "<PR title verbatim>", "kind": "how-to", "question": "...", "keywords": "..."}
]}
```
`kind` is one of how-to, how-it-works, convention, where, troubleshooting. Validate the file with `python3 -m json.tool <file> > /dev/null`. Reply with just the file path and the number of questions per kind.
````

The other corpora got the same prompt with their own project, scope and mix of kinds:

<details>
<summary>Node.js contributor docs</summary>

````text
You are helping build a benchmark that measures how well a documentation search tool (AgentIndex: lexical search over a folder of markdown docs) helps coding agents find project knowledge. This is phase 1 of 2: you write realistic questions that a coding agent would need answered while doing real tasks. You must NOT look at the documentation being searched — that is deliberate. A different person will later find which doc answers each question. Writing blind keeps the questions phrased the way an agent asks *before* it has read the docs, so they don't copy the docs' wording (which would make the benchmark too easy and unconvincing).

## Project and knowledge base
Project: Node.js (github.com/nodejs/node). The agent is working on a task in that repository.
Knowledge base to be searched: Node.js's contributor documentation (the `doc/contributing/` folder). Scope, in general terms: building Node.js, writing and running tests and benchmarks, coding conventions for the JavaScript and C++ parts of the codebase, internal JavaScript APIs and conventions inside `lib/`, how errors are defined and thrown internally, documentation conventions, how pull requests are reviewed and landed, collaborator responsibilities and onboarding, backporting and the release process, security releases, and project maintenance/governance procedures (including maintaining dependencies).

## Inputs
Real tasks: `<work>/tasks/nodejs_node.txt` holds 300 recently merged PR titles (`#number<TAB>title`). Base your questions on these.

## Rules
1. Do NOT open, read, list, grep or search any documentation of this project, local or on the web. In particular never look inside `<work>/corpora/` or `<work>/agentfiles/`, and don't fetch nodejs docs pages. Use only the PR titles file and your own general knowledge of the project.
2. Write 40 questions. For each, pick a PR title representing a task during which an agent would realistically need to look something up in the contributor docs, and write the question that agent would ask. At most 8 questions may come from general knowledge of common contributor tasks instead of a specific PR (then `"pr": null` and `"task"` describes the task).
3. Questions must be about project-specific knowledge that the docs plausibly cover given their scope — procedures, commands, where things live, conventions and rules, how internals work, what to do when something fails — not general JavaScript/C++ knowledge.
4. Mix of kinds, roughly: how-to/procedure (~35%), how-it-works (~20%), convention/rule (~25%), where-is (~5%), troubleshooting (~15%). Spread across different areas; no near-duplicates (no two questions answerable by the same paragraph).
5. Two phrasings per question:
   - `"question"`: natural language, as the agent would ask a teammate, 8–25 words.
   - `"keywords"`: the 2–6 words the agent would type into a docs search box. Use words the agent knows from the task, the code or tool output — don't try to guess doc titles.
6. Realism over cleverness: write what an agent that knows JavaScript/C++ and has the repo open, but has not read the contributor docs, would really ask.

## Output
Write valid JSON (UTF-8) to `<work>/cases-draft/node-contributing.json`:
```json
{"corpus": "node-contributing", "questions": [
  {"id": "node-01", "pr": "#66599", "task": "<PR title verbatim>", "kind": "how-to", "question": "...", "keywords": "..."}
]}
```
`kind` is one of how-to, how-it-works, convention, where, troubleshooting. Validate the file with `python3 -m json.tool <file> > /dev/null`. Reply with just the file path and the number of questions per kind.
````

</details>

<details>
<summary>GitLab development docs</summary>

````text
You are helping build a benchmark that measures how well a documentation search tool (AgentIndex: lexical search over a folder of markdown docs) helps coding agents find project knowledge. This is phase 1 of 2: you write realistic questions that a coding agent would need answered while doing real tasks. You must NOT look at the documentation being searched — that is deliberate. A different person will later find which doc answers each question. Writing blind keeps the questions phrased the way an agent asks *before* it has read the docs, so they don't copy the docs' wording (which would make the benchmark too easy and unconvincing).

## Project and knowledge base
Project: GitLab (the gitlab-org/gitlab Rails monolith on gitlab.com). The agent is working on a task in that repository.
Knowledge base to be searched: GitLab's development documentation (`doc/development/`, ~670 docs). Scope, in general terms: engineering guidelines for contributing to GitLab — backend (Ruby on Rails) and frontend (Vue, GraphQL client) conventions; database guidelines (migrations of all kinds, batched background migrations, large tables, indexes, query performance, multiple databases, partitioning); feature flags; testing (RSpec, Jest, end-to-end/QA, test levels, flaky tests); REST and GraphQL API style guides; Sidekiq workers and background jobs; caching, Redis; internationalization; security and secure coding; logging, metrics and instrumentation; permissions and authorization; code review process and merge request workflow; changelog entries; Danger; documentation for many specific subsystems and features (AI features, CI/CD internals, Gitaly, search, etc.).

## Inputs
Real tasks: `<work>/tasks/gitlab-org_gitlab.txt` holds 300 recently merged merge request titles (`!number<TAB>title`). Base your questions on these.

## Rules
1. Do NOT open, read, list, grep or search any documentation of GitLab, local or on the web. In particular never look inside `<work>/corpora/` or `<work>/agentfiles/`, and don't fetch docs.gitlab.com pages. Use only the MR titles file and your own general knowledge of the project.
2. Write 40 questions. For each, pick an MR title representing a task during which an agent would realistically need to look something up in the development docs, and write the question that agent would ask. At most 8 questions may come from general knowledge of common GitLab contributor tasks instead of a specific MR (then `"pr": null` and `"task"` describes the task).
3. Questions must be about project-specific knowledge the docs plausibly cover given their scope — procedures, conventions and rules, how a subsystem works, where things go, what to do when something fails — not general Ruby/Rails/JavaScript knowledge.
4. Mix of kinds, roughly: how-to/procedure (~35%), convention/rule (~25%), how-it-works (~20%), where-is (~5%), troubleshooting (~15%). Spread across different areas (database, frontend, testing, API, workers, feature flags, security, AI, observability, review process, ...); no near-duplicates.
5. Two phrasings per question:
   - `"question"`: natural language, as the agent would ask a teammate, 8–25 words.
   - `"keywords"`: the 2–6 words the agent would type into a docs search box. Use words the agent knows from the task, code or tool output — don't try to guess doc titles.
6. Realism over cleverness: write what an agent that knows Rails/Vue and has the repo open, but has not read the development docs, would really ask.

## Output
Write valid JSON (UTF-8) to `<work>/cases-draft/gitlab-development.json`:
```json
{"corpus": "gitlab-development", "questions": [
  {"id": "gitlab-01", "pr": "!265874", "task": "<MR title verbatim>", "kind": "how-to", "question": "...", "keywords": "..."}
]}
```
`kind` is one of how-to, how-it-works, convention, where, troubleshooting. Validate with `python3 -m json.tool <file> > /dev/null`. Reply with just the file path and the number of questions per kind.
````

</details>

<details>
<summary>Electron docs</summary>

````text
You are helping build a benchmark that measures how well a documentation search tool (AgentIndex: lexical search over a folder of markdown docs) helps coding agents find knowledge. This is phase 1 of 2: you write realistic questions that a coding agent would need answered while doing real tasks. You must NOT look at the documentation being searched — that is deliberate. A different person will later find which doc answers each question. Writing blind keeps the questions phrased the way an agent asks *before* it has read the docs, so they don't copy the docs' wording (which would make the benchmark too easy and unconvincing).

## Project and knowledge base
Knowledge base to be searched: Electron's official documentation (the `docs/` folder of github.com/electron/electron). Scope, in general terms: API reference for every module (main-process and renderer APIs: windows, IPC, menus, dialogs, tray, notifications, protocols, sessions and networking, web contents, clipboard, power and system events, crash reporting, auto-updating, etc.), tutorials and guides for app developers (process model, context isolation and preload scripts, security, packaging and distribution, code signing, updates, native modules, performance, accessibility, testing and debugging, offscreen rendering, deep links, keyboard shortcuts, dark mode, ...), and development docs for contributors who build Electron itself (building from source, debugging, testing, coding style, patches against Chromium/Node, PR process).

Two kinds of agents use these docs:
- **App developers** (about 30 of your questions): an agent building or maintaining an Electron app. Tasks are typical app features and problems (e.g. "add a tray icon with a context menu", "app shows a white flash on startup", "open external links in the default browser"). Use `"pr": null` and put the task in `"task"`.
- **Electron contributors** (about 10 questions): an agent working in the electron/electron repo. Base these on the real PR titles in `<work>/tasks/electron_electron.txt` (`#number<TAB>title`), with `"pr"` set.

## Rules
1. Do NOT open, read, list, grep or search any documentation of Electron, local or on the web. In particular never look inside `<work>/corpora/` or `<work>/agentfiles/`, and don't fetch electronjs.org pages. Use only the PR titles file and your general knowledge.
2. Write 40 questions (≈30 app developer, ≈10 contributor).
3. Questions must be ones the docs plausibly answer given the scope above — how to do something with Electron's APIs, how Electron works, what is required/recommended, how to fix a known class of problem — the things an agent would look up rather than already know for sure.
4. Mix of kinds, roughly: how-to (~45%), how-it-works (~15%), convention/recommendation/security rule (~15%), where/which API (~10%), troubleshooting (~15%). Spread across different areas; no near-duplicates.
5. Two phrasings per question:
   - `"question"`: natural language, as the agent would ask a teammate, 8–25 words.
   - `"keywords"`: the 2–6 words the agent would type into a docs search box. Use words the agent knows from the task, code or error output — don't try to guess doc titles or exact API names you are unsure of.
6. Realism over cleverness.

## Output
Write valid JSON (UTF-8) to `<work>/cases-draft/electron.json`:
```json
{"corpus": "electron", "questions": [
  {"id": "electron-01", "pr": null, "task": "Add a system tray icon with a context menu", "kind": "how-to", "question": "...", "keywords": "..."}
]}
```
`kind` is one of how-to, how-it-works, convention, where, troubleshooting. Validate with `python3 -m json.tool <file> > /dev/null`. Reply with just the file path and the number of questions per kind.
````

</details>

<details>
<summary>PostHog, Next.js and workerd AGENTS.md files (one prompt for all three)</summary>

````text
You are helping build a benchmark that measures how well a documentation search tool (AgentIndex: lexical search over markdown docs) helps coding agents find project knowledge. This is phase 1 of 2: you write realistic questions that a coding agent would need answered while doing real tasks. You must NOT look at the documents being searched — that is deliberate. A different person will later find which part of the document answers each question (and drop questions it doesn't answer). Writing blind keeps the questions phrased the way an agent asks *before* it has read the docs, so they don't copy the docs' wording (which would make the benchmark too easy and unconvincing).

There are three projects. Each has a large AGENTS.md (instructions for coding agents) that will be split into topic docs and searched. Write questions for all three.

## 1. PostHog (github.com/PostHog/posthog)
Monorepo: Django/Python backend, React/TypeScript frontend (Kea), ClickHouse, Celery, products/ folders. The AGENTS.md covers, in general terms: how the repo is laid out, how to run things (dev environment, tests, linters), conventions for code, commits and PRs, CI, security rules, architecture rules, product copy, analytics instrumentation, and agent tooling.
Real tasks: `<work>/tasks/PostHog_posthog.txt` (300 merged PR titles, `#number<TAB>title`).
Output: `<work>/cases-draft/posthog-agents.json`, ids `posthog-01`…

## 2. Next.js (github.com/vercel/next.js)
Monorepo: the Next.js framework (packages/next), Turbopack (Rust), tests in test/. The AGENTS.md covers, in general terms: repo layout, building and fast local development, running and writing tests, linting and types, PR/issue/discussion conventions, CI failures, secrets safety, efficient workflows, and common pitfalls.
Real tasks: `<work>/tasks/vercel_next.js.txt`.
Output: `<work>/cases-draft/nextjs-agents.json`, ids `nextjs-01`…

## 3. Cloudflare workerd (github.com/cloudflare/workerd)
The Cloudflare Workers runtime: C++ on V8, built with Bazel, plus Rust (JSG bindings) and TypeScript parts. The AGENTS.md covers, in general terms: building and testing, architecture, coding conventions and anti-patterns, backward compatibility, development workflow, and dependency/V8 updates.
Real tasks: `<work>/tasks/cloudflare_workerd.txt`.
Output: `<work>/cases-draft/workerd-agents.json`, ids `workerd-01`…

## Rules
1. Do NOT open, read, grep or search the AGENTS.md/CLAUDE.md files or any docs of these projects, local or on the web. Never look inside `<work>/agentfiles/` or `<work>/corpora/`. Use only the PR title files and your general knowledge.
2. Write 36 questions per project (many will be dropped later because an AGENTS.md can't answer everything — that's expected). For each, pick a PR title representing a task during which an agent would realistically need project guidance, and write the question that agent would ask. Up to 8 per project may come from general knowledge of common tasks (`"pr": null`, task described in `"task"`).
3. Aim at what an AGENTS.md typically answers: how to run/build/test/lint, where code goes, required conventions and rules, what not to do, how to write commits/PRs, how a part of the system is structured, what to do when CI or a tool fails.
4. Kinds: how-to, how-it-works, convention, where, troubleshooting — a healthy mix, no near-duplicates.
5. Two phrasings per question:
   - `"question"`: natural language, as the agent would ask a teammate, 8–25 words.
   - `"keywords"`: the 2–6 words the agent would type into a docs search box. Use words known from the task, code or tool output — don't guess doc headings.
6. Realism over cleverness.

## Output format (each file)
```json
{"corpus": "posthog-agents", "questions": [
  {"id": "posthog-01", "pr": "#126377", "task": "<PR title verbatim>", "kind": "how-to", "question": "...", "keywords": "..."}
]}
```
Validate each with `python3 -m json.tool <file> > /dev/null`. Reply with just the three file paths and question counts.
````

</details>

## 2. Labeling answers

Two labelers labeled every question independently, in batches of nine or ten, each with a
different search strategy. Where their labels were not identical, a third agent
reconciled them. Questions left with no answer were dropped, with the reason.

````text
You are labeling ground truth for a benchmark that measures how well a documentation search tool helps coding agents find project knowledge. The questions were written by someone who never saw the docs, from real tasks (merged PR titles). For each question, find every doc in the knowledge base that answers it, and the most specific section, or report that the knowledge base does not answer it. An independent labeler is labeling the same questions and the two sets of labels will be compared, so be thorough, strict and precise, and read the candidate sections before deciding. Stay neutral: you are not trying to make any tool look good or bad.

## Knowledge base
<title>, pinned to a commit, at `<root>/`. The docs are the markdown files under `<source>/`. A doc's id is its path under `<source>/` without the extension, for example <an example id>.

Useful commands, run from `/home/user/AgentIndex`:
- `python3 -m agentindex --root <root> list`: every doc with its title and summary.
- `python3 -m agentindex --root <root> read <id> --outline`: a doc's sections with their exact anchors.
- `python3 -m agentindex --root <root> read <id>` or `read <id>#<anchor>`: read a doc or one section.
- grep, rg and find over `<root>/<source>/`, and opening files directly, are fine.
- Never run `agentindex search` or any search_docs tool. It is the system under test, and labels must not be influenced by it.

## What counts as an answer
- A doc or section answers a question if an agent who reads it would know what to do, or would have the information asked for: the specific procedure, command, API, rule, location or explanation. A doc that only mentions the topic in passing, or just links elsewhere for the details, does not answer it (the link target might). The answer must cover the question's main point.
- List every doc that answers it: often one, sometimes two or three when the content is duplicated. Do not add related reading.
- For each answering doc, give the most specific section that contains the answer as `id#anchor`, using the exact anchor shown by `--outline`. If the answer spans several sections of that doc, list each. Give just `id` when the doc is short (under about 400 words) and on one topic, or when the answer is spread across the whole doc.
- If nothing in the knowledge base answers it, return an empty answers list and say why in the note. Do not stretch: a partial or tangential match is not an answer.

<search strategy: A or B, below>

## Questions
Your questions are the entries with these ids in `<draft file>` (a JSON file with a `questions` array; each entry has id, task, question and keywords): <ids>. Label what the `question` asks; `keywords` is another phrasing of it and `task` is the work the asker was doing.

Return one label per question id: `answers` (doc ids or id#anchor, empty if unanswered) and a short `note`. Double-check every anchor against `--outline` output.
````

The two strategies:

- **Labeler A:** Search strategy: start from the structure. Read the full doc list (titles and summaries) and the folder tree, decide which docs should cover each question, read them, then use grep to check for other docs that cover it too.
- **Labeler B:** Search strategy: start from the contents. Grep the doc files for several different words, synonyms and likely identifiers for each question, read the matching sections, then skim the doc list for docs your searches could have missed.

The reconciler:

````text
You are settling disagreements between two independent labelers of a documentation benchmark. For each question below, decide the correct labels on the merits. Read the sections both labelers cited, check whether each one really answers the question by the criteria below, and look for answers both of them missed. The final answers may be one labeler's, a combination, or empty when the docs do not answer the question. Stay neutral.

## Knowledge base
<title>, pinned to a commit, at `<root>/`. The docs are the markdown files under `<source>/`. A doc's id is its path under `<source>/` without the extension, for example <an example id>.

Useful commands, run from `/home/user/AgentIndex`:
- `python3 -m agentindex --root <root> list`: every doc with its title and summary.
- `python3 -m agentindex --root <root> read <id> --outline`: a doc's sections with their exact anchors.
- `python3 -m agentindex --root <root> read <id>` or `read <id>#<anchor>`: read a doc or one section.
- grep, rg and find over `<root>/<source>/`, and opening files directly, are fine.
- Never run `agentindex search` or any search_docs tool. It is the system under test, and labels must not be influenced by it.

## What counts as an answer
- A doc or section answers a question if an agent who reads it would know what to do, or would have the information asked for: the specific procedure, command, API, rule, location or explanation. A doc that only mentions the topic in passing, or just links elsewhere for the details, does not answer it (the link target might). The answer must cover the question's main point.
- List every doc that answers it: often one, sometimes two or three when the content is duplicated. Do not add related reading.
- For each answering doc, give the most specific section that contains the answer as `id#anchor`, using the exact anchor shown by `--outline`. If the answer spans several sections of that doc, list each. Give just `id` when the doc is short (under about 400 words) and on one topic, or when the answer is spread across the whole doc.
- If nothing in the knowledge base answers it, return an empty answers list and say why in the note. Do not stretch: a partial or tangential match is not an answer.

## Disputed questions
Question text is in `<draft file>` (by id). The two labelers said:
<for each disputed id: labeler A's answers and note, labeler B's answers and note>

Return final labels for exactly these ids. Double-check every anchor against `--outline` output.
````

## 3. Judging pooled results

After labeling, `python3 -m bench pool` listed every doc that any system ranked in its
top 3, for either phrasing, that no one had judged for that question, in no particular
order and without saying which system found it. Two judges judged each batch; a third
judged the pairs they disagreed on, and the majority decided. Docs judged to answer were
added to the case's `answers` (and listed in `pooled`); the rest went to `not_answers`.

````text
You are judging whether documents answer questions, for a benchmark of documentation search for coding agents. Stay neutral.

## Knowledge base
<title>, at `<root>/`. The docs are the markdown files under `<source>/`; a doc's id is its path there without the extension.
Commands, run from `/home/user/AgentIndex`:
- `python3 -m agentindex --root <root> read <id> --outline`: a doc's sections with their exact anchors.
- `python3 -m agentindex --root <root> read <id>` or `read <id>#<anchor>`: read a doc or one section.
- Opening the files directly is fine too. Never run `agentindex search` or any search_docs tool.

## Task
`<batch file>` has an `entries` list. Each entry is a question (`question`, with `keywords` as another phrasing) with `candidates`: docs to judge, in no particular order. You are not told how they were found. `answers` lists docs already accepted as answers, for reference only: a candidate can also answer, for example when content is duplicated, so judge each candidate on its own content.

Judge every candidate of every entry: <n> (case, doc) pairs in total.
(The third judge instead gets: Judge exactly these (case, doc) pairs: <the disputed pairs>)

For each pair, read the candidate (its outline, then the relevant sections) and decide whether it answers the question.

## What counts as an answer
- A doc or section answers a question if an agent who reads it would know what to do, or would have the information asked for: the specific procedure, command, API, rule, location or explanation. A doc that only mentions the topic in passing, or just links elsewhere for the details, does not answer it. The answer must cover the question's main point.
- Do not stretch: a partial or tangential match is not an answer.

Return one verdict per pair, with `case` set to the entry's case id and `doc` to the candidate's id.
````

## 4. Real agents answering

Each question, in both conditions, went to a fresh agent with no other context:

````text
You are a coding agent about to start this task in <project>: "<task>". First you need the project's guidance on this question:

<question>

Find the answer in the project's documentation, and stop as soon as you have it. Answer only from the docs, not from memory; if the docs don't answer it, say so.

<how, by condition, below>

Return the answer in 2 to 5 sentences, your sources (doc id or file path, and section heading), and whether the docs answered the question.
````

AgentIndex:

````text
The docs are indexed by AgentIndex. Consult them only with these commands, run from /home/user/AgentIndex:
  python3 -m agentindex --root <root> search "<a few keywords>"
  python3 -m agentindex --root <root> read <id>            (a whole doc)
  python3 -m agentindex --root <root> read <id>#<anchor>   (one section)
Do not grep, cat, find or open the doc files any other way, and do not open any other files. Do not use the search_docs, read_doc or list_docs MCP tools: they index a different project. Do not use the web.
````

grep and read (documentation folders):

````text
The docs are the markdown files under <root>/<source>/. Consult them only with grep, rg, find, ls and file reading (Bash, Read, Grep or Glob), and only inside that folder. Do not use agentindex or the search_docs, read_doc or list_docs MCP tools. Do not use the web.
````

Whole AGENTS.md (AGENTS.md corpora):

````text
The project's agent instructions are the file <root>/AGENTS.md. Coding agents load this whole file at the start of every session, so begin by reading all of it with the Read tool (no offset or limit), then answer from it. Do not use any other tool or file, and do not use the web.
````

The agents returned `answer`, `sources` and `found` as structured output.

## 5. Grading their answers

Answers were graded in batches of six questions. Each question's two answers were put in
slots 1 and 2, with the AgentIndex answer first in every other question. The judges saw
only each answer's text and whether it said the docs don't answer, not its sources or which
tools the agent used. Two judges graded every answer; a third graded the answers they
disagreed on, and the majority decided.

````text
You are grading answers that coding agents gave to questions about a project's documentation. Grade carefully and neutrally.

`<batch file>` is a JSON list of items. Each item has a `question`, `gold` (doc ids, or id#anchor sections, that people who labeled the benchmark found to answer it), the knowledge base location (`root`, with the docs under `root`/`source`/), and two `answers` (`slot` 1 and 2; `says_not_found` is true when that agent reported the docs don't answer it).

For each item: read the gold sections first, with `python3 -m agentindex --root <root> read <id>` or `read <id>#<anchor>` (run from /home/user/AgentIndex), or by opening the files. Then grade each answer on its own against what the docs say:
- correct: it gives the information the docs provide on the question's main point, with no material errors. Extra correct detail is fine.
- partial: it gets part of the main point right but misses, or gets wrong, an important part.
- incorrect: it is wrong, contradicts the docs, or answers a different question.
- not_found: it says the docs don't answer the question and gives no answer to its main point.
An answer can be correct even when it relies on a doc other than the gold ones, as long as it matches what the docs say; check the docs when unsure. Do not reward length or confidence. You are not told how the answers were produced, and it does not matter. Never run `agentindex search`.

Grade both answers of every item: <n> grades in total.
(The third judge instead gets: Grade only these (case, slot) answers: <the disputed answers>)
````
