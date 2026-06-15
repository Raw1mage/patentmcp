---
description: Check patent application formalities (abstract, title, drawings per MPEP 608)
argument-hint: "[optional: abstract | title | drawings | all] abstract-text title-text spec-text"
allowed-tools:
  - check_formalities
  - search_mpep
  - get_mpep_section
model: claude-sonnet-4-5-20250929
---

# Formalities Check

Verify all formal requirements for a complete patent application.

**Check Type:** $ARGUMENTS

## What I'll Check

1. **Abstract** - 150 words max, proper content (MPEP 608.01(b))
2. **Title** - 500 characters max, descriptive (MPEP 606)
3. **Drawings** - All claim features shown, proper numbering (MPEP 608.02)
4. **Required Sections** - Field, Background, Summary, etc.
5. **Filing Checklist** - Declaration, fees, IDS

Specified check type focuses on that requirement; otherwise checks everything.

## Process

1. Ask for application sections
2. Check each formality requirement
3. Search MPEP for standards
4. Generate compliance report with:
   - Requirements checklist
   - Non-compliance issues
   - Fix instructions
   - Pre-filing checklist

## Output

- Section-by-section compliance status
- Issues with character/word counts
- Required vs optional items
- Filing preparation checklist
- Estimated fees based on claim count

---

**DISCLAIMER:** This tool assists with patent application preparation but does NOT replace legal advice from a registered patent attorney. Always consult with legal counsel before filing. Not affiliated with or endorsed by the USPTO.
