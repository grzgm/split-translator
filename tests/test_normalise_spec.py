"""One edition's normalisation multipliers: their clamping, their CSS, and
their stored form. Pure logic, so no Qt and no display."""

import unittest

from split_translator.normalise_spec import (
    DEFAULT_GAP_EM,
    DEFAULT_LINE_HEIGHT,
    MAX_SCALE,
    MIN_SCALE,
    ORIGINAL_SIDE,
    TRANSLATION_SIDE,
    NormaliseSpec,
)

#: What the default spec must render as, character for character. The three
#: rules after `body` are copied verbatim from the fixed stylesheet this object
#: replaces, so a change here is a change to how every book has always looked.
DEFAULT_CSS = (
    "body { font-size: 100%; line-height: 1.55; }"
    " p, div, blockquote, li, h1, h2, h3, h4, h5, h6 { margin: 0; }"
    " p, div, blockquote, li { margin-block: 0.6em; }"
    " p:empty, div:empty, .st-blank { margin: 0; height: 0; }"
)


class DefaultsTests(unittest.TestCase):
    def test_a_fresh_spec_is_all_ones(self):
        spec = NormaliseSpec()
        self.assertEqual((spec.font, spec.line_height, spec.gap), (1.0, 1.0, 1.0))

    def test_a_fresh_spec_is_default(self):
        self.assertTrue(NormaliseSpec().is_default)

    def test_any_changed_field_is_not_default(self):
        self.assertFalse(NormaliseSpec(font=0.9).is_default)
        self.assertFalse(NormaliseSpec(line_height=1.1).is_default)
        self.assertFalse(NormaliseSpec(gap=0.8).is_default)

    def test_the_default_css_is_the_fixed_spec_plus_a_neutral_font_rule(self):
        # The font rule is new but neutral: the book HTML sets no font size on
        # body, so 100% resolves to the browser default already in effect.
        self.assertEqual(NormaliseSpec().css(), DEFAULT_CSS)


class ScalingTests(unittest.TestCase):
    def test_font_scales_the_percentage(self):
        self.assertIn("font-size: 90%", NormaliseSpec(font=0.9).css())

    def test_line_height_scales_the_default(self):
        # 1.55 * 0.8 = 1.24
        self.assertIn("line-height: 1.24", NormaliseSpec(line_height=0.8).css())

    def test_gap_scales_the_default(self):
        # 0.6 * 0.5 = 0.3
        self.assertIn("margin-block: 0.3em", NormaliseSpec(gap=0.5).css())

    def test_numbers_carry_no_float_noise(self):
        # 0.6 * 1.05 is 0.6300000000000001 in binary floating point, which must
        # not reach the stylesheet.
        css = NormaliseSpec(gap=1.05).css()
        self.assertIn("margin-block: 0.63em", css)
        self.assertNotIn("0.6300000", css)

    def test_the_unscaled_rules_never_change(self):
        # Whatever the multipliers, the three rules that carry no value are
        # untouched.
        css = NormaliseSpec(font=1.4, line_height=0.7, gap=1.9).css()
        self.assertIn(
            " p, div, blockquote, li, h1, h2, h3, h4, h5, h6 { margin: 0; }", css
        )
        self.assertIn(" p:empty, div:empty, .st-blank { margin: 0; height: 0; }", css)


class ClampingTests(unittest.TestCase):
    def test_a_value_below_the_range_is_clamped_up(self):
        self.assertEqual(NormaliseSpec(font=0.1).font, MIN_SCALE)

    def test_a_value_above_the_range_is_clamped_down(self):
        self.assertEqual(NormaliseSpec(gap=99.0).gap, MAX_SCALE)

    def test_a_value_inside_the_range_is_kept(self):
        self.assertEqual(NormaliseSpec(line_height=1.25).line_height, 1.25)

    def test_a_non_numeric_value_falls_back_to_one(self):
        self.assertEqual(NormaliseSpec(font="wide").font, 1.0)

    def test_none_falls_back_to_one(self):
        self.assertEqual(NormaliseSpec(gap=None).gap, 1.0)

    def test_a_nan_falls_back_to_one(self):
        # NaN survives min/max unchanged, so it needs its own guard or it would
        # reach the stylesheet as "nan".
        self.assertEqual(NormaliseSpec(font=float("nan")).font, 1.0)


class DictTests(unittest.TestCase):
    def test_round_trips(self):
        spec = NormaliseSpec(font=0.9, line_height=1.1, gap=0.75)
        self.assertEqual(NormaliseSpec.from_dict(spec.to_dict()), spec)

    def test_a_missing_field_defaults_without_losing_its_neighbours(self):
        spec = NormaliseSpec.from_dict({"font": 0.8})
        self.assertEqual(spec.font, 0.8)
        self.assertEqual(spec.line_height, 1.0)
        self.assertEqual(spec.gap, 1.0)

    def test_a_malformed_field_defaults_without_losing_its_neighbours(self):
        spec = NormaliseSpec.from_dict({"font": "big", "gap": 0.7})
        self.assertEqual(spec.font, 1.0)
        self.assertEqual(spec.gap, 0.7)

    def test_a_non_dict_gives_the_default(self):
        self.assertTrue(NormaliseSpec.from_dict("nonsense").is_default)
        self.assertTrue(NormaliseSpec.from_dict(None).is_default)

    def test_to_dict_names_match_the_field_names(self):
        # The stored keys are the constructor's argument names, so the file is
        # readable and from_dict needs no mapping table.
        self.assertEqual(
            sorted(NormaliseSpec().to_dict()), ["font", "gap", "line_height"]
        )


class ConstantsTests(unittest.TestCase):
    def test_the_defaults_are_the_values_the_fixed_spec_used(self):
        self.assertEqual(DEFAULT_LINE_HEIGHT, 1.55)
        self.assertEqual(DEFAULT_GAP_EM, 0.6)

    def test_the_side_names_are_the_stored_keys(self):
        self.assertEqual(ORIGINAL_SIDE, "original")
        self.assertEqual(TRANSLATION_SIDE, "translation")


if __name__ == "__main__":
    unittest.main()
