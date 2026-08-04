import unittest

from split_translator.flashcard_tags import (
    BOOK_TAG_PREFIX,
    book_tag,
    format_tags,
    normalise_tag,
    parse_tag_list,
    parse_tags,
)


class NormaliseTagTests(unittest.TestCase):
    def test_lowercases_and_strips(self):
        self.assertEqual(normalise_tag("  Gothic  "), "gothic")

    def test_collapses_internal_whitespace(self):
        self.assertEqual(normalise_tag("phrasal\t  verb"), "phrasal verb")

    def test_commas_become_spaces(self):
        # A comma separates tags, so one inside a tag would split it in two on
        # the next round trip through the editor field.
        self.assertEqual(normalise_tag("Stoker, Bram"), "stoker bram")

    def test_blank_gives_empty_string(self):
        self.assertEqual(normalise_tag("   "), "")


class ParseTagsTests(unittest.TestCase):
    def test_splits_on_commas(self):
        self.assertEqual(
            parse_tags("gothic, phrasal verb"), ["gothic", "phrasal verb"]
        )

    def test_drops_blank_segments(self):
        self.assertEqual(parse_tags("gothic,,   , verb"), ["gothic", "verb"])

    def test_dedupes_keeping_first_seen_order(self):
        self.assertEqual(parse_tags("verb, Gothic, VERB"), ["verb", "gothic"])

    def test_empty_text_gives_no_tags(self):
        self.assertEqual(parse_tags(""), [])


class ParseTagListTests(unittest.TestCase):
    def test_cleans_and_dedupes(self):
        self.assertEqual(
            parse_tag_list([" Gothic ", "gothic", "verb"]), ["gothic", "verb"]
        )

    def test_non_list_gives_no_tags(self):
        self.assertEqual(parse_tag_list("gothic"), [])
        self.assertEqual(parse_tag_list(None), [])

    def test_non_string_entries_are_dropped(self):
        # A hand-edited file: null must not become the tag "none".
        self.assertEqual(parse_tag_list(["gothic", None, 5]), ["gothic"])


class FormatTagsTests(unittest.TestCase):
    def test_joins_with_comma_and_space(self):
        self.assertEqual(format_tags(["gothic", "verb"]), "gothic, verb")

    def test_empty_list_gives_empty_string(self):
        self.assertEqual(format_tags([]), "")

    def test_round_trips_through_parse_tags(self):
        tags = ["book:dracula - bram stoker", "phrasal verb"]
        self.assertEqual(parse_tags(format_tags(tags)), tags)


class BookTagTests(unittest.TestCase):
    def test_prefix_is_the_expected_literal(self):
        self.assertEqual(BOOK_TAG_PREFIX, "book:")

    def test_epub_path_gives_prefixed_lowercase_stem(self):
        self.assertEqual(
            book_tag("/books/Dracula - Bram Stoker.epub"),
            "book:dracula - bram stoker",
        )

    def test_pdf_path(self):
        self.assertEqual(book_tag("/books/Pan Tadeusz.pdf"), "book:pan tadeusz")

    def test_path_without_an_extension(self):
        self.assertEqual(book_tag("/books/Dracula"), "book:dracula")

    def test_comma_in_the_file_name_does_not_split_the_tag(self):
        self.assertEqual(
            book_tag("/books/Stoker, Bram - Dracula.epub"),
            "book:stoker bram - dracula",
        )

    def test_empty_path_gives_no_tag(self):
        # Not a bare "book:", which would tag every card with nothing.
        self.assertEqual(book_tag(""), "")


if __name__ == "__main__":
    unittest.main()
