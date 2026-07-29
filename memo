#!/usr/bin/env python3
"""OptMem: a permanent, append-only memory for AI agents.

  {memo} init             create this memory; print the setup block.
  {memo} wake [part [T]]  read your memory. Run first, every session.
  {memo} note "..."       record one memory: one short line.
  {memo} nap [id "..."]   do the pending compressions.
  {memo} recall <regex>   search every memory ever recorded.
  {memo} zoom <lo>-<hi>   open a tree node: its two halves.
  {memo} forget <lo>-<hi> drop a bad summary; nap rebuilds it.
  {memo} config [NAME=N]  show this memory's sizes, or change one.
  {memo} import <file>    bulk-load dated memories (bootstrap only).

The memories live in ~/.optmem/memory, or in $MEMORY_DIR if set.
See github.com/VictorTaelin/OptMem.
"""

import datetime
try:
    import fcntl
except ImportError:
    fcntl = None  # Windows has no fcntl; we fall back to msvcrt below
import os
import re
import sys
from collections import deque


# The store is UTF-8 by construction, so the tool reads and prints UTF-8
# no matter what the machine's locale says. Without this, one arrow in a
# memory makes wake crash on a latin-1 locale.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):  # Python 3.7+
        _s.reconfigure(encoding="utf-8")


def pretty(p):
    """A path as the user would type it: keep symlinks, fold $HOME to ~."""
    p, home = os.path.abspath(p), os.path.expanduser("~")
    return "~" + p[len(home):] if p.startswith(home + os.sep) else p


# Every command this tool prints has to RUN. After `curl | sh` nothing is on
# PATH, so a bare `memo nap 0-1 "..."` would not: the tool names itself.
ME = pretty(__file__)

# The sizes a memory may override in its own `config` file: the default, and
# what it means. `memo config` shows and edits them. The globals below start
# at these defaults, so a memory that overrides nothing follows the tool.
KNOBS = {
    "WAKE_LINES": (96, "the memory context: how many lines wake prints"),
    "ENTRY_CHARS": (280, "the longest one memory may be, in bytes"),
    "PART_CHARS": (20000, "output paging: largest part, in bytes"),
    "PART_LINES": (500, "output paging: largest part, in lines"),
}
WAKE_LINES = KNOBS["WAKE_LINES"][0]  # ~8k tokens of dense text, in 2 parts
ENTRY_CHARS = KNOBS["ENTRY_CHARS"][0]
# Every harness truncates a command that prints too much, and each drops a
# different piece: Claude Code cuts the middle at 30,000 chars, pi cuts the
# head at 50 KB, Codex budgets 10,000 tokens. So the memory is handed over in
# parts that fit all of them. These are transport limits, not memory limits.
PART_CHARS = KNOBS["PART_CHARS"][0]
PART_LINES = KNOBS["PART_LINES"][0]

RAW_MAX = 16  # blocks up to this many memories compress from the raw log


# Records are FIXED WIDTH, so a memory or a block is found by seeking to its
# offset -- no scanning, no index file to keep in sync. Position IS identity:
# memory i lives at i*LOG_REC of LOG.txt, and block [k*s,(k+1)*s) lives at
# k*TREE_REC of TREE/<s>. Padding costs ~2x on disk and buys O(1) everywhere.
LOG_REC = 320
TREE_REC = 288


# ---------------------------------------------------------------- blocks

# A BLOCK is an aligned power-of-two range of memories, [lo,hi), compressed
# into one line. Blocks form a binary merge tree over LOG.txt: block [lo,hi)
# is the compression of [lo,mid) and [mid,hi).

def _cover(T, alpha):
    """Tile [0,T) with aligned power-of-two blocks; keep a block whole iff its
    size is at most `alpha` times its age. Bigger alpha = coarser = fewer
    lines."""
    root = 1
    while root < T:
        root *= 2
    out, stack = [], [(0, root)]
    while stack:
        lo, hi = stack.pop()
        if lo >= T:
            continue
        size = hi - lo
        if size > 1 and (hi > T or size > alpha * (T - lo)):
            mid = (lo + hi) // 2
            stack.append((mid, hi))
            stack.append((lo, mid))
        else:
            out.append((lo, hi))
    out.sort()
    return out


def cover(T, budget):
    """The blocks `memo wake` prints: at most `budget` of them, finest near T.

    Detail decays with age, so recent memories stay verbatim and ancient ones
    collapse. If everything fits, nothing is compressed at all."""
    if T <= 0:
        return []
    if T <= budget:
        return [(i, i + 1) for i in range(T)]
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if len(_cover(T, mid)) > budget:
            lo = mid
        else:
            hi = mid
    out = _cover(T, hi)
    # Block sizes jump in powers of two, so alpha alone can undershoot the
    # budget. Spend what is left on the present, where detail is worth most.
    while len(out) < budget:
        i = max((i for i, b in enumerate(out) if b[1] - b[0] > 1), default=None)
        if i is None:
            break
        lo_, hi_ = out[i]
        mid = (lo_ + hi_) // 2
        out[i:i + 1] = [(lo_, mid), (mid, hi_)]
    return out


# ---------------------------------------------------------------- store

def memory_dir():
    return os.path.expanduser(os.environ.get("MEMORY_DIR") or "~/.optmem/memory")


def store():
    d = memory_dir()
    # The directory is only ever created by `memo init`: creating it IS
    # creating the identity, and that is a deliberate act. If any other
    # command created it, a typo in MEMORY_DIR would silently open an empty
    # store, and the agent would wake with no past and write a second
    # identity.
    if not os.path.isdir(d):
        die("No memory at %s.\nTo create one, run: %s init\n"
            "To use an existing one, point MEMORY_DIR at it." % (d, ME))
    os.makedirs(os.path.join(d, "TREE"), exist_ok=True)
    p = os.path.join(d, "LOG.txt")
    if not os.path.exists(p):
        open(p, "a").close()
    return d


def size(k, v, where=""):
    """Validate one knob, wherever it came from: the config file or argv. A
    bad knob stops every command, so the message has to say where it is
    written -- `memo config` cannot fix a file it also refuses to read."""
    if not v.isdigit() or int(v) < 1:
        die("%s%s must be a positive whole number, not '%s'." % (where, k, v))
    top = min(TREE_REC - 8, LOG_REC - 40)
    if k == "ENTRY_CHARS" and int(v) > top:
        die("%sENTRY_CHARS is at most %d: a memory has to fit the fixed-width "
            "records." % (where, top))
    return int(v)


def overrides(d):
    """The knobs this memory sets for itself, read from its `config` file."""
    out = {}
    p = os.path.join(d, "config")
    if not os.path.exists(p):
        return out
    for n, line in enumerate(open(p, encoding="utf-8"), 1):
        line = line.split("#")[0].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().upper(), v.strip()
        where = "%s line %d: " % (pretty(p), n)
        if k not in KNOBS:
            die("%s%s is not a size. Delete the line, or name one of: %s."
                % (where, k, ", ".join(KNOBS)))
        out[k] = size(k, v, where)
    return out


def config(d):
    """Apply this memory's overrides. A knob it does not set keeps the tool's
    default, so updating the tool still changes how it behaves."""
    for k, v in overrides(d).items():
        globals()[k] = v  # a knob's name IS the name of the global it sets


def write_config(d, over):
    """Rewrite `config`: every knob on its own line, commented out unless this
    memory overrides it."""
    out = ["# OptMem sizes for this memory. A commented line means: follow the",
           "# tool's default. Edit with `%s config NAME=VALUE`." % ME, ""]
    for k, (default, what) in KNOBS.items():
        out.append("%-2s%-12s = %-6d # %s"
                   % ("" if k in over else "# ", k, over.get(k, default), what))
    with open(os.path.join(d, "config"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def log_path(d):
    return os.path.join(d, "LOG.txt")


def tree_path(d, size):
    return os.path.join(d, "TREE", str(size))


def count(path, rec):
    try:
        return os.path.getsize(path) // rec
    except FileNotFoundError:  # any other failure is real and must surface
        return 0


def log_len(d):
    return count(log_path(d), LOG_REC)


def repair(path, rec):
    """Drop a partial trailing record left by a crash. It was never
    acknowledged. Without this the next append lands at a wrong offset and
    every later record is misaligned. Callers hold the lock."""
    try:
        n = os.path.getsize(path)
    except FileNotFoundError:
        return
    if n % rec:
        with open(path, "r+b") as f:
            f.truncate(n - n % rec)


def parse(line):
    head, _, rest = line.partition(" ")
    date, _, text = rest.partition(" ")
    return int(head[1:]), date, text


def records(buf):
    """Decode a run of log records. They are sliced as BYTES and decoded one
    by one -- slicing decoded text would shift every boundary after the first
    multi-byte character."""
    return [parse(buf[i * LOG_REC:(i + 1) * LOG_REC].decode().rstrip())
            for i in range(len(buf) // LOG_REC)]


def log_slice(d, lo, hi):
    """Memories [lo,hi) in one read."""
    with open(log_path(d), "rb") as f:
        f.seek(lo * LOG_REC)
        return records(f.read((hi - lo) * LOG_REC))


def log_get(d, i):
    """(id, date, text) of memory i, in one seek."""
    return log_slice(d, i, i + 1)[0]


def log_scan(d):
    """Every memory, streamed. A search reads the whole log by nature, but it
    must not HOLD it: at a million memories that is 300 MB."""
    with open(log_path(d), "rb") as f:
        while True:
            buf = f.read(LOG_REC * 4096)
            if not buf:
                return
            for e in records(buf):
                yield e


def tree_get(d, lo, hi):
    """The summary of block [lo,hi), in one seek. None if not built yet."""
    size = hi - lo
    try:
        with open(tree_path(d, size), "rb") as f:
            f.seek((lo // size) * TREE_REC)
            rec = f.read(TREE_REC)
    except FileNotFoundError:  # not built yet; any other failure is real
        return None
    try:
        return rec.decode().rstrip() or None
    except UnicodeDecodeError:
        die("The summary of #%d-%d is corrupt. Run: %s forget %d-%d"
            % (lo, hi - 1, ME, lo, hi - 1))


def pad(text, rec):
    b = text.encode()
    if len(b) > rec - 1:
        die("Too long: %d bytes. The record holds %d." % (len(b), rec - 1))
    return b + b" " * (rec - 1 - len(b)) + b"\n"


def locked(d):
    # Open in append mode ("a"), NOT "w": reopening with "w" truncates the
    # lock file and breaks advisory locks held by other processes on Windows.
    lock = open(os.path.join(d, ".lock"), "a")
    if fcntl is not None:
        fcntl.flock(lock, fcntl.LOCK_EX)
    else:
        # Windows: no fcntl. Use msvcrt advisory lock with spin/backoff so
        # parallel sessions (the documented multi-process case) queue instead
        # of raising "Resource deadlock avoided" under contention.
        import msvcrt as _ms
        import time as _t
        waited = 0.0
        while True:
            try:
                _ms.locking(lock.fileno(), _ms.LK_NBLCK, 1)
                break
            except OSError:
                if waited > 30.0:
                    raise
                _t.sleep(min(0.01 + waited * 0.2, 0.25))
                waited += 0.01
        _orig_close = lock.close
        def _close():
            try:
                _ms.locking(lock.fileno(), _ms.LK_UNLCK, 1)
            except Exception:
                pass
            _orig_close()
        lock.close = _close
    return lock


def log_append(d, items):
    """Append memories, items = [(date, text)]. The only way LOG.txt ever
    changes. Ids are assigned INSIDE the lock: two sessions noting at the same
    moment must not be handed the same id. Returns the first id used."""
    lock = locked(d)
    try:
        repair(log_path(d), LOG_REC)
        base = log_len(d)
        with open(log_path(d), "ab") as f:
            for k, (date, text) in enumerate(items):
                f.write(pad("#%d %s %s" % (base + k, date, text), LOG_REC))
            f.flush()
            os.fsync(f.fileno())
        return base
    finally:
        lock.close()


def tree_put(d, lo, hi, text):
    """Write block [lo,hi). Blocks are built in order, so this only ever
    appends one record to one level file."""
    size = hi - lo
    lock = locked(d)
    try:
        p = tree_path(d, size)
        repair(p, TREE_REC)
        if count(p, TREE_REC) != lo // size:
            return False
        with open(p, "ab") as f:
            f.write(pad(text, TREE_REC))
            f.flush()
            os.fsync(f.fileno())
        return True
    finally:
        lock.close()


def tree_drop(d, lo, hi):
    """Forget block [lo,hi) and every block built from it, by truncating each
    level back to that point. Later blocks at those levels go too and are
    rebuilt; the log is never touched, so nothing is lost."""
    gone, size = [], hi - lo
    lock = locked(d)
    try:
        while size <= log_len(d):
            p, k = tree_path(d, size), lo // size
            n = count(p, TREE_REC)
            if n > k:
                gone += [(i * size, (i + 1) * size) for i in range(k, n)]
                with open(p, "r+b") as f:
                    f.truncate(k * TREE_REC)
            size *= 2
        return gone
    finally:
        lock.close()


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def plural(n, word):
    if n == 1:
        return "1 " + word
    if word.endswith("y"):
        word = word[:-1] + "ie"
    elif word.endswith(("s", "h", "x")):
        word += "e"
    return "%d %ss" % (n, word)


def block_id(s):
    """Parse `<lo>-<hi>` as wake and the nap prompts print it: inclusive at
    both ends, and a real block -- an aligned power-of-two range. Without the
    shape check, `4-5` and `5-6` read the same record."""
    m = re.fullmatch(r"(\d+)-(\d+)", s)
    if not m:
        die("'%s' is not a block id. Copy it from the prompt." % s)
    lo, hi = int(m.group(1)), int(m.group(2)) + 1
    n = hi - lo
    if n < 2 or n & (n - 1) or lo % n:
        die("%s is not a block. Copy the id printed by wake, like 16-31." % s)
    return lo, hi


def check(text):
    text = text.strip()
    if not text:
        die("Empty. A memory is one line of text.")
    if "\n" in text or "\r" in text:
        die("%d lines. A memory is one line: merge them, or note them "
            "separately." % (text.count("\n") + 1))
    n = len(text.encode())
    if n > ENTRY_CHARS:
        die("Too long: %d bytes, limit %d. Accented characters cost 2 bytes. "
            "Compress it further." % (n, ENTRY_CHARS))
    return text


# ---------------------------------------------------------------- naps

def pending(d, T, limit=None):
    """Blocks that can be built and have not been, smallest first. Each level
    file holds a dense prefix, so its length says exactly how far that level
    got: this costs one stat per level, never a scan."""
    todo, size = [], 2
    while size <= T:
        have = count(tree_path(d, size), TREE_REC)
        for k in range(have, T // size):
            todo.append((k * size, (k + 1) * size))
            if limit and len(todo) >= limit:
                return todo
        size *= 2
    return todo


def pending_count(d, T):
    """How many blocks pending() would list, without listing them. A level can
    hold MORE blocks than T needs -- T is a snapshot, and memories keep
    arriving while an agent reads -- so each level is clamped at zero."""
    n, size = 0, 2
    while size <= T:
        n += max(0, T // size - count(tree_path(d, size), TREE_REC))
        size *= 2
    return n


def nap_prompt(d, lo, hi, left):
    if hi - lo <= RAW_MAX:
        body = "\n".join("  #%d %s %s" % e for e in log_slice(d, lo, hi))
    else:
        mid, halves = (lo + hi) // 2, []
        for a, b in ((lo, mid), (mid, hi)):
            s = tree_get(d, a, b)
            if s is None:
                # pending() lists a block only after its halves settled, so
                # a missing half is a blank record -- a corrupt write. Drop
                # it and the next nap rebuilds it.
                die("The summary of #%d-%d is blank. Run: %s forget %d-%d"
                    % (a, b - 1, ME, a, b - 1))
            halves.append("  #%d-%d %s" % (a, b - 1, s))
        body = "\n".join(halves)
    tail = "" if not left else "\n%s after this one." % (
        "1 compression remains" if left == 1 else
        "%d compressions remain" % left)
    return ("Compress memories #%d-%d into one line of at most %d bytes.\n"
            "Keep what has lasting effect, drop what does not. Invent "
            "nothing.\n\n"
            "%s\n%s\n"
            "Run: %s nap %d-%d \"<your line>\""
            % (lo, hi - 1, ENTRY_CHARS, body, tail, ME, lo, hi - 1))


def next_nap(d, T):
    todo = pending(d, T, limit=1)
    if not todo:
        return None
    lo, hi = todo[0]
    return nap_prompt(d, lo, hi, pending_count(d, T) - 1)


# ---------------------------------------------------------------- commands

TEMPLATE = """\
## Memory

Your memory is OptMem:
- The tool is `{memo}`
- Your memories are in `{data}`

OptMem outlives every session, compaction, model and vendor change.
Without it you do not know who you are, or what was decided and tried.

### At startup: activating OptMem (mandatory)

Run `{memo} wake` before any other tool call, in every session, and
then do exactly what it prints, to the end of its output.

### While working: register memories (mandatory)

Call `{memo} note "<1 line, max {chars} bytes>"` whenever you learn
something new, or something worth keeping happens. That covers a task
worth real effort, a fact or insight the user teaches you, anything you
learn about their life (even indirectly), any event of lasting effect.

Do not register redundant memories.

If `{memo} note` asks a compression: do it before your next action.

Never edit or delete anything under `{data}`: the tool manages it.

### When you need an old memory: search, or navigate

`{memo} recall <regex>` searches every memory, word for word.

Your memories also form a binary tree: #0-1, #2-3 ... exist as one-line
summaries, pairs of those as #0-3, and so on -- every `#a-b` line wake
prints is one node of it. `{memo} zoom <a-b>` opens a node into its
two halves, down to the raw memories.

### If you're a subagent: skip everything above

Parallel sessions on this machine are all you, and may all write memories.
A subagent is not: it must never run `memo`, because it cannot judge what
is already known, and its notes would arrive duplicated and incorrectly.
When you spawn one, write: `You are a subagent. Don't run memo.`
"""


def cmd_init(d, args):
    """The one command that may create the memory directory, and the whole
    setup: make the store, write the size knobs, print the block the user
    pastes into their agent's instruction file. Re-running it is safe: it
    only ever creates what is missing, and never rewrites what is there."""
    if args:
        die("usage: %s init" % ME)
    fresh = not os.path.isdir(d)
    os.makedirs(os.path.join(d, "TREE"), exist_ok=True)
    open(log_path(d), "a").close()
    if not os.path.exists(os.path.join(d, "config")):
        write_config(d, {})
    config(d)
    if fresh:
        print("Created %s: this machine's memory, one identity, forever." % pretty(d))
    else:
        print("Found %s: %s." % (pretty(d), plural(log_len(d), "memory")))
    print("Sizes live in %s/config; the defaults are fine." % pretty(d))
    print()
    print("Paste this at the top of your agent's AGENTS.md (or CLAUDE.md), done:")
    print()
    print(TEMPLATE.format(memo=ME, data=pretty(d), chars=ENTRY_CHARS).rstrip())


def paginate(lines):
    """Split the document into parts that survive any harness's output cap."""
    parts, cur, size = [], [], 0
    for line in lines:
        n = len(line.encode()) + 1
        if cur and (len(cur) >= PART_LINES or size + n > PART_CHARS):
            parts.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += n
    if cur:
        parts.append(cur)
    return parts


def cmd_wake(d, args):
    now = log_len(d)
    k, T = 1, now
    if args:
        if len(args) > 2 or not all(a.isdigit() for a in args):
            die("usage: %s wake [part [T]]" % ME)
        k = int(args[0])
        if len(args) == 2:
            T = int(args[1])
            if T > now:
                die("T=%d, but the log holds %s. Run: %s wake"
                    % (T, plural(now, "memory"), ME))
    # A part is rendered as of T, so a note landing between two parts cannot
    # shift a boundary and drop a line.
    if not T:
        print("No memories yet. Record the first with: %s note \"<one line>\""
              % ME)
        print("You are awake.")
        return
    lines = []
    for lo, hi in cover(T, WAKE_LINES):
        if hi - lo == 1:
            lines.append("#%d %s %s" % log_get(d, lo))
        else:
            s = tree_get(d, lo, hi)
            if s is None:
                nap = next_nap(d, T)
                if nap:
                    # The ONLY reason to refuse: this document cannot be
                    # written without that summary. Work that the document
                    # does not need is handed over after the read instead,
                    # costing no round trip.
                    print("Cannot wake: the memory context needs #%d-%d, "
                          "which is not compressed yet.\nDo the %s below, "
                          "then run %s wake again.\n"
                          % (lo, hi - 1,
                             plural(pending_count(d, T), "compression"), ME))
                    print(nap)
                    sys.exit(1)
                s = tree_get(d, lo, hi)  # a parallel session may have paid it
            if s is None:
                # Nothing is pending, so the record exists but is blank -- a
                # corrupt write. Drop it and the next nap rebuilds it.
                die("The summary of #%d-%d is blank. Run: %s forget %d-%d"
                    % (lo, hi - 1, ME, lo, hi - 1))
            lines.append("#%d-%d %s" % (lo, hi - 1, s))
    parts = paginate(lines)
    if not 1 <= k <= len(parts):
        die("No part %d: the memory has %s. Run: %s wake"
            % (k, plural(len(parts), "part"), ME))
    if len(parts) > 1:
        # The count is here so the T in `memo wake 2 296` reads as what it
        # is: the snapshot this document was written from.
        print("Your memory, part %d of %d, oldest first (%s)."
              % (k, len(parts), plural(T, "memory")))
    print("\n".join(parts[k - 1]))
    if k < len(parts):
        # This footer is the only instruction that survives every harness's
        # truncation (pi drops the HEAD of a long output), so it has to say
        # both that the read is unfinished and how to continue it.
        print("Not awake yet. Run: %s wake %d %d" % (ME, k + 1, T))
    else:
        # always, even for a one-part memory: the contract an agent is given
        # is "run parts until one says awake", so it must always arrive
        print("You are awake.")
        nap = next_nap(d, T)
        if nap:
            print("\n" + nap)


def cmd_note(d, args):
    if len(args) != 1:
        die("usage: %s note \"<one line, at most %d bytes>\""
            % (ME, ENTRY_CHARS))
    text = check(args[0])
    i = log_append(d, [(datetime.date.today().isoformat(), text)])
    print("Saved as #%d." % i)
    nap = next_nap(d, i + 1)
    if nap:
        print("\n" + nap)


def cmd_nap(d, args):
    T, said = log_len(d), False
    if args:
        said = True
        if len(args) != 2:
            die("usage: %s nap <lo>-<hi> \"<one line>\"" % ME)
        lo, hi = block_id(args[0])
        todo = pending(d, T, limit=1)
        if not todo:
            print("Nothing left to compress.")
            return
        if (lo, hi) != todo[0]:
            if tree_get(d, lo, hi) is not None:
                print("%d-%d is already settled." % (lo, hi - 1))
            else:
                die("Wrong block: %s. Blocks are built in order; the next is "
                    "%d-%d. Run: %s nap"
                    % (args[0], todo[0][0], todo[0][1] - 1, ME))
        elif not tree_put(d, lo, hi, check(args[1])):
            print("%d-%d was settled or forgotten meanwhile." % (lo, hi - 1))
        else:
            print("%d-%d saved." % (lo, hi - 1))
    nap = next_nap(d, T)
    if not nap:
        print("Nothing left to compress.")
        return
    print(("\n" if said else "") + nap)


def cmd_config(d, args):
    """Show this memory's sizes, or change one. An empty value restores the
    default. Sizes only select what is printed, so changing one is free: no
    memory is touched and nothing is recomputed."""
    over = overrides(d)
    for a in args:
        k, eq, v = a.partition("=")
        k = k.strip().upper()
        if not eq or k not in KNOBS:
            die("usage: %s config [NAME=VALUE ...]   # NAME one of %s"
                % (ME, ", ".join(KNOBS)))
        if v.strip():
            over[k] = size(k, v.strip())
        else:
            over.pop(k, None)
    if args:
        write_config(d, over)
    for k, (default, what) in KNOBS.items():
        print("%-12s %-7d %s%s" % (k, over.get(k, default), what,
                                   "" if k not in over else
                                   " (default %d)" % default))


def cmd_forget(d, args):
    """A summary can be wrong -- mistyped, or a bad compression. Drop it and
    everything built on top of it; the next nap computes them again. The log
    is untouched, so nothing is ever actually lost."""
    if len(args) != 1:
        die("usage: %s forget <lo>-<hi>" % ME)
    gone = tree_drop(d, *block_id(args[0]))
    if not gone:
        die("No summary at %s." % args[0])
    print("Forgot %s, from %d-%d up. Run: %s nap"
          % (plural(len(gone), "summary"), gone[0][0], gone[0][1] - 1, ME))


def cmd_recall(d, args):
    if len(args) != 1:
        die("usage: %s recall <regex>" % ME)
    try:
        pat = re.compile(args[0], re.I)
    except re.error as e:
        die("bad regex: %s" % e)
    # One pass, keeping only the newest matches that fit the cap `wake`
    # respects -- a vague regex matches the whole log, and the whole log does
    # not fit in a harness's output or in memory.
    hits, out, size = 0, deque(), 0
    for e in log_scan(d):
        line = "#%d %s %s" % e
        if not pat.search(line):
            continue
        hits += 1
        out.append(line)
        size += len(line.encode()) + 1
        while size > PART_CHARS:
            size -= len(out.popleft().encode()) + 1
    if not hits:
        print("No match.")
        return
    print("\n".join(out))
    if len(out) < hits:
        print("Newest %d of %s. Narrow the regex."
              % (len(out), plural(hits, "match")))
    else:
        print("%s." % plural(hits, "match"))


def cmd_zoom(d, args):
    """One node of the tree, opened: its two halves, each rendered as wake
    renders it -- a summary, or the raw memory once a half is single. The
    navigating intelligence is the agent's; the tool only reads."""
    if len(args) != 1:
        die("usage: %s zoom <lo>-<hi>   # a block id, as wake prints them"
            % ME)
    lo, hi = block_id(args[0])
    T = log_len(d)
    if lo >= T:
        die("#%s is beyond the memory: it holds %s. Run: %s wake"
            % (args[0], plural(T, "memory"), ME))
    mid = (lo + hi) // 2
    for a, b in ((lo, mid), (mid, hi)):
        if a >= T:
            continue  # the future: no memories there yet
        if b - a == 1:
            print("#%d %s %s" % log_get(d, a))
        else:
            print("#%d-%d %s" % (a, b - 1, tree_get(d, a, b)
                                 or "not compressed yet"))


def cmd_import(d, args):
    """Bulk-append historical memories: 'YYYY-MM-DD <text>' per line.
    For bootstrapping an identity from older records. Used once."""
    if len(args) != 1:
        die("usage: %s import <file>   # lines of 'YYYY-MM-DD <text>'" % ME)
    try:
        src = open(args[0], encoding="utf-8").readlines()
    except UnicodeDecodeError:
        die("%s is not UTF-8 text. Convert it, then import again."
            % pretty(args[0]))
    last = log_get(d, log_len(d) - 1)[1] if log_len(d) else "0000-00-00"
    out = []
    for i, line in enumerate(src, 1):
        line = line.rstrip("\n")
        if not line.strip():
            continue
        date, _, text = line.partition(" ")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            die("line %d: expected 'YYYY-MM-DD <text>', got: %s" % (i, line))
        try:
            datetime.datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            die("line %d: %s is not a real date." % (i, date))
        if date < last:
            die("line %d: date %s precedes the previous memory (%s)."
                % (i, date, last))
        text = text.strip()
        if not text or len(text.encode()) > ENTRY_CHARS:
            die("line %d: %d bytes, limit %d." % (i, len(text.encode()), ENTRY_CHARS))
        out.append((date, text))
        last = date
    if not out:
        die("%s has no memories." % args[0])
    base = log_append(d, out)
    print("Imported %s, #%d to #%d."
          % (plural(len(out), "memory"), base, base + len(out) - 1))
    n = pending_count(d, log_len(d))
    if n:
        print("%s pending. Run: %s nap" % (plural(n, "compression"), ME))


COMMANDS = {"init": cmd_init, "wake": cmd_wake, "note": cmd_note,
            "nap": cmd_nap, "recall": cmd_recall, "zoom": cmd_zoom,
            "forget": cmd_forget, "config": cmd_config, "import": cmd_import}


def main():
    usage = __doc__.strip().format(memo=ME)
    if len(sys.argv) < 2:
        print(usage)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print("No such command: %s\n" % cmd, file=sys.stderr)
        print(usage, file=sys.stderr)
        sys.exit(1)
    try:
        # `init` is the only command that may run without an existing memory:
        # it is the one that creates it. Every other command refuses, so a
        # typo in MEMORY_DIR is an error instead of a second, empty identity.
        if cmd == "init":
            cmd_init(memory_dir(), sys.argv[2:])
            return
        d = store()
        config(d)
        COMMANDS[cmd](d, sys.argv[2:])
    except OSError as e:
        # The filesystem is the one thing the tool does not control. Report it
        # the way every other failure is reported: a Python traceback tells an
        # agent nothing it can act on.
        die("%s: %s." % (pretty(e.filename or memory_dir()), e.strerror or e))


if __name__ == "__main__":
    main()
