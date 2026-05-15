# Tutsan Media Relink Design

Date: 2026-05-16

## Goal

Safely repair the media-path problem for the Tutsan section of the open REAPER project without disturbing media that already works elsewhere in the project.

The problem is that some recordings were written into the project root, `/Volumes/Project 1/11`, instead of the shared audio directory, `/Volumes/Project 1/1/Audio`. Some of those files have the same basename as older, different files in the audio directory. A blind move or merge could overwrite unrelated takes.

## Scope

The corrective operation is limited to region `7 / Tutsan` in:

```text
/Volumes/Project 1/11/Kolot StudioTorun_052logic click_022.RPP
```

The region boundaries from the project file are:

```text
start: 11813.301324594368
end:   12104.358446433422
```

Files outside this region are audit-only unless the user explicitly approves a later, separate operation.

## Audit Design

The audit parses the full `.RPP` file so that source usage is understood globally, but the report stays compact. It should aggregate item sources and report only risk-relevant slices:

- Relative source files used by items that overlap region `7 / Tutsan`.
- Basename duplicates between `/Volumes/Project 1/11` and `/Volumes/Project 1/1/Audio`.
- Future rename or copy conflicts.
- Suspicious cases where the same basename exists in more than one place with different size, creation date, or modified date.
- Non-Tutsan duplicate warnings, without changing those files.

For each reported file, include:

- Current source path as written in the project.
- Resolved filesystem path.
- Basename.
- File size.
- Creation date.
- Modified date.
- Whether an identically named file exists in `/Volumes/Project 1/1/Audio`.
- Number of project items using that source.
- Whether any using item overlaps `7 / Tutsan`.

The audit must not read audio sample data. Metadata and `.RPP` parsing are enough.

## Rename Rule

Only Tutsan candidate files are eligible for rename. A candidate must satisfy all of these:

- The item source is relative, for example `FILE "Aniel Vocal 2-11.wav"`.
- The resolved file exists under `/Volumes/Project 1/11`.
- At least one item using that source overlaps region `7 / Tutsan`.
- The filename does not already include the suffix ` - R7 Tutsan`.

The rename target is:

```text
<original stem> - R7 Tutsan.<ext>
```

Example:

```text
Aniel Vocal 2-11.wav
Aniel Vocal 2-11 - R7 Tutsan.wav
```

## Safety Gates

Before any rename, copy, or relink, produce a dry-run report. The process must stop if any of these are true:

- A source file is missing.
- A target filename already exists in `/Volumes/Project 1/11`.
- A target filename already exists in `/Volumes/Project 1/1/Audio`.
- The same basename is used both inside and outside Tutsan in a way that would make a global file rename ambiguous.
- The open REAPER project path or project filename does not match the expected project.
- REAPER has unsaved changes that the user has not acknowledged.

No operation should use Finder merge or automatic overwrite behavior.

## User Copy Step

After the approved rename, the user manually copies the renamed files from:

```text
/Volumes/Project 1/11
```

to:

```text
/Volumes/Project 1/1/Audio
```

The copy step should produce no duplicate-file prompt. Any prompt means the operation should stop and be re-audited.

## Relink Design

After the renamed files exist in `/Volumes/Project 1/1/Audio`, use REAPER/MCP to change item sources only for items overlapping region `7 / Tutsan`.

Each corrected item source should point to:

```text
/Volumes/Project 1/1/Audio/<original stem> - R7 Tutsan.<ext>
```

Items outside Tutsan remain unchanged, even if they use relative files from `/Volumes/Project 1/11`.

## Verification

After relink:

- The corrected Tutsan items no longer reference the old relative filenames.
- Each corrected Tutsan item points to an existing file in `/Volumes/Project 1/1/Audio`.
- Non-Tutsan items are unchanged.
- REAPER reports no missing media.
- The project is saved as a new version, for example:

```text
Kolot StudioTorun_052logic click_023_tutsan_relinked.RPP
```

## Non-Goals

- Do not normalize every root-level audio file.
- Do not move or relink older working media outside Tutsan.
- Do not resolve every duplicate automatically.
- Do not overwrite audio files in `/Volumes/Project 1/1/Audio`.
