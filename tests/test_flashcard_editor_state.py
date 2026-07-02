import unittest

from split_translator.flashcard_editor_state import EditorState


class EditorStateTests(unittest.TestCase):
    def test_starts_new_and_unaltered(self):
        state = EditorState()
        self.assertEqual(state.mode, "new")
        self.assertTrue(state.is_new)
        self.assertFalse(state.is_editing)
        self.assertIsNone(state.loaded_card_id)
        self.assertIsNone(state.loaded_created_at)
        self.assertFalse(state.altered)

    def test_to_editing_sets_ids_and_stays_unaltered(self):
        state = EditorState()
        state.mark_altered()
        state.to_editing("id-1", "2026-01-01T00:00:00")
        self.assertEqual(state.mode, "editing")
        self.assertTrue(state.is_editing)
        self.assertEqual(state.loaded_card_id, "id-1")
        self.assertEqual(state.loaded_created_at, "2026-01-01T00:00:00")
        # Entering editing is a clean baseline, not a user edit.
        self.assertFalse(state.altered)

    def test_to_new_clears_ids_and_unalters(self):
        state = EditorState()
        state.to_editing("id-1", "t")
        state.mark_altered()
        state.to_new()
        self.assertEqual(state.mode, "new")
        self.assertIsNone(state.loaded_card_id)
        self.assertIsNone(state.loaded_created_at)
        self.assertFalse(state.altered)

    def test_mark_altered_sets_flag(self):
        state = EditorState()
        self.assertFalse(state.altered)
        state.mark_altered()
        self.assertTrue(state.altered)
