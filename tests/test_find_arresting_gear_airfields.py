import io
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

import find_arresting_gear_airfields as mod


class TestParsingHelpers(unittest.TestCase):
    def test_localname(self):
        self.assertEqual(mod.localname('{ns}tag'), 'tag')
        self.assertEqual(mod.localname('tag'), 'tag')

    def test_parse_gear_from_text_basic(self):
        note = 'RWY 14/32 equipped with BAK-12 and BAK14. 1500 FT FM THR (1200).'
        items = mod.parse_gear_from_text(note)
        types = {i['type'] for i in items}
        self.assertIn('BAK-12', types)
        # Implementation normalizes BAK12 -> BAK-12 but keeps BAK14 as-is
        self.assertIn('BAK14', types)
        # Distances parsed
        for i in items:
            self.assertIn(1500, i['distances_from_threshold_ft'])
            # 1200 appears only in misc because 1500 is the FM THR value
            self.assertIn(1200, i['distances_misc_ft'])

    def test_parse_gear_from_text_hook_prefix(self):
        note = 'HOOK BAK12 available; MB60 also present (1000 FT).'
        items = mod.parse_gear_from_text(note)
        types = {i['type'] for i in items}
        self.assertIn('HOOK BAK-12', types)
        self.assertIn('MB60', types)


class TestTimesliceGearDetection(unittest.TestCase):
    def _make_timeslice(self, note_text: str, code: str = 'TEST', name: str = 'Test Airfield') -> ET.Element:
        xml = f'''
        <a:AirportHeliportTimeSlice xmlns:a="http://www.aixm.aero/schema/5.1">
          <a:designator>{code}</a:designator>
          <a:name>{name}</a:name>
          <a:annotation>
            <a:Note>
              <a:translatedNote>
                <a:LinguisticNote>
                  <a:note>{note_text}</a:note>
                </a:LinguisticNote>
              </a:translatedNote>
            </a:Note>
          </a:annotation>
        </a:AirportHeliportTimeSlice>
        '''
        return ET.fromstring(xml)

    def test_timeslice_has_gear_true(self):
        ts = self._make_timeslice('A-GEAR BAK-12 at 1500 FT FM THR')
        self.assertTrue(mod.timeslice_has_gear(ts))

    def test_timeslice_has_gear_false(self):
        ts = self._make_timeslice('No special equipment installed')
        self.assertFalse(mod.timeslice_has_gear(ts))

    def test_extract_designator_and_name(self):
        ts = self._make_timeslice('A‑GEAR present', code='ABCD', name='Alpha Base')
        code, name = mod.extract_designator_and_name(ts)
        self.assertEqual(code, 'ABCD')
        self.assertEqual(name, 'Alpha Base')

    def test_sample_gear_note(self):
        ts = self._make_timeslice('A-GEAR BAK-14 located centerfield')
        note = mod.sample_gear_note(ts)
        self.assertIsNotNone(note)
        self.assertIn('BAK-14', note)


class TestFileLevelFunctions(unittest.TestCase):
    def test_iter_airport_timeslices_reads_file(self):
        # Build a tiny AIXM-like file with two timeslices
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <root xmlns:a="http://www.aixm.aero/schema/5.1">
          <a:AirportHeliport>
            <a:timeSlice>
              <a:AirportHeliportTimeSlice>
                <a:designator>AAA</a:designator>
                <a:name>Alpha</a:name>
                <a:annotation><a:Note><a:translatedNote><a:LinguisticNote><a:note>A-GEAR BAK-12</a:note></a:LinguisticNote></a:translatedNote></a:Note></a:annotation>
              </a:AirportHeliportTimeSlice>
            </a:timeSlice>
            <a:timeSlice>
              <a:AirportHeliportTimeSlice>
                <a:designator>BBB</a:designator>
                <a:name>Bravo</a:name>
              </a:AirportHeliportTimeSlice>
            </a:timeSlice>
          </a:AirportHeliport>
        </root>'''
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'small.xml')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(xml)
            # Consume generator and compute booleans immediately to avoid cleared elements
            has_gear = []
            count = 0
            for ts in mod.iter_airport_timeslices(p):
                count += 1
                has_gear.append(mod.timeslice_has_gear(ts))
            self.assertEqual(count, 2)
            self.assertIn(True, has_gear)

    def test_find_xml_files_priority(self):
        with tempfile.TemporaryDirectory() as td:
            # create non-priority xml and priority APT_AIXM.xml
            other = os.path.join(td, 'x.xml')
            with open(other, 'w') as f:
                f.write('<r/>')
            prio = os.path.join(td, 'APT_AIXM.xml')
            with open(prio, 'w') as f:
                f.write('<r/>')
            files = list(mod.find_xml_files(td))
            # Only priority should be yielded then return
            self.assertEqual(files, [prio])


class TestRunwayIndexing(unittest.TestCase):
    def test_index_runways_with_displaced_threshold(self):
        # Minimal synthetic XML capturing relevant structure and id patterns
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <root xmlns:aixm="http://www.aixm.aero/schema/5.1" xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:xlink="http://www.w3.org/1999/xlink">
          <aixm:Runway gml:id="RWY_ABC123">
            <aixm:timeSlice>
              <aixm:RunwayTimeSlice>
                <aixm:designator>18/36</aixm:designator>
                <aixm:associatedAirportHeliport xlink:href="#/aixm:AirportHeliport[@gml:id='AH_1']"/>
                <aixm:lengthStrip>8000</aixm:lengthStrip>
                <aixm:widthStrip>150</aixm:widthStrip>
              </aixm:RunwayTimeSlice>
            </aixm:timeSlice>
          </aixm:Runway>
          <aixm:Runway gml:id="RWY_BASE_END_ABC123">
            <aixm:timeSlice>
              <aixm:RunwayTimeSlice>
                <aixm:designator>18</aixm:designator>
                <aixm:associatedAirportHeliport xlink:href="#/aixm:AirportHeliport[@gml:id='AH_1']"/>
              </aixm:RunwayTimeSlice>
            </aixm:timeSlice>
          </aixm:Runway>
          <aixm:Runway gml:id="RWY_RECIPROCAL_END_ABC123">
            <aixm:timeSlice>
              <aixm:RunwayTimeSlice>
                <aixm:designator>36</aixm:designator>
                <aixm:associatedAirportHeliport xlink:href="#/aixm:AirportHeliport[@gml:id='AH_1']"/>
              </aixm:RunwayTimeSlice>
            </aixm:timeSlice>
          </aixm:Runway>
          <aixm:RunwayDirection gml:id="RWY_DIRECTION_BASE_END_ABC123">
            <aixm:timeSlice>
              <aixm:RunwayDirectionTimeSlice>
                <aixm:displacedThresholdLength>500</aixm:displacedThresholdLength>
              </aixm:RunwayDirectionTimeSlice>
            </aixm:timeSlice>
          </aixm:RunwayDirection>
          <aixm:RunwayDirection gml:id="RWY_DIRECTION_RECIPROCAL_END_ABC123">
            <aixm:timeSlice>
              <aixm:RunwayDirectionTimeSlice>
                <aixm:displacedThresholdLength>0</aixm:displacedThresholdLength>
              </aixm:RunwayDirectionTimeSlice>
            </aixm:timeSlice>
          </aixm:RunwayDirection>
        </root>'''
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'rwy.xml')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(xml)
            by_airport = mod.index_runways(p)
        self.assertIn('AH_1', by_airport)
        ends = by_airport['AH_1']
        # Expect two runway ends with adjusted lengths
        end_map = {e['designator']: e for e in ends}
        self.assertEqual(end_map['18']['length_ft'], 8000 - 500)
        self.assertEqual(end_map['36']['length_ft'], 8000)
        self.assertEqual(end_map['18']['width_ft'], 150)


class TestAirportIndexing(unittest.TestCase):
    def test_index_airports_extracts_core_fields_and_gear(self):
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <root xmlns:aixm="http://www.aixm.aero/schema/5.1" xmlns:gml="http://www.opengis.net/gml/3.2">
          <aixm:AirportHeliport gml:id="AH_1">
            <aixm:timeSlice>
              <aixm:AirportHeliportTimeSlice>
                <aixm:designator>TEST</aixm:designator>
                <aixm:name>Test Field</aixm:name>
                <aixm:locationIndicatorICAO>KTEST</aixm:locationIndicatorICAO>
                <aixm:ARP>
                  <aixm:ElevatedPoint>
                    <gml:pos>-120.5 35.2</gml:pos>
                  </aixm:ElevatedPoint>
                </aixm:ARP>
                <aixm:annotation>
                  <aixm:Note>
                    <aixm:translatedNote>
                      <aixm:LinguisticNote>
                        <aixm:note>A-GEAR BAK-12, (1200 FT)</aixm:note>
                      </aixm:LinguisticNote>
                    </aixm:translatedNote>
                  </aixm:Note>
                </aixm:annotation>
              </aixm:AirportHeliportTimeSlice>
            </aixm:timeSlice>
          </aixm:AirportHeliport>
        </root>'''
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'apt.xml')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(xml)
            airports, gear_notes = mod.index_airports(p)
        self.assertIn('AH_1', airports)
        info = airports['AH_1']
        self.assertEqual(info['code'], 'TEST')
        self.assertEqual(info['name'], 'Test Field')
        self.assertEqual(info['icao'], 'KTEST')
        self.assertAlmostEqual(info['lat'], 35.2)
        self.assertAlmostEqual(info['lon'], -120.5)
        self.assertIn('AH_1', gear_notes)
        self.assertTrue(any('BAK-12' in n for n in gear_notes['AH_1']))


if __name__ == '__main__':
    unittest.main()
