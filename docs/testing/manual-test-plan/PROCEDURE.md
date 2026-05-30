# How to test

The working procedure for running through this plan. Read [ONBOARDING.md](ONBOARDING.md) first if you haven't.

---

## The loop, per case

Inside each suite file is a series of numbered test cases. For each one:

1. **Read the whole case first.** Note its **Customer value**, **Priority**, and **Pre**.
2. **Set up the Pre.** Get the system into the state the case expects (logged in, a project exists, on a paid tier, etc.).
3. **Run the Scenario** as a real user would. Don't shortcut. Click the buttons, type the prompts, wait for things to finish.
4. **Compare against What good looks like and Watch for.**
5. **Mark the Result line:** `[x] Pass`, `[x] Fail`, or `[x] Blocked`.
6. **Fill Notes** - always for Fail / Blocked, and any time something surprised you on a Pass.
7. **File a bug if it failed** (see below) and put the bug ID in Notes.

A case **passes only if every "What good looks like" point holds**. Slow, confusing, or ugly counts as Fail.

Critical cases get extra attention - those are the value loop. If a Critical case fails or blocks, message your point of contact, don't just keep going silently.

---

## Filing a bug

Use the template in [README Appendix A](README.md#appendix-a---bug-report-template):

```
Title:        [Suite/Area] Short description
Test case:    e.g. AGENT-B3
Severity:     S1 / S2 / S3 / S4
Environment:  URL, mode (Cloud/Docker/Desktop), browser + version, OS
Account:      Which test account
Preconditions:What state existed before
Steps to reproduce:
  1.
  2.
Expected:
Actual:
Evidence:     Screenshots / recording / console + network trace
Frequency:    Always / Intermittent (X of Y) / Once
Notes:
```

Rules:

- **One bug per report.** Don't combine.
- **File immediately.** Don't batch. The cost is filing it twice; the risk of batching is forgetting details.
- **Put the bug ID in the case's Notes** so the case <-> bug link is preserved.
- **Always include console + network evidence** for errors - even if the UI looks fine, the network tab usually tells you the real story.
- **Reproduce intermittents.** If it didn't repro a second time, file it anyway with Frequency `Intermittent (X of Y)`. Intermittent defects are still defects.

**Severity quick reference:**

- **S1 Blocker** - crash, data loss, or a Critical case completely broken. Tell your point of contact immediately.
- **S2 Major** - feature broken with no reasonable workaround.
- **S3 Minor** - works but wrong or awkward; a workaround exists.
- **S4 Trivial** - cosmetic, copy, alignment, console noise.

---

## When a fix lands

If you're told a fix is on the build:

1. Re-run only the case that failed.
2. If it passes - change the Result to `[x] Pass`, update Notes ("verified on build <id>"), close the bug.
3. If it still fails - re-open the bug with new observations.
4. Also re-run any case that was **Blocked** by the now-fixed defect.

Don't expand scope. The fix changed one thing; verify that one thing.

---

## Finishing a suite

Each suite file ends with a small roll-up table. Fill it in:

- Cases passed / failed / blocked / not run
- IDs of bugs you opened
- Anything the next reader should know (env quirks you hit, accounts you used)

Hand the completed file back the way the team set up (commit, send the file, copy results into a doc - your point of contact will tell you).

---

## Practical tips

- **Test as a customer, not a developer.** You're someone trying to build a real app, not someone probing endpoints. If a prompt doesn't make sense to a normal person, that's the bug.
- **Keep DevTools open the whole time.** Network + Console. Errors there matter even when the UI looks clean.
- **Watch the timing.** Long pauses, hangs, "is it doing something?" moments are defects. Note them.
- **Don't fight the product.** If you can't figure out how to do the thing without reading the source code, a customer can't either. That's a Fail.
- **One environment, one build, one session per case.** Don't mix - it muddles results.
- **Save evidence as you go.** Screenshots / recordings are cheap to take, painful to recreate later.

That's the whole loop. Go open your suite.
