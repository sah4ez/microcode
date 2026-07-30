# What Loki built for you

Here is what Loki built and how to take it from here, in plain language - no code reading required.

## What you have now

You asked Loki to build this:

> Create exactly one file src/hello.txt containing the text GLM_LIVE_OK. Nothing else.

No file changes were recorded for this run.

## Is it working?

Not fully verified. Loki's honest verdict for this run is: NOT VERIFIED

In plain terms: Loki could not confirm this build works. Treat it as unfinished until the gaps below are resolved.

This means Loki is NOT telling you it is ready to ship. Here is what was not verified:

- execution - failed; exit_code=20
- tests - not_run; no test command recorded
- build - not_run; build not run
- git.diff - not_run; no file changes detected

This describes the last build Loki finished. If the code changed since then, this verdict is about the older version.
To confirm it still matches your current code, run: `loki proof verify run-20260729193712-14942-6392`

## How to run it on your computer

First, install it:

```
No installation required. The project consists only of a shell script and a text file.
```

To start it:

```
Execute the run script:

./run.sh
```

To check it works:

```
Run the script directly:

./run.sh

Expected output:
GLM_LIVE_OK

Alternatively, inspect the source file directly:

cat src/hello.txt

Expected output:
GLM_LIVE_OK
```

## How to put it online

This build has not been put online yet.

When you are ready, you have two options:

- `loki deploy` - deploy it using your own cloud account.
- `loki preview --public` - share a temporary public link to the version running on your computer.

## What a developer needs to know

No changed-file list was recorded for this run.

A developer should read USAGE.md (run/verify commands) and the developer handoff notes in .loki/memory/handoffs/.

## What is verified

Loki keeps a tamper-evident receipt of exactly what it did. Anyone can inspect or re-check it:

- `loki proof show run-20260729193712-14942-6392` - read the full receipt.
- `loki proof verify run-20260729193712-14942-6392` - confirm the receipt has not been altered.

## What you still need to do or decide

Work through these in order:

1. Review 24 assumptions Loki had to make where your spec was ambiguous (7 of them high-impact). See .loki/assumptions/ledger.md.
2. Address: execution (exit_code=20)
3. Address: tests (no test command recorded)
4. Address: build (build not run)
5. Address: git.diff (no file changes detected)
6. No pull request was opened. Open one when you are ready to merge the changes.
7. It is not deployed yet. Use `loki deploy` when you are ready.

