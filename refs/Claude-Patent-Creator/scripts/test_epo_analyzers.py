#!/usr/bin/env python3
"""
Tests for EPO and PCT patent analyzers.

Tests cover:
- EPO Claims Analyzer (Art. 84 EPC)
- EPO Specification Analyzer (Art. 83 EPC)
- EPO Formalities Checker (Rules 42-49 EPC)
- PCT Formalities Checker (PCT Rules 5-12)

Run from project root:
    python scripts/test_epo_analyzers.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path for imports
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.epo_claims_analyzer import EPOClaimsAnalyzer
from mcp_server.epo_formalities_checker import EPOFormalitiesChecker
from mcp_server.epo_specification_analyzer import EPOSpecificationAnalyzer
from mcp_server.pct_formalities_checker import PCTFormalitiesChecker

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {detail}")


# =============================================================================
# EPO Claims Analyzer
# =============================================================================
print("Testing EPO Claims Analyzer (Art. 84 EPC)")
print("=" * 70)

epo_claims = EPOClaimsAnalyzer()

# Test 1: Two-part form detection (with "characterized in that")
r = epo_claims.analyze("""
1. A device for processing signals, the device comprising a receiver,
characterized in that the receiver includes a filter configured to reduce noise.
""")
two_part_issues = [i for i in r["issues"] if i["type"] == "two_part_form"]
check("Two-part form: no issue when present", len(two_part_issues) == 0)

# Test 2: Two-part form missing
epo_claims2 = EPOClaimsAnalyzer()
r2 = epo_claims2.analyze("""
1. A method comprising:
    a) receiving input data;
    b) processing the input data; and
    c) outputting results.
""")
two_part_issues2 = [i for i in r2["issues"] if i["type"] == "two_part_form"]
check("Two-part form: flagged when absent", len(two_part_issues2) > 0)
if two_part_issues2:
    check("Two-part form: severity is IMPORTANT", two_part_issues2[0]["severity"] == "IMPORTANT")
    check("Two-part form: cites Rule 43(1) EPC", "Rule 43" in two_part_issues2[0]["legal_ref"])

# Test 3: Subjective terms
epo_claims3 = EPOClaimsAnalyzer()
r3 = epo_claims3.analyze("1. A system comprising a substantially efficient processor.")
subj_issues = [i for i in r3["issues"] if i["type"] == "clarity" and i.get("term")]
check("Subjective terms detected", len(subj_issues) >= 1)
if subj_issues:
    check("Subjective term cites Art. 84 EPC", "Art. 84" in subj_issues[0]["legal_ref"])

# Test 4: Vague phrases
epo_claims4 = EPOClaimsAnalyzer()
r4 = epo_claims4.analyze("1. A method using algorithms or the like to process data etc.")
vague_issues = [i for i in r4["issues"] if i["type"] == "clarity" and "vague" in i.get("problem", "").lower() or "etc" in i.get("term", "").lower() or "or the like" in i.get("term", "").lower()]
check("Vague phrases detected", len(vague_issues) >= 1)

# Test 5: Art. 52(2) excluded subject matter
epo_claims5 = EPOClaimsAnalyzer()
r5 = epo_claims5.analyze("1. A computer program for performing a business method.")
excluded_issues = [i for i in r5["issues"] if i["type"] == "excluded_subject_matter"]
check("Art. 52(2) excluded subject matter detected", len(excluded_issues) >= 1)
if excluded_issues:
    check("Excluded matter cites Art. 52(2) EPC", "Art. 52" in excluded_issues[0]["legal_ref"])

# Test 6: Claims count > 15 (conciseness)
many_claims = "\n".join([f"{i+1}. A method step {i+1}." for i in range(20)])
epo_claims6 = EPOClaimsAnalyzer()
r6 = epo_claims6.analyze(many_claims)
fee_issues = [i for i in r6["issues"] if i["type"] == "conciseness" and "fee" in i.get("problem", "").lower()]
check("Claims >15 triggers fee warning", len(fee_issues) >= 1)

# Test 7: Output uses legal_ref not mpep
epo_claims7 = EPOClaimsAnalyzer()
r7 = epo_claims7.analyze("1. A method using an appropriate algorithm.")
check("Output uses 'legal_ref' key", all("legal_ref" in i for i in r7["issues"]))
check("Output does NOT use 'mpep' key", all("mpep" not in i for i in r7["issues"]))


# =============================================================================
# EPO Specification Analyzer
# =============================================================================
print("\nTesting EPO Specification Analyzer (Art. 83 EPC)")
print("=" * 70)

# Test 8: Rule 42 section detection
epo_spec = EPOSpecificationAnalyzer()
spec_with_sections = """
TECHNICAL FIELD
The present invention relates to data processing systems.

BACKGROUND ART
Prior systems suffer from high latency.

DISCLOSURE OF THE INVENTION
The invention provides a low-latency processing pipeline.

BRIEF DESCRIPTION OF DRAWINGS
FIG. 1 shows a system diagram.

DETAILED DESCRIPTION
The system includes a processor connected to memory.

INDUSTRIAL APPLICABILITY
The invention is applicable to cloud computing.
"""
claims_for_spec = [{"number": 1, "text": "A data processing system comprising a processor.", "is_independent": True, "depends_on": None}]
r8 = epo_spec.analyze(claims_for_spec, spec_with_sections)
section_issues = [i for i in r8["issues"] if i["type"] == "section_missing"]
check("Rule 42 sections: no issues when all present", len(section_issues) == 0)

# Test 9: Missing sections
epo_spec2 = EPOSpecificationAnalyzer()
r9 = epo_spec2.analyze(claims_for_spec, "This is a short specification about data processing.")
section_issues2 = [i for i in r9["issues"] if i["type"] == "section_missing"]
check("Rule 42 sections: flags missing sections", len(section_issues2) > 0)
if section_issues2:
    check("Missing section cites Rule 42 EPC", "Rule 42" in section_issues2[0]["legal_ref"])


# =============================================================================
# EPO Formalities Checker
# =============================================================================
print("\nTesting EPO Formalities Checker (Rules 42-49 EPC)")
print("=" * 70)

epo_form = EPOFormalitiesChecker()

# Test 10: Abstract word count
short_abstract = "A data processing system."
r10 = epo_form.check_all_formalities(abstract=short_abstract)
abstract_issues = [i for i in r10["issues"] if i["section"] == "abstract"]
check("Short abstract flagged", len(abstract_issues) > 0)
if abstract_issues:
    check("Abstract issue cites Rule 47 EPC", "Rule 47" in abstract_issues[0]["legal_ref"])

# Test 11: Good abstract with reference signs
epo_form2 = EPOFormalitiesChecker()
good_abstract = (
    "A data processing system (100) includes a processor (110) connected to a memory (120) "
    "via a bus (130). The processor (110) executes instructions stored in the memory (120) "
    "to perform signal analysis on input data received from a sensor array (140). "
    "The system achieves improved throughput by employing a multi-stage pipeline (150) "
    "with parallel execution units (160) operating on partitioned data streams. "
    "Results are output through an interface module (170) to external devices."
)
r11 = epo_form2.check_all_formalities(abstract=good_abstract)
ref_sign_issues = [i for i in r11["issues"] if "reference sign" in i.get("problem", "").lower()]
check("Good abstract with ref signs: no ref sign issue", len(ref_sign_issues) == 0)

# Test 12: No "means/said/whereby" prohibition (unlike USPTO)
epo_form3 = EPOFormalitiesChecker()
abstract_with_means = (
    "A means for processing data includes a said processor connected to memory "
    "whereby computation is performed on input signals. The means employs "
    "parallel execution units for improved throughput across multiple data channels. "
    "Results are stored in a cache for subsequent retrieval by downstream components."
)
r12 = epo_form3.check_all_formalities(abstract=abstract_with_means)
forbidden_issues = [i for i in r12["issues"] if "means" in i.get("problem", "").lower() and "forbidden" in i.get("problem", "").lower()]
check("EPO: no prohibition on 'means/said/whereby' in abstract", len(forbidden_issues) == 0)


# =============================================================================
# PCT Formalities Checker
# =============================================================================
print("\nTesting PCT Formalities Checker (PCT Rules 5-12)")
print("=" * 70)

pct = PCTFormalitiesChecker()

# Test 13: Abstract > 150 words
long_abstract = " ".join(["word"] * 200) + "."
r13 = pct.check_all_formalities(abstract=long_abstract)
length_issues = [i for i in r13["issues"] if i["section"] == "abstract" and "150" in i.get("problem", "") or "exceed" in i.get("problem", "").lower() or "long" in i.get("problem", "").lower()]
check("PCT abstract >150 words flagged", len(length_issues) >= 1)
if length_issues:
    check("Abstract issue cites PCT Rule 8", "Rule 8" in length_issues[0]["legal_ref"])

# Test 14: Rule 5 description elements
pct2 = PCTFormalitiesChecker()
good_pct_spec = """
TECHNICAL FIELD
The invention relates to data processing.

BACKGROUND ART
Prior systems are slow.

DISCLOSURE OF THE INVENTION
A faster method is provided.

BRIEF DESCRIPTION OF DRAWINGS
FIG. 1 shows the system.

DETAILED DESCRIPTION
The system processes data efficiently.

BEST MODE
The preferred embodiment uses a GPU.
"""
r14 = pct2.check_all_formalities(specification=good_pct_spec)
desc_issues = [i for i in r14["issues"] if i["section"] == "description"]
check("PCT Rule 5: no issues when all elements present", len(desc_issues) == 0)

# Test 15: Missing description elements
pct3 = PCTFormalitiesChecker()
r15 = pct3.check_all_formalities(specification="This is a brief spec about data.")
desc_issues2 = [i for i in r15["issues"] if i["section"] == "description"]
check("PCT Rule 5: flags missing description elements", len(desc_issues2) > 0)
if desc_issues2:
    check("Missing element cites PCT Rule 5", "Rule 5" in desc_issues2[0]["legal_ref"])


# =============================================================================
# Cross-jurisdiction comparison
# =============================================================================
print("\nTesting Cross-Jurisdiction Comparison")
print("=" * 70)

from mcp_server.claims_analyzer import ClaimsAnalyzer

test_text = "1. A method comprising processing data in an appropriate manner."
us = ClaimsAnalyzer()
epo = EPOClaimsAnalyzer()
us_r = us.analyze(test_text)
epo_r = epo.analyze(test_text)

check("US analyzer outputs 'mpep' key", all("mpep" in i for i in us_r["issues"]))
check("EPO analyzer outputs 'legal_ref' key", all("legal_ref" in i for i in epo_r["issues"]))
check("US refs contain MPEP", all("MPEP" in i["mpep"] for i in us_r["issues"] if i.get("mpep")))
check("EPO refs contain EPC", all("EPC" in i["legal_ref"] or "Rule" in i["legal_ref"] for i in epo_r["issues"] if i.get("legal_ref")))


# =============================================================================
# Summary
# =============================================================================
print("\n" + "=" * 70)
total = passed + failed
print(f"Results: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed} test(s) failed")
    sys.exit(1)
