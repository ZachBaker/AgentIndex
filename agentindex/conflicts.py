"""Find statements in different docs that contradict each other.

Knowledge bases drift: a fact gets written in two docs, then only one of them is
updated. This module splits docs into statements (sentences, list items and table
rows) and reports pairs from different docs that say nearly the same thing but
differ in a value (a number, a code span, a name) or in polarity (one is negated,
or uses the opposite word, such as enabled and disabled).

Like search, it is lexical. It finds copies of a statement that drifted apart, not
contradictions phrased in different words, and each pair it reports is a candidate
for a person or an agent to judge. See knowledge/architecture/contradictions.md.
"""

from __future__ import annotations

import bisect
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from .markdown import plain_text, prose_blocks

# Thresholds, tuned on this repository's docs and on npm's (see the doc above).
CANDIDATE_SIMILARITY = 0.5  # Dice coefficient of two statements' terms, worth aligning
MIN_SIMILARITY = 0.75  # the same, leaving out the terms that differ
MIN_SHARED = 2  # words and values both statements contain, besides the difference
MAX_NOISE = 2  # other terms only one statement has (fewer when they share little)
MIN_TERMS, MAX_TERMS = 3, 60  # shorter statements say too little, longer ones are not one
MAX_VERSIONS = 3  # a sentence found in more versions is a template, like a dated footer

WORD, VALUE, NEGATION = "word", "value", "negation"
_NOT = "\x00not"  # every negation gets this norm, so "never" and "do not" agree
# Link texts are wrapped in these, so a term knows it only names a link target.
_LINK_OPEN, _LINK_CLOSE = "\x01", "\x02"

# "see" and "refer" count as function words too: they introduce references to other
# pages, not claims, so "see `x()` for details" then starts with what differs.
_FUNCTION_WORDS = frozenset(
    """
    a an the this that these those it its of to in on at for from by with as into onto
    via per and or but so then also just very really both is are was were be been being
    am has have had having do does did doing will would shall i me my we us our you your
    he she they them their his her there here which who whom whose what how e.g i.e etc
    vs cf see refer
    """.split()  # noqa: SIM905 (a word list reads better as text)
)
_NEGATIONS = frozenset(
    "not no never none nothing neither nor without nobody nowhere".split()  # noqa: SIM905
)
_CONTRACTIONS = {"can't": "can", "won't": "will", "shan't": "shall", "ain't": "is"}
_ABBREVIATIONS = frozenset({"e.g", "i.e", "etc", "vs", "cf", "eg", "ie"})
_OPPOSITE_WORDS = [
    ("enable", "disable"),
    ("allow", "deny"),
    ("allow", "forbid"),
    ("allow", "prohibit"),
    ("allowed", "forbidden"),
    ("required", "optional"),
    ("mandatory", "optional"),
    ("include", "exclude"),
    ("true", "false"),
    ("before", "after"),
    ("if", "unless"),
    ("public", "private"),
    ("internal", "external"),
    ("inside", "outside"),
    ("local", "global"),
    ("locally", "globally"),
    ("min", "max"),
    ("minimum", "maximum"),
    ("least", "most"),
    ("more", "less"),
    ("more", "fewer"),
    ("higher", "lower"),
    ("highest", "lowest"),
    ("upper", "lower"),
    ("uppercase", "lowercase"),
    ("increase", "decrease"),
    ("ascending", "descending"),
    ("newest", "oldest"),
    ("success", "failure"),
    ("succeed", "fail"),
    ("pass", "fail"),
    ("same", "different"),
    ("sync", "async"),
    ("synchronous", "asynchronous"),
    ("show", "hide"),
    ("shown", "hidden"),
    ("visible", "hidden"),
    ("add", "remove"),
    ("keep", "remove"),
    ("keep", "delete"),
    ("keep", "drop"),
    ("accept", "reject"),
    ("start", "stop"),
]
_NEGATING_PREFIXES = ("non-", "non", "un", "in", "im", "dis")

_SENTENCE_END = re.compile(r"[.!?;][\"')\]*_]*\s+")
_UNSPLITTABLE = re.compile(r"(`+).+?\1|\]\([^)]*\)")  # code spans and link targets
_ANY_CODE_SPAN = re.compile(r"(`+).+?\1")
_LINK = re.compile(r"!?\[((?:[^\[\]\\]|\\.)*)\](?:\([^)]*\)|\[[^\]]*\])")
# A heading that names one thing: `--force`, caseSensitive, max_retries, v0.2.0.
_NAMED_HEADING = re.compile(
    r"#+\s*(?:`+([^`]+)`+|(--?[^\W\d_][\w-]*|[^\W\d_]+(?:[-_.]|[a-z][A-Z])[\w.-]*"
    r"|v\d[\w.-]*))\s*#*"
)
_CODE_SPAN = re.compile(r"`([^`]+)`")
_CODE_TERM = re.compile(r"[^\s()\[\]{}<>,;\"'`|=]*[^\s()\[\]{}<>,;\"'`|=.:]")
_PROSE_TERM = re.compile(
    r"(?P<value>[A-Za-z][\w+.-]*://[^\s`]*[\w/]"  # URLs
    r"|(?<![\w-])--?[^\W\d_][\w-]*"  # --flags and -n
    r"|\d+(?:[.,:/-]\d+)*%?[^\W\d_]*)"  # numbers, versions, dates, 30s, 50%
    r"|(?P<word>[^\W\d_](?:[\w'’-]|\.(?=\w))*)"  # words and identifiers (file.py, v1.2)
)
_STARTS_SENTENCE = ".!?:;—|(\"'“‘["
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3})")
_IDENTIFIER = re.compile(r"[\d_.]")


@dataclass
class Term:
    """A word, value or negation of a statement, and where it is in the text."""

    norm: str  # what is compared: lowercased, words stemmed
    kind: str  # WORD, VALUE or NEGATION
    start: int
    end: int
    link: bool = False  # part of a link's text


@dataclass(eq=False)
class Statement:
    doc: str
    path: str
    line: int  # 1-based line in the file
    anchor: str  # the section it is in
    text: str  # plain text; code spans keep their backticks, link texts are marked
    terms: list[Term]
    topic: frozenset  # words of the doc id, title and section heading
    subject: str  # the section's heading if it names one thing, such as `--force`


@dataclass
class Conflict:
    """Two claims that disagree, each with the statements in different docs making it."""

    kind: str  # "value" or "opposite"
    similarity: float
    a: list[Statement]
    b: list[Statement]
    marks_a: list[int]  # indexes of the terms that differ
    marks_b: list[int]

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "difference": [_surface(self.a[0], self.marks_a), _surface(self.b[0], self.marks_b)],
            "similarity": self.similarity,
            "statements": [_side(self.a, self.marks_a), _side(self.b, self.marks_b)],
        }


def extract_statements(
    doc: str,
    path: str,
    title: str,
    body: str,
    body_line: int,
    sections: list[tuple[int, str, str]],
) -> list[Statement]:
    """A doc's statements. ``sections`` are ``(first body line, anchor, heading)``."""
    lines = body.split("\n")
    starts = [section[0] for section in sections]
    topic = _parts(doc) | _parts(title)
    contexts = [("", frozenset(topic), "")]  # for text before the first section
    for start, anchor, heading in sections:
        named = _NAMED_HEADING.fullmatch(lines[start].strip()) if anchor else None
        subject = (named.group(1) or named.group(2)).strip().lower() if named else ""
        contexts.append((anchor, frozenset(topic | _parts(heading)), subject))
    statements = []
    for first, block, row in prose_blocks(lines):
        for offset, sentence in [(0, block)] if row else _sentences(block):
            text = plain_text(_mark_links(sentence), code_marks=True)
            terms = _terms(text)
            if (
                not MIN_TERMS <= len(terms) <= MAX_TERMS
                or text.endswith(":")
                or all(term.kind == VALUE for term in terms)
            ):
                continue  # too short or long to be one claim, a lead-in, or only code
            line = first + block.count("\n", 0, offset)
            anchor, section_topic, subject = contexts[bisect.bisect_right(starts, line)]
            statements.append(
                Statement(
                    doc, path, body_line + line + 1, anchor, text, terms, section_topic, subject
                )
            )
    return statements


def find_conflicts(statements: list[Statement], focus: Iterable[str] = ()) -> list[Conflict]:
    """Claims made in different docs that disagree, most similar first.

    With ``focus``, only conflicts involving at least one of those doc ids.
    """
    focus = set(focus)
    # Statements with the same terms make the same claim: compare each claim once.
    claims: dict[tuple, list[Statement]] = defaultdict(list)
    for statement in statements:
        claims[tuple((t.norm, t.kind) for t in statement.terms)].append(statement)
    groups = list(claims.values())
    matches = []
    for m, n in _similar_pairs([frozenset(norm for norm, _ in key) for key in claims]):
        found = _compare(groups[m][0].terms, groups[n][0].terms)
        if found:
            matches.append((m, n, *found))
    # A sentence found in many versions (a date in every doc's footer) is a template with
    # a field, not one fact that drifted; so is a sentence that a doc itself repeats with
    # different values (one per option, say), whose value depends on where it is.
    others = Counter(k for m, n, *_ in matches for k in (m, n))  # versions besides its own
    templated = {
        s
        for m, n, *_ in matches
        for x in groups[m]
        for y in groups[n]
        if x.doc == y.doc
        for s in (x, y)
    }
    conflicts = []
    for m, n, kind, marks_m, marks_n, similarity in matches:
        if max(others[m], others[n]) >= MAX_VERSIONS:
            continue
        pairs = [
            (x, y)
            for x in groups[m]
            for y in groups[n]
            if x.doc != y.doc
            and x not in templated
            and y not in templated
            and (not focus or x.doc in focus or y.doc in focus)
            and _same_subject(x, marks_m, y, marks_n)
        ]
        if pairs:
            side_m = sorted({x for x, _ in pairs}, key=_place)
            side_n = sorted({y for _, y in pairs}, key=_place)
            if (
                focus
                and not any(s.doc in focus for s in side_m)
                or (not focus and _place(side_n[0]) < _place(side_m[0]))
            ):
                side_m, side_n, marks_m, marks_n = side_n, side_m, marks_n, marks_m
            conflicts.append(Conflict(kind, similarity, side_m, side_n, marks_m, marks_n))
    conflicts.sort(key=lambda c: (-c.similarity, _place(c.a[0]), _place(c.b[0])))
    return conflicts


def _similar_pairs(sets: list[frozenset]) -> Iterable[tuple[int, int]]:
    """Index pairs of the sets whose Dice similarity is at least CANDIDATE_SIMILARITY.

    Prefix filtering, so that most pairs are never compared: sets this similar must
    share one of their rarest terms. Taking the sets from small to large, each one
    indexes enough of its rarest terms to meet any larger set, and probes with enough
    to meet any smaller one (no smaller than ``ratio`` of its size).
    """
    threshold = CANDIDATE_SIMILARITY
    ratio = threshold / (2 - threshold)
    frequency = Counter(term for terms in sets for term in terms)
    index: dict[str, list[int]] = defaultdict(list)
    for n in sorted(range(len(sets)), key=lambda n: len(sets[n])):
        terms, size = sets[n], len(sets[n])
        ordered = sorted(terms, key=lambda term: (frequency[term], term))
        probe = size - math.ceil(threshold * size * (1 + ratio) / 2 - 1e-9) + 1
        candidates = {m for term in ordered[:probe] for m in index[term]}
        for m in sorted(candidates):
            other = len(sets[m])
            if other >= ratio * size and 2 * len(sets[m] & terms) >= threshold * (other + size):
                yield m, n
        for term in ordered[: size - math.ceil(threshold * size - 1e-9) + 1]:
            index[term].append(n)


def _compare(a: list[Term], b: list[Term]) -> tuple[str, list[int], list[int], float] | None:
    """How two statements disagree, if in exactly one way: ``(kind, marks_a, marks_b,
    similarity)``. The marks are the indexes of the terms that differ, and similarity
    compares the rest."""
    opcodes = SequenceMatcher(
        None, [t.norm for t in a], [t.norm for t in b], autojunk=False
    ).get_opcodes()
    left = [
        (op, i)
        for op, (tag, i1, i2, _, _) in enumerate(opcodes)
        if tag != "equal"
        for i in range(i1, i2)
    ]
    right = [
        (op, j)
        for op, (tag, _, _, j1, j2) in enumerate(opcodes)
        if tag != "equal"
        for j in range(j1, j2)
    ]
    # A word that only moved ("by default, X" and "X by default") is not a difference,
    # but values that swap places ("true unless X, false" and "false unless X, true") are.
    moved = Counter(a[i].norm for _, i in left if a[i].kind != VALUE) & Counter(
        b[j].norm for _, j in right if b[j].kind != VALUE
    )
    left, right = _without(left, a, moved), _without(right, b, moved)

    value_ops = {op for op, i in left if a[i].kind == VALUE} & {
        op for op, j in right if b[j].kind == VALUE
    }
    opposites = _opposites(
        [i for _, i in left if a[i].kind == WORD], [j for _, j in right if b[j].kind == WORD], a, b
    )
    negations_a = [i for _, i in left if a[i].kind == NEGATION]
    negations_b = [j for _, j in right if b[j].kind == NEGATION]
    flipped = (len(negations_a) + len(negations_b) + len(opposites)) % 2 == 1
    if len(value_ops) == 1 and not flipped:
        op = value_ops.pop()
        if opcodes[op][1] == 0 and opcodes[op][3] == 0:
            return None  # nothing in common before them: the subjects differ, not the facts
        kind = "value"
        marks_a = [i for o, i in left if o == op and a[i].kind == VALUE]
        marks_b = [j for o, j in right if o == op and b[j].kind == VALUE]
    elif flipped and not value_ops:
        kind = "opposite"
        marks_a = negations_a + [i for i, _ in opposites]
        marks_b = negations_b + [j for _, j in opposites]
    else:
        return None

    # Words swapped anywhere else change the context ("in staging" and "in production"),
    # so the statements disagree in two places; words only one side has are detail.
    marked = {op for op, i in left if i in marks_a} | {op for op, j in right if j in marks_b}
    swapped = {op for op, _ in left} & {op for op, _ in right}
    if swapped - marked:
        return None
    # The less two statements share, the more exactly they must match.
    noise = len(left) + len(right) - len(marks_a) - len(marks_b)
    rest_a = {t.norm for i, t in enumerate(a) if i not in marks_a}
    rest_b = {t.norm for j, t in enumerate(b) if j not in marks_b}
    common = rest_a & rest_b
    shared = len(common - {_NOT})
    if shared < MIN_SHARED or noise > min(MAX_NOISE, shared - MIN_SHARED):
        return None
    similarity = 2 * len(common) / (len(rest_a) + len(rest_b))
    if similarity < MIN_SIMILARITY:
        return None
    return kind, marks_a, marks_b, round(similarity, 2)


def _same_subject(x: Statement, marks_x: list[int], y: Statement, marks_y: list[int]) -> bool:
    """Whether two statements that differ at the marks talk about the same thing."""
    if x.subject and y.subject and x.subject != y.subject:
        return False  # sections about different named things, like two options
    if any(x.terms[i].link for i in marks_x) and any(y.terms[j].link for j in marks_y):
        return False  # they point to different pages ("see X", "see Y")
    # Each names its own topic, like "run `npm ci`" in the npm-ci doc and
    # "run `npm install`" in the npm-install doc.
    parts_x = _parts(" ".join(x.terms[i].norm for i in marks_x))
    parts_y = _parts(" ".join(y.terms[j].norm for j in marks_y))
    return not ((parts_x - parts_y) & x.topic and (parts_y - parts_x) & y.topic)


def _without(diff: list[tuple[int, int]], terms: list[Term], drop: Counter) -> list:
    drop = Counter(drop)
    kept = []
    for op, i in diff:
        if terms[i].kind != VALUE and drop[terms[i].norm] > 0:
            drop[terms[i].norm] -= 1
        else:
            kept.append((op, i))
    return kept


def _opposites(left: list[int], right: list[int], a: list[Term], b: list[Term]) -> list:
    """Pairs of indexes of opposite words, one from each side."""
    pairs = []
    unused = list(right)
    for i in left:
        for j in unused:
            if _opposite(a[i].norm, b[j].norm):
                pairs.append((i, j))
                unused.remove(j)
                break
    return pairs


def _opposite(x: str, y: str) -> bool:
    if frozenset((x, y)) in _OPPOSITES:
        return True
    for word, other in ((x, y), (y, x)):
        for prefix in _NEGATING_PREFIXES:
            if other.startswith(prefix) and other[len(prefix) :] == word and len(word) >= 3:
                return True
    return False


def _sentences(block: str) -> list[tuple[int, str]]:
    """Split a paragraph or list item into ``(offset, sentence)`` pieces."""
    protected = [m.span() for m in _UNSPLITTABLE.finditer(block)]
    pieces, start = [], 0
    for match in _SENTENCE_END.finditer(block):
        end, mark = match.end(), match.start()
        if end >= len(block) or any(a <= mark < b for a, b in protected):
            continue
        after = block[end]
        if block[mark] != ";" and not (after.isupper() or after.isdigit() or after in "`\"'([*_"):
            continue  # "e.g. this" or "v1. then" do not end a sentence
        if block[mark] == "." and _word_before(block, mark).lower() in _ABBREVIATIONS:
            continue
        pieces.append((start, block[start : mark + 1]))
        start = end
    pieces.append((start, block[start:]))
    return pieces


def _word_before(text: str, end: int) -> str:
    match = re.search(r"[\w.]+$", text[:end])
    return match.group() if match else ""


def _mark_links(markdown: str) -> str:
    """Replace each link or image with its text, wrapped in the link markers."""
    code = [m.span() for m in _ANY_CODE_SPAN.finditer(markdown)]
    out, last = [], 0
    for link in _LINK.finditer(markdown):
        if not any(a <= link.start() < b for a, b in code):
            out += [markdown[last : link.start()], _LINK_OPEN, link.group(1), _LINK_CLOSE]
            last = link.end()
    return "".join(out) + markdown[last:]


def _terms(text: str) -> list[Term]:
    """Terms of a statement's plain text, in order, without function words."""
    terms: list[Term] = []
    position = 0
    for code in _CODE_SPAN.finditer(text):
        terms += _prose_terms(text, position, code.start())
        for match in _CODE_TERM.finditer(text, code.start(1), code.end(1)):
            terms.append(Term(match.group().lower(), VALUE, match.start(), match.end()))
        position = code.end()
    terms += _prose_terms(text, position, len(text))
    markers = [m.start() for m in re.finditer(f"[{_LINK_OPEN}{_LINK_CLOSE}]", text)]
    for term in terms:
        k = bisect.bisect_left(markers, term.start) - 1
        term.link = k >= 0 and text[markers[k]] == _LINK_OPEN
    return terms


def _prose_terms(text: str, start: int, end: int) -> list[Term]:
    terms = []
    for match in _PROSE_TERM.finditer(text, start, end):
        raw, span = match.group(), match.span()
        if match.lastgroup == "value":
            norm = _THOUSANDS.sub("", raw.lower()) if "," in raw else raw.lower()
            terms.append(Term(norm, VALUE, *span))
            continue
        lower = raw.lower().replace("’", "'").strip("'-")
        if lower.endswith("n't") or lower == "cannot":
            base = _CONTRACTIONS.get(lower, lower[:-3] if lower.endswith("n't") else "can")
            if base not in _FUNCTION_WORDS:
                terms.append(Term(_stem(base), WORD, *span))
            terms.append(Term(_NOT, NEGATION, *span))
            continue
        lower = lower.split("'")[0]  # it's, the doc's, you'll
        if not lower or lower in _FUNCTION_WORDS:
            continue
        if lower in _NEGATIONS:
            terms.append(Term(_NOT, NEGATION, *span))
        elif _IDENTIFIER.search(lower):
            terms.append(Term(lower, VALUE, *span))  # v1.2, file.py, snake_case
        elif any(c.isupper() for c in raw[1:]) or (raw[0].isupper() and not _starts(text, span[0])):
            terms.append(Term(lower, VALUE, *span))  # a name: SQLite, Redis, HTTP
        else:
            terms.append(Term(_stem(lower), WORD, *span))
    return terms


def _starts(text: str, position: int) -> bool:
    """Whether a word at ``position`` starts a sentence or a table cell."""
    k = position - 1
    while k >= 0 and (text[k].isspace() or text[k] in (_LINK_OPEN, _LINK_CLOSE)):
        k -= 1
    return k < 0 or text[k] in _STARTS_SENTENCE


def _stem(word: str) -> str:
    """Strip common endings so "defaults", "defaulted" and "default" compare equal."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith(("sses", "xes", "zes", "ches", "shes")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            word = word[: -len(suffix)]
            if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "lsz":
                word = word[:-1]  # running, stopped
            break
    if word.endswith("e") and len(word) > 2:
        word = word[:-1]
    return word


def _parts(text: str) -> set[str]:
    """Lowercased words of an id, title or value, plain and stemmed."""
    words = {w for w in re.split(r"[\W_]+", text.lower()) if w}
    return words | {_stem(w) for w in words}


def _place(statement: Statement) -> tuple[str, int]:
    return statement.path, statement.line


def _unmarked(text: str) -> str:
    return text.replace(_LINK_OPEN, "").replace(_LINK_CLOSE, "")


def _surface(statement: Statement, marks: list[int]) -> str:
    """The differing words as written, such as "8765" or "disabled"."""
    spans = _spans(statement, marks)
    return " ".join(_unmarked(statement.text[start:end]) for start, end in spans)


def _side(statements: list[Statement], marks: list[int]) -> dict:
    """One claim: its text with the differing words in ``**bold**``, and where it is."""
    text = statements[0].text
    for start, end in reversed(_spans(statements[0], marks)):
        text = f"{text[:start]}**{text[start:end]}**{text[end:]}"
    return {
        "text": _unmarked(text),
        "locations": [
            {"id": s.doc, "anchor": s.anchor, "path": s.path, "line": s.line} for s in statements
        ],
    }


def _spans(statement: Statement, marks: list[int]) -> list[tuple[int, int]]:
    """Character spans of the marked terms, joining neighbors separated by spaces."""
    spans: list[tuple[int, int]] = []
    terms = statement.terms
    for start, end in sorted({(terms[i].start, terms[i].end) for i in marks}):
        if spans and not _unmarked(statement.text[spans[-1][1] : start]).strip():
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))
    return spans


_OPPOSITES = frozenset(frozenset((_stem(x), _stem(y))) for x, y in _OPPOSITE_WORDS)
