"""
Unit tests for enrollment methods in views.py

"""

from django.test.utils import override_settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from courseware.access import _course_staff_group_name
from courseware.tests.helpers import LoginEnrollmentTestCase
from courseware.tests.modulestore_config import TEST_DATA_XML_MODULESTORE
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.tests.factories import CourseFactory
from student.tests.factories import UserFactory, CourseEnrollmentFactory, AdminFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from courseware.tests.tests import TEST_DATA_MONGO_MODULESTORE, LoginEnrollmentTestCase
from student.models import CourseEnrollment, CourseEnrollmentAllowed
from instructor.views import get_and_clean_student_list, send_mail_to_student
from django.core import mail

USER_COUNT = 4


@override_settings(MODULESTORE=TEST_DATA_MONGO_MODULESTORE)
class TestInstructorEnrollsStudent(ModuleStoreTestCase, LoginEnrollmentTestCase):
    """
    Check Enrollment/Unenrollment with/without auto-enrollment on activation and with/without email notification
    """

    def setUp(self):

        instructor = AdminFactory.create()
        self.client.login(username=instructor.username, password='test')

        self.course = CourseFactory.create()

        self.users = [
            UserFactory.create(username="student%d" % i, email="student%d@test.com" % i)
            for i in xrange(USER_COUNT)
        ]

        for user in self.users:
            CourseEnrollmentFactory.create(user=user, course_id=self.course.id)

        # Empty the test outbox
        mail.outbox = []

    def test_unenrollment_email_off(self):
        """
        Do un-enrollment email off test
        """

        course = self.course

        #Run the Un-enroll students command
        url = reverse('instructor_dashboard', kwargs={'course_id': course.id})
        response = self.client.post(url, {'action': 'Unenroll multiple students', 'multiple_students': 'student0@test.com student1@test.com'})

        #Check the page output
        self.assertContains(response, '<td>student0@test.com</td>')
        self.assertContains(response, '<td>student1@test.com</td>')
        self.assertContains(response, '<td>un-enrolled</td>')

        #Check the enrollment table
        user = User.objects.get(email='student0@test.com')
        ce = CourseEnrollment.objects.filter(course_id=course.id, user=user)
        self.assertEqual(0, len(ce))

        user = User.objects.get(email='student1@test.com')
        ce = CourseEnrollment.objects.filter(course_id=course.id, user=user)
        self.assertEqual(0, len(ce))

        #Check the outbox
        self.assertEqual(len(mail.outbox), 0)

    def test_enrollment_new_student_autoenroll_on_email_off(self):
        """
        Do auto-enroll on, email off test
        """

        course = self.course

        #Run the Enroll students command
        url = reverse('instructor_dashboard', kwargs={'course_id': course.id})
        response = self.client.post(url, {'action': 'Enroll multiple students', 'multiple_students': 'student1_1@test.com, student1_2@test.com', 'auto_enroll': 'on'})

        #Check the page output
        self.assertContains(response, '<td>student1_1@test.com</td>')
        self.assertContains(response, '<td>student1_2@test.com</td>')
        self.assertContains(response, '<td>user does not exist, enrollment allowed, pending with auto enrollment on</td>')

        #Check the outbox
        self.assertEqual(len(mail.outbox), 0)

        #Check the enrollmentallowed db entries
        cea = CourseEnrollmentAllowed.objects.filter(email='student1_1@test.com', course_id=course.id)
        self.assertEqual(1, cea[0].auto_enroll)
        cea = CourseEnrollmentAllowed.objects.filter(email='student1_2@test.com', course_id=course.id)
        self.assertEqual(1, cea[0].auto_enroll)

        #Check there is no enrollment db entry other than for the other students
        ce = CourseEnrollment.objects.filter(course_id=course.id)
        self.assertEqual(4, len(ce))

        #Create and activate student accounts with same email
        self.student1 = 'student1_1@test.com'
        self.password = 'bar'
        self.create_account('s1_1', self.student1, self.password)
        self.activate_user(self.student1)

        self.student2 = 'student1_2@test.com'
        self.create_account('s1_2', self.student2, self.password)
        self.activate_user(self.student2)

        #Check students are enrolled
        user = User.objects.get(email='student1_1@test.com')
        ce = CourseEnrollment.objects.filter(course_id=course.id, user=user)
        self.assertEqual(1, len(ce))

        user = User.objects.get(email='student1_2@test.com')
        ce = CourseEnrollment.objects.filter(course_id=course.id, user=user)
        self.assertEqual(1, len(ce))

    def test_repeat_enroll(self):
        """
        Try to enroll an already enrolled student
        """

        course = self.course

        url = reverse('instructor_dashboard', kwargs={'course_id': course.id})
        response = self.client.post(url, {'action': 'Enroll multiple students', 'multiple_students': 'student0@test.com', 'auto_enroll': 'on'})
        self.assertContains(response, '<td>student0@test.com</td>')
        self.assertContains(response, '<td>already enrolled</td>')

    def test_enrollmemt_new_student_autoenroll_off_email_off(self):
        """
        Do auto-enroll off, email off test
        """

        course = self.course

        #Run the Enroll students command
        url = reverse('instructor_dashboard', kwargs={'course_id': course.id})
        response = self.client.post(url, {'action': 'Enroll multiple students', 'multiple_students': 'student2_1@test.com, student2_2@test.com'})

        #Check the page output
        self.assertContains(response, '<td>student2_1@test.com</td>')
        self.assertContains(response, '<td>student2_2@test.com</td>')
        self.assertContains(response, '<td>user does not exist, enrollment allowed, pending with auto enrollment off</td>')

        #Check the outbox
        self.assertEqual(len(mail.outbox), 0)

        #Check the enrollmentallowed db entries
        cea = CourseEnrollmentAllowed.objects.filter(email='student2_1@test.com', course_id=course.id)
        self.assertEqual(0, cea[0].auto_enroll)
        cea = CourseEnrollmentAllowed.objects.filter(email='student2_2@test.com', course_id=course.id)
        self.assertEqual(0, cea[0].auto_enroll)

        #Check there is no enrollment db entry other than for the setup instructor and students
        ce = CourseEnrollment.objects.filter(course_id=course.id)
        self.assertEqual(4, len(ce))

        #Create and activate student accounts with same email
        self.student = 'student2_1@test.com'
        self.password = 'bar'
        self.create_account('s2_1', self.student, self.password)
        self.activate_user(self.student)

        self.student = 'student2_2@test.com'
        self.create_account('s2_2', self.student, self.password)
        self.activate_user(self.student)

        #Check students are not enrolled
        user = User.objects.get(email='student2_1@test.com')
        ce = CourseEnrollment.objects.filter(course_id=course.id, user=user)
        self.assertEqual(0, len(ce))
        user = User.objects.get(email='student2_2@test.com')
        ce = CourseEnrollment.objects.filter(course_id=course.id, user=user)
        self.assertEqual(0, len(ce))

    def test_get_and_clean_student_list(self):
        """
        Clean user input test
        """

        string = "abc@test.com, def@test.com ghi@test.com \n \n jkl@test.com   \n mno@test.com   "
        cleaned_string, cleaned_string_lc = get_and_clean_student_list(string)
        self.assertEqual(cleaned_string, ['abc@test.com', 'def@test.com', 'ghi@test.com', 'jkl@test.com', 'mno@test.com'])

    def test_enrollment_email_on(self):
        """
        Do email on enroll test
        """

        course = self.course

        #Create activated, but not enrolled, user
        UserFactory.create(username="student3_0", email="student3_0@test.com")

        url = reverse('instructor_dashboard', kwargs={'course_id': course.id})
        response = self.client.post(url, {'action': 'Enroll multiple students', 'multiple_students': 'student3_0@test.com, student3_1@test.com, student3_2@test.com', 'auto_enroll': 'on', 'email_students': 'on'})

        #Check the page output
        self.assertContains(response, '<td>student3_0@test.com</td>')
        self.assertContains(response, '<td>student3_1@test.com</td>')
        self.assertContains(response, '<td>student3_2@test.com</td>')
        self.assertContains(response, '<td>added, email sent</td>')
        self.assertContains(response, '<td>user does not exist, enrollment allowed, pending with auto enrollment on, email sent</td>')

        #Check the outbox
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(mail.outbox[0].subject, 'You have been enrolled in MITx/999/Robot_Super_Course')

        self.assertEqual(mail.outbox[1].subject, 'You have been invited to register for MITx/999/Robot_Super_Course')
        self.assertEqual(mail.outbox[1].body, "Dear student,\n\nYou have been invited to join MITx/999/Robot_Super_Course at edx.org by a member of the course staff.\n\n" +
                                              "To finish your registration, please visit https://edx.org/register and fill out the registration form.\n" +
                                              "Once you have registered and activated your account, you will see MITx/999/Robot_Super_Course listed on your dashboard.\n\n" +
                                              "----\nThis email was automatically sent from edx.org to student3_1@test.com")

    def test_unenrollment_email_on(self):
        """
        Do email on unenroll test
        """

        course = self.course

        #Create invited, but not registered, user
        cea = CourseEnrollmentAllowed(email='student4_0@test.com', course_id=course.id)
        cea.save()

        url = reverse('instructor_dashboard', kwargs={'course_id': course.id})
        response = self.client.post(url, {'action': 'Unenroll multiple students', 'multiple_students': 'student4_0@test.com, student2@test.com, student3@test.com', 'email_students': 'on'})

        #Check the page output
        self.assertContains(response, '<td>student2@test.com</td>')
        self.assertContains(response, '<td>student3@test.com</td>')
        self.assertContains(response, '<td>un-enrolled, email sent</td>')

        #Check the outbox
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(mail.outbox[0].subject, 'You have been un-enrolled from MITx/999/Robot_Super_Course')
        self.assertEqual(mail.outbox[0].body, "Dear Student,\n\nYou have been un-enrolled from course MITx/999/Robot_Super_Course by a member of the course staff. " +
                         "Please disregard the invitation previously sent.\n\n" +
                         "----\nThis email was automatically sent from edx.org to student4_0@test.com")
        self.assertEqual(mail.outbox[1].subject, 'You have been un-enrolled from MITx/999/Robot_Super_Course')

    def test_send_mail_to_student(self):
        """
        Do invalid mail template test
        """

        d = {'message': 'message_type_that_doesn\'t_exist'}

        send_mail_ret = send_mail_to_student('student0@test.com', d)
        self.assertFalse(send_mail_ret)
