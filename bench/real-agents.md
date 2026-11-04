# Real agents with and without AgentIndex

Every benchmark question was handed to two fresh coding agents (the same model in the same Claude Code harness, one run each). One could consult the docs only through AgentIndex (`search` and `read`). The other could use only grep, find and file reads on the docs folder or, for the AGENTS.md corpora, had to read the whole AGENTS.md first, as an agent does when the file is its CLAUDE.md. Two judges who did not know which agent was which graded each answer against the labeled docs, with a third judge where they disagreed. Context and token counts come from the agents' own transcripts. How it was run: [knowledge/development/benchmarks.md](../knowledge/development/benchmarks.md#real-agents); the exact prompts: [prompts.md](prompts.md#4-real-agents-answering). Every run, with its answer, commands and grade, is in [real-agents.json](real-agents.json).

## Documentation folders: AgentIndex vs grep

149 answerable questions, each answered both ways and graded.

| | AgentIndex | grep and read |
|---|---|---|
| Correct | 147 (99%) | **148 (99%)** |
| Partly correct | 2 (1%) | 1 (1%) |
| Wrong | 0 (0%) | 0 (0%) |
| Said the docs don't answer it | 0 (0%) | 0 (0%) |
| Context added by the lookup (median tokens) | **7,432** | 8,923 |
| Text the tools returned (median tokens) | 3,469 | **3,459** |
| Tool calls (median) | **3** | 4 |
| Time (median seconds) | 24 | **22** |

The better value of each row is in bold where the two differ.

Per question: AgentIndex added less context in 95 of 149 cases. Its answer was graded better in 1 and worse in 2.

On the 11 questions the labelers found the docs do not answer, the AgentIndex agent said so 9 times and the grep and read agent 8 times. Looking for an answer that is not there added a median 22,232 tokens of context with AgentIndex and 17,706 with grep and read.

## AGENTS.md files: AgentIndex vs loading the whole file

66 answerable questions, each answered both ways and graded.

| | AgentIndex | whole AGENTS.md |
|---|---|---|
| Correct | 64 (97%) | **66 (100%)** |
| Partly correct | 2 (3%) | 0 (0%) |
| Wrong | 0 (0%) | 0 (0%) |
| Said the docs don't answer it | 0 (0%) | 0 (0%) |
| Context added by the lookup (median tokens) | **6,796** | 14,972 |
| Text the tools returned (median tokens) | **2,804** | 8,389 |
| Tool calls (median) | 4 | **1** |
| Time (median seconds) | 25 | **24** |

The better value of each row is in bold where the two differ.

Per question: AgentIndex added less context in 58 of 66 cases. Its answer was graded better in 0 and worse in 2.

An agent pays for the whole AGENTS.md in every session, whether it needs it or not, and for AgentIndex only when it looks something up. Per corpus, the whole-file agent added 1.6 to 3.1 times as much context as the AgentIndex agent, so AgentIndex costs less in sessions with fewer lookups than that, and more in sessions with more.

On the 42 questions the labelers found the docs do not answer, the AgentIndex agent said so 40 times and the whole AGENTS.md agent 42 times. Looking for an answer that is not there added a median 17,090 tokens of context with AgentIndex and 14,969 with whole AGENTS.md.

## By corpus

Answerable questions: correct answers, and median context added per lookup.

| Corpus | Questions | AgentIndex correct | Other correct | AgentIndex context | Other context |
|---|---|---|---|---|---|
| Rust compiler dev guide (grep and read) | 36 | 100% | 100% | 7,270 | 7,842 |
| Node.js contributor docs (grep and read) | 34 | 97% | 100% | 6,340 | 6,686 |
| Electron docs (grep and read) | 40 | 98% | 100% | 7,425 | 9,082 |
| GitLab development docs (grep and read) | 39 | 100% | 97% | 10,835 | 10,875 |
| PostHog AGENTS.md (whole AGENTS.md) | 20 | 95% | 100% | 6,424 | 19,726 |
| Next.js AGENTS.md (whole AGENTS.md) | 24 | 96% | 100% | 6,540 | 14,978 |
| workerd AGENTS.md (whole AGENTS.md) | 22 | 100% | 100% | 8,002 | 12,480 |

## Caveats

- One model and one run per question and condition, and agents vary from run to run: 18 runs that were repeated by accident differed from the first run by a median 6% in context added. The first run of each is the one counted.
- These agents ran AgentIndex 0.2.0, before 0.2.1 weighted all fields equally. 0.2.1 ranks the answer first more often on the simulated benchmark ([search ranking](../knowledge/architecture/search-ranking.md#why-the-fields-are-weighted-equally)), but the real-agent runs were not repeated with it.
- Each agent was limited to one way of reading the docs. Real agents mix tools.
- "Context added" is the growth of the agent's context from its first model call to its last, so it includes the agent's own reasoning and tool calls as well as what the tools returned (search results, grep matches, and doc and file contents). Every call also carries the harness's own prompt of about 54k tokens, which is not counted here.
- Judges are models too. Each answer had two independent grades, and a third where they differed.
