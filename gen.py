"""Build the listening sets: validate vocabulary, add pinyin, synthesize audio.

    python gen.py              # build every set under tests/, skip existing audio
    python gen.py --force      # re-synthesize all audio
    python gen.py --check      # validate vocabulary only, no audio, no writes
    python gen.py --rate -20%  # slower speech

Sets live under tests/hsk<N>/<name>.json, one HSK level per directory. Level N
gates vocabulary through hsk_vocab.load_level(N): the cumulative HSK1..N word
list, so a set under tests/hsk3/ may use any HSK1+2+3 word. A set that uses a
word outside its level's cumulative vocabulary fails the build rather than
quietly shipping. Pinyin comes from pypinyin, never from hand-typing.

Adding a new level later: drop data/vocab/raw/hsk_2012_L<N>.txt (the official
word list newly introduced at that level) next to the existing ones, then
create tests/hsk<N>/*.json with "level": "HSK<N>".
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import edge_tts
from pypinyin import Style, pinyin

import hsk_vocab

ROOT = Path(__file__).parent
TESTS = ROOT / "tests"
AUDIO = ROOT / "audio"
PLAYER_DATA = ROOT / "player_data.js"

# Alternating voices so the ear does not lock onto one speaker.
VOICES = ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"]
CONCURRENCY = 4

LEVEL_DIR = re.compile(r"^hsk(\d+)$", re.IGNORECASE)


def to_pinyin(zh: str) -> str:
    out = ""
    for syl in pinyin(zh, style=Style.TONE):
        token = syl[0]
        # pypinyin passes punctuation through untouched; keep it tight to the
        # preceding syllable instead of floating on its own space.
        sep = "" if not out or token in "，。？！、：；" else " "
        out += sep + token
    return out


def load_sets() -> list[dict]:
    """Load every tests/hsk<N>/*.json set, tagged with its level and a unique key."""
    sets = []
    for level_dir in sorted(p for p in TESTS.iterdir() if p.is_dir()):
        m = LEVEL_DIR.match(level_dir.name)
        if not m:
            sys.exit(f"tests/{level_dir.name}/ does not match the hsk<N> naming convention")
        level = int(m.group(1))
        for f in sorted(level_dir.glob("*.json")):
            s = json.loads(f.read_text(encoding="utf-8"))
            declared = s.get("level", "")
            if declared.upper() != f"HSK{level}":
                sys.exit(
                    f"{f}: level field is {declared!r} but the file lives under "
                    f"tests/{level_dir.name}/ -- fix one or the other"
                )
            s["_level_num"] = level
            s["key"] = f"{level_dir.name}/{f.stem}"
            sets.append(s)
    if not sets:
        sys.exit(f"no sets found under {TESTS} (expected tests/hsk<N>/*.json)")
    return sets


def validate(sets: list[dict]) -> int:
    """Print a vocabulary report. Returns the number of out-of-range sentences."""
    failures = 0
    for s in sets:
        vocab = hsk_vocab.load_level(s["_level_num"])
        print(
            f"\n[{s['key']}] {s['title']}  "
            f"({len(s['sentences'])} sentences, HSK{s['_level_num']} cumulative vocab={len(vocab.allowed)} words)"
        )
        for item in s["sentences"]:
            ok, tokens, bad = vocab.check(item["zh"])
            if not ok:
                failures += 1
                print(f"  NG {item['n']:>2}. {item['zh']}")
                print(f"        HSK{s['_level_num']} range外: {' '.join(bad)}")
                continue
            extras = vocab.used_extras(tokens)
            note = f"   [extra: {' '.join(extras)}]" if extras else ""
            print(f"  ok {item['n']:>2}. {item['zh']}{note}")
    return failures


async def synth(zh: str, voice: str, rate: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    await edge_tts.Communicate(zh, voice, rate=rate).save(str(out))


async def build_audio(sets: list[dict], rate: str, force: bool) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    jobs = []

    async def one(zh: str, voice: str, out: Path) -> None:
        if out.exists() and not force:
            return
        async with sem:
            await synth(zh, voice, rate, out)
            print(f"  audio {out.relative_to(ROOT)}  [{voice.split('-')[-1]}]")

    for s in sets:
        for i, item in enumerate(s["sentences"]):
            voice = VOICES[i % len(VOICES)]
            item["voice"] = voice
            item["audio"] = f"audio/{s['key']}/s{item['n']:02d}.mp3"
            jobs.append(one(zh=item["zh"], voice=voice, out=ROOT / item["audio"]))

    print(f"\nsynthesizing (rate={rate}, force={force})...")
    await asyncio.gather(*jobs)


def write_player_data(sets: list[dict]) -> None:
    for s in sets:
        for item in s["sentences"]:
            item["pinyin"] = to_pinyin(item["zh"])
        s.pop("_level_num", None)  # build-time bookkeeping only
    body = json.dumps(sets, ensure_ascii=False, indent=2)
    # A .js assignment rather than .json so player.html works over file:// too,
    # where fetch() of a local file is blocked by CORS.
    PLAYER_DATA.write_text(
        f"// generated by gen.py -- do not edit\nwindow.TEST_DATA = {body};\n",
        encoding="utf-8",
    )
    total = sum(len(s["sentences"]) for s in sets)
    print(f"\nwrote {PLAYER_DATA.name}: {len(sets)} set(s), {total} sentences")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-synthesize existing audio")
    ap.add_argument("--check", action="store_true", help="validate vocabulary only")
    ap.add_argument("--rate", default="-10%", help="edge-tts speech rate (default -10%%)")
    args = ap.parse_args()

    sets = load_sets()
    failures = validate(sets)
    if failures:
        sys.exit(f"\n{failures} sentence(s) outside their HSK level. Fix them or add to data/vocab/extra_allowed.txt.")
    print("\nvocabulary: all sentences within their declared HSK level.")

    if args.check:
        return
    asyncio.run(build_audio(sets, args.rate, args.force))
    write_player_data(sets)


if __name__ == "__main__":
    main()
