import json
import tempfile
import unittest
from pathlib import Path

from split_translator.workspace import (
    Workspace,
    create_workspace,
    delete_workspace,
    duplicate_workspace,
    last_workspace,
    list_workspaces,
    load_settings,
    read_workspace,
    rename_workspace_folder,
    save_settings,
    save_workspace,
    set_last_workspace,
    slugify,
    taken_slugs,
)


def _write_workspace(root, slug, name=None, original="", translation=""):
    """Create a workspace folder with a config.json, returning its path."""
    directory = Path(root) / slug
    directory.mkdir(parents=True)
    data = {"original_path": original, "translation_path": translation}
    if name is not None:
        data["name"] = name
    (directory / "config.json").write_text(json.dumps(data), encoding="utf-8")
    return directory


class SlugifyTests(unittest.TestCase):
    def test_lowercases_and_hyphenates(self):
        self.assertEqual(slugify("Pan Tadeusz", set()), "pan-tadeusz")

    def test_collapses_runs_and_trims_ends(self):
        self.assertEqual(slugify("  Solaris (Lem)!  ", set()), "solaris-lem")

    def test_folds_accented_letters_to_ascii(self):
        # NFKD decomposes most Polish letters; l with stroke is not decomposable
        # and needs the explicit table, so both are checked here.
        # "Przedwiosnie" and "Lodz" as actually spelled. Escaped so this file
        # stays pure ASCII, like every other source file here.
        self.assertEqual(slugify("Przedwio\u015bnie", set()), "przedwiosnie")
        self.assertEqual(slugify("\u0141\u00f3d\u017a", set()), "lodz")

    def test_falls_back_when_nothing_survives(self):
        self.assertEqual(slugify("!!!", set()), "workspace")
        # "Solaris" in Cyrillic: nothing survives folding, so the fallback wins.
        self.assertEqual(
            slugify("\u0421\u043e\u043b\u044f\u0440\u0438\u0441", set()), "workspace"
        )

    def test_suffixes_on_collision(self):
        self.assertEqual(slugify("Lalka", {"lalka"}), "lalka-2")
        self.assertEqual(slugify("Lalka", {"lalka", "lalka-2"}), "lalka-3")


class ReadWorkspaceTests(unittest.TestCase):
    def test_reads_name_and_paths(self):
        with tempfile.TemporaryDirectory() as d:
            directory = _write_workspace(
                d, "lalka", name="Lalka", original="/b/a.epub", translation="/b/b.epub"
            )
            workspace = read_workspace(directory)
            self.assertEqual(workspace.slug, "lalka")
            self.assertEqual(workspace.name, "Lalka")
            self.assertEqual(workspace.dir, directory)
            self.assertEqual(workspace.original_path, "/b/a.epub")
            self.assertEqual(workspace.translation_path, "/b/b.epub")

    def test_falls_back_to_the_folder_name_when_unnamed(self):
        with tempfile.TemporaryDirectory() as d:
            directory = _write_workspace(d, "lalka")
            self.assertEqual(read_workspace(directory).name, "lalka")

    def test_returns_none_without_a_config(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / "empty"
            directory.mkdir()
            self.assertIsNone(read_workspace(directory))

    def test_returns_none_on_malformed_json(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / "broken"
            directory.mkdir()
            (directory / "config.json").write_text("{ not json", encoding="utf-8")
            self.assertIsNone(read_workspace(directory))

    def test_returns_none_when_the_config_is_not_an_object(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / "listy"
            directory.mkdir()
            (directory / "config.json").write_text("[1, 2]", encoding="utf-8")
            self.assertIsNone(read_workspace(directory))


class ListWorkspacesTests(unittest.TestCase):
    def test_missing_root_gives_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(list_workspaces(Path(d) / "absent"), [])

    def test_sorted_by_display_name_ignoring_case(self):
        with tempfile.TemporaryDirectory() as d:
            _write_workspace(d, "b", name="apple")
            _write_workspace(d, "a", name="Banana")
            names = [ws.name for ws in list_workspaces(Path(d))]
            self.assertEqual(names, ["apple", "Banana"])

    def test_skips_folders_that_are_not_workspaces_and_loose_files(self):
        with tempfile.TemporaryDirectory() as d:
            _write_workspace(d, "real", name="Real")
            (Path(d) / "not-a-workspace").mkdir()
            (Path(d) / "stray.json").write_text("{}", encoding="utf-8")
            self.assertEqual([ws.slug for ws in list_workspaces(Path(d))], ["real"])


class SettingsTests(unittest.TestCase):
    def test_missing_file_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_settings(Path(d) / "settings.json"), {})

    def test_malformed_file_reads_as_empty_and_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text("{ not json", encoding="utf-8")
            self.assertEqual(load_settings(path), {})
            self.assertEqual(path.read_text(encoding="utf-8"), "{ not json")

    def test_round_trips_and_stamps_the_version(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            save_settings({"last_workspace": "lalka"}, path)
            self.assertEqual(load_settings(path)["last_workspace"], "lalka")
            self.assertEqual(load_settings(path)["version"], 1)

    def test_last_workspace_is_none_when_absent_or_blank(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            self.assertIsNone(last_workspace(path))
            save_settings({"last_workspace": ""}, path)
            self.assertIsNone(last_workspace(path))

    def test_set_last_workspace_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            save_settings({"other": 7}, path)
            set_last_workspace("lalka", path)
            settings = load_settings(path)
            self.assertEqual(settings["last_workspace"], "lalka")
            self.assertEqual(settings["other"], 7)


class TakenSlugsTests(unittest.TestCase):
    def test_missing_root_gives_an_empty_set(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(taken_slugs(Path(d) / "absent"), set())

    def test_counts_folders_that_are_not_valid_workspaces(self):
        # The name is taken on disk whether or not the folder is a workspace, so
        # a new workspace must not be allocated that slug.
        with tempfile.TemporaryDirectory() as d:
            _write_workspace(d, "real", name="Real")
            (Path(d) / "junk").mkdir()
            self.assertEqual(taken_slugs(Path(d)), {"real", "junk"})


class CreateWorkspaceTests(unittest.TestCase):
    def test_creates_the_folder_and_config_with_no_book_paths(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = create_workspace("Pan Tadeusz", Path(d))
            self.assertEqual(workspace.slug, "pan-tadeusz")
            self.assertEqual(workspace.name, "Pan Tadeusz")
            self.assertEqual(workspace.original_path, "")
            self.assertEqual(read_workspace(workspace.dir), workspace)

    def test_suffixes_a_slug_already_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            create_workspace("Lalka", Path(d))
            second = create_workspace("Lalka", Path(d))
            self.assertEqual(second.slug, "lalka-2")
            self.assertEqual(second.name, "Lalka")


class SaveWorkspaceTests(unittest.TestCase):
    def test_writes_edited_fields_back(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = create_workspace("Lalka", Path(d))
            edited = Workspace(
                slug=workspace.slug,
                name="Lalka (Prus)",
                dir=workspace.dir,
                original_path="/b/a.epub",
                translation_path="/b/b.epub",
            )
            save_workspace(edited)
            self.assertEqual(read_workspace(workspace.dir), edited)


class DeleteWorkspaceTests(unittest.TestCase):
    def test_removes_the_folder_and_its_contents(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = create_workspace("Lalka", Path(d))
            (workspace.dir / "flashcards.json").write_text("{}", encoding="utf-8")
            delete_workspace(workspace.slug, Path(d))
            self.assertFalse(workspace.dir.exists())
            self.assertEqual(list_workspaces(Path(d)), [])


class DuplicateWorkspaceTests(unittest.TestCase):
    def test_copies_every_file_under_a_new_slug_and_name(self):
        with tempfile.TemporaryDirectory() as d:
            source = create_workspace("Lalka", Path(d))
            save_workspace(
                Workspace(
                    slug=source.slug,
                    name=source.name,
                    dir=source.dir,
                    original_path="/b/a.epub",
                    translation_path="/b/b.epub",
                )
            )
            (source.dir / "flashcards.json").write_text(
                '{"cards": []}', encoding="utf-8"
            )
            copy = duplicate_workspace(source.slug, "Lalka copy", Path(d))
            self.assertEqual(copy.slug, "lalka-copy")
            self.assertEqual(copy.name, "Lalka copy")
            # The book paths travel with the copy, and so do the data files.
            self.assertEqual(copy.original_path, "/b/a.epub")
            self.assertTrue((copy.dir / "flashcards.json").exists())
            # The source is untouched.
            self.assertEqual(read_workspace(source.dir).name, "Lalka")

    def test_rejects_a_folder_that_is_not_a_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "junk").mkdir()
            with self.assertRaises(ValueError):
                duplicate_workspace("junk", "Copy", Path(d))


class RenameWorkspaceFolderTests(unittest.TestCase):
    def test_moves_the_folder_with_its_contents(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = create_workspace("Lalka", Path(d))
            (workspace.dir / "history.json").write_text("[]", encoding="utf-8")
            rename_workspace_folder("lalka", "lalka-prus", Path(d))
            moved = Path(d) / "lalka-prus"
            self.assertFalse(workspace.dir.exists())
            self.assertTrue((moved / "history.json").exists())
            self.assertEqual(read_workspace(moved).slug, "lalka-prus")

    def test_is_a_no_op_when_the_slug_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = create_workspace("Lalka", Path(d))
            rename_workspace_folder("lalka", "lalka", Path(d))
            self.assertTrue(workspace.dir.exists())

    def test_raises_rather_than_clobbering_an_existing_folder(self):
        with tempfile.TemporaryDirectory() as d:
            create_workspace("Lalka", Path(d))
            create_workspace("Solaris", Path(d))
            with self.assertRaises(OSError):
                rename_workspace_folder("lalka", "solaris", Path(d))
            # Neither workspace is lost.
            self.assertEqual(
                sorted(ws.slug for ws in list_workspaces(Path(d))),
                ["lalka", "solaris"],
            )
