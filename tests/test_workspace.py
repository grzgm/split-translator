import json
import tempfile
import unittest
from pathlib import Path

from split_translator.workspace import (
    Workspace,
    last_workspace,
    list_workspaces,
    load_settings,
    read_workspace,
    save_settings,
    set_last_workspace,
    slugify,
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
