## Kiro Explain Discipline

Re-read `/qexplain-change` SKILL.md in full before you write the first content file: context pressure degrades recall of the Brief's fixed sections and of the rules below.

### On Step 1: Measure, then read

A diff dump is not the file. Before you write any content file, open every changed production file the measuring script still shows, at its path in the repository, with the file-read tool. For a file too long to read whole, read every changed function whole. Then open at least one caller and one test of each behaviour you explain. In the `verified` section, list the files you read in full and the files you read only in part or only as a diff. Never write "read in full" for a file you opened only as a diff.

### On `CREDENTIAL` lines

Never quote or paraphrase the value of a `CREDENTIAL` match: not in a content file, not in the chat, not in a report. Never write that such a value is made up, a fixture or not live. Say that a match was masked, give its path and line, and leave the judgement to the user. The build refuses a content file that holds the value.

### On Step 4: Validate

A page is checked only when the browser check ends with `RESULT COMPLETE` and 0 `BAD`. On `RESULT INCOMPLETE`, or on a `BAD` line you cannot clear by changing your own content files, do not run the same command again hoping for another result, and do not name a cause you have not observed. Report the page as built and **not visually confirmed**, quote the `RESULT` line and every `BAD` line, and stop. Open the Brief's screenshot and one map's screenshot before you report.

### On the Brief's `verified` section

Copy each figure with the name its source gives it. Do not turn "accepted by the user" into "fixed", or a result recorded on another page into a result on this page. When several plans meet in the range, give each plan one sentence on what it contributed to this range; a plan named only as precedent is not covered.

### On the page's language and on screenshots

- State the page's language to the user before you write, even when the project's rules say documents keep the project's language: this page follows the conversation.
- Before any screenshot, look for the repo's procedure (`docs/howtos/index.md`) and follow it step by step, cleanup included.
- Never write about a screen you did not capture. If a capture failed, say so in `verified`.

### On replies to comments

- Copy each comment id from its `Id:` line, character for character. Never write an id from memory or from the comment's number.
- When the build prints a WARN that a reply was not added, say so in your report. Do not run the build again with the same file.
