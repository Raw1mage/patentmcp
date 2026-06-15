---
description: Check patent application formalities for EPO compliance (Rules 42-49 EPC, EPO Guidelines Part A)
argument-hint: "[optional: description | claims | abstract | drawings | all] application-text"
allowed-tools:
  - check_epo_formalities
  - search_patent_law
  - search_mpep
model: claude-sonnet-4-5-20250929
---

# EPO Formalities Check

Verify all formal requirements for a European patent application under EPC Rules 42-49.

**Check Type:** $ARGUMENTS

## What I'll Check

1. **Description** (Rule 42 EPC) - Required sections, disclosure sufficiency, unity
2. **Claims** (Rule 43 EPC) - Two-part form, numbering, fees for excess claims
3. **Abstract** (Rule 47 EPC) - Max 150 words, single figure designation, content
4. **Drawings** (Rule 46 EPC) - Technical quality, reference signs, margins
5. **Request for Grant** (Rule 41 EPC) - Form 1001, designation of states, priorities
6. **Translation Requirements** - Language of proceedings (Rule 6 EPC)
7. **Fees** - Filing fee, search fee, designation fee, claims fee (> 15 claims)

Specified check type focuses on that requirement; otherwise checks everything.

## Process

1. Ask for application sections (or read from file)
2. Check each EPO formality requirement
3. Search EPC rules and EPO Guidelines for standards
4. Generate compliance report with:
   - Requirements checklist per rule
   - Non-compliance issues
   - Fix instructions with rule citations
   - Pre-filing checklist for EPO

## EPO-Specific Requirements

### Description (Rule 42 EPC)

Required sections in order:
- Title of the invention
- Technical field
- Background art (with citation of prior art documents)
- Disclosure of the invention (technical problem and solution)
- Brief description of drawings (if any)
- Detailed description of at least one embodiment
- Industrial applicability (if not obvious)

### Claims (Rule 43 EPC)

- Two-part form for independent claims (preamble + "characterised in that")
- Clear reference to description and drawings
- No drawings or graphs in claims
- Numbered consecutively in Arabic numerals
- Fee applies for each claim beyond 15 (Rule 45 EPC)
- Fee applies for each claim beyond 50

### Abstract (Rule 47 EPC)

- Maximum 150 words
- Must indicate technical field
- Must include concise summary of disclosure
- Must designate most illustrative figure (if drawings exist)
- No commercial statements
- Single paragraph preferred

### Drawings (Rule 46 EPC)

- Minimum margins: top 2.5cm, left 2.5cm, right 1.5cm, bottom 1cm
- No text in drawings (except single words like "water", "steam")
- Reference signs in description must match drawings
- Figures numbered consecutively (Fig. 1, Fig. 2, ...)
- A4 paper size (21cm x 29.7cm)
- Black, sufficiently dense lines

### Request for Grant (Rule 41 EPC)

- EPO Form 1001
- Applicant details (name, address, nationality)
- Title of invention
- Designation of Contracting States (all states designated by default)
- Priority claims (convention priority within 12 months)
- Inventor designation
- Representative details (if applicable)

## Report Structure

```
EPO FORMALITIES COMPLIANCE REPORT
===================================

Application: [Title]
Date: [Date]
Filing Route: Direct EP / Euro-PCT

Summary:
--------
- Requirements Checked: 42
- Compliant: 35
- Non-Compliant: 5
- Warnings: 2

STATUS: CORRECTIONS NEEDED BEFORE FILING

DESCRIPTION (Rule 42 EPC):
============================

[PASS] Title present and descriptive
[PASS] Technical field identified
[FAIL] Background art section missing prior art citations
  -> Rule 42(1)(b): "indicate the background art which,
     as far as known to the applicant, can be regarded as
     useful to understand the invention"
  -> Fix: Add at least 2-3 prior art document citations
[PASS] Problem-solution format used
[PASS] At least one embodiment described in detail
[WARN] Industrial applicability not explicitly stated
  -> Rule 42(1)(f): Required if not obvious from description

CLAIMS (Rule 43 EPC):
======================

[PASS] Claims numbered consecutively
[FAIL] Independent claim 1 not in two-part form
  -> Rule 43(1): "shall contain a statement indicating the
     designation of the subject-matter, a statement of features
     which are necessary for the definition... and a characterising
     portion preceded by 'characterised in that'"
  -> Fix: Restructure with preamble + characterised in that
[PASS] Dependent claims properly reference parent claims
[PASS] 15 or fewer claims (no excess claims fee)
[PASS] No drawings or graphs in claims

ABSTRACT (Rule 47 EPC):
=========================

[PASS] Word count: 127 (max 150)
[FAIL] No figure designated as most illustrative
  -> Rule 47(2)(b): "shall indicate the figure of the drawings
     which should accompany the abstract"
  -> Fix: Add "Figure to accompany abstract: Fig. 1"
[PASS] Technical field indicated
[PASS] No commercial statements

DRAWINGS (Rule 46 EPC):
=========================

[PASS] Margins within specification
[PASS] Reference signs consistent
[WARN] Fig. 3 contains text label "Processing Unit"
  -> Rule 46(2)(j): Drawings shall not contain text,
     except single words like "water", "steam"
  -> Fix: Replace text with reference number, add to description

REQUEST FOR GRANT (Rule 41 EPC):
==================================

[PASS] Applicant details complete
[PASS] Title matches description
[PASS] Priority claim within 12 months
[PASS] Inventor designation filed

FEES CALCULATION:
==================

Filing fee (online): EUR 135
Search fee: EUR 1,775
Designation fee: EUR 685 (all states)
Claims fee: EUR 0 (15 or fewer claims)
---
Total at filing: EUR 2,595

FILING CHECKLIST:
==================

[x] Form 1001 (Request for Grant)
[x] Description with all required sections
[x] Claims (numbered, proper form)
[ ] Abstract with designated figure (NEEDS FIX)
[x] Drawings (A4, proper margins)
[x] Priority document (if claiming priority)
[x] Power of attorney (if using representative)
[ ] Filing fee payment
[ ] Search fee payment

NEXT STEPS:
============

1. Fix 5 non-compliance items listed above
2. Address 2 warnings (recommended)
3. Prepare fee payment (EUR 2,595)
4. File via EPO Online Filing or eOLF
5. Note: Examination request due within 6 months of search report
```

## Output

- Section-by-section compliance status
- Issues with EPC rule citations
- Required vs optional items
- Fee calculation based on claim count
- Filing preparation checklist
- EPO-specific deadlines and requirements

## EPO vs USPTO Formalities

| Requirement | USPTO | EPO |
|-------------|-------|-----|
| Abstract length | 150 words max | 150 words max |
| Claims fee threshold | > 3 independent / > 20 total | > 15 total / > 50 total |
| Description format | MPEP 608 sections | Rule 42 EPC sections |
| Claim form | Open format | Two-part form (Rule 43) |
| Drawings text | Limited text allowed | No text except single words |
| Paper size | Letter or A4 | A4 only |
| Filing language | English | English, French, or German |
| Priority period | 12 months | 12 months |

---

**DISCLAIMER:** This tool assists with patent application preparation but does NOT replace legal advice from a registered European Patent Attorney. Always consult with legal counsel before filing. Not affiliated with or endorsed by the EPO.
