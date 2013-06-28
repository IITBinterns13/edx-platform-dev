# -*- coding: utf-8 -*-

import unittest
from fs.memoryfs import MemoryFS

from lxml import etree
from mock import Mock, patch

from xmodule.xml_module import is_pointer_tag
from xmodule.modulestore import Location
from xmodule.modulestore.xml import ImportSystem, XMLModuleStore
from xmodule.modulestore.inheritance import compute_inherited_metadata
from xmodule.fields import Date

from .test_export import DATA_DIR
import datetime
from django.utils.timezone import UTC

ORG = 'test_org'
COURSE = 'test_course'


class DummySystem(ImportSystem):

    @patch('xmodule.modulestore.xml.OSFS', lambda dir: MemoryFS())
    def __init__(self, load_error_modules):

        xmlstore = XMLModuleStore("data_dir", course_dirs=[], load_error_modules=load_error_modules)
        course_id = "/".join([ORG, COURSE, 'test_run'])
        course_dir = "test_dir"
        policy = {}
        error_tracker = Mock()
        parent_tracker = Mock()

        super(DummySystem, self).__init__(
            xmlstore,
            course_id,
            course_dir,
            policy,
            error_tracker,
            parent_tracker,
            load_error_modules=load_error_modules,
        )

    def render_template(self, _template, _context):
        raise Exception("Shouldn't be called")


class BaseCourseTestCase(unittest.TestCase):
    '''Make sure module imports work properly, including for malformed inputs'''
    @staticmethod
    def get_system(load_error_modules=True):
        '''Get a dummy system'''
        return DummySystem(load_error_modules)

    def get_course(self, name):
        """Get a test course by directory name.  If there's more than one, error."""
        print("Importing {0}".format(name))

        modulestore = XMLModuleStore(DATA_DIR, course_dirs=[name])
        courses = modulestore.get_courses()
        self.assertEquals(len(courses), 1)
        return courses[0]


class ImportTestCase(BaseCourseTestCase):
    date = Date()

    def test_fallback(self):
        '''Check that malformed xml loads as an ErrorDescriptor.'''

        # Use an exotic character to also flush out Unicode issues.
        bad_xml = u'''<sequential display_name="oops\N{SNOWMAN}"><video url="hi"></sequential>'''
        system = self.get_system()

        descriptor = system.process_xml(bad_xml)

        self.assertEqual(descriptor.__class__.__name__, 'ErrorDescriptor')

    def test_unique_url_names(self):
        '''Check that each error gets its very own url_name'''
        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        bad_xml2 = '''<sequential url_name="oops"><video url="hi"></sequential>'''
        system = self.get_system()

        descriptor1 = system.process_xml(bad_xml)
        descriptor2 = system.process_xml(bad_xml2)

        self.assertNotEqual(descriptor1.location, descriptor2.location)

    def test_reimport(self):
        '''Make sure an already-exported error xml tag loads properly'''

        self.maxDiff = None
        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        system = self.get_system()
        descriptor = system.process_xml(bad_xml)

        resource_fs = None
        tag_xml = descriptor.export_to_xml(resource_fs)
        re_import_descriptor = system.process_xml(tag_xml)

        self.assertEqual(re_import_descriptor.__class__.__name__,
                         'ErrorDescriptor')

        self.assertEqual(descriptor.contents,
                         re_import_descriptor.contents)
        self.assertEqual(descriptor.error_msg,
                         re_import_descriptor.error_msg)

    def test_fixed_xml_tag(self):
        """Make sure a tag that's been fixed exports as the original tag type"""

        # create a error tag with valid xml contents
        root = etree.Element('error')
        good_xml = '''<sequential display_name="fixed"><video url="hi"/></sequential>'''
        root.text = good_xml

        xml_str_in = etree.tostring(root)

        # load it
        system = self.get_system()
        descriptor = system.process_xml(xml_str_in)

        # export it
        resource_fs = None
        xml_str_out = descriptor.export_to_xml(resource_fs)

        # Now make sure the exported xml is a sequential
        xml_out = etree.fromstring(xml_str_out)
        self.assertEqual(xml_out.tag, 'sequential')

    def test_metadata_import_export(self):
        """Two checks:
            - unknown metadata is preserved across import-export
            - inherited metadata doesn't leak to children.
        """
        system = self.get_system()
        v = 'March 20 17:00'
        url_name = 'test1'
        start_xml = '''
        <course org="{org}" course="{course}"
                due="{due}" url_name="{url_name}" unicorn="purple">
            <chapter url="hi" url_name="ch" display_name="CH">
                <html url_name="h" display_name="H">Two houses, ...</html>
            </chapter>
        </course>'''.format(due=v, org=ORG, course=COURSE, url_name=url_name)
        descriptor = system.process_xml(start_xml)
        compute_inherited_metadata(descriptor)

        # pylint: disable=W0212
        print(descriptor, descriptor._model_data)
        self.assertEqual(descriptor.lms.due, ImportTestCase.date.from_json(v))

        # Check that the child inherits due correctly
        child = descriptor.get_children()[0]
        self.assertEqual(child.lms.due, ImportTestCase.date.from_json(v))
        self.assertEqual(child._inheritable_metadata, child._inherited_metadata)
        self.assertEqual(2, len(child._inherited_metadata))
        self.assertLessEqual(
            ImportTestCase.date.from_json(child._inherited_metadata['start']),
            datetime.datetime.now(UTC())
        )
        self.assertEqual(v, child._inherited_metadata['due'])

        # Now export and check things
        resource_fs = MemoryFS()
        exported_xml = descriptor.export_to_xml(resource_fs)

        # Check that the exported xml is just a pointer
        print("Exported xml:", exported_xml)
        pointer = etree.fromstring(exported_xml)
        self.assertTrue(is_pointer_tag(pointer))
        # but it's a special case course pointer
        self.assertEqual(pointer.attrib['course'], COURSE)
        self.assertEqual(pointer.attrib['org'], ORG)

        # Does the course still have unicorns?
        with resource_fs.open('course/{url_name}.xml'.format(url_name=url_name)) as f:
            course_xml = etree.fromstring(f.read())

        self.assertEqual(course_xml.attrib['unicorn'], 'purple')

        # the course and org tags should be _only_ in the pointer
        self.assertTrue('course' not in course_xml.attrib)
        self.assertTrue('org' not in course_xml.attrib)

        # did we successfully strip the url_name from the definition contents?
        self.assertTrue('url_name' not in course_xml.attrib)

        # Does the chapter tag now have a due attribute?
        # hardcoded path to child
        with resource_fs.open('chapter/ch.xml') as f:
            chapter_xml = etree.fromstring(f.read())
        self.assertEqual(chapter_xml.tag, 'chapter')
        self.assertFalse('due' in chapter_xml.attrib)

    def test_metadata_no_inheritance(self):
        """
        Checks that default value of None (for due) does not get marked as inherited.
        """
        system = self.get_system()
        url_name = 'test1'
        start_xml = '''
        <course org="{org}" course="{course}"
                url_name="{url_name}" unicorn="purple">
            <chapter url="hi" url_name="ch" display_name="CH">
                <html url_name="h" display_name="H">Two houses, ...</html>
            </chapter>
        </course>'''.format(org=ORG, course=COURSE, url_name=url_name)
        descriptor = system.process_xml(start_xml)
        compute_inherited_metadata(descriptor)

        self.assertEqual(descriptor.lms.due, None)

        # Check that the child does not inherit a value for due
        child = descriptor.get_children()[0]
        self.assertEqual(child.lms.due, None)
        # pylint: disable=W0212
        self.assertEqual(child._inheritable_metadata, child._inherited_metadata)
        self.assertEqual(1, len(child._inherited_metadata))
        # why do these tests look in the internal structure v just calling child.start?
        self.assertLessEqual(
            ImportTestCase.date.from_json(child._inherited_metadata['start']),
            datetime.datetime.now(UTC())
        )

    def test_metadata_override_default(self):
        """
        Checks that due date can be overriden at child level.
        """
        system = self.get_system()
        course_due = 'March 20 17:00'
        child_due = 'April 10 00:00'
        url_name = 'test1'
        start_xml = '''
        <course org="{org}" course="{course}"
                due="{due}" url_name="{url_name}" unicorn="purple">
            <chapter url="hi" url_name="ch" display_name="CH">
                <html url_name="h" display_name="H">Two houses, ...</html>
            </chapter>
        </course>'''.format(due=course_due, org=ORG, course=COURSE, url_name=url_name)
        descriptor = system.process_xml(start_xml)
        child = descriptor.get_children()[0]
        # pylint: disable=W0212
        child._model_data['due'] = child_due
        compute_inherited_metadata(descriptor)

        self.assertEqual(descriptor.lms.due, ImportTestCase.date.from_json(course_due))
        self.assertEqual(child.lms.due, ImportTestCase.date.from_json(child_due))
        # Test inherited metadata. Due does not appear here (because explicitly set on child).
        self.assertEqual(1, len(child._inherited_metadata))
        self.assertLessEqual(
            ImportTestCase.date.from_json(child._inherited_metadata['start']),
            datetime.datetime.now(UTC()))
        # Test inheritable metadata. This has the course inheritable value for due.
        self.assertEqual(2, len(child._inheritable_metadata))
        self.assertEqual(course_due, child._inheritable_metadata['due'])

    def test_is_pointer_tag(self):
        """
        Check that is_pointer_tag works properly.
        """

        yes = ["""<html url_name="blah"/>""",
               """<html url_name="blah"></html>""",
               """<html url_name="blah">    </html>""",
               """<problem url_name="blah"/>""",
               """<course org="HogwartsX" course="Mathemagics" url_name="3.14159"/>"""]

        no = ["""<html url_name="blah" also="this"/>""",
              """<html url_name="blah">some text</html>""",
              """<problem url_name="blah"><sub>tree</sub></problem>""",
              """<course org="HogwartsX" course="Mathemagics" url_name="3.14159">
                     <chapter>3</chapter>
                  </course>
              """]

        for xml_str in yes:
            print("should be True for {0}".format(xml_str))
            self.assertTrue(is_pointer_tag(etree.fromstring(xml_str)))

        for xml_str in no:
            print("should be False for {0}".format(xml_str))
            self.assertFalse(is_pointer_tag(etree.fromstring(xml_str)))

    def test_metadata_inherit(self):
        """Make sure that metadata is inherited properly"""

        print("Starting import")
        course = self.get_course('toy')

        def check_for_key(key, node):
            "recursive check for presence of key"
            print("Checking {0}".format(node.location.url()))
            self.assertTrue(key in node._model_data)
            for c in node.get_children():
                check_for_key(key, c)

        check_for_key('graceperiod', course)

    def test_policy_loading(self):
        """Make sure that when two courses share content with the same
        org and course names, policy applies to the right one."""

        toy = self.get_course('toy')
        two_toys = self.get_course('two_toys')

        self.assertEqual(toy.url_name, "2012_Fall")
        self.assertEqual(two_toys.url_name, "TT_2012_Fall")

        toy_ch = toy.get_children()[0]
        two_toys_ch = two_toys.get_children()[0]

        self.assertEqual(toy_ch.display_name, "Overview")
        self.assertEqual(two_toys_ch.display_name, "Two Toy Overview")

        # Also check that the grading policy loaded
        self.assertEqual(two_toys.grade_cutoffs['C'], 0.5999)

        # Also check that keys from policy are run through the
        # appropriate attribute maps -- 'graded' should be True, not 'true'
        self.assertEqual(toy.lms.graded, True)

    def test_definition_loading(self):
        """When two courses share the same org and course name and
        both have a module with the same url_name, the definitions shouldn't clash.

        TODO (vshnayder): once we have a CMS, this shouldn't
        happen--locations should uniquely name definitions.  But in
        our imperfect XML world, it can (and likely will) happen."""

        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['toy', 'two_toys'])

        toy_id = "edX/toy/2012_Fall"
        two_toy_id = "edX/toy/TT_2012_Fall"

        location = Location(["i4x", "edX", "toy", "video", "Welcome"])
        toy_video = modulestore.get_instance(toy_id, location)
        two_toy_video = modulestore.get_instance(two_toy_id, location)
        self.assertEqual(toy_video.youtube_id_1_0, "p2Q6BrNhdh8")
        self.assertEqual(two_toy_video.youtube_id_1_0, "p2Q6BrNhdh9")

    def test_colon_in_url_name(self):
        """Ensure that colons in url_names convert to file paths properly"""

        print("Starting import")
        # Not using get_courses because we need the modulestore object too afterward
        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['toy'])
        courses = modulestore.get_courses()
        self.assertEquals(len(courses), 1)
        course = courses[0]
        course_id = course.id

        print("course errors:")
        for (msg, err) in modulestore.get_item_errors(course.location):
            print(msg)
            print(err)

        chapters = course.get_children()
        self.assertEquals(len(chapters), 2)

        ch2 = chapters[1]
        self.assertEquals(ch2.url_name, "secret:magic")

        print("Ch2 location: ", ch2.location)

        also_ch2 = modulestore.get_instance(course_id, ch2.location)
        self.assertEquals(ch2, also_ch2)

        print("making sure html loaded")
        cloc = course.location
        loc = Location(cloc.tag, cloc.org, cloc.course, 'html', 'secret:toylab')
        html = modulestore.get_instance(course_id, loc)
        self.assertEquals(html.display_name, "Toy lab")

    def test_url_name_mangling(self):
        """
        Make sure that url_names are only mangled once.
        """

        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['toy'])

        toy_id = "edX/toy/2012_Fall"

        course = modulestore.get_course(toy_id)
        chapters = course.get_children()
        ch1 = chapters[0]
        sections = ch1.get_children()

        self.assertEqual(len(sections), 4)

        for i in (2, 3):
            video = sections[i]
            # Name should be 'video_{hash}'
            print("video {0} url_name: {1}".format(i, video.url_name))

            self.assertEqual(len(video.url_name), len('video_') + 12)

    def test_poll_and_conditional_import(self):
        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['conditional_and_poll'])

        course = modulestore.get_courses()[0]
        chapters = course.get_children()
        ch1 = chapters[0]
        sections = ch1.get_children()

        self.assertEqual(len(sections), 1)

        location = course.location

        conditional_location = Location(
            location.tag, location.org, location.course,
            'conditional', 'condone'
        )
        module = modulestore.get_instance(course.id, conditional_location)
        self.assertEqual(len(module.children), 1)

        poll_location = Location(
            location.tag, location.org, location.course,
            'poll_question', 'first_poll'
        )
        module = modulestore.get_instance(course.id, poll_location)
        self.assertEqual(len(module.get_children()), 0)
        self.assertEqual(module.voted, False)
        self.assertEqual(module.poll_answer, '')
        self.assertEqual(module.poll_answers, {})
        self.assertEqual(
            module.answers,
            [
                {'text': u'Yes', 'id': 'Yes'},
                {'text': u'No', 'id': 'No'},
                {'text': u"Don't know", 'id': 'Dont_know'}
            ]
        )

    def test_error_on_import(self):
        '''Check that when load_error_module is false, an exception is raised, rather than returning an ErrorModule'''

        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        system = self.get_system(False)

        self.assertRaises(etree.XMLSyntaxError, system.process_xml, bad_xml)

    def test_graphicslidertool_import(self):
        '''
        Check to see if definition_from_xml in gst_module.py
        works properly.  Pulls data from the graphic_slider_tool directory
        in the test data directory.
        '''
        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['graphic_slider_tool'])

        sa_id = "edX/gst_test/2012_Fall"
        location = Location(["i4x", "edX", "gst_test", "graphical_slider_tool", "sample_gst"])
        gst_sample = modulestore.get_instance(sa_id, location)
        render_string_from_sample_gst_xml = """
        <slider var="a" style="width:400px;float:left;"/>\
<plot style="margin-top:15px;margin-bottom:15px;"/>""".strip()
        self.assertEqual(gst_sample.render, render_string_from_sample_gst_xml)

    def test_word_cloud_import(self):
        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['word_cloud'])

        course = modulestore.get_courses()[0]
        chapters = course.get_children()
        ch1 = chapters[0]
        sections = ch1.get_children()

        self.assertEqual(len(sections), 1)

        location = course.location
        location = Location(
            location.tag, location.org, location.course,
            'word_cloud', 'cloud1'
        )
        module = modulestore.get_instance(course.id, location)
        self.assertEqual(len(module.get_children()), 0)
        self.assertEqual(module.num_inputs, 5)
        self.assertEqual(module.num_top_words, 250)

    def test_cohort_config(self):
        """
        Check that cohort config parsing works right.
        """
        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['toy'])

        toy_id = "edX/toy/2012_Fall"

        course = modulestore.get_course(toy_id)

        # No config -> False
        self.assertFalse(course.is_cohorted)

        # empty config -> False
        course.cohort_config = {}
        self.assertFalse(course.is_cohorted)

        # false config -> False
        course.cohort_config = {'cohorted': False}
        self.assertFalse(course.is_cohorted)

        # and finally...
        course.cohort_config = {'cohorted': True}
        self.assertTrue(course.is_cohorted)
