"""The knowledge index: markdown sources synced into SQLite/FTS5, then searched and read.

Markdown files are the source of truth. The database is a disposable cache that
is brought up to date before every query (unchanged files are skipped by
mtime/size, then by content hash), so nobody ever has to remember a rebuild
step, and deleting the database file is always safe.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import json
import math
import os
import posixpath
import sqlite3
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Iterable

from . import __version__
from .config import DOC_SUFFIXES, Config
from .errors import AgentIndexError, NotFoundError, QueryError
from .markdown import ParsedDoc, parse_document, searchable_text, slugify, word_count
from .query import parse_query

# Bump whenever the schema or the parsing rules change: existing databases are
# then rebuilt from the markdown sources on next use.
SCHEMA_VERSION = "1"
TOKENIZER = "porter unicode61"
# Field weights; each field's term frequency saturates separately, so a title
# hit is worth ~3 body mentions, not ~1 (see knowledge/architecture/search-ranking.md).
DOC_WEIGHTS = (3.0, 2.0, 1.5, 1.5, 1.5, 1.0)  # title, keywords, tags, summary, headings, body
SECTION_WEIGHTS = (2.0, 0.5, 1.0)  # own heading, parent headings + doc title, body
SECTIONS_PER_RESULT = 2
MAX_LIMIT = 50
LONG_DOC_WORDS = 2500
SKIP_DIRS = frozenset({"node_modules", "__pycache__"})
_MARK_OPEN, _MARK_CLOSE = "\x02", "\x03"

_SCHEMA = f"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE documents (
    rowid INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    tags TEXT NOT NULL,
    keywords TEXT NOT NULL,
    meta TEXT NOT NULL,
    body TEXT NOT NULL,
    body_line INTEGER NOT NULL,
    words INTEGER NOT NULL,
    has_title INTEGER NOT NULL,
    has_summary INTEGER NOT NULL,
    warnings TEXT NOT NULL,
    hash TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL
);
CREATE TABLE sections (
    rowid INTEGER PRIMARY KEY,
    doc INTEGER NOT NULL,
    ord INTEGER NOT NULL,
    level INTEGER NOT NULL,
    heading TEXT NOT NULL,
    anchor TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    subtree_end INTEGER NOT NULL,
    words INTEGER NOT NULL
);
CREATE INDEX sections_doc ON sections (doc);
CREATE TABLE tags (doc INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (doc, tag));
CREATE INDEX tags_tag ON tags (tag);
CREATE TABLE links (
    doc INTEGER NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    anchor TEXT NOT NULL,
    line INTEGER NOT NULL
);
CREATE INDEX links_doc ON links (doc);
CREATE INDEX links_target ON links (target);
CREATE VIRTUAL TABLE docs_fts USING fts5(
    title, keywords, tags, summary, headings, body, tokenize = '{TOKENIZER}'
);
CREATE VIRTUAL TABLE sections_fts USING fts5(
    heading, context, body, tokenize = '{TOKENIZER}'
)
"""
# links.kind: "doc" (markdown link to a doc file), "file" (any other repo path),
# "anchor" (#section in the same doc), "related" (doc id from front matter).


@dataclass
class SourceFile:
    path: Path
    rel: str  # path relative to the project root, with forward slashes
    doc_id: str


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0
    duplicates: list[tuple[str, str, str]] = field(default_factory=list)  # id, kept, skipped
    missing_sources: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # path, message
    seconds: float = 0.0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)

    def to_dict(self) -> dict:
        return asdict(self)


class KnowledgeIndex:
    """Search and read a knowledge base; the index syncs itself before each query."""

    def __init__(self, config: Config, *, auto_sync: bool = True, min_sync_interval: float = 0.0):
        self.config = config
        self.auto_sync = auto_sync
        self.min_sync_interval = min_sync_interval
        self.last_report: SyncReport | None = None
        self._synced_at: float | None = None
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> KnowledgeIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- database -----------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._open()
        return self._conn

    def _open(self) -> sqlite3.Connection:
        path = self.config.db_path
        if path == ":memory:":
            return self._connect(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._connect(path)
        except sqlite3.DatabaseError as exc:
            if "locked" in str(exc):
                raise
            # Only a cache of the markdown sources: if it is corrupt, start over.
            for suffix in ("", "-wal", "-shm"):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(path + suffix)
            return self._connect(path)

    def _connect(self, path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            if path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL")
            if _schema_version(conn) != SCHEMA_VERSION:
                self._create_schema(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _schema_version(conn) != SCHEMA_VERSION:  # another process may have won
                virtual = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                    " AND sql LIKE 'CREATE VIRTUAL TABLE%'"
                ).fetchall()
                for (name,) in virtual:
                    conn.execute(f'DROP TABLE IF EXISTS "{name}"')
                tables = conn.execute(
                    "SELECT name FROM sqlite_master"
                    " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                for (name,) in tables:
                    conn.execute(f'DROP TABLE IF EXISTS "{name}"')
                for statement in _SCHEMA.split(";"):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,)
                )
            conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            conn.execute("ROLLBACK")
            if "fts5" in str(exc) or "tokenizer" in str(exc):
                raise AgentIndexError(
                    f"this Python's SQLite ({sqlite3.sqlite_version}) lacks FTS5 full-text"
                    f" search ({exc}); use a Python from python.org, Homebrew, uv, or a"
                    " recent OS package"
                ) from None
            raise
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    # -- syncing ------------------------------------------------------------------

    def discover(self) -> tuple[list[SourceFile], list[str]]:
        """List the markdown files under the configured sources (and missing sources)."""
        root = self.config.root
        files: list[SourceFile] = []
        missing: list[str] = []
        seen: set[str] = set()  # sources may overlap; the first one listed wins
        for source in self.config.sources:
            base = root / source
            if base.is_file():
                rel = base.relative_to(root).as_posix()
                if base.suffix.lower() in DOC_SUFFIXES and rel not in seen:
                    seen.add(rel)
                    files.append(SourceFile(base, rel, base.stem))
                continue
            if not base.is_dir():
                missing.append(source)
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(
                    d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                )
                for name in sorted(filenames):
                    if name.startswith(".") or not name.lower().endswith(DOC_SUFFIXES):
                        continue
                    path = Path(dirpath, name)
                    rel = path.relative_to(root).as_posix()
                    if rel not in seen and not self._excluded(rel):
                        seen.add(rel)
                        doc_id = PurePosixPath(path.relative_to(base).as_posix()).with_suffix("")
                        files.append(SourceFile(path, rel, doc_id.as_posix()))
        return files, missing

    def _excluded(self, rel: str) -> bool:
        for pattern in self.config.exclude:
            pattern = pattern.lstrip("/")
            if fnmatch(rel, pattern) or (pattern.startswith("**/") and fnmatch(rel, pattern[3:])):
                return True
        return False

    def ensure_synced(self) -> None:
        """Sync unless auto-sync is off or the last sync was very recent."""
        if not self.auto_sync:
            return
        if (
            self._synced_at is not None
            and time.monotonic() - self._synced_at < self.min_sync_interval
        ):
            return
        self.sync()

    def sync(self, force: bool = False) -> SyncReport:
        """Bring the index up to date with the sources; ``force`` re-parses every file."""
        started = time.monotonic()
        report = SyncReport()
        files, report.missing_sources = self.discover()
        wanted_ids = {f.rel: f.doc_id for f in files}
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = {
                row["path"]: row
                for row in conn.execute(
                    "SELECT rowid, id, path, hash, mtime_ns, size FROM documents"
                )
            }
            # Drop files that are gone, and files whose id changed because the
            # sources did (they are re-added under their new id below).
            for path, row in list(existing.items()):
                if wanted_ids.get(path) != row["id"]:
                    self._delete(row["rowid"])
                    report.removed.append(row["id"])
                    del existing[path]
            owners = {row["id"]: path for path, row in existing.items()}
            for source in files:
                self._sync_file(source, existing.get(source.rel), owners, report, force)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_sync', ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        report.seconds = round(time.monotonic() - started, 4)
        self.last_report = report
        self._synced_at = time.monotonic()
        return report

    def _sync_file(
        self,
        source: SourceFile,
        row: sqlite3.Row | None,
        owners: dict[str, str],
        report: SyncReport,
        force: bool,
    ) -> None:
        try:
            stat = source.path.stat()
        except OSError:
            return  # vanished since discovery; the next sync removes it
        same_stat = row is not None and (row["mtime_ns"], row["size"]) == (
            stat.st_mtime_ns,
            stat.st_size,
        )
        if same_stat and not force:
            report.unchanged += 1
            return
        owner = owners.get(source.doc_id)
        if owner is not None and owner != source.rel:
            report.duplicates.append((source.doc_id, owner, source.rel))
            return
        try:
            raw = source.path.read_bytes()
        except OSError as exc:
            report.errors.append((source.rel, str(exc)))
            return
        digest = hashlib.sha256(raw).hexdigest()
        if row is not None and not force and row["hash"] == digest:
            self.conn.execute(
                "UPDATE documents SET mtime_ns = ?, size = ? WHERE rowid = ?",
                (stat.st_mtime_ns, stat.st_size, row["rowid"]),
            )
            report.unchanged += 1
            return
        try:
            text = raw.decode("utf-8-sig")
            decode_warning = None
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
            decode_warning = "file is not valid UTF-8; undecodable bytes were replaced"
        parsed = parse_document(text, fallback_title=_humanize(source.doc_id))
        if decode_warning:
            parsed.warnings.insert(0, decode_warning)
        if row is not None:
            self._delete(row["rowid"])
            report.updated.append(source.doc_id)
        else:
            report.added.append(source.doc_id)
        self._insert(source, parsed, digest, stat)
        owners[source.doc_id] = source.rel

    def _insert(
        self, source: SourceFile, doc: ParsedDoc, digest: str, stat: os.stat_result
    ) -> None:
        conn = self.conn
        rowid = conn.execute(
            "INSERT INTO documents (id, path, title, summary, tags, keywords, meta, body,"
            " body_line, words, has_title, has_summary, warnings, hash, mtime_ns, size)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source.doc_id,
                source.rel,
                doc.title,
                doc.summary,
                json.dumps(doc.tags),
                json.dumps(doc.keywords),
                json.dumps(doc.meta, ensure_ascii=False),
                doc.body,
                doc.body_line,
                doc.words,
                int(doc.has_title),
                int(doc.has_summary),
                json.dumps(doc.warnings),
                digest,
                stat.st_mtime_ns,
                stat.st_size,
            ),
        ).lastrowid
        conn.execute(
            "INSERT INTO docs_fts (rowid, title, keywords, tags, summary, headings, body)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                rowid,
                doc.title,
                # The id is the file path, usually chosen to name the topic.
                " ".join(doc.keywords + [source.doc_id]),
                " ".join(doc.tags),
                doc.summary,
                "\n".join(s.heading for s in doc.sections if s.level and s.heading != doc.title),
                "\n\n".join(searchable_text(s.text) for s in doc.sections),
            ),
        )
        lines = doc.body.split("\n")
        for order, section in enumerate(doc.sections):
            section_id = conn.execute(
                "INSERT INTO sections (doc, ord, level, heading, anchor, start_line, end_line,"
                " subtree_end, words) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rowid,
                    order,
                    section.level,
                    section.heading,
                    section.anchor,
                    section.start,
                    section.end,
                    section.subtree_end,
                    word_count("\n".join(lines[section.start : section.subtree_end])),
                ),
            ).lastrowid
            context = [h for h in [doc.title, *section.trail[:-1]] if h != section.heading]
            conn.execute(
                "INSERT INTO sections_fts (rowid, heading, context, body) VALUES (?, ?, ?, ?)",
                (section_id, section.heading, " › ".join(context), searchable_text(section.text)),
            )
        conn.executemany(
            "INSERT OR IGNORE INTO tags (doc, tag) VALUES (?, ?)", [(rowid, t) for t in doc.tags]
        )
        conn.executemany(
            "INSERT INTO links (doc, kind, target, anchor, line) VALUES (?, ?, ?, ?, ?)",
            [(rowid, *link) for link in _resolve_links(source, doc)],
        )

    def _delete(self, rowid: int) -> None:
        conn = self.conn
        conn.execute(
            "DELETE FROM sections_fts WHERE rowid IN (SELECT rowid FROM sections WHERE doc = ?)",
            (rowid,),
        )
        for table in ("sections", "tags", "links"):
            conn.execute(f"DELETE FROM {table} WHERE doc = ?", (rowid,))
        conn.execute("DELETE FROM docs_fts WHERE rowid = ?", (rowid,))
        conn.execute("DELETE FROM documents WHERE rowid = ?", (rowid,))

    # -- queries ------------------------------------------------------------------

    def search(self, query: str, limit: int = 8, tags: Iterable[str] = ()) -> dict:
        """Rank docs for ``query``; each hit includes its best-matching sections."""
        self.ensure_synced()
        parsed = parse_query(query)
        expression = parsed.to_fts()
        phrases = parsed.scoring_phrases()
        limit = max(1, min(int(limit), MAX_LIMIT))
        try:
            allowed = self._docs_matching(expression, _clean_tags(tags))
            scores = self._score_docs(phrases, allowed)
            ranked = sorted(scores, key=lambda rowid: (-scores[rowid], rowid))[:limit]
            sections = self._best_sections(phrases, ranked)
        except sqlite3.OperationalError as exc:
            raise QueryError(f"search failed for {query!r}: {exc}") from None
        docs = {
            row["rowid"]: row
            for row in self.conn.execute(
                "SELECT rowid, id, path, title, summary, tags, words FROM documents"
                f" WHERE rowid IN ({_marks(ranked)})",
                ranked,
            )
        }
        return {
            "query": query,
            "total": len(allowed),
            "indexed": self._count("documents"),
            "results": [
                {
                    "id": docs[rowid]["id"],
                    "title": docs[rowid]["title"],
                    "path": docs[rowid]["path"],
                    "summary": docs[rowid]["summary"],
                    "tags": json.loads(docs[rowid]["tags"]),
                    "words": docs[rowid]["words"],
                    "score": round(scores[rowid], 3),
                    "sections": sections.get(rowid, []),
                }
                for rowid in ranked
            ],
        }

    def _docs_matching(self, expression: str, tags: list[str]) -> set[int]:
        sql = "SELECT rowid FROM docs_fts WHERE docs_fts MATCH ?"
        params: list = [expression]
        if tags:
            sql += f" AND rowid IN ({_TAGGED_ALL.format(marks=_marks(tags))})"
            params += [*tags, len(tags)]
        return {row[0] for row in self.conn.execute(sql, params)}

    def _score_docs(self, phrases: list[str], allowed: set[int]) -> dict[int, float]:
        if not allowed:
            return {}
        total = self._count("documents")
        scores: dict[int, float] = defaultdict(float)
        for phrase in phrases:
            idf, hits = self._phrase_hits("docs_fts", DOC_WEIGHTS, phrase, total)
            for rowid, tf in hits:
                if rowid in allowed:
                    scores[rowid] += idf * tf
        return scores

    def _best_sections(self, phrases: list[str], doc_rowids: list[int]) -> dict[int, list[dict]]:
        """The top sections of each result doc, scored the same way as documents."""
        if not doc_rowids:
            return {}
        owner = dict(
            self.conn.execute(
                f"SELECT rowid, doc FROM sections WHERE doc IN ({_marks(doc_rowids)})", doc_rowids
            ).fetchall()
        )
        total = self._count("sections")
        scores: dict[int, float] = defaultdict(float)
        for phrase in phrases:
            idf, hits = self._phrase_hits("sections_fts", SECTION_WEIGHTS, phrase, total)
            for rowid, tf in hits:
                if rowid in owner:
                    scores[rowid] += idf * tf
        best: dict[int, list[int]] = defaultdict(list)
        for rowid in sorted(scores, key=lambda r: (-scores[r], r)):
            if len(best[owner[rowid]]) < SECTIONS_PER_RESULT:
                best[owner[rowid]].append(rowid)
        chosen = [rowid for rowids in best.values() for rowid in rowids]
        if not chosen:
            return {}
        info = {
            row["rowid"]: {
                "heading": row["heading"],
                "anchor": row["anchor"],
                "snippet": _clean_snippet(row["snippet"]),
            }
            for row in self.conn.execute(
                "SELECT s.rowid, s.heading, s.anchor,"
                " snippet(sections_fts, 2, ?, ?, '…', 24) AS snippet"
                " FROM sections_fts JOIN sections s ON s.rowid = sections_fts.rowid"
                f" WHERE sections_fts MATCH ? AND s.rowid IN ({_marks(chosen)})",
                (_MARK_OPEN, _MARK_CLOSE, " OR ".join(phrases), *chosen),
            )
        }
        return {doc: [info[r] for r in rowids if r in info] for doc, rowids in best.items()}

    def _phrase_hits(
        self, table: str, weights: tuple, phrase: str, total: int
    ) -> tuple[float, list[tuple[int, float]]]:
        """Rows matching one phrase, with per-field BM25 term-frequency scores.

        FTS5's bm25() sums all columns into one saturating term frequency and
        clamps the IDF of phrases found in over half the rows to ~0, which
        makes ranking arbitrary in a small knowledge base. So bm25() is called
        once per column (all other weights zero), its clamped IDF divided back
        out, and the caller applies a smoothed IDF that is always positive.
        Returns ``(idf, [(rowid, weighted tf), ...])``.
        """
        columns = [(i, w) for i, w in enumerate(weights) if w]
        calls = ", ".join(
            f"bm25({table}, {', '.join('1' if j == i else '0' for j in range(len(weights)))})"
            for i, _ in columns
        )
        rows = self.conn.execute(
            f"SELECT rowid, {calls} FROM {table} WHERE {table} MATCH ?", (phrase,)
        ).fetchall()
        if not rows:
            return 0.0, []
        idf, fts_idf = _idf(total, len(rows))
        return idf, [
            (row[0], sum(w * -row[k + 1] for k, (_, w) in enumerate(columns)) / fts_idf)
            for row in rows
        ]

    def read(self, ref: str, section: str | None = None) -> dict:
        """A whole doc, or one section of it (``id#anchor`` or ``section=``)."""
        self.ensure_synced()
        ref, _, anchor = ref.strip().partition("#")
        section = section or anchor or None
        doc = self._resolve(ref)
        sections = self._sections(doc["rowid"])
        lines = doc["body"].split("\n")
        result = _doc_info(doc)
        if section:
            found = self._find_section(doc, sections, section)
            start, end = found["start_line"], found["subtree_end"]
            result["section"] = {
                "heading": found["heading"],
                "anchor": found["anchor"],
                "level": found["level"],
            }
        else:
            start, end = 0, len(lines)
            result["section"] = None
        while start < end and not lines[start].strip():
            start += 1
        while end > start and not lines[end - 1].strip():
            end -= 1
        result["line"] = doc["body_line"] + start + 1
        result["content"] = "\n".join(lines[start:end])
        result["outline"] = [_outline_entry(s) for s in sections if s["level"]]
        result["links"] = self._linked_docs(doc)
        result["backlinks"] = self._backlinks(doc)
        return result

    def outline(self, ref: str) -> dict:
        """Headings of a doc with anchors and sizes, to pick a section to read."""
        self.ensure_synced()
        doc = self._resolve(ref.partition("#")[0])
        result = _doc_info(doc)
        result["outline"] = [_outline_entry(s) for s in self._sections(doc["rowid"]) if s["level"]]
        return result

    def list_docs(self, tags: Iterable[str] = ()) -> dict:
        """Every doc (optionally only those with all ``tags``), plus tag counts."""
        self.ensure_synced()
        tag_list = _clean_tags(tags)
        sql = "SELECT id, path, title, summary, tags, words FROM documents d"
        params: list = []
        if tag_list:
            sql += f" WHERE d.rowid IN ({_TAGGED_ALL.format(marks=_marks(tag_list))})"
            params = [*tag_list, len(tag_list)]
        docs = [
            {
                "id": row["id"],
                "title": row["title"],
                "path": row["path"],
                "summary": row["summary"],
                "tags": json.loads(row["tags"]),
                "words": row["words"],
            }
            for row in self.conn.execute(sql + " ORDER BY id", params)
        ]
        return {"total": len(docs), "documents": docs, "tags": self._tag_counts()}

    def status(self) -> dict:
        self.ensure_synced()
        last_sync = self.conn.execute("SELECT value FROM meta WHERE key = 'last_sync'").fetchone()
        return {
            "version": __version__,
            "root": str(self.config.root),
            "config_file": str(self.config.config_file) if self.config.config_file else None,
            "sources": [
                {"path": s, "exists": (self.config.root / s).exists()} for s in self.config.sources
            ],
            "exclude": list(self.config.exclude),
            "database": self.config.db_path,
            "documents": self._count("documents"),
            "sections": self._count("sections"),
            "links": self._count("links"),
            "tags": self._tag_counts(),
            "last_sync": last_sync[0] if last_sync else None,
            "schema_version": SCHEMA_VERSION,
            "sqlite_version": sqlite3.sqlite_version,
        }

    def check(self) -> dict:
        """Lint the knowledge base: broken links, duplicate ids, missing metadata."""
        report = self.sync()
        issues: list[dict] = []

        def add(severity: str, path: str, message: str, line: int | None = None) -> None:
            issues.append({"severity": severity, "path": path, "line": line, "message": message})

        for source in report.missing_sources:
            add("error", source, "source path does not exist (check 'sources' in .agentindex.json)")
        for doc_id, kept, skipped in report.duplicates:
            add(
                "error", skipped, f"doc id {doc_id!r} is already used by {kept}; rename one of them"
            )
        for path, message in report.errors:
            add("error", path, f"could not read file: {message}")

        conn = self.conn
        docs = conn.execute(
            "SELECT rowid, id, path, has_title, has_summary, words, warnings FROM documents"
            " ORDER BY path"
        ).fetchall()
        paths = {d["id"]: d["path"] for d in docs}
        anchors: dict[str, set[str]] = defaultdict(set)
        for path, anchor in conn.execute(
            "SELECT d.path, s.anchor FROM sections s JOIN documents d ON d.rowid = s.doc"
        ):
            anchors[path].add(anchor)
        links: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for link in conn.execute("SELECT * FROM links ORDER BY doc, line"):
            links[link["doc"]].append(link)
        known_paths = set(paths.values())

        for doc in docs:
            path = doc["path"]
            for warning in json.loads(doc["warnings"]):
                add("warning", path, warning)
            if not doc["has_title"]:
                add("warning", path, "no title: add 'title:' front matter or a '# Heading'")
            if not doc["has_summary"]:
                add("warning", path, "no summary: add 'summary:' front matter (shown in results)")
            if doc["words"] == 0:
                add("warning", path, "document is empty")
            elif doc["words"] > LONG_DOC_WORDS:
                add(
                    "warning",
                    path,
                    f"{doc['words']} words: consider splitting it so agents can read just the"
                    " part they need",
                )
            for link in links[doc["rowid"]]:
                kind, target, anchor, line = (
                    link["kind"],
                    link["target"],
                    link["anchor"],
                    link["line"],
                )
                if kind == "related":
                    target_path = paths.get(target)
                    if target_path is None:
                        add("error", path, f"related doc {target!r} does not exist", line)
                    elif anchor and anchor not in anchors[target_path]:
                        add(
                            "warning",
                            path,
                            f"related section {target}#{anchor} does not exist",
                            line,
                        )
                elif kind == "anchor":
                    if anchor not in anchors[path]:
                        add("warning", path, f"link to missing section #{anchor}", line)
                elif target in known_paths:
                    if anchor and anchor not in anchors[target]:
                        add("warning", path, f"link to missing section {target}#{anchor}", line)
                elif not (self.config.root / target).exists():
                    add("error", path, f"broken link: {target} does not exist", line)

        errors = sum(1 for i in issues if i["severity"] == "error")
        return {
            "documents": len(docs),
            "errors": errors,
            "warnings": len(issues) - errors,
            "issues": issues,
        }

    # -- helpers ------------------------------------------------------------------

    def _resolve(self, ref: str) -> sqlite3.Row:
        """Find a doc by id or path, forgiving extensions, case and partial paths."""
        wanted = ref.strip().replace("\\", "/")
        if not wanted:
            raise NotFoundError("no doc id given")
        if Path(wanted).is_absolute():
            with contextlib.suppress(ValueError):
                wanted = Path(wanted).resolve().relative_to(self.config.root).as_posix()
        wanted = wanted[2:] if wanted.startswith("./") else wanted
        key = _strip_suffix(wanted.lower())
        rows = self.conn.execute("SELECT rowid, id, path FROM documents").fetchall()
        tests = (
            lambda r: wanted in (r["id"], r["path"]),
            lambda r: key in (r["id"].lower(), _strip_suffix(r["path"].lower())),
            lambda r: r["id"].lower().endswith("/" + key),
        )
        for test in tests:
            matches = [r for r in rows if test(r)]
            if len(matches) == 1:
                return self.conn.execute(
                    "SELECT * FROM documents WHERE rowid = ?", (matches[0]["rowid"],)
                ).fetchone()
            if matches:
                raise NotFoundError(
                    f"{ref!r} matches several docs; use the full id",
                    sorted(r["id"] for r in matches),
                )
        ids = [r["id"] for r in rows]
        suggestions = difflib.get_close_matches(wanted, ids, n=5, cutoff=0.5)
        if not suggestions:
            with contextlib.suppress(QueryError):
                suggestions = [r["id"] for r in self.search(ref, limit=3)["results"]]
        raise NotFoundError(f"no doc with id {ref!r}", suggestions)

    def _sections(self, doc_rowid: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sections WHERE doc = ? ORDER BY ord", (doc_rowid,)
        ).fetchall()

    @staticmethod
    def _find_section(doc: sqlite3.Row, sections: list[sqlite3.Row], wanted: str) -> sqlite3.Row:
        text = wanted.strip().lstrip("#").strip()
        lowered, slug = text.lower(), slugify(text)
        named = [s for s in sections if s["anchor"]]
        exact = [s for s in named if s["anchor"] == text]
        if not exact:
            exact = [s for s in named if s["anchor"] == slug or s["heading"].lower() == lowered]
        if exact:
            return exact[0]
        fuzzy = [
            s for s in named if s["anchor"].startswith(slug) or lowered in s["heading"].lower()
        ]
        if len(fuzzy) == 1:
            return fuzzy[0]
        candidates = fuzzy or named
        raise NotFoundError(
            f"no section {wanted!r} in {doc['id']}"
            + ("; several sections match" if len(fuzzy) > 1 else ""),
            [f"{doc['id']}#{s['anchor']}" for s in candidates],
        )

    def _linked_docs(self, doc: sqlite3.Row) -> list[dict]:
        rows = self.conn.execute(
            "SELECT DISTINCT d.id, d.title FROM links l JOIN documents d"
            " ON (l.kind = 'doc' AND d.path = l.target) OR (l.kind = 'related' AND d.id = l.target)"
            " WHERE l.doc = ? AND d.rowid != ? ORDER BY d.id",
            (doc["rowid"], doc["rowid"]),
        )
        return [{"id": r["id"], "title": r["title"]} for r in rows]

    def _backlinks(self, doc: sqlite3.Row) -> list[dict]:
        rows = self.conn.execute(
            "SELECT DISTINCT d.id, d.title FROM links l JOIN documents d ON d.rowid = l.doc"
            " WHERE ((l.kind = 'doc' AND l.target = ?) OR (l.kind = 'related' AND l.target = ?))"
            " AND d.rowid != ? ORDER BY d.id",
            (doc["path"], doc["id"], doc["rowid"]),
        )
        return [{"id": r["id"], "title": r["title"]} for r in rows]

    def _tag_counts(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY n DESC, tag"
        )
        return [{"tag": r["tag"], "count": r["n"]} for r in rows]

    def _count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


_TAGGED_ALL = "SELECT doc FROM tags WHERE tag IN ({marks}) GROUP BY doc HAVING COUNT(*) = ?"


def _schema_version(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def _resolve_links(source: SourceFile, doc: ParsedDoc) -> list[tuple[str, str, str, int]]:
    """Links as ``(kind, target, anchor, file line)`` with targets relative to the root."""
    out = []
    directory = posixpath.dirname(source.rel)
    for link in doc.links:
        line = doc.body_line + link.line + 1
        if not link.target:
            out.append(("anchor", "", link.anchor, line))
            continue
        target = link.target.replace("\\", "/")
        if target.startswith("/"):
            path = posixpath.normpath(target.lstrip("/"))
        else:
            path = posixpath.normpath(posixpath.join(directory, target))
        if path == ".." or path.startswith("../"):
            continue  # points outside the project
        kind = "doc" if path.lower().endswith(DOC_SUFFIXES) else "file"
        out.append((kind, path, link.anchor, line))
    for ref in doc.related:
        target, _, anchor = ref.partition("#")
        out.append(("related", target.strip(), anchor.strip(), 1))
    return out


def _doc_info(doc: sqlite3.Row) -> dict:
    return {
        "id": doc["id"],
        "title": doc["title"],
        "path": doc["path"],
        "summary": doc["summary"],
        "tags": json.loads(doc["tags"]),
        "keywords": json.loads(doc["keywords"]),
        "meta": json.loads(doc["meta"]),
        "words": doc["words"],
    }


def _outline_entry(section: sqlite3.Row) -> dict:
    return {
        "level": section["level"],
        "heading": section["heading"],
        "anchor": section["anchor"],
        "words": section["words"],
    }


def _idf(total: int, hits: int) -> tuple[float, float]:
    """A smoothed IDF, and the clamped one FTS5's bm25() applied (to divide it out)."""
    ratio = (total - hits + 0.5) / (hits + 0.5)
    return math.log(1.0 + ratio), max(1e-6, math.log(ratio))


def _clean_snippet(snippet: str) -> str:
    """One line of text with match markers turned into ``**bold**``."""
    text = " ".join((snippet or "").split())
    return text.replace(_MARK_OPEN, "**").replace(_MARK_CLOSE, "**")


def _clean_tags(tags: Iterable[str] | str | None) -> list[str]:
    if isinstance(tags, str):
        tags = tags.split(",")
    return sorted({t.strip().lstrip("#").lower() for t in tags or () if t and t.strip()})


def _marks(values: list) -> str:
    return ", ".join("?" * len(values))


def _strip_suffix(path: str) -> str:
    for suffix in DOC_SUFFIXES:
        if path.endswith(suffix):
            return path[: -len(suffix)]
    return path


def _humanize(doc_id: str) -> str:
    name = doc_id.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip()
    return name[:1].upper() + name[1:] if name else doc_id
