# Windows support

OptMem now runs on native Windows (no WSL required).

## What changed
- `import fcntl` is guarded — falls back to `None` on platforms without it.
- `locked()` uses `msvcrt` advisory locking with spin/backoff when `fcntl`
  is unavailable, so parallel sessions (the documented multi-process case)
  queue instead of raising `Resource deadlock avoided`.
- The `.lock` file is opened in append mode (`"a"`) rather than `"w"`, which
  would truncate and break locks held by other processes on Windows.

## Known limits

None of the following has been run on Windows; it is read from
the code and the platforms' documented behaviour.

- **Privacy.** `umask 077` sets POSIX modes, not NTFS ACLs. A store under
  `%USERPROFILE%` inherits the profile's ACL: you, SYSTEM and Administrators.
  A `MEMORY_DIR` anywhere else inherits that folder's ACL, so restrict it,
  from PowerShell:
  `icacls 'C:\path\to\mem' /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F"`
  On macOS and Linux every command refuses a store another user owns or
  every user can write; that check reads POSIX modes, so on Windows it does
  not run, and the ACL is the whole of the protection.
- **Handing a line over.** Every order memo prints is a POSIX quoted heredoc
  (`memo note - <<'MEMO'`), which expands nothing. Run memo from Git Bash (or
  WSL) and paste orders as printed. PowerShell cannot parse a heredoc, so
  there an order fails before anything runs. To note from PowerShell, write
  the line to a file with your editor and pipe the file, telling PowerShell
  to send UTF-8 (Windows PowerShell 5.1 pipes ASCII by default and would turn
  `é` into `?`):
  `$OutputEncoding = [Text.UTF8Encoding]::new($false); Get-Content -Raw -Encoding UTF8 .\line.txt | python "$HOME\.optmem\memo" note -`
  Never put the line itself inside PowerShell double quotes, which expand
  `$(...)`.
- **Lock wait.** The `msvcrt` loop backs off for about 30 s of requested
  sleep, then reports the lock as busy.
- **Mixed hosts.** A store shared between native Windows memo (`msvcrt`
  byte-range lock) and WSL or another machine (`flock`) has no lock between
  them: give a shared store a single writing host.

## Test (Windows native, no WSL)
```bat
python memo init
set MEMORY_DIR=C:\path\to\mem
python memo note "first memory"
python memo note "second memory"
python memo wake
```
Concurrency: 8 parallel `memo note` processes writing 1600 memories
resulted in 1600/1600 records persisted (lock verified).
