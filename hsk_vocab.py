"""HSK vocabulary gate, generalized across HSK levels (old HSK 2.0: 1-6).

A sentence passes level N only if it can be fully segmented into words that
are cumulatively allowed through that level: the union of
data/vocab/raw/hsk_2012_L1.txt .. LN.txt (each file lists only the words newly
introduced at that level, per the 2012 Hanban lists), plus the grammatical
exceptions in data/vocab/extra_allowed.txt (shared across all levels -- see
that file's header for why it exists and what belongs in it).

Segmentation is a DP over the allowed word set: if no covering exists, the
sentence uses vocabulary outside the level. This is a mechanical check, not a
judgement call -- that is the whole point of it.
"""

from pathlib import Path

DATA = Path(__file__).parent / "data" / "vocab"
RAW = DATA / "raw"

# Punctuation / digits are not vocabulary; they are skipped before checking.
SKIP = set(" \t\n﻿0123456789，。？！、：；“”‘’…—,.?!:;\"'()（）《》")


def _load(path: Path) -> set[str]:
    if not path.exists():
        return set()
    words = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.strip().lstrip("﻿")
        if word and not word.startswith("#"):
            words.add(word)
    return words


def _runs(text: str) -> list[str]:
    """Split text into maximal runs of checkable (non-punctuation) characters."""
    runs, cur = [], []
    for ch in text:
        if ch in SKIP:
            if cur:
                runs.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        runs.append("".join(cur))
    return runs


class Vocab:
    """Cumulative allowed vocabulary through one HSK level."""

    def __init__(self, level: int, allowed: set[str], extra: set[str]):
        self.level = level
        self.allowed = allowed
        self.extra = extra
        self.words = allowed | extra
        self.maxlen = max((len(w) for w in self.words), default=1)

    def _segment(self, run: str) -> list[str] | None:
        n = len(run)
        # back[i] = length of the word ending at i in some valid covering of run[:i]
        back: list[int | None] = [None] * (n + 1)
        reachable = [False] * (n + 1)
        reachable[0] = True
        for i in range(1, n + 1):
            for length in range(1, min(self.maxlen, i) + 1):
                if reachable[i - length] and run[i - length : i] in self.words:
                    reachable[i] = True
                    back[i] = length
                    break
        if not reachable[n]:
            return None
        tokens, i = [], n
        while i > 0:
            length = back[i]
            tokens.append(run[i - length : i])
            i -= length
        return tokens[::-1]

    def _offenders(self, run: str) -> list[str]:
        """Greedy scan listing the substrings that could not be matched."""
        bad, i = [], 0
        while i < len(run):
            for length in range(min(self.maxlen, len(run) - i), 0, -1):
                if run[i : i + length] in self.words:
                    i += length
                    break
            else:
                bad.append(run[i])
                i += 1
        return bad

    def check(self, text: str) -> tuple[bool, list[str], list[str]]:
        """Check one sentence: (ok, tokens, offenders)."""
        tokens: list[str] = []
        offenders: list[str] = []
        ok = True
        for run in _runs(text):
            seg = self._segment(run)
            if seg is None:
                ok = False
                offenders.extend(self._offenders(run))
            else:
                tokens.extend(seg)
        return ok, tokens, offenders

    def used_extras(self, tokens: list[str]) -> list[str]:
        """Which tokens were only allowed because of extra_allowed.txt."""
        return sorted({t for t in tokens if t in self.extra and t not in self.allowed})


_cache: dict[int, Vocab] = {}


def load_level(level: int) -> Vocab:
    """Load the cumulative vocabulary through HSK `level` (old HSK 2.0, 1-6)."""
    if level in _cache:
        return _cache[level]
    allowed: set[str] = set()
    for lv in range(1, level + 1):
        path = RAW / f"hsk_2012_L{lv}.txt"
        if not path.exists():
            raise FileNotFoundError(
                f"HSK{level} needs {path} (the word list newly introduced at level {lv}) -- not downloaded yet"
            )
        allowed |= _load(path)
    extra = _load(DATA / "extra_allowed.txt")
    vocab = Vocab(level, allowed, extra)
    _cache[level] = vocab
    return vocab


if __name__ == "__main__":
    import sys

    # Windows consoles default to cp932/cp1252 and cannot print Chinese.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    level = 2
    if args and args[0].isdigit():
        level = int(args[0])
        args = args[1:]
    lines = args or [l for l in sys.stdin.read().splitlines() if l.strip()]

    vocab = load_level(level)
    print(f"HSK{level}: cumulative words={len(vocab.allowed)} extra={len(vocab.extra)} maxlen={vocab.maxlen}")
    for line in lines:
        ok, tokens, bad = vocab.check(line)
        mark = "OK  " if ok else "OOV "
        detail = "/".join(tokens) if ok else "范围外: " + " ".join(bad)
        print(f"{mark} {line}\n     {detail}")
