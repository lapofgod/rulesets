from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rulesgen.source import parse_conf_line, parse_file  # noqa: E402


class ParseConfLineTests(unittest.TestCase):
    def test_basic_kinds_supported(self) -> None:
        cases = [
            ("DOMAIN,api.example.com", ("DOMAIN", "api.example.com", ())),
            ("DOMAIN-SUFFIX,example.com", ("DOMAIN-SUFFIX", "example.com", ())),
            ("DOMAIN-KEYWORD,foo", ("DOMAIN-KEYWORD", "foo", ())),
            ("DOMAIN-WILDCARD,*.example.com", ("DOMAIN-WILDCARD", "*.example.com", ())),
            ("DOMAIN-REGEX,^.*\\.example\\.com$", ("DOMAIN-REGEX", r"^.*\.example\.com$", ())),
            ("IP-ASN,13335", ("IP-ASN", "13335", ())),
            ("GEOIP,CN", ("GEOIP", "CN", ())),
            ("IP-CIDR,1.1.1.0/24,no-resolve", ("IP-CIDR", "1.1.1.0/24", ("no-resolve",))),
            ("IP-CIDR6,2400:3200::/32", ("IP-CIDR6", "2400:3200::/32", ())),
            ("URL-REGEX,^https?:\\/\\/example\\.com\\/api", ("URL-REGEX", r"^https?:\/\/example\.com\/api", ())),
            ("USER-AGENT,Curl*", ("USER-AGENT", "Curl*", ())),
            ("DST-PORT,443", ("DST-PORT", "443", ())),
            ("SRC-PORT,53", ("SRC-PORT", "53", ())),
        ]

        for line, expected in cases:
            with self.subTest(line=line):
                rule, warning = parse_conf_line(line)
                self.assertIsNone(warning)
                self.assertIsNotNone(rule)
                assert rule is not None
                self.assertEqual((rule.kind, rule.value, rule.extras), expected)

    def test_logical_rules_preserve_expression_after_first_comma(self) -> None:
        cases = [
            ("AND,((DOMAIN,example.com),(DST-PORT,443))", "AND", "((DOMAIN,example.com),(DST-PORT,443))"),
            ("OR,((DOMAIN-SUFFIX,example.com),(DOMAIN-KEYWORD,foo))", "OR", "((DOMAIN-SUFFIX,example.com),(DOMAIN-KEYWORD,foo))"),
            ("NOT,((DOMAIN-REGEX,^ads\\\\.example\\\\.com$))", "NOT", r"((DOMAIN-REGEX,^ads\\.example\\.com$))"),
        ]

        for line, kind, expression in cases:
            with self.subTest(line=line):
                rule, warning = parse_conf_line(line)
                self.assertIsNone(warning)
                self.assertIsNotNone(rule)
                assert rule is not None
                self.assertEqual(rule.kind, kind)
                self.assertEqual(rule.value, expression)
                self.assertEqual(rule.extras, ())

    def test_logical_rules_are_modeled_recursively(self) -> None:
        line = "AND,((NOT,((DOMAIN,ads.example.com))),(OR,((DOMAIN-SUFFIX,example.com),(DST-PORT,443))))"
        rule, warning = parse_conf_line(line)

        self.assertIsNone(warning)
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertEqual(rule.kind, "AND")
        self.assertEqual(len(rule.logical_children), 2)

        left = rule.logical_children[0]
        right = rule.logical_children[1]
        self.assertEqual(left.kind, "NOT")
        self.assertEqual(len(left.logical_children), 1)
        self.assertEqual(left.logical_children[0].kind, "DOMAIN")
        self.assertEqual(left.logical_children[0].value, "ads.example.com")

        self.assertEqual(right.kind, "OR")
        self.assertEqual(len(right.logical_children), 2)
        self.assertEqual(right.logical_children[0].kind, "DOMAIN-SUFFIX")
        self.assertEqual(right.logical_children[1].kind, "DST-PORT")

    def test_invalid_not_operand_count_is_warned(self) -> None:
        rule, warning = parse_conf_line("NOT,((DOMAIN,foo.com),(DOMAIN,bar.com))")
        self.assertIsNone(rule)
        self.assertEqual(warning, "Invalid NOT rule ignored: exactly one operand is required")

    def test_unknown_kind_is_ignored_with_warning(self) -> None:
        rule, warning = parse_conf_line("FAKE-TYPE,foo")
        self.assertIsNone(rule)
        self.assertEqual(warning, "Unknown rule kind 'FAKE-TYPE' ignored")

    def test_domainset_shorthand_is_not_supported(self) -> None:
        for line in (".example.com", "+.example.com", "*.example.com"):
            with self.subTest(line=line):
                rule, warning = parse_conf_line(line)
                self.assertIsNone(rule)
                self.assertIsNone(warning)

    def test_trailing_comment_is_ignored(self) -> None:
        rule, warning = parse_conf_line("DOMAIN-SUFFIX,example.com # note")
        self.assertIsNone(warning)
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertEqual(rule.kind, "DOMAIN-SUFFIX")
        self.assertEqual(rule.value, "example.com")


class ParseFileWarningTests(unittest.TestCase):
    def test_parse_file_prints_warning_with_file_and_line(self) -> None:
        content = "\n".join(
            [
                "DOMAIN,ok.example.com",
                "FAKE-TYPE,ignore-me",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "sample.conf"
            file_path.write_text(content, encoding="utf-8")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rules = parse_file(file_path)

            self.assertEqual(len(rules), 1)
            self.assertIn("[WARN] sample.conf:2: Unknown rule kind 'FAKE-TYPE' ignored", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
