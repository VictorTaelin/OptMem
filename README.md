# OptMem

Permanent memory for AI agents. A 586-token prompt, a script, plug and play.

![how OptMem works](anim/optmem.gif)

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/VictorTaelin/OptMem/main/install.sh | sh
```

It prints a `## Memory` block. Paste that at the top of your agent's
`AGENTS.md` (or `CLAUDE.md`), and you are done. Run the same line again to
update.

The tool lands at `~/.optmem/memo`; put `~/.optmem` on `PATH` to type `memo`.
The installer replaces it only with a download that is Python, so a Wi-Fi
sign-in page cannot take its place.

To pin a tag or a commit, and check the tool against the sha256 of its
`memo` (`shasum -a 256 memo` in a clone at that ref):

```sh
curl -fsSL https://raw.githubusercontent.com/VictorTaelin/OptMem/<ref>/install.sh |
  OPTMEM_REF=<ref> OPTMEM_SHA256=<sha256 of memo> sh
```

## Commands

| | |
|---|---|
| `memo wake` | read the memory — the first command of every session |
| `memo note - <<'MEMO'` | record one memory from stdin: one line of plain text, up to 280 bytes |
| `memo nap` | answer the merges that came due |
| `memo wake --brief <topic>` | the same, plus the memories that best match a topic |
| `memo find <words>` | rank every memory and summary by those words (BM25), ignoring case and accents; the exact word ranks above another form of it |
| `memo recall <regex>` | search every memory ever recorded, word for word (a pattern that backtracks is stopped after 5 s) |
| `memo brief <topic>` | a topic's best memories, newest first, in `BRIEF_BYTES` (its header included) |
| `memo zoom <lo>-<hi>` | open a tree node into its two halves |
| `memo forget <lo>-<hi>` | drop a bad summary; the next nap rebuilds it |
| `memo check` | read the whole store and report any record out of place; writes nothing |

Merges arrive one at a time, in the output of `note`. Nothing ever runs in the
background.

A memory is permanent, so `note`, `nap` and `import` refuse what must never be
kept: a second line (any line break Python knows, not just `\n`), a control
character, an invisible character (bidi overrides, zero-width spaces, tag
characters), or a string shaped like a credential (API keys, tokens, private
keys, webhook URLs, a password written into a URL). Record where a secret
lives, never its value.

`note` and `nap` take their line as an argument or, given `-`, from stdin, and
every order `memo` prints uses a quoted heredoc. Memories quote commands, and
a shell expands `` `...` ``, `$(...)` and `$VAR` inside double quotes: a line
retyped from them would run code or lose words. `<<'MEMO'` expands nothing.

## Files

```
~/.optmem/
  memo          the tool: one file of Python 3, no dependencies
  memory/
    LOG.txt     every memory, one per line, append-only, never edited
    TREE/       the summaries: a cache, rebuildable from the log alone
    config      the sizes, written by `memo config`
```

```sh
memo config                  # show the sizes
memo config WAKE_LINES=300   # how many lines wake prints (96 ≈ 8k tokens)
memo config WAKE_LINES=      # back to the default
memo config WAKE_BYTES=9500  # cap wake's output in bytes (0 = no cap)
memo config BRIEF_BYTES=2500 # most bytes a topic brief takes (0 = none)
```

`WAKE_LINES`, `WAKE_BYTES` and `BRIEF_BYTES` are reading budgets, not storage
budgets: change them whenever, in either direction, and nothing is recomputed. An older `memo`
refuses a `config` that sets `WAKE_BYTES` or `BRIEF_BYTES`; on a store it
shares, leave those at their defaults.

### Waking from a startup hook

A hook prints once and is cut in place. Claude Code (verified on 2.1.276)
keeps 10,000 characters of a hook's `additionalContext`; anything longer is
saved to a file and the agent gets its path and a 2 KB preview, so a 96-line
wake silently arrives as a few lines. Set `WAKE_BYTES` below the cap and wake
fits itself: it prints the finest memory, up to `WAKE_LINES` lines, that fits
in one part. A summary nobody has compressed yet
is shown as its halves, down to the raw memories, so a backlog of naps costs
bytes rather than the whole wake. When a pending compression does not fit
beside the memory, one line points at `memo nap` instead. A UTF-8 byte is never
fewer than one character, so a byte cap is also a character cap.

```sh
memo config WAKE_BYTES=9500   # leaves room for the hook's own preamble
```

```json
{"hooks": {"SessionStart": [{"matcher": "startup|clear|compact", "hooks": [{"type": "command",
  "command": "~/.optmem/memo wake --brief \"$(basename \"$(git rev-parse --show-toplevel 2>/dev/null || pwd)\")\" 2>&1 | jq -Rs '{hookSpecificOutput: {hookEventName: \"SessionStart\", additionalContext: .}}'"}]}]}}
```

`2>&1` hands an error to the agent as well: Claude Code sends a hook's
stderr to its debug log, where the agent never sees it. The matcher
includes `compact` because compaction drops the wake from context:
Claude Code fires `SessionStart` again after a compaction, and `compact` is the
documented matcher for it. `--brief`
names the repository the session starts in, so a project you left months ago
wakes with its own memories. The brief shares `WAKE_BYTES`: the memory gives
up at most `BRIEF_BYTES`, never more than half the cap, and keeps all of it
when it cannot shrink that far (many pending naps). A topic with no match
changes nothing.

Records are fixed width, so position *is* identity and every lookup is one
seek. At a million memories (608 MB), `wake` takes 0.03s.

Everything `memo` creates is readable by its owner only (umask 077). A store
made by an older version keeps its modes; tighten it once with
`chmod -R go-rwx ~/.optmem`. Every command refuses a store another user
owns or every user can write, since whoever writes it steers the agent that
wakes from it; group write is allowed, for the Linux accounts whose group is
their own. On Windows the umask sets no ACLs and the check does not run:
see [WINDOWS.md](WINDOWS.md).

Set `$MEMORY_DIR` to keep `memory/` elsewhere — a synced folder, a git repo.

### What OptMem is not

No hook captures every message, no server runs, no embeddings are computed:
the agent decides what is worth a line, and that line is all there is.
Retrieval is `recall` (a regex) and `find` (BM25 over the words), both
computed on the spot from the files. The log is never edited, so a bad
summary loses nothing: `forget` it and `nap` builds it again from the log.

## The prompt

This is what the installer prints, and the whole of the integration.

```markdown
## Memory

Your memory is OptMem:
- The tool is `~/.optmem/memo`
- Your memories are in `~/.optmem/memory`

OptMem outlives every session, compaction, model and vendor change.
Without it you do not know who you are, or what was decided and tried.

### At startup: activating OptMem (mandatory)

Run `~/.optmem/memo wake` before any other tool call, in every session, and
then do exactly what it prints, to the end of its output.

### While working: register memories (mandatory)

Call `~/.optmem/memo note` when you learn what will still matter next month:
a decision and why, a correction the user made, a fact about the user,
their life or their tools, how a thing actually works. Do not note status
(pushed, merged, PR or commit ids), only the fact behind it. Hand it the
memory (1 line, max 280 bytes) exactly like this, so your shell expands
nothing in it:

~~~sh
~/.optmem/memo note - <<'MEMO'
<your line>
MEMO
~~~

Do not repeat a memory. When a fact changes, note the new one and say
which memory it supersedes. Before a long task ends, and before context
is compacted, note what was decided.

If `~/.optmem/memo note` asks a compression: do it before your next action.

Never edit or delete anything under `~/.optmem/memory`: the tool manages it.

### When you need an old memory: search, or navigate

`~/.optmem/memo find <words>` ranks every memory by those words, ignoring case
and accents: run it before you say you do not know.
`~/.optmem/memo recall <regex>` matches exact text.
`~/.optmem/memo brief <topic>` gathers one project's memories.

Every `#a-b` line wake prints is one node of a binary tree of summaries.
`~/.optmem/memo zoom <a-b>` opens it into its two halves, down to the raw memories.

### If you're a subagent: skip everything above

Parallel sessions on this machine are all you, and may all write memories.
A subagent is not: it must never run `memo`, because it cannot judge what
is already known, and its notes would arrive duplicated and incorrectly.
When you spawn one, write: `You are a subagent. Don't run memo.`
```
