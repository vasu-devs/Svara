# Wispr Flow comparison and Svara implementation

Reviewed 2026-09-06 using Wispr's official product and help pages. This is a
behavioral comparison, not a claim of matching its proprietary models or quality.

## Implemented in this pass

| Capability | Svara behavior | Implementation |
| --- | --- | --- |
| Exact snippets | Longest matching trigger wins; expansions keep their original whitespace, code and wording. Rules never recursively rewrite an expansion. Standalone triggers tolerate a final transcription period. | `pipeline/personal.py` |
| Writing presets | Auto, Formal, Casual, Very casual and Excited. English casing and final punctuation, with per-app and chat/default overrides. No model required. | `pipeline/writing_style.py`, Writing settings |
| Spoken developer formatting | Explicit camelCase, snake_case, PascalCase, kebab-case, CONSTANT_CASE and filenames/paths. Requires explicit closing phrases; no document scanning or command execution. | `pipeline/developer.py`, Writing settings |
| Numeric lists | Three or more consecutive numbered items become separate lines, including shopping-list introductions. Decimal versions, incomplete sequences and quoted examples remain unchanged. Medium/High cleanup; suppressed in terminals. | `pipeline/lists.py` |
| Correct delivery | Styles, snippets, punctuation and developer syntax use final insertion so live typing cannot bypass the pipeline. | `CleanupPipeline.requires_final_cleanup` |

The presets are inspired by Flow's distinction between formatting and rewriting:
its [personalized styles](https://wisprflow.ai/post/personalized-style) adjust
capitalization, punctuation and spacing. Svara's initial implementation formats
the first letter and final mark rather than performing arbitrary grammar edits.
Saved-text fidelity follows the intended behavior of
[voice snippets](https://docs.wisprflow.ai/articles/5784437944-create-and-use-snippets).

## Existing capabilities and remaining gaps

The [official feature overview](https://wisprflow.ai/features) covers dictation,
cleanup, personalization, team features and developer support. Svara already has
these local equivalents:

| Area | Current Svara support | Limit |
| --- | --- | --- |
| Filler removal and corrections | Offline explicit repairs, preview captions, optional local AI refinement | Rules are conservative English patterns; general semantic quality depends on the configured model |
| Language support | Whisper model/language selection, locale typography, optional Hindi romanization | Model-dependent; no claim of identical language coverage or accuracy |
| Dictionary and snippets | Manual entries, recognition hotwords, replacements, CSV import/export | Automatic learning is opt-in and suggestions require acceptance |
| Context | Focused app, title hotwords, optional caret text, per-app tone hints | No new screen-reading permissions enabled |
| Text transforms | Nine custom slots, writing samples, selected-text rewrites, diff preview, command mode | Requires a ready local LLM for generative rewrites |
| Notes and history | Local scratchpad, search, recovery, meeting capture/summary | Meeting quality and diarization were not assessed in this pass |
| Quiet dictation | Existing gain-based whisper mode | Hardware and noise-dependent |

Flow's [Transforms](https://docs.wisprflow.ai/articles/8068950331-how-to-use-transforms-beta)
are comparable in purpose to Svara's existing transform slots; those were not
reimplemented. Its [file tagging](https://docs.wisprflow.ai/articles/9805771321-file-tagging)
commits native IDE attachments. Svara's new filename formatter **only inserts
text**. Native attachment selection and live IDE symbol recognition remain gaps.

Mobile/macOS apps, built-in cross-device sync, organization usage dashboards and
account administration are not implemented. They require separate platform and
service work. Portable vocabulary libraries and personal usage insights are now
implemented below; these are not a managed team service. No file indexing or model
download was added.

## Product additions: portable vocabulary and local insights

- **Portable libraries:** Dictionary → Export creates a versioned JSON file with
  personal words, replacements and multiline snippets. Import reports duplicates
  and conflicts and keeps existing personal entries. CSV remains available.
- **Read-only shared libraries:** `dictionary.libraries` names up to 16 files to
  read on startup/reload. Personal entries win, then libraries in listed order.
  A team may distribute a library or put it in a separately synchronized folder;
  Svara does not create accounts, upload it, or manage synchronization.
- **History insights:** the History window shows retained dictations, word counts,
  active days and top apps over 30 UTC calendar days, plus a daily activity chart.
  Tab to the chart and use arrows, or hover to inspect a day. F5 refreshes it.
- **Lossless history export:** History → Export writes retained entries as JSON,
  including timestamps, source apps, entry kinds and exact text. It streams rows
  into a temporary file and replaces the destination only after success.
- **Retention repair:** expiration applies during reads and exports as well as
  pruning. An old entry cannot reappear in search, last-dictation recovery or
  insights just because Svara has been running for a long time.
- **Literal search:** `%` and `_` are searched as characters rather than SQL
  wildcards, making technical snippets easier to find.

Library imports validate format/version, types, entry counts and size before
merging anything. A broken shared file leaves personal vocabulary usable.
Libraries contain vocabulary data only, not model settings, prompts or history.
An individual library is limited to 2,000 entries and 3 MB. Relative library paths
resolve from Svara's data directory. Reload dictionary to see external edits.

```yaml
dictionary:
  libraries:
    - "E:/Shared/Svara/team.svara-library.json"
```

Personal insights derive from the existing retained history, without a separate
telemetry database. Disabling history gives empty insights. Clearing history also
clears its statistics. Word counts use whitespace separation, not a claim about
typing time saved or language-independent word segmentation.

Validation for this addition: **175 targeted headless tests passed**. Database,
retention, import/export, corruption and failure checks used temporary fixtures.
UI code was syntax-checked; the activity chart has not been visually validated.

## Try the source features

Writing settings now expose **Writing style** and **Developer voice syntax**.
The developer option is off until enabled. These source changes are not yet a
published or installed executable.

```yaml
cleanup:
  developer_syntax: true
context:
  writing_style: auto
  formatting_styles:
    chat: casual
    outlook.exe: formal
    notepad.exe: formal
```

- “Use snake case user account end name” → `Use user_account`
- “Create constant case max retries end name” → `Create MAX_RETRIES`
- “Open file name src slash main dot py end file” → `Open src/main.py`
- “Groceries: 1. apples 2. bananas 3. oranges” → three numbered lines (Medium/High)

These explicit commands format the words supplied. They do not infer filenames
from your project, execute terminal commands or alter existing document text.
For immediate live typing, use plain Light cleanup with corrections, syntax,
writing presets and text dictionary expansions disabled. Rich formatting inserts
once at the end of the recording.

## Verification

Headless tests cover exact snippets, overlapping replacements, literal code and
URLs, preset selection and precedence, list false positives, developer syntax,
pipeline ordering, delivery requirements and existing cleanup/privacy behavior.
Settings source is syntax-checked without opening it. No Svara launch, simulated
global hotkey, desktop UI test or installed-app restart was used for this pass.
