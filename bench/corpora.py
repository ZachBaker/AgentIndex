"""The real knowledge bases the benchmark runs on, and how to fetch them.

Each corpus is a folder of docs, or one large agent instructions file, in a public
repository, pinned to a commit in ``corpora.json``. ``fetch`` makes a sparse,
blob-filtered checkout of just those paths into ``bench/.cache/<name>/`` and
writes an ``.agentindex.json`` there, so a corpus can also be explored by hand:
``python3 -m agentindex --root bench/.cache/<name> search "..."``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agentindex.scaffold import import_markdown

BENCH_DIR = Path(__file__).resolve().parent
CORPORA_FILE = BENCH_DIR / "corpora.json"
CACHE_DIR = BENCH_DIR / ".cache"
IMPORTED = "knowledge"  # where an "import" corpus is split into docs


@dataclass
class Corpus:
    name: str
    title: str
    kind: str  # "docs": index folders as they are; "import": split one file with import
    repo: str
    commit: str
    paths: list[str]
    license: str
    about: str

    @property
    def root(self) -> Path:
        return CACHE_DIR / self.name

    @property
    def sources(self) -> list[str]:
        """What the index reads, relative to ``root``."""
        return [IMPORTED] if self.kind == "import" else list(self.paths)

    @property
    def original(self) -> Path | None:
        """The agent instructions file an "import" corpus was split from."""
        return self.root / self.paths[0] if self.kind == "import" else None

    @property
    def web_url(self) -> str:
        base = self.repo[:-4] if self.repo.endswith(".git") else self.repo
        middle = "/-/tree/" if "gitlab.com" in base else "/tree/"
        return f"{base}{middle}{self.commit}/{self.paths[0]}"


def load_corpora(names: list[str] | None = None) -> list[Corpus]:
    """The corpora in ``corpora.json``, or just the named ones (in that order)."""
    data = json.loads(CORPORA_FILE.read_text(encoding="utf-8"))
    corpora = {c["name"]: Corpus(**c) for c in data["corpora"]}
    if not names:
        return list(corpora.values())
    unknown = [n for n in names if n not in corpora]
    if unknown:
        raise SystemExit(f"unknown corpus {', '.join(unknown)}; known: {', '.join(corpora)}")
    return [corpora[n] for n in names]


def is_fetched(corpus: Corpus) -> bool:
    return (corpus.root / ".agentindex.json").is_file() and _head(corpus.root) == corpus.commit


def fetch(corpus: Corpus, log=print) -> None:
    """Check out the corpus at its pinned commit (once) and prepare it for indexing."""
    root = corpus.root
    if _head(root) != corpus.commit:
        log(f"fetching {corpus.name} from {corpus.repo} at {corpus.commit[:12]}")
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        _git(root, "init", "-q")
        _git(root, "remote", "add", "origin", corpus.repo)
        patterns = ["/" + path.strip("/") for path in corpus.paths]
        _git(root, "sparse-checkout", "set", "--no-cone", *patterns)
        _git(root, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", corpus.commit)
        _git(root, "-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD")
    if corpus.kind == "import":
        # Import exactly as an adopter would: defaults, no hand edits afterwards.
        shutil.rmtree(root / IMPORTED, ignore_errors=True)
        import_markdown(corpus.original, root / IMPORTED)
    config = {"sources": corpus.sources}
    (root / ".agentindex.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _head(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return done.stdout.strip() if done.returncode == 0 else None


def _git(root: Path, *args: str) -> None:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {root}:\n{done.stderr.strip()}")
