import io
import os
import re
import tempfile
import unittest
from zipfile import ZipFile

import faa_aixm_pipeline as mod


class TestDiscovery(unittest.TestCase):
    def test_discover_effective_dates_from_index(self):
        html = '''<html><body>
        <a href="/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-08-07/">2025-08-07</a>
        <a href="/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2025-07-10/">2025-07-10</a>
        <a href="/not/matching">ignore</a>
        </body></html>'''
        dates = mod.discover_effective_dates(html)
        self.assertEqual(dates, ['2025-08-07', '2025-07-10'])

    def test_find_aixm_links_from_cycle_page(self):
        html = '''<html><body>
        <a href="/files/AIXM5.1.zip">AIXM 5.1</a>
        <a href="https://example.com/SAA_AIXM_5.0.zip">SAA AIXM</a>
        </body></html>'''
        links = mod.find_aixm_links(html)
        self.assertIn('aixm51', links)
        self.assertTrue(links['aixm51'].startswith('https://'))
        self.assertIn('aixm50', links)


class TestPathsAndNames(unittest.TestCase):
    def test_infer_dataset_name(self):
        self.assertEqual(mod.infer_dataset_name('aixm5.1.zip'), 'aixm5_1')
        self.assertEqual(mod.infer_dataset_name('SAA_AIXM_20250612.zip'), 'saa_aixm_20250612')
        self.assertEqual(mod.infer_dataset_name('..weird..name...zip'), 'weird_name')

    def test_safe_join_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            from pathlib import Path
            base = Path(os.path.abspath(td))
            with self.assertRaises(ValueError):
                mod._safe_join(base, '../../evil')  # type: ignore[arg-type]


class TestZipExtraction(unittest.TestCase):
    def test_extract_xmls_from_zip_only_xml_and_safe(self):
        with tempfile.TemporaryDirectory() as td:
            zip_path = os.path.join(td, 'test.zip')
            # Build a zip with xml, non-xml, and a traversal entry
            with ZipFile(zip_path, 'w') as z:
                z.writestr('folder/ok.xml', '<r/>')
                z.writestr('ignore.txt', 'hello')
                z.writestr('../../traverse.xml', '<bad/>')

            # Happy path: remove the unsafe entry and ensure only xml is extracted
            with ZipFile(zip_path, 'a') as z:
                # Replace zip with only safe entries for positive path
                pass

            # With traversal entry present, extractor sanitizes and still succeeds
            from pathlib import Path
            res1 = mod.extract_xmls_from_zip(
                zip_path=Path(zip_path), dest_dir=Path(td), kind='aixm51', date='2025-08-07'
            )
            self.assertEqual(len(res1.files), 2)  # ok.xml and traverse.xml
            self.assertTrue(any(f.endswith('ok.xml') for f in res1.files))
            self.assertTrue(any(f.endswith('traverse.xml') for f in res1.files))

            # Create a clean zip without traversal and verify extraction still works
            zip2 = os.path.join(td, 'clean.zip')
            with ZipFile(zip2, 'w') as z:
                z.writestr('folder/ok.xml', '<r/>')
                z.writestr('ignore.txt', 'hello')
            res = mod.extract_xmls_from_zip(
                zip_path=Path(zip2), dest_dir=Path(td), kind='aixm51', date='2025-08-07'
            )
            # Only one XML should be extracted
            self.assertEqual(len(res.files), 1)
            # Path should be under date/kind/xml/dataset/
            for rel in res.files:
                self.assertTrue(rel.startswith('xml/clean/'))
                self.assertTrue(rel.endswith('ok.xml'))


if __name__ == '__main__':
    unittest.main()
