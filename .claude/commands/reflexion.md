---
description: Audit and optimize the .claude/ ecosystem — skills, hooks, guides, patterns, agents, and settings — for quality, coherence, and token efficiency. Use when reviewing configuration health, fixing dead references, improving skill triggers, or optimizing the instruction budget.
---

You are a `.claude/` ecosystem auditor. Scan silently (no intermediate output), then present a flat prioritized report.

## Phase 0 — Conversation History Analysis

Review the full conversation history in your context window. Look for:

**Discovered patterns**
- Bugs or solutions found during the session that could become new patterns in `.claude/patterns/`
- Recurring error types that should be added to a skill's Common Issues table
- Workarounds applied that should be documented to avoid rediscovery

**Miscommunications & friction**
- User requests misunderstood or requiring multiple attempts — suggests missing/unclear trigger in CLAUDE.md or skill description
- User had to correct the approach — suggests a missing critical rule or anti-pattern doc
- User explicitly said "remember this" or "always/never do X" — suggests a new rule or skill update

**Knowledge gaps**
- Questions answered by reading code that should be documented in a skill's `references/`
- External knowledge applied (API quirks, library gotchas) not yet captured in any guide or pattern
- Workflow steps repeated manually that could be automated via a hook or script

**Skill/hook improvement candidates**
- Patterns used successfully that an existing skill doesn't cover yet (skill update candidate)
- Validation logic applied manually that could become a hook check
- New agent workflows that emerged from multi-step tasks

Tag findings as: `NEW-PATTERN`, `SKILL-UPDATE`, `NEW-TRIGGER`, `NEW-RULE`, `NEW-REFERENCE`

## Phase 1 — Skill Quality Audit

Read each `.claude/skills/*/SKILL.md`. For each skill check:

**Frontmatter**
- `name` is kebab-case matching its folder name
- `description` follows `[What it does] + [When to use] + [Key capabilities]`, under 1024 chars, no XML brackets
- Includes user-phrased `triggers` (positive) AND `negative_triggers`

**Structure**
- Total word count (flag if >5000 words — progressive disclosure needed)
- Has `references/` subdirectory for detailed docs (flag `NO-PROGRESSIVE-DISCLOSURE` if missing and >3000 words)
- Has `scripts/` subdirectory if skill involves automation steps
- All internal file paths in the skill resolve to real files on disk
- Has "Examples" section with `User says:` scenarios
- Has "Common Issues" or troubleshooting table
- Critical instructions appear at top, not buried

**Trigger cross-check**
- Compare skill description triggers against CLAUDE.md "Agent Skills" table entries
- Flag `UNDER-TRIGGER` if skill handles cases not listed in CLAUDE.md
- Flag `OVER-TRIGGER` if CLAUDE.md lists triggers the skill doesn't actually handle

## Phase 2 — Hook & Agent Effectiveness Audit

Read `.claude/settings.json` hooks config, all `.claude/hooks/*.sh`, and `.claude/commands/agents/*.md`.

**Hook registration**
- List hooks on disk vs hooks registered in `settings.json` `hooks` section
- Flag `UNREGISTERED-HOOK` for any `.sh` file on disk not in settings.json (exclude `pre-commit.sh` which is a git hook, and `check-signals.sh` which is a manual CLI utility)

**Hook coverage**
- Map what each registered hook validates against documented critical rules and patterns
- Flag `DUPLICATE-LOGIC` if two hooks check the same thing
- Flag gaps where critical rules have no hook enforcement

**Hook configuration**
- Check timeout values are reasonable (2-30s for pre-tool, 5-60s for post-tool)
- Check matcher patterns match actual tool names

**Agents**
- Read each `.claude/commands/agents/*.md`
- Validate agent description triggers vs CLAUDE.md workflows section
- Flag `MISSING-AGENT-TRIGGER` for agents not reachable from any CLAUDE.md trigger
- Check for overlap between agents (same problem space, no differentiation)

## Phase 3 — Documentation & Cross-Reference Integrity

Read CLAUDE.md, settings.json guide paths, and list all files on disk under `.claude/`.

**Dead references** (`DEAD-REF`)
- Every path in `settings.json` `guides` section must resolve to a real file
- Every path mentioned in CLAUDE.md must resolve to a real file
- Every path in skill `references/` must resolve

**Orphaned files** (`ORPHAN-GUIDE`, `ORPHAN-PATTERN`)
- Files under `.claude/documentation/guides/` not referenced from CLAUDE.md, settings.json, or any skill
- Files under `.claude/patterns/` not referenced from CLAUDE.md, settings.json, or any skill

**Trigger coverage** (`MISSING-TRIGGER`)
- Compare CLAUDE.md "Automatic Triggers" entries against `automatic-guide-triggers` in settings.json
- Flag entries in one but not the other
- Flag triggers pointing to nonexistent files

### Phase 3b — Orphan Repurposing Analysis

For each `ORPHAN-GUIDE` or `ORPHAN-PATTERN` from Phase 3, evaluate before proposing deletion:

**Repurpose criteria** (all must be true for `REPURPOSE-TO-SKILL`):
1. Content covers a topic within an existing skill's domain
2. Knowledge is NOT already in the skill's SKILL.md or existing `references/`
3. Contains actionable patterns, anti-patterns, or solutions (not session logs or status reports)
4. At least 300 words of substantive technical material

For each candidate: identify target skill, note unique vs overlapping sections, propose a `references/{name}.md` filename.

Tag: `REPURPOSE-TO-SKILL`

## Phase 4 — Settings Coherence & Token Budget

**preApprovedTools** (`MISSING-PRE-APPROVED`, `BROAD-PATTERN`)
- MCP servers defined but not covered in preApprovedTools
- Overly broad Bash patterns (e.g., `Bash(cat:*)` allows reading any file)
- Commands used frequently in workflows but not pre-approved

**Token budget** (`TOKEN-REDUNDANCY`)
- CLAUDE.md word count (target <4000 words for main content)
- Skill frontmatter description sizes (target <1024 chars each)
- Redundancy between CLAUDE.md trigger table and skill descriptions

**Reminders** (`STALE-REMINDER`)
- `reminders` entries in settings.json that conflict with current skill instructions
- References to removed or renamed files/tools
- Outdated guidance (e.g., referencing deprecated patterns)

## Output Format

```
## Ecosystem Health Report

### Critical (broken, causes failures)
1. [TAG] Finding with specific file path(s)

### Recommended (structural improvements)
1. [TAG] Finding with specific file path(s)

### Observations (optimization opportunities)
1. [TAG] Finding with specific file path(s)

### Proposed Changes
- [TAG] One-line fix per finding
- [REPURPOSE-TO-SKILL] {orphan} → {skill}/references/{name}.md — {reason}
```

**Tags**: `DEAD-REF`, `UNREGISTERED-HOOK`, `ORPHAN-GUIDE`, `ORPHAN-PATTERN`, `NO-PROGRESSIVE-DISCLOSURE`, `UNDER-TRIGGER`, `OVER-TRIGGER`, `MISSING-PRE-APPROVED`, `MISSING-TRIGGER`, `TOKEN-REDUNDANCY`, `BROAD-PATTERN`, `STALE-REMINDER`, `DUPLICATE-LOGIC`, `MISSING-AGENT-TRIGGER`, `NEW-PATTERN`, `SKILL-UPDATE`, `NEW-TRIGGER`, `NEW-RULE`, `NEW-REFERENCE`, `REPURPOSE-TO-SKILL`

**Rules**:
- No XML tags in output
- No empty template sections — skip phases with zero findings
- One-line findings only (path + problem), no multi-paragraph explanations
- Group related findings under the same tag

## Interaction Flow

1. **Scan silently** — read all files without intermediate output
2. **Present flat report** — using the format above
3. **Ask**: "Which items should I fix? (e.g., 'all Critical', 'items 1,3,5', 'repurpose all', or specific tags like 'DEAD-REF')"
4. **Implement** approved changes (for `REPURPOSE-TO-SKILL`: extract unique knowledge into `references/` doc, update SKILL.md References section, then delete orphan)
5. **Offer re-scan** to verify fixes
