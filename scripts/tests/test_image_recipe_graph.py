"""Exercise the shared include walker using temporary recipe trees."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image_matrix as matrix


class RecipeGraph(unittest.TestCase):
    def test_nested_includes_preserve_order_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'recipes/layers').mkdir(parents=True)
            recipe = root / 'recipes/image.yml'
            layer = root / 'recipes/layers/shared.yml'
            recipe.write_text('modules:\n  - from-file: layers/shared.yml\n  - from-file: "recipes/layers/shared.yml" # repeat\n')
            layer.write_text('modules: []\n')
            with patch.object(matrix, 'ROOT', root):
                self.assertEqual(matrix.recipe_graph(recipe), [recipe, layer, layer])

    def test_cycles_missing_files_and_unsupported_paths_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'recipes').mkdir()
            recipe = root / 'recipes/image.yml'
            for ref, message in [('recipes/image.yml', 'recursive'),
                                 ('layers/absent.yml', 'missing'),
                                 ('unknown.yml', 'unsupported')]:
                recipe.write_text(f'modules:\n  - from-file: {ref}\n')
                with self.subTest(ref=ref), patch.object(matrix, 'ROOT', root), self.assertRaisesRegex(SystemExit, message):
                    matrix.recipe_graph(recipe)
