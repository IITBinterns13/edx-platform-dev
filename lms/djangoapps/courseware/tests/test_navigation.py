from django.core.urlresolvers import reverse
from django.test.utils import override_settings

from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory

from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from helpers import LoginEnrollmentTestCase, check_for_get_code
from modulestore_config import TEST_DATA_MONGO_MODULESTORE


@override_settings(MODULESTORE=TEST_DATA_MONGO_MODULESTORE)
class TestNavigation(ModuleStoreTestCase, LoginEnrollmentTestCase):
    """
    Check that navigation state is saved properly.
    """

    STUDENT_INFO = [('view@test.com', 'foo'), ('view2@test.com', 'foo')]

    def setUp(self):

        self.test_course = CourseFactory.create(display_name='Robot_Sub_Course')
        self.course = CourseFactory.create(display_name='Robot_Super_Course')
        self.chapter0 = ItemFactory.create(parent_location=self.course.location,
                                           display_name='Overview')
        self.chapter9 = ItemFactory.create(parent_location=self.course.location,
                                           display_name='factory_chapter')
        self.section0 = ItemFactory.create(parent_location=self.chapter0.location,
                                           display_name='Welcome')
        self.section9 = ItemFactory.create(parent_location=self.chapter9.location,
                                           display_name='factory_section')

        # Create student accounts and activate them.
        for i in range(len(self.STUDENT_INFO)):
            email, password = self.STUDENT_INFO[i]
            username = 'u{0}'.format(i)
            self.create_account(username, email, password)
            self.activate_user(email)

    def test_redirects_first_time(self):
        """
        Verify that the first time we click on the courseware tab we are
        redirected to the 'Welcome' section.
        """
        email, password = self.STUDENT_INFO[0]
        self.login(email, password)
        self.enroll(self.course, True)
        self.enroll(self.test_course, True)

        resp = self.client.get(reverse('courseware',
                               kwargs={'course_id': self.course.id}))

        self.assertRedirects(resp, reverse(
            'courseware_section', kwargs={'course_id': self.course.id,
                                          'chapter': 'Overview',
                                          'section': 'Welcome'}))

    def test_redirects_second_time(self):
        """
        Verify the accordion remembers we've already visited the Welcome section
        and redirects correpondingly.
        """
        email, password = self.STUDENT_INFO[0]
        self.login(email, password)
        self.enroll(self.course, True)
        self.enroll(self.test_course, True)

        self.client.get(reverse('courseware_section', kwargs={'course_id': self.course.id,
                                                              'chapter': 'Overview',
                                                              'section': 'Welcome'}))

        resp = self.client.get(reverse('courseware',
                               kwargs={'course_id': self.course.id}))

        self.assertRedirects(resp, reverse('courseware_chapter',
                                           kwargs={'course_id': self.course.id,
                                                   'chapter': 'Overview'}))

    def test_accordion_state(self):
        """
        Verify the accordion remembers which chapter you were last viewing.
        """
        email, password = self.STUDENT_INFO[0]
        self.login(email, password)
        self.enroll(self.course, True)
        self.enroll(self.test_course, True)

        # Now we directly navigate to a section in a chapter other than 'Overview'.
        check_for_get_code(self, 200, reverse('courseware_section',
                                              kwargs={'course_id': self.course.id,
                                                      'chapter': 'factory_chapter',
                                                      'section': 'factory_section'}))

        # And now hitting the courseware tab should redirect to 'factory_chapter'
        resp = self.client.get(reverse('courseware',
                               kwargs={'course_id': self.course.id}))

        self.assertRedirects(resp, reverse('courseware_chapter',
                                           kwargs={'course_id': self.course.id,
                                                   'chapter': 'factory_chapter'}))
