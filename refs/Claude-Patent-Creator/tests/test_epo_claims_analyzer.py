"""Tests for EPO Claims Analyzer (Art. 84 EPC)."""

from mcp_server.epo_claims_analyzer import EPOClaimsAnalyzer


class TestTwoPartForm:
    """Rule 43(1) EPC: two-part form detection."""

    def test_present_no_issue(self, sample_claims_two_part):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_two_part)
        issues = [i for i in result["issues"] if i["type"] == "two_part_form"]
        assert len(issues) == 0

    def test_absent_flagged(self, sample_claims_no_two_part):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_no_two_part)
        issues = [i for i in result["issues"] if i["type"] == "two_part_form"]
        assert len(issues) > 0

    def test_absent_severity_important(self, sample_claims_no_two_part):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_no_two_part)
        issues = [i for i in result["issues"] if i["type"] == "two_part_form"]
        assert issues[0]["severity"] == "IMPORTANT"

    def test_absent_cites_rule_43(self, sample_claims_no_two_part):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_no_two_part)
        issues = [i for i in result["issues"] if i["type"] == "two_part_form"]
        assert "Rule 43" in issues[0]["legal_ref"]


class TestClarity:
    """Art. 84 EPC: clarity (subjective terms, vague phrases)."""

    def test_subjective_terms_detected(self, sample_claims_subjective):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_subjective)
        clarity_issues = [i for i in result["issues"] if i["type"] == "clarity" and i.get("term")]
        assert len(clarity_issues) >= 1

    def test_subjective_terms_cite_art_84(self, sample_claims_subjective):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_subjective)
        clarity_issues = [i for i in result["issues"] if i["type"] == "clarity" and i.get("term")]
        assert all("Art. 84" in i["legal_ref"] for i in clarity_issues)

    def test_vague_phrases_detected(self):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze("1. A method using algorithms or the like to process data etc.")
        terms = [i.get("term", "") for i in result["issues"]]
        assert any("or the like" in t or "etc" in t for t in terms)


class TestExcludedSubjectMatter:
    """Art. 52(2) EPC: excluded subject matter."""

    def test_computer_program_detected(self, sample_claims_excluded):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_excluded)
        excluded = [i for i in result["issues"] if i["type"] == "excluded_subject_matter"]
        assert len(excluded) >= 1

    def test_excluded_cites_art_52(self, sample_claims_excluded):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_excluded)
        excluded = [i for i in result["issues"] if i["type"] == "excluded_subject_matter"]
        assert "Art. 52" in excluded[0]["legal_ref"]


class TestConciseness:
    """Art. 84 EPC: conciseness (claims fees at 16+)."""

    def test_many_claims_triggers_fee_warning(self):
        claims = "\n".join([f"{i+1}. A method step {i+1}." for i in range(20)])
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(claims)
        fee_issues = [i for i in result["issues"] if i["type"] == "conciseness" and "fee" in i.get("problem", "").lower()]
        assert len(fee_issues) >= 1


class TestOutputFormat:
    """Output uses legal_ref, not mpep."""

    def test_uses_legal_ref_key(self, sample_claims_subjective):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_subjective)
        assert all("legal_ref" in i for i in result["issues"])

    def test_no_mpep_key(self, sample_claims_subjective):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_subjective)
        assert all("mpep" not in i for i in result["issues"])

    def test_has_compliance_score(self, sample_claims_no_two_part):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(sample_claims_no_two_part)
        assert "compliance_score" in result
        assert 0 <= result["compliance_score"] <= 100
