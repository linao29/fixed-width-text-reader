import io
import os
import tempfile
import unittest

from fixed_width_text_reader import Field, parse, parse_file, parse_lines


class FieldTests(unittest.TestCase):
    def test_end_is_start_plus_width(self):
        f = Field(name="ssn", start=0, width=9)
        self.assertEqual(f.end, 9)

    def test_start_must_be_non_negative(self):
        with self.assertRaises(ValueError):
            Field(name="x", start=-1, width=3)

    def test_width_must_be_positive(self):
        with self.assertRaises(ValueError):
            Field(name="x", start=0, width=0)

    def test_unknown_type_name_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            Field(name="x", start=0, width=3, type="bool")

    def test_custom_callable_accepted(self):
        seen = []

        def upper(s: str) -> str:
            seen.append(s)
            return s.upper()

        f = Field(name="x", start=0, width=3, type=upper)
        self.assertEqual(f.type, upper)
        # Touching the converter through parse exercises the resolution path.
        self.assertEqual(parse_lines(["abc"], [f]), [{"x": "ABC"}])
        self.assertEqual(seen, ["abc"])


class ParseTests(unittest.TestCase):
    def test_basic_string_field(self):
        fields = [Field(name="first", start=0, width=5), Field(name="last", start=5, width=5)]
        self.assertEqual(parse("Jane Smith", fields), [{"first": "Jane", "last": "Smith"}])

    def test_int_and_float_coercion(self):
        fields = [
            Field(name="qty", start=0, width=4, type="int"),
            Field(name="price", start=4, width=6, type="float"),
        ]
        out = parse("  12  3.50", fields)
        self.assertEqual(out, [{"qty": 12, "price": 3.5}])
        self.assertIsInstance(out[0]["qty"], int)
        self.assertIsInstance(out[0]["price"], float)

    def test_percent_type(self):
        fields = [Field(name="tax", start=0, width=6, type="percent")]
        self.assertEqual(parse("12.5%", fields), [{"tax": 12.5}])

    def test_blank_field_becomes_none(self):
        fields = [
            Field(name="a", start=0, width=3),
            Field(name="b", start=3, width=3, type="int"),
        ]
        self.assertEqual(parse("abc   ", fields), [{"a": "abc", "b": None}])

    def test_short_line_is_padded(self):
        # The second field is entirely missing from the input; it should be
        # treated as blank, i.e. None.
        fields = [
            Field(name="a", start=0, width=3),
            Field(name="b", start=3, width=3),
        ]
        self.assertEqual(parse("abc", fields), [{"a": "abc", "b": None}])

    def test_long_line_is_truncated(self):
        fields = [Field(name="a", start=0, width=3)]
        self.assertEqual(parse("abcdefEXTRA", fields), [{"a": "abc"}])

    def test_blank_lines_skipped(self):
        fields = [Field(name="a", start=0, width=1)]
        text = "x\n\n   \ny\n"
        self.assertEqual(parse(text, fields), [{"a": "x"}, {"a": "y"}])

    def test_multiple_records(self):
        fields = [
            Field(name="id", start=0, width=2, type="int"),
            Field(name="name", start=2, width=5),
        ]
        text = "01Alice\n02Bob  \n03Carol"
        self.assertEqual(
            parse(text, fields),
            [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Carol"},
            ],
        )

    def test_custom_converter(self):
        fields = [
            Field(
                name="flag",
                start=0,
                width=1,
                type=lambda s: s == "Y",
            )
        ]
        self.assertEqual(
            parse("Y\nN", fields),
            [{"flag": True}, {"flag": False}],
        )

    def test_crlf_line_endings(self):
        fields = [Field(name="a", start=0, width=3)]
        self.assertEqual(parse("abc\r\ndef", fields), [{"a": "abc"}, {"a": "def"}])

    def test_cr_only_line_endings(self):
        fields = [Field(name="a", start=0, width=3)]
        self.assertEqual(parse("abc\rdef", fields), [{"a": "abc"}, {"a": "def"}])

    def test_empty_input_returns_empty_list(self):
        fields = [Field(name="a", start=0, width=1)]
        self.assertEqual(parse("", fields), [])

    def test_int_parse_error_propagates(self):
        # We do not swallow conversion errors; the caller needs to see them to
        # fix the spec.
        fields = [Field(name="n", start=0, width=3, type="int")]
        with self.assertRaises(ValueError):
            parse("abc", fields)

    def test_no_fields_rejected(self):
        with self.assertRaises(ValueError):
            parse_lines(["abc"], [])

    def test_non_overlapping_adjacent_fields(self):
        fields = [
            Field(name="a", start=0, width=2),
            Field(name="b", start=2, width=2),
            Field(name="c", start=4, width=2),
        ]
        self.assertEqual(
            parse("abcdef", fields),
            [{"a": "ab", "b": "cd", "c": "ef"}],
        )

    def test_gap_between_fields_is_dropped(self):
        # Columns that are not declared in any Field are simply ignored.
        fields = [
            Field(name="a", start=0, width=2),
            Field(name="c", start=4, width=2),
        ]
        self.assertEqual(parse("abXXcd", fields), [{"a": "ab", "c": "cd"}])


class ParseFileTests(unittest.TestCase):
    def test_parse_file_from_path(self):
        fields = [Field(name="a", start=0, width=3), Field(name="b", start=3, width=3)]
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("abc123\ndef456\n")
            path = fh.name
        try:
            self.assertEqual(
                parse_file(path, fields),
                [
                    {"a": "abc", "b": "123"},
                    {"a": "def", "b": "456"},
                ],
            )
        finally:
            os.remove(path)

    def test_parse_file_from_open_file_object(self):
        fields = [Field(name="a", start=0, width=3)]
        buf = io.StringIO("abc\ndef\n")
        self.assertEqual(
            parse_file(buf, fields),
            [{"a": "abc"}, {"a": "def"}],
        )


if __name__ == "main__":
    unittest.main()
