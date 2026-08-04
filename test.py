#!/usr/bin/env python3
"""OptMem invariants, checked against a synthetic life of 5000 memories.

Uses a fake compressor (join + truncate) so the run is deterministic and free.
"""

import contextlib
import datetime
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
MEMO = os.path.join(HERE, "memo")
cli = SourceFileLoader("memo_cli", MEMO).load_module()
cover = cli.cover


def complete(T):
    """Every block buildable from T memories, smallest first. The oracle for
    the tool's `pending()`: written straight from the definition, so a bug in
    the fast version (which reads level lengths, never scanning) shows up."""
    out, size = [], 2
    while size <= T:
        out += [(i * size, (i + 1) * size) for i in range(T // size)]
        size *= 2
    return out

# The shipped defaults. A fresh process starts from these, so an in-process
# call must too, or one store's config would leak into the next.
DEFAULTS = {k: getattr(cli, k) for k in
            ("ENTRY_CHARS", "WAKE_LINES", "PART_CHARS", "PART_LINES")}

N = 2000
WAKE_LINES = cli.WAKE_LINES   # the shipped budget, not a second copy of it
PART_CHARS = cli.PART_CHARS
# Verified caps of the harnesses in the wild: Claude Code cuts a command's
# output at 30,000 chars (middle), pi at 50 KB / 2000 lines (head), Codex
# budgets 10,000 tokens. A part must fit the strictest of each kind.
CAP_CHARS, CAP_LINES = 30000, 2000
ok, fail = 0, 0


def check(cond, msg):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("FAIL: " + msg)


# ---- pure block math -------------------------------------------------

for T in list(range(1, 400)) + [1000, 4096, 10000, 65536, 100003]:
    c = cover(T, WAKE_LINES)
    check(len(c) <= WAKE_LINES, "T=%d: %d lines > budget" % (T, len(c)))
    check(c[0][0] == 0 and c[-1][1] == T, "T=%d: does not span [0,T)" % T)
    for a, b in zip(c, c[1:]):
        check(a[1] == b[0], "T=%d: gap or overlap at %s %s" % (T, a, b))
    for lo, hi in c:
        s = hi - lo
        check(s & (s - 1) == 0 and lo % s == 0,
              "T=%d: [%d,%d) is not an aligned power-of-two block" % (T, lo, hi))
    for a, b in zip(c, c[1:]):
        check(b[1] - b[0] <= a[1] - a[0],
              "T=%d: detail does not increase toward the present" % T)

check(cover(300, 320) == [(i, i + 1) for i in range(300)],
      "under budget, memory should be verbatim")

# every block a cover ever needs must be buildable. cover() costs a 60-step
# binary search, so this walks every tree shape up to 300 and then samples:
# the property is structural, not a function of the exact T.
seen = set()
for T in list(range(1, 300)) + [512, 700, 1000, 1023, 1024, 2000, 2999]:
    seen.update(b for b in cover(T, WAKE_LINES) if b[1] - b[0] > 1)
buildable = set(complete(3000))
check(seen <= buildable, "a cover wants a block that complete() never yields")

# work never spikes: naps created by one new memory
worst, prev = 0, 0
for T in range(1, N):
    cur = len(complete(T))
    worst = max(worst, cur - prev)
    prev = cur
check(worst <= 16, "a single memory created %d naps" % worst)

# ---- the real CLI ----------------------------------------------------

d = tempfile.mkdtemp(prefix="optmem-test-")
memo = [sys.executable, MEMO]


class Result:
    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def run(*args, store=None):
    """One `memo` command, in-process. Spawning an interpreter per call cost
    ~40ms x ~2000 naps; the cross-process behaviour that genuinely needs real
    processes (the lock) is tested with real processes below."""
    os.environ["MEMORY_DIR"] = store or d
    for k, v in DEFAULTS.items():
        setattr(cli, k, v)
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            sd = cli.store()
            cli.config(sd)
            cli.COMMANDS[args[0]](sd, list(args[1:]))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    return Result(code, out.getvalue(), err.getvalue())


def nap_id(out):
    """The block id from the command a nap prompt offers."""
    m = re.search(r"memo nap (\d+)-(\d+)", out)
    return "%s-%s" % m.groups() if m else None


def offered(out):
    """The line offering a command. Every command handed to an agent must be
    an order, not a label: `Run: memo ...`, never `next: memo ...`."""
    return [l for l in out.splitlines() if "memo nap " in l or "memo wake " in l]


# the real entry point still has to work: shebang, argv parsing, exit code
smoke = subprocess.run(memo + ["wake"], env=dict(os.environ, MEMORY_DIR=d),
                       capture_output=True, text=True)
check(smoke.returncode == 0 and "No memories yet" in smoke.stdout,
      "the memo CLI does not run: " + smoke.stdout + smoke.stderr)

# a typo in MEMORY_DIR must not silently open a second, empty identity
ghost = subprocess.run(memo + ["wake"], capture_output=True, text=True,
                       env=dict(os.environ, MEMORY_DIR=d + "-typo"))
check(ghost.returncode == 1 and "No memory at" in ghost.stderr,
      "a missing MEMORY_DIR was created instead of reported")
check(not os.path.exists(d + "-typo"), "a missing MEMORY_DIR was created")

# the fresh-user path: no MEMORY_DIR, wake refuses, init creates the memory,
# prints the paste block, and is idempotent
fresh = {k: v for k, v in os.environ.items() if k != "MEMORY_DIR"}
fresh["HOME"] = tempfile.mkdtemp()
noenv = subprocess.run(memo + ["wake"], capture_output=True, text=True, env=fresh)
check(noenv.returncode == 1 and "memo init" in noenv.stderr,
      "with no MEMORY_DIR and no memory, wake must point at init")
init = subprocess.run(memo + ["init"], capture_output=True, text=True, env=fresh)
check(init.returncode == 0 and "## Memory" in init.stdout
      and "You are a" in init.stdout, "init must print the AGENTS.md block")
check("Never include a date or timestamp in memory text" in init.stdout,
      "init must keep date metadata out of memory text")
check(os.path.exists(os.path.join(fresh["HOME"], ".optmem", "memory", "config")),
      "init must create ~/.optmem/memory with its config")
again = subprocess.run(memo + ["init"], capture_output=True, text=True, env=fresh)
check(again.returncode == 0 and "Found" in again.stdout, "init must be idempotent")
woke = subprocess.run(memo + ["wake"], capture_output=True, text=True, env=fresh)
check(woke.returncode == 0 and "You are awake." in woke.stdout,
      "after init, wake must work with zero configuration")

# Every command the tool prints must RUN on the machine it printed it on.
# `curl | sh` puts nothing on PATH, so a bare `memo nap ...` would not: the
# whole loop (note -> merge prompt -> nap) dies on `command not found`.
bare = dict(fresh, PATH="/usr/bin:/bin")
subprocess.run(memo + ["note", "the first thing that happened"], env=bare,
               capture_output=True)
asked = subprocess.run(memo + ["note", "the second thing that happened"],
                       env=bare, capture_output=True, text=True)
order = [l[5:] for l in asked.stdout.splitlines() if l.startswith("Run: ")]
check(len(order) == 1, "note did not order a compression: " + asked.stdout)
obeyed = subprocess.run(order[0].replace('"<your line>"', '"both things"'),
                        shell=True, env=bare, capture_output=True, text=True)
check(obeyed.returncode == 0 and "saved" in obeyed.stdout,
      "the order the tool printed does not run with nothing on PATH: %r -> %s"
      % (order[0], obeyed.stderr.strip()))

# a size written by hand into `config` must not brick the tool with a
# recovery that is itself broken: name the file and the line
badcfg = os.path.join(fresh["HOME"], ".optmem", "memory", "config")
with open(badcfg, "a") as f:
    f.write("WAKE_LNES = 100\n")
for c in (["wake"], ["config"]):
    r_ = subprocess.run(memo + c, capture_output=True, text=True, env=fresh)
    check(r_.returncode == 1 and "config line" in r_.stderr
          and "WAKE_LNES" in r_.stderr,
          "a typo in config does not say where it is: " + r_.stderr)
open(badcfg, "w").write("")

# the filesystem is the one thing the tool does not control: report it in the
# tool's own voice, never as a Python traceback
r_ = subprocess.run(memo + ["init"], capture_output=True, text=True,
                    env=dict(fresh, MEMORY_DIR=MEMO))   # a file, not a store
check(r_.returncode == 1 and "Traceback" not in r_.stderr
      and "Not a directory" in r_.stderr,
      "a filesystem error printed a traceback: " + r_.stderr)


r = run("note", "x" * 281)
check(r.returncode == 1 and "Too long" in r.stderr, "over-long note accepted")
r = run("note", "two\nlines")
check(r.returncode == 1 and "one line" in r.stderr, "multi-line note accepted")
r = run("note", "   ")
check(r.returncode == 1, "empty note accepted")
r = run("wake")
check("No memories yet" in r.stdout, "empty wake should say so")
check(r.stdout.rstrip().endswith("You are awake."),
      "an empty wake must still end with `You are awake.`")

with open(os.path.join(d, "seed.txt"), "w") as f:
    day = datetime.date(2020, 1, 1)
    for i in range(N):
        f.write("%s memory number %d, a thing that happened, was weighed "
                "against the rest of the week, turned out to matter more than "
                "anyone guessed at the time, and left a mark on every plan "
                "that followed it\n"
                % ((day + datetime.timedelta(days=i // 5)).isoformat(), i))
r = run("import", os.path.join(d, "seed.txt"))
check("Imported %d" % N in r.stdout, "import failed: " + r.stdout + r.stderr)
check(not os.path.exists(os.path.join(d, "config")),
      "a store wrote its own config file: the defaults are now frozen in it")

r = run("wake")
check(r.returncode == 1 and "Cannot wake" in r.stdout,
      "wake must refuse while work is pending")
check("wake again" in r.stdout,
      "the refusal must order the agent back to wake")
check("None" not in r.stdout, "the refusal printed a Python None")

# nap loop, with a fake compressor
naps = 0
r = run("nap")
check("Compress memories #" in r.stdout, "nap prompt must name its object")
check("Never include a date or timestamp" in r.stdout,
      "nap prompt must keep date metadata out of summaries")
while "Nothing left to compress" not in r.stdout:
    line = offered(r.stdout)
    check(bool(line), "no command offered:\n" + r.stdout + r.stderr)
    if not line:
        break
    check(line[0].startswith("Run: "), "a command was offered as a label, not "
          "an order: %r" % line[0])
    bid = nap_id(r.stdout)
    body = [l.strip() for l in r.stdout.splitlines() if l.startswith("  #")]
    r = run("nap", bid, (" ".join(body)[:280]).strip() or "empty")
    check(r.returncode == 0, "nap rejected a valid merge: " + r.stderr)
    naps += 1
check("You are awake" not in r.stdout,
      "nap must never claim the agent is awake; only wake may")
check(naps == len(complete(N)), "did %d naps, expected %d" % (naps, len(complete(N))))

r = run("wake")
check(r.returncode == 0, "wake still refuses after a full nap chain")

# the document survives pagination, and every part fits every harness's cap
parts, k = [], 1
while True:
    r = run("wake", str(k))
    if r.returncode != 0:
        break
    body = [l for l in r.stdout.splitlines() if l.startswith("#")]
    check(len(r.stdout) < CAP_CHARS, "part %d is %d chars, over the %d cap"
          % (k, len(r.stdout), CAP_CHARS))
    check(len(r.stdout.splitlines()) < CAP_LINES, "part %d is over %d lines"
          % (k, CAP_LINES))
    parts.append(body)
    k += 1
check(len(parts) > 1, "a %d-line memory should need more than one part" % WAKE_LINES)
lines = [l for p in parts for l in p]
check(len(lines) == WAKE_LINES, "woke with %d lines, want %d" % (len(lines), WAKE_LINES))
check(lines[-1].startswith("#%d " % (N - 1)), "newest memory not last / not raw")
check(lines[0].startswith("#0-"), "oldest line should be a summary block")
check(re.search(r"Run: \S*memo wake 2", run("wake").stdout),
      "part 1 must ORDER the next command, not label it")
check("You are awake." in run("wake", str(len(parts))).stdout,
      "last part must say it is last")
check(run("wake", str(len(parts) + 1)).returncode == 1, "a nonexistent part should fail")

# append-only: nothing was ever rewritten
logsz = os.path.getsize(os.path.join(d, "LOG.txt"))
run("note", "one more thing happened today")
check(os.path.getsize(os.path.join(d, "LOG.txt")) > logsz, "note did not append")
check(logsz % 320 == 0, "LOG.txt is not a whole number of records")
for f in os.listdir(os.path.join(d, "TREE")):
    check(os.path.getsize(os.path.join(d, "TREE", f)) % 288 == 0,
          "TREE/%s is not a whole number of records" % f)

# a nap when nothing is pending writes nothing and says so
r = run("nap", "0-1", "attempted overwrite")
check(r.returncode == 0 and "Nothing left to compress" in r.stdout,
      "nap with nothing pending must say so and write nothing")

# recall reaches memories the summaries lost, and matches the whole line:
# id and date included, not just the text
r = run("recall", "memory number 7,")
check(r.returncode == 0 and "#7 " in r.stdout, "recall missed a memory")
check("1 match." in r.stdout, "a single match is not `1 matches`: " + r.stdout)
r = run("recall", "^#7 ")
check("memory number 7," in r.stdout, "recall cannot find a memory by id")
r = run("recall", "2020-01-02")
check("#7 " in r.stdout and "5 matches." in r.stdout,
      "recall cannot find memories by date: " + r.stdout)


# zoom: one tree node, opened into its two halves. The tool only reads;
# the agent is the navigator: it descends from a wake line by halving, and
# may leap to any block id it can name.
def halves(bid):
    r = run("zoom", bid)
    check(r.returncode == 0, "zoom %s failed: %s" % (bid, r.stderr))
    out = []
    for line in r.stdout.splitlines():
        m = re.match(r"#(\d+)(?:-(\d+))? ", line)
        check(bool(m), "zoom printed a line with no id: %r" % line)
        a = int(m.group(1))
        out.append((a, int(m.group(2)) + 1 if m.group(2) else a + 1))
    return out


target, lo, hi, calls = 777, 0, 1024, 0
while hi - lo > 1:
    mid = (lo + hi) // 2
    kids = halves("%d-%d" % (lo, hi - 1))
    check(kids == [(lo, mid), (mid, hi)],
          "zoom %d-%d is not its two halves: %r" % (lo, hi - 1, kids))
    lo, hi = kids[target >= mid]
    calls += 1
check(lo == target and calls == 10,
      "halving 1024 memories took %d calls and landed on #%d" % (calls, lo))
check("memory number %d," % target in run("zoom", "776-777").stdout,
      "the last zoom must print the raw memories themselves")

# the unbuilt tail is named, the empty future is omitted
r = run("zoom", "1024-2047")  # T is N+1, so the right half has no summary
check("#1536-2047 not compressed yet" in r.stdout,
      "an unbuilt half must say so: " + r.stdout)
r = run("zoom", "%d-%d" % (N, N + 1))  # the newest memory + one not yet made
check(r.stdout.count("\n") == 1 and "#%d " % N in r.stdout,
      "a half beyond the newest memory must be omitted: " + r.stdout)

# zoom answers with the tree's own records, so the id must BE a node
check(run("zoom", "3-9").returncode == 1, "zoom accepted a non-block")
check(run("zoom", "9-3").returncode == 1, "zoom accepted a backwards range")
check(run("zoom").returncode == 1, "zoom with no id must show usage")
r = run("zoom", "1048576-2097151")
check(r.returncode == 1 and "beyond the memory" in r.stderr
      and "memo wake" in r.stderr, "zoom past the end must name a way back")


def treesize():
    t = os.path.join(d, "TREE")
    return sum(os.path.getsize(os.path.join(t, f)) for f in os.listdir(t))

before, logsize = treesize(), os.path.getsize(os.path.join(d, "LOG.txt"))
r = run("forget", "16-31")
check("16-31" in r.stdout, "forget did not report the block: " + r.stdout + r.stderr)
check(treesize() < before, "forget did not shrink the tree")
check(os.path.getsize(os.path.join(d, "LOG.txt")) == logsize, "forget touched the log")
check(run("wake").returncode == 1, "wake should refuse after a forget")
# a settled block cannot be rewritten. Resubmitting one (two sessions paid
# the same nap) is not an error: say it is settled, write nothing
mid = treesize()
r = run("nap", "0-1", "attempted overwrite")
check(r.returncode == 0 and "already settled" in r.stdout,
      "resubmitting a settled block was not reported as settled: " + r.stderr)
check(treesize() == mid, "resubmitting a settled block wrote something")
# a block that is neither settled nor next (here: a dropped ancestor,
# submitted before its half is rebuilt) is a real mistake
r = run("nap", "0-31", "out of order")
check(r.returncode == 1 and "Wrong block" in r.stderr,
      "an out-of-order block was accepted")
n = 0
while True:
    r = run("nap")
    if "Nothing left to compress" in r.stdout:
        break
    bid = nap_id(r.stdout)
    check(run("nap", bid, "rebuilt after forget").returncode == 0, "rebuild rejected")
    n += 1
check(n > 0, "forget created no work")
check(run("wake").returncode == 0, "wake still refuses after rebuilding")
check(treesize() == before, "tree did not return to its original size")
check(run("forget", "17-32").returncode == 1, "forgetting a non-block should fail")
# a summary that is not built yet is named as such, never left blank
run("forget", "16-31")
z = run("zoom", "0-31").stdout
check("#16-31 not compressed yet" in z, "zoom hid a missing summary: " + z)
while True:
    bid = nap_id(run("nap").stdout)
    if not bid:
        break
    run("nap", bid, "rebuilt after forget")
check(treesize() == before, "tree did not return to its original size")
check(run("forget", "1048576-1048577").returncode == 1, "forgetting a missing block should fail")

# UTF-8: multi-byte characters must not shift record boundaries or dodge limits
run("note", "reunião com João em São Paulo: ação aprovada, coração tranquilo")
run("note", "a plain ascii memory right after the accented one")
r = run("recall", "coração")
check("João" in r.stdout, "recall lost the accented memory: " + r.stdout + r.stderr)
r = run("recall", "plain ascii memory right after")
check("#%d " % (N + 2) in r.stdout, "record after a multi-byte one reads shifted")
r = run("note", "ã" * 150)
check(r.returncode == 1 and "300 bytes" in r.stderr,
      "multi-byte note dodged the byte limit: " + r.stderr)

# note landed -> its blocks are pending; settle before the final wake check
while True:
    r = run("nap")
    if "Nothing left to compress" in r.stdout:
        break
    bid = nap_id(r.stdout)
    run("nap", bid, "settled")
check(run("wake").returncode == 0, "wake refuses at the very end")

# a part is rendered as of T, so a note landing mid-wake cannot shift a
# boundary and silently drop a line
T0 = os.path.getsize(os.path.join(d, "LOG.txt")) // 320
before = run("wake", "1", str(T0))
check(before.returncode == 0, "as-of-T wake failed: " + before.stdout + before.stderr)
run("note", "a note that lands between two wake calls")
check(run("wake", "1", str(T0)).stdout == before.stdout,
      "a note between parts changed an already-rendered part")
check(run("wake", "1", str(T0 + 99)).returncode == 1, "wake accepted a future T")

# ...and the agent pays that note's compressions on the spot, as it is told
# to. The tree then holds MORE blocks than the snapshot needs: a level must
# never count as negative work, or the rest of the wake is refused with an
# impossible number.
while True:
    r = run("nap")
    if "Nothing left to compress" in r.stdout:
        break
    run("nap", nap_id(r.stdout), "settled mid-wake")
r = run("wake", "1", str(T0))
check(r.returncode == 0 and r.stdout == before.stdout,
      "a compression paid mid-wake broke the rest of the wake:\n"
      + r.stdout + r.stderr)
for T in list(range(1, 40)) + [T0 - 1, T0, T0 + 1]:
    check(cli.pending_count(d, T) == len(cli.pending(d, T)),
          "pending_count disagrees with pending at T=%d" % T)

# recall must not hand back more than a harness will carry
r = run("recall", "memory number")
check(len(r.stdout) < CAP_CHARS, "recall returned %d chars" % len(r.stdout))
check("Narrow the regex" in r.stdout, "recall did not say it had been capped")

# ---- concurrency and crash recovery ----------------------------------

d2 = tempfile.mkdtemp(prefix="optmem-race-")
env2 = dict(os.environ, MEMORY_DIR=d2)
P = 16  # real processes: this is the cross-process lock under test
procs = [subprocess.Popen(memo + ["note", "parallel note %d" % i], env=env2,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
         for i in range(P)]
for p in procs:
    p.wait()
with open(os.path.join(d2, "LOG.txt"), "rb") as f:
    recs = [f.read(320) for _ in range(P)]
ids = [r.decode().split()[0] for r in recs if r.strip()]
check(len(ids) == P, "%d of %d parallel notes survived" % (len(ids), P))
check(len(set(ids)) == P, "parallel notes collided on an id: %s" % sorted(ids))
check(sorted(ids) == sorted("#%d" % i for i in range(P)),
      "parallel note ids are not 0..%d: %s" % (P - 1, sorted(ids)))

# a crash mid-append leaves a partial record; the next append must drop it,
# or every later record is misaligned forever
with open(os.path.join(d2, "LOG.txt"), "ab") as f:
    f.write(b"#99 2026-01-01 a half-written record killed by a power cut")
r = run("note", "the memory right after a torn write", store=d2)
check(r.returncode == 0, "note failed after a torn write: " + r.stderr)
sz = os.path.getsize(os.path.join(d2, "LOG.txt"))
check(sz % 320 == 0, "LOG.txt left misaligned after a torn write: %d" % sz)
check("Saved as #%d" % P in r.stdout, "torn record was counted as a memory")
r = run("recall", "right after a torn write", store=d2)
check("#%d " % P in r.stdout, "the memory after a torn write reads wrong")

# a memory small enough to fit one part must still end with the terminator
# the agent was told to wait for
while True:
    r = run("nap", store=d2)
    if "Nothing left to compress" in r.stdout:
        break
    bid = nap_id(r.stdout)
    run("nap", bid, "settled", store=d2)
r = run("wake", store=d2)
check(r.stdout.rstrip().endswith("You are awake."),
      "a one-part wake never says `You are awake.`:\n" + r.stdout)

# a blank summary record (a corrupt write) is work nap cannot see: wake must
# name the one exit, `forget`, instead of refusing forever
d3 = tempfile.mkdtemp(prefix="optmem-blank-")
for i in range(4):
    run("note", "corrupt store memory %d" % i, store=d3)
for bid, s in (("0-1", "one"), ("2-3", "two"), ("0-3", "all")):
    run("nap", bid, s, store=d3)
with open(os.path.join(d3, "config"), "w") as f:
    f.write("WAKE_LINES = 2\n")
with open(os.path.join(d3, "TREE", "2"), "r+b") as f:
    f.write(b" " * 287 + b"\n")
r = run("wake", store=d3)
check(r.returncode == 1 and "forget 0-1" in r.stderr
      and "None" not in r.stdout,
      "a blank summary must point at forget:\n" + r.stdout + r.stderr)

# an unreadable level is a filesystem failure and must surface as one --
# reading it as "not compressed yet" offers work that cannot be done
os.chmod(os.path.join(d3, "TREE", "2"), 0)
r_ = subprocess.run(memo + ["wake"], capture_output=True, text=True,
                    env=dict(os.environ, MEMORY_DIR=d3))
check(r_.returncode == 1 and "Permission denied" in r_.stderr
      and "not compressed" not in r_.stdout,
      "an unreadable level was read as pending work: " + r_.stdout + r_.stderr)
os.chmod(os.path.join(d3, "TREE", "2"), 0o644)

# an impossible calendar date would poison every later import: the store's
# order check compares against it forever
with open(os.path.join(d3, "bad.txt"), "w") as f:
    f.write("2027-99-99 an impossible date\n")
r = run("import", os.path.join(d3, "bad.txt"), store=d3)
check(r.returncode == 1 and "not a real date" in r.stderr,
      "import accepted an impossible date: " + r.stdout + r.stderr)
shutil.rmtree(d3)

# the same blank-record dead end at the other site: a big block's half
d4 = tempfile.mkdtemp(prefix="optmem-half-")
for i in range(32):
    run("note", "half probe memory %d" % i, store=d4)
while True:
    r = run("nap", store=d4)
    if "Compress memories #0-31 " in r.stdout:
        break
    run("nap", nap_id(r.stdout), "settled", store=d4)
with open(os.path.join(d4, "TREE", "16"), "r+b") as f:
    f.write(b" " * 287 + b"\n")
r = run("nap", store=d4)
check(r.returncode == 1 and "forget 0-15" in r.stderr,
      "a blank half summary must point at forget: " + r.stdout + r.stderr)
shutil.rmtree(d4)

# the store is UTF-8 whatever the locale says: without pinning the streams,
# one arrow in a memory made wake crash forever on a latin-1 machine
d5 = tempfile.mkdtemp(prefix="optmem-utf8-")
run("note", "an arrow \u2192 survives any locale", store=d5)
r_ = subprocess.run(memo + ["wake"], capture_output=True,
                    env=dict(os.environ, MEMORY_DIR=d5,
                             PYTHONIOENCODING="latin-1"))
check(r_.returncode == 0 and "\u2192".encode() in r_.stdout,
      "wake must print UTF-8 on a non-UTF-8 locale: "
      + repr(r_.stdout + r_.stderr))

# an import file that is not UTF-8 is refused -- neither a traceback nor,
# worse, silently mis-decoded into mojibake and stored forever
with open(os.path.join(d5, "latin1.txt"), "wb") as f:
    f.write(b"2027-01-01 caf\xe9 in latin-1\n")
r = run("import", os.path.join(d5, "latin1.txt"), store=d5)
check(r.returncode == 1 and "not UTF-8" in r.stderr,
      "a non-UTF-8 import file must be refused: " + r.stdout + r.stderr)

# a summary record holding invalid UTF-8 is the blank-record dead end in
# another coat: it must name forget, not print a traceback
run("note", "utf8 probe second memory", store=d5)
run("nap", "0-1", "both utf8 probes", store=d5)
with open(os.path.join(d5, "TREE", "2"), "r+b") as f:
    f.write(b"\xff\xfe corrupt bytes")
r = run("zoom", "0-3", store=d5)
check(r.returncode == 1 and "forget 0-1" in r.stderr,
      "a corrupt summary must point at forget: " + r.stdout + r.stderr)
shutil.rmtree(d5)

# re-running init on a lived-in store must not touch one byte of it: the
# whole setup is idempotent, so it is safe on every provision. `init` only
# ever makedirs(exist_ok), opens LOG.txt for APPEND, and writes `config`
# when absent -- never truncating, never overwriting a tuned config.
def fingerprint(path):
    out = {}
    for root, _, files in os.walk(path):
        for f in files:
            if f == ".lock":
                continue
            p = os.path.join(root, f)
            out[os.path.relpath(p, path)] = open(p, "rb").read()
    return out


# `memo config` is how a size is changed: it writes the file the tool reads
# back, an empty value restores the default, and a wake obeys immediately --
# nothing is recomputed, because a size only selects what gets printed.
r = run("config", "WAKE_LINES=12")
check("12" in r.stdout and "default 96" in r.stdout, "config did not set:\n" + r.stdout)
check(len(run("wake").stdout.splitlines()) <= 13, "wake ignored the new size")
r = run("config", "WAKE_LINES=")
check("default" not in r.stdout, "an empty value did not restore the default")
check(len(run("wake").stdout.splitlines()) > 13, "the default did not come back")
for bad in ("WAKE_LINES=0", "WAKE_LINES=x", "ENTRY_CHARS=999", "NOPE=1", "WAKE_LINES"):
    check(run("config", bad).returncode == 1, "config accepted %s" % bad)

with open(os.path.join(d, "config"), "a") as f:
    f.write("WAKE_LINES=12\n")           # a size the user tuned by hand
before = fingerprint(d)
check(len(before) > 3 and before["LOG.txt"], "the store under test is empty")
for _ in range(3):
    r = run("init")
    check(r.returncode == 0 and "Found" in r.stdout, "init on a live store failed")
check(fingerprint(d) == before, "init modified an existing memory")
r = run("wake")
check(r.stdout.rstrip().endswith("You are awake."), "wake broke after re-init")

shutil.rmtree(d2)
shutil.rmtree(d)
print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
