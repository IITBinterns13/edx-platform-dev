"""
Tests of the instructor dashboard gradebook
"""

from django.test.utils import override_settings
from django.core.urlresolvers import reverse
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from student.tests.factories import UserFactory, CourseEnrollmentFactory, AdminFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from courseware.tests.tests import TEST_DATA_MONGO_MODULESTORE
from capa.tests.response_xml_factory import StringResponseXMLFactory
from courseware.tests.factories import StudentModuleFactory
from xmodule.modulestore import Location
from xmodule.modulestore.django import modulestore


USER_COUNT = 11


@override_settings(MODULESTORE=TEST_DATA_MONGO_MODULESTORE)
class TestGradebook(ModuleStoreTestCase):
    grading_policy = None

    def setUp(self):
        instructor = AdminFactory.create()
        self.client.login(username=instructor.username, password='test')

        modulestore().request_cache = modulestore().metadata_inheritance_cache_subsystem = None

        course_data = {}
        if self.grading_policy is not None:
            course_data['grading_policy'] = self.grading_policy

        self.course = CourseFactory.create(data=course_data)
        chapter = ItemFactory.create(
            parent_location=self.course.location,
            template="i4x://edx/templates/sequential/Empty",
        )
        section = ItemFactory.create(
            parent_location=chapter.location,
            template="i4x://edx/templates/sequential/Empty",
            metadata={'graded': True, 'format': 'Homework'}
        )

        self.users = [UserFactory() for _ in xrange(USER_COUNT)]

        for user in self.users:
            CourseEnrollmentFactory.create(user=user, course_id=self.course.id)

        for i in xrange(USER_COUNT-1):
            template_name = "i4x://edx/templates/problem/Blank_Common_Problem"
            item = ItemFactory.create(
                parent_location=section.location,
                template=template_name,
                data=StringResponseXMLFactory().build_xml(answer='foo'),
                metadata={'rerandomize': 'always'}
            )

            for j, user in enumerate(self.users):
                StudentModuleFactory.create(
                    grade=1 if i < j else 0,
                    max_grade=1,
                    student=user,
                    course_id=self.course.id,
                    module_state_key=Location(item.location).url()
                )

        self.response = self.client.get(reverse('gradebook', args=(self.course.id,)))

    def test_response_code(self):
        self.assertEquals(self.response.status_code, 200)


class TestDefaultGradingPolicy(TestGradebook):
    def test_all_users_listed(self):
        for user in self.users:
            self.assertIn(user.username, unicode(self.response.content, 'utf-8'))

    def test_default_policy(self):
        # Default >= 50% passes, so Users 5-10 should be passing for Homework 1 [6]
        # One use at the top of the page [1]
        self.assertEquals(7, self.response.content.count('grade_Pass'))

        # Users 1-5 attempted Homework 1 (and get Fs) [4]
        # Users 1-10 attempted any homework (and get Fs) [10]
        # Users 4-10 scored enough to not get rounded to 0 for the class (and get Fs) [7]
        # One use at top of the page [1]
        self.assertEquals(22, self.response.content.count('grade_F'))

        # All other grades are None [29 categories * 11 users - 27 non-empty grades = 292]
        # One use at the top of the page [1]
        self.assertEquals(293, self.response.content.count('grade_None'))


class TestLetterCutoffPolicy(TestGradebook):
    grading_policy = {
        "GRADER": [
            {
                "type": "Homework",
                "min_count": 1,
                "drop_count": 0,
                "short_label": "HW",
                "weight": 1
            },
        ],
        "GRADE_CUTOFFS": {
            'A': .9,
            'B': .8,
            'C': .7,
            'D': .6,
        }
    }

    def test_styles(self):

        self.assertIn("grade_A {color:green;}", self.response.content)
        self.assertIn("grade_B {color:Chocolate;}", self.response.content)
        self.assertIn("grade_C {color:DarkSlateGray;}", self.response.content)
        self.assertIn("grade_D {color:DarkSlateGray;}", self.response.content)

    def test_assigned_grades(self):
        print self.response.content
        # Users 9-10 have >= 90% on Homeworks [2]
        # Users 9-10 have >= 90% on the class [2]
        # One use at the top of the page [1]
        self.assertEquals(5, self.response.content.count('grade_A'))

        # User 8 has 80 <= Homeworks < 90 [1]
        # User 8 has 80 <= class < 90 [1]
        # One use at the top of the page [1]
        self.assertEquals(3, self.response.content.count('grade_B'))

        # User 7 has 70 <= Homeworks < 80 [1]
        # User 7 has 70 <= class < 80 [1]
        # One use at the top of the page [1]
        self.assertEquals(3, self.response.content.count('grade_C'))

        # User 6 has 60 <= Homeworks < 70 [1]
        # User 6 has 60 <= class < 70 [1]
        # One use at the top of the page [1]
        self.assertEquals(3, self.response.content.count('grade_C'))

        # Users 1-5 have 60% > grades > 0 on Homeworks [5]
        # Users 1-5 have 60% > grades > 0 on the class [5]
        # One use at top of the page [1]
        self.assertEquals(11, self.response.content.count('grade_F'))

        # User 0 has 0 on Homeworks [1]
        # User 0 has 0 on the class [1]
        # One use at the top of the page [1]
        self.assertEquals(3, self.response.content.count('grade_None'))
