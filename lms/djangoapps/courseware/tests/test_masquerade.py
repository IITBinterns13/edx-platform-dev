"""
Unit tests for masquerade

Based on (and depends on) unit tests for courseware.

Notes for running by hand:

django-admin.py test --settings=lms.envs.test --pythonpath=. lms/djangoapps/courseware
"""

from django.test.utils import override_settings

from django.core.urlresolvers import reverse

from django.contrib.auth.models import Group, User
from courseware.access import _course_staff_group_name
from courseware.tests.helpers import LoginEnrollmentTestCase
from courseware.tests.modulestore_config import TEST_DATA_XML_MODULESTORE
from xmodule.modulestore.django import modulestore
import xmodule.modulestore.django
import json


@override_settings(MODULESTORE=TEST_DATA_XML_MODULESTORE)
class TestStaffMasqueradeAsStudent(LoginEnrollmentTestCase):
    '''
    Check for staff being able to masquerade as student
    '''

    def setUp(self):
        xmodule.modulestore.django._MODULESTORES = {}

        #self.full = modulestore().get_course("edX/full/6.002_Spring_2012")
        #self.toy = modulestore().get_course("edX/toy/2012_Fall")
        self.graded_course = modulestore().get_course("edX/graded/2012_Fall")

        # Create staff account
        self.instructor = 'view2@test.com'
        self.password = 'foo'
        self.create_account('u2', self.instructor, self.password)
        self.activate_user(self.instructor)

        def make_instructor(course):
            group_name = _course_staff_group_name(course.location)
            g = Group.objects.create(name=group_name)
            g.user_set.add(User.objects.get(email=self.instructor))

        make_instructor(self.graded_course)

        self.logout()
        self.login(self.instructor, self.password)
        self.enroll(self.graded_course)
        # self.factory = RequestFactory()

    def get_cw_section(self):
        url = reverse('courseware_section',
                      kwargs={'course_id': self.graded_course.id,
                              'chapter': 'GradedChapter',
                              'section': 'Homework1'})

        resp = self.client.get(url)

        print "url ", url
        return resp

    def test_staff_debug_for_staff(self):
        resp = self.get_cw_section()
        sdebug = '<div><a href="#i4x_edX_graded_problem_H1P1_debug" id="i4x_edX_graded_problem_H1P1_trig">Staff Debug Info</a></div>'

        self.assertTrue(sdebug in resp.content)

    def toggle_masquerade(self):
        '''
        Toggle masquerade state
        '''
        masq_url = reverse('masquerade-switch', kwargs={'marg': 'toggle'})
        print "masq_url ", masq_url
        resp = self.client.get(masq_url)
        return resp

    def test_no_staff_debug_for_student(self):
        togresp = self.toggle_masquerade()
        print "masq now ", togresp.content
        self.assertEqual(togresp.content, '{"status": "student"}', '')

        resp = self.get_cw_section()
        sdebug = '<div><a href="#i4x_edX_graded_problem_H1P1_debug" id="i4x_edX_graded_problem_H1P1_trig">Staff Debug Info</a></div>'

        self.assertFalse(sdebug in resp.content)

    def get_problem(self):
        pun = 'H1P1'
        problem_location = "i4x://edX/graded/problem/%s" % pun

        modx_url = reverse('modx_dispatch',
                           kwargs={'course_id': self.graded_course.id,
                                   'location': problem_location,
                                   'dispatch': 'problem_get', })

        resp = self.client.get(modx_url)

        print "modx_url ", modx_url
        return resp

    def test_showanswer_for_staff(self):
        resp = self.get_problem()
        html = json.loads(resp.content)['html']
        print html
        sabut = '<button class="show"><span class="show-label">Show Answer(s)</span> <span class="sr">(for question(s) above - adjacent to each field)</span></button>'
        self.assertTrue(sabut in html)

    def test_no_showanswer_for_student(self):
        togresp = self.toggle_masquerade()
        print "masq now ", togresp.content
        self.assertEqual(togresp.content, '{"status": "student"}', '')

        resp = self.get_problem()
        html = json.loads(resp.content)['html']
        print html
        sabut = '<button class="show"><span class="show-label">Show Answer(s)</span> <span class="sr">(for question(s) above - adjacent to each field)</span></button>'
        self.assertFalse(sabut in html)
