"""Turn a free-text search into an FTS5 ``MATCH`` expression.

Agents tend to search with natural language ("how do we roll back a deploy?").
Passed straight to FTS5 that is a syntax error (the ``?``) or a strict AND of
every word, including "how" and "we". Instead:

* stop words are dropped and the remaining terms are OR-ed, so BM25 ranks docs
  that match more (and rarer) terms higher instead of requiring all of them;
* each term also matches as a prefix ("auth" finds "authentication",
  "config" finds "configuration"), while exact matches count twice;
* adjacent query words are added as phrases, so docs containing "feature
  flag" outrank docs that merely mention "feature" and "flag" separately;
* ``"quoted phrases"`` are required and ``-term`` excludes docs.

Everything is quoted before it reaches FTS5, so no user input can produce an
FTS5 syntax error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import QueryError

STOPWORDS = frozenset(
    """
    a about after all also am an and any are as at be because been before being both
    but by can could did do does doing during each else for from had has have having
    he her here hers him his how i if in into is it its itself just me might more most
    must my no nor not of on once only or other our ours she should so some such than
    that the their theirs them then there these they this those through to too until
    us very was way we were what when where which while who whom whose why will with
    would you your yours
    """.split()  # noqa: SIM905 (a word list reads better as text)
)
MIN_PREFIX_LENGTH = 3
MAX_TERMS = 16
_TOKEN = re.compile(r"[^\W_]+")


def tokenize(text: str) -> list[str]:
    """Split like FTS5's unicode61 tokenizer: runs of letters and digits."""
    return [t.lower() for t in _TOKEN.findall(text)]


@dataclass
class ParsedQuery:
    terms: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    phrases: list[list[str]] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)

    def alternatives(self) -> list[str]:
        """FTS5 phrases any of which may match: terms, term prefixes, adjacent pairs."""
        out = []
        for term in self.terms:
            out.append(_quote([term]))
            if len(term) >= MIN_PREFIX_LENGTH and not term.isdigit():
                out.append(_quote([term]) + "*")
        out.extend(_quote(list(pair)) for pair in self.pairs)
        return out

    def required(self) -> list[str]:
        return [_quote(phrase) for phrase in self.phrases]

    def scoring_phrases(self) -> list[str]:
        """Every phrase that contributes to a document's score."""
        return self.alternatives() + self.required()

    def to_fts(self) -> str:
        """The full match expression: (any alternative) AND required phrases, minus exclusions."""
        alternatives = self.alternatives()
        parts = ["(" + " OR ".join(alternatives) + ")"] if alternatives else []
        parts.extend(self.required())
        if not parts:
            raise QueryError("the query has no search terms (only exclusions or punctuation)")
        expression = " AND ".join(parts)
        if self.excluded:  # one flat group: nesting a NOT per term overflows FTS5's parser
            excluded = " OR ".join(_quote([term]) for term in self.excluded)
            expression = f"({expression}) NOT ({excluded})"
        return expression


def parse_query(text: str) -> ParsedQuery:
    """Parse free text into terms, adjacent pairs, required phrases and exclusions."""
    if not text or not text.strip():
        raise QueryError("the search query is empty")
    query = ParsedQuery()

    def take_phrase(match: re.Match) -> str:
        tokens = tokenize(match.group(1))
        if len(tokens) > 1:
            query.phrases.append(tokens)
            return " "
        return f" {match.group(1)} "  # a quoted single word is just a word

    rest = re.sub(r'"([^"]*)"', take_phrase, text).replace('"', " ")
    sequence: list[str | None] = []  # None marks a break in adjacency
    for chunk in rest.split():
        if re.match(r"-[^\W_]", chunk):
            query.excluded.extend(t for t in tokenize(chunk[1:]) if t not in query.excluded)
            sequence.append(None)
        else:
            sequence.extend(tokenize(chunk))
            if chunk[-1] in ",;.?!:)":  # punctuation ends a phrase
                sequence.append(None)

    keep_stopwords = all(t is None or t in STOPWORDS for t in sequence)
    previous = None
    for token in sequence:
        if token is None or (token in STOPWORDS and not keep_stopwords):
            previous = None
            continue
        if token not in query.terms:
            query.terms.append(token)
        pair = (previous, token)
        if previous is not None and previous != token and pair not in query.pairs:
            query.pairs.append(pair)
        previous = token
    del query.terms[MAX_TERMS:]
    del query.pairs[MAX_TERMS:]
    return query


def _quote(tokens: list[str]) -> str:
    return '"' + " ".join(tokens).replace('"', '""') + '"'
