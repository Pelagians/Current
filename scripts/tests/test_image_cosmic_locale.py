"""Keep native territory identity while supporting older iso-codes schemas."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'files/scripts/cosmic-locale-compat.sh'


class CosmicLocaleData(unittest.TestCase):
    def run_script(self, data):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'iso_3166-1.json'
        original = json.dumps(data, ensure_ascii=False).encode()
        path.write_bytes(original)
        path.chmod(0o640)
        env = {**os.environ, 'CURRENT_COSMIC_ISO3166_JSON': str(path)}
        result = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
        return result, path, original, env

    def test_missing_flags_preserve_native_identifiers_names_and_other_data(self):
        data = {'3166-1': [{'alpha_2': 'US', 'alpha_3': 'USA', 'name': 'United States', 'numeric': '840'},
                          {'alpha_2': 'GB', 'name': 'United Kingdom', 'flag': '🇬🇧'}], 'native-extra': 'retained'}
        result, path, _, env = self.run_script(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = json.loads(json.dumps(data))
        expected['3166-1'][0]['flag'] = '🇺🇸'
        self.assertEqual(json.loads(path.read_text()), expected)
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        once = path.read_bytes()
        subprocess.run(['bash', str(SCRIPT)], env=env, check=True, capture_output=True)
        self.assertEqual(path.read_bytes(), once)

    def test_compatible_native_bytes_and_existing_flag_are_unchanged(self):
        data = {'3166-1': [{'alpha_2': 'US', 'flag': 'native value'}]}
        result, path, original, _ = self.run_script(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_metadata_fails_before_writing(self):
        for data in ({}, {'3166-1': []}, {'3166-1': [None]},
                     {'3166-1': [{'alpha_2': 'USA'}]}, {'3166-1': [{'alpha_2': 'uS'}]},
                     {'3166-1': [{'alpha_2': 'US', 'flag': None}]},
                     {'3166-1': [{'alpha_2': 'US'}, {'alpha_2': 'bad'}]}):
            with self.subTest(data=data):
                result, path, original, _ = self.run_script(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_bytes(), original)
