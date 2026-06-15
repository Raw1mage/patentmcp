---
description: Complete patent application review (claims + specification + formalities in parallel)
argument-hint: "Provide complete application text (claims, specification, abstract)"
allowed-tools:
  - review_patent_claims
  - review_specification
  - check_formalities
  - search_mpep
  - get_mpep_section
model: claude-sonnet-4-5-20250929
---

# Complete Patent Application Review

Comprehensive USPTO compliance review of your complete application.

## What You'll Get

1. **Claims Analysis** - 35 USC 112(b) compliance
2. **Specification Review** - 35 USC 112(a) compliance
3. **Formalities Check** - MPEP 608 requirements
4. **Prior Art Search** (optional) - Similar patents
5. **Consolidated Report** - All findings in one place

## How It Works

Three specialized reviews run in parallel:
- `/review-claims` for claims
- `/review-specification` for spec
- `/review-formalities` for formalities

Results synthesized into one master report.

## What I Need

1. Patent claims (independent + dependent)
2. Specification (or key sections)
3. Abstract
4. Drawings info (if any)

Provide all at once or incrementally.

## Final Report Includes

- **Executive Summary** - Overall readiness
- **Critical Issues** - Must fix before filing
- **Important Issues** - Strongly recommend fixing
- **Minor Improvements** - Consider addressing
- **MPEP References** - Citations for findings
- **Action Items** - Prioritized to-do list
- **Filing Checklist** - Everything needed
- **Timeline Estimate** - Time to filing-ready

## When to Use

**Use `/full-review` when:**
- Have complete draft application
- Want comprehensive feedback
- Preparing to file soon

**Use individual commands when:**
- Only checking one section
- Working on specific part
- Want faster, focused feedback

---

**DISCLAIMER:** This tool assists with patent application preparation but does NOT replace legal advice from a registered patent attorney. Always consult with legal counsel before filing. Not affiliated with or endorsed by the USPTO.
