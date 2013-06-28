"""This file contains (or should), all access control logic for the courseware.
Ideally, it will be the only place that needs to know about any special settings
like DISABLE_START_DATES"""
import logging
from datetime import datetime, timedelta
from functools import partial

from django.conf import settings
from django.contrib.auth.models import Group

from xmodule.course_module import CourseDescriptor
from xmodule.error_module import ErrorDescriptor
from xmodule.modulestore import Location
from xmodule.x_module import XModule, XModuleDescriptor

from student.models import CourseEnrollmentAllowed
from external_auth.models import ExternalAuthMap
from courseware.masquerade import is_masquerading_as_student
from django.utils.timezone import UTC

DEBUG_ACCESS = False

log = logging.getLogger(__name__)


class CourseContextRequired(Exception):
    """
    Raised when a course_context is required to determine permissions
    """
    pass


def debug(*args, **kwargs):
    # to avoid overly verbose output, this is off by default
    if DEBUG_ACCESS:
        log.debug(*args, **kwargs)


def has_access(user, obj, action, course_context=None):
    """
    Check whether a user has the access to do action on obj.  Handles any magic
    switching based on various settings.

    Things this module understands:
    - start dates for modules
    - DISABLE_START_DATES
    - different access for instructor, staff, course staff, and students.

    user: a Django user object. May be anonymous.

    obj: The object to check access for.  A module, descriptor, location, or
                    certain special strings (e.g. 'global')

    action: A string specifying the action that the client is trying to perform.

    actions depend on the obj type, but include e.g. 'enroll' for courses.  See the
    type-specific functions below for the known actions for that type.

    course_context: A course_id specifying which course run this access is for.
        Required when accessing anything other than a CourseDescriptor, 'global',
        or a location with category 'course'

    Returns a bool.  It is up to the caller to actually deny access in a way
    that makes sense in context.
    """
    # delegate the work to type-specific functions.
    # (start with more specific types, then get more general)
    if isinstance(obj, CourseDescriptor):
        return _has_access_course_desc(user, obj, action)

    if isinstance(obj, ErrorDescriptor):
        return _has_access_error_desc(user, obj, action, course_context)

    # NOTE: any descriptor access checkers need to go above this
    if isinstance(obj, XModuleDescriptor):
        return _has_access_descriptor(user, obj, action, course_context)

    if isinstance(obj, XModule):
        return _has_access_xmodule(user, obj, action, course_context)

    if isinstance(obj, Location):
        return _has_access_location(user, obj, action, course_context)

    if isinstance(obj, basestring):
        return _has_access_string(user, obj, action, course_context)

    # Passing an unknown object here is a coding error, so rather than
    # returning a default, complain.
    raise TypeError("Unknown object type in has_access(): '{0}'"
                    .format(type(obj)))


def get_access_group_name(obj, action):
    '''
    Returns group name for user group which has "action" access to the given object.

    Used in managing access lists.
    '''

    if isinstance(obj, CourseDescriptor):
        return _get_access_group_name_course_desc(obj, action)

    # Passing an unknown object here is a coding error, so rather than
    # returning a default, complain.
    raise TypeError("Unknown object type in get_access_group_name(): '{0}'"
                    .format(type(obj)))


# ================ Implementation helpers ================================
def _has_access_course_desc(user, course, action):
    """
    Check if user has access to a course descriptor.

    Valid actions:

    'load' -- load the courseware, see inside the course
    'enroll' -- enroll.  Checks for enrollment window,
                  ACCESS_REQUIRE_STAFF_FOR_COURSE,
    'see_exists' -- can see that the course exists.
    'staff' -- staff access to course.
    """
    def can_load():
        """
        Can this user load this course?

        NOTE: this is not checking whether user is actually enrolled in the course.
        """
        # delegate to generic descriptor check to check start dates
        return _has_access_descriptor(user, course, 'load')

    def can_enroll():
        """
        First check if restriction of enrollment by login method is enabled, both
            globally and by the course.
        If it is, then the user must pass the criterion set by the course, e.g. that ExternalAuthMap 
            was set by 'shib:https://idp.stanford.edu/", in addition to requirements below.
        Rest of requirements:
        Enrollment can only happen in the course enrollment period, if one exists.
            or
        
        (CourseEnrollmentAllowed always overrides)
        (staff can always enroll)
        """
        # if using registration method to restrict (say shibboleth)
        if settings.MITX_FEATURES.get('RESTRICT_ENROLL_BY_REG_METHOD') and course.enrollment_domain:
            if user is not None and user.is_authenticated() and \
                ExternalAuthMap.objects.filter(user=user, external_domain=course.enrollment_domain):
                debug("Allow: external_auth of " + course.enrollment_domain)
                reg_method_ok = True
            else:
                reg_method_ok = False
        else:
            reg_method_ok = True #if not using this access check, it's always OK.

        now = datetime.now(UTC())
        start = course.enrollment_start
        end = course.enrollment_end

        if reg_method_ok and (start is None or now > start) and (end is None or now < end):
            # in enrollment period, so any user is allowed to enroll.
            debug("Allow: in enrollment period")
            return True

        # if user is in CourseEnrollmentAllowed with right course_id then can also enroll
        if user is not None and user.is_authenticated() and CourseEnrollmentAllowed:
            if CourseEnrollmentAllowed.objects.filter(email=user.email, course_id=course.id):
                return True

        # otherwise, need staff access
        return _has_staff_access_to_descriptor(user, course)

    def see_exists():
        """
        Can see if can enroll, but also if can load it: if user enrolled in a course and now
        it's past the enrollment period, they should still see it.

        TODO (vshnayder): This means that courses with limited enrollment periods will not appear
        to non-staff visitors after the enrollment period is over.  If this is not what we want, will
        need to change this logic.
        """
        # VS[compat] -- this setting should go away once all courses have
        # properly configured enrollment_start times (if course should be
        # staff-only, set enrollment_start far in the future.)
        if settings.MITX_FEATURES.get('ACCESS_REQUIRE_STAFF_FOR_COURSE'):
            # if this feature is on, only allow courses that have ispublic set to be
            # seen by non-staff
            if course.lms.ispublic:
                debug("Allow: ACCESS_REQUIRE_STAFF_FOR_COURSE and ispublic")
                return True
            return _has_staff_access_to_descriptor(user, course)

        return can_enroll() or can_load()

    checkers = {
        'load': can_load,
        'enroll': can_enroll,
        'see_exists': see_exists,
        'staff': lambda: _has_staff_access_to_descriptor(user, course),
        'instructor': lambda: _has_instructor_access_to_descriptor(user, course),
        }

    return _dispatch(checkers, action, user, course)


def _get_access_group_name_course_desc(course, action):
    '''
    Return name of group which gives staff access to course.  Only understands action = 'staff' and 'instructor'
    '''
    if action == 'staff':
        return _course_staff_group_name(course.location)
    elif action == 'instructor':
        return _course_instructor_group_name(course.location)

    return []




def _has_access_error_desc(user, descriptor, action, course_context):
    """
    Only staff should see error descriptors.

    Valid actions:
    'load' -- load this descriptor, showing it to the user.
    'staff' -- staff access to descriptor.
    """
    def check_for_staff():
        return _has_staff_access_to_descriptor(user, descriptor, course_context)

    checkers = {
        'load': check_for_staff,
        'staff': check_for_staff
        }

    return _dispatch(checkers, action, user, descriptor)


def _has_access_descriptor(user, descriptor, action, course_context=None):
    """
    Check if user has access to this descriptor.

    Valid actions:
    'load' -- load this descriptor, showing it to the user.
    'staff' -- staff access to descriptor.

    NOTE: This is the fallback logic for descriptors that don't have custom policy
    (e.g. courses).  If you call this method directly instead of going through
    has_access(), it will not do the right thing.
    """
    def can_load():
        """
        NOTE: This does not check that the student is enrolled in the course
        that contains this module.  We may or may not want to allow non-enrolled
        students to see modules.  If not, views should check the course, so we
        don't have to hit the enrollments table on every module load.
        """
        # If start dates are off, can always load
        if settings.MITX_FEATURES['DISABLE_START_DATES'] and not is_masquerading_as_student(user):
            debug("Allow: DISABLE_START_DATES")
            return True

        # Check start date
        if descriptor.lms.start is not None:
            now = datetime.now(UTC())
            effective_start = _adjust_start_date_for_beta_testers(user, descriptor)
            if now > effective_start:
                # after start date, everyone can see it
                debug("Allow: now > effective start date")
                return True
            # otherwise, need staff access
            return _has_staff_access_to_descriptor(user, descriptor, course_context)

        # No start date, so can always load.
        debug("Allow: no start date")
        return True

    checkers = {
        'load': can_load,
        'staff': lambda: _has_staff_access_to_descriptor(user, descriptor, course_context)
        }

    return _dispatch(checkers, action, user, descriptor)


def _has_access_xmodule(user, xmodule, action, course_context):
    """
    Check if user has access to this xmodule.

    Valid actions:
      - same as the valid actions for xmodule.descriptor
    """
    # Delegate to the descriptor
    return has_access(user, xmodule.descriptor, action, course_context)


def _has_access_location(user, location, action, course_context):
    """
    Check if user has access to this location.

    Valid actions:
    'staff' : True if the user has staff access to this location

    NOTE: if you add other actions, make sure that

     has_access(user, location, action) == has_access(user, get_item(location), action)

    And in general, prefer checking access on loaded items, rather than locations.
    """
    checkers = {
        'staff': lambda: _has_staff_access_to_location(user, location, course_context)
        }

    return _dispatch(checkers, action, user, location)


def _has_access_string(user, perm, action, course_context):
    """
    Check if user has certain special access, specified as string.  Valid strings:

    'global'

    Valid actions:

    'staff' -- global staff access.
    """

    def check_staff():
        if perm != 'global':
            debug("Deny: invalid permission '%s'", perm)
            return False
        return _has_global_staff_access(user)

    checkers = {
        'staff': check_staff
        }

    return _dispatch(checkers, action, user, perm)


#####  Internal helper methods below

def _dispatch(table, action, user, obj):
    """
    Helper: call table[action], raising a nice pretty error if there is no such key.

    user and object passed in only for error messages and debugging
    """
    if action in table:
        result = table[action]()
        debug("%s user %s, object %s, action %s",
              'ALLOWED' if result else 'DENIED',
              user,
              obj.location.url() if isinstance(obj, XModuleDescriptor) else str(obj)[:60],
              action)
        return result

    raise ValueError("Unknown action for object type '{0}': '{1}'".format(
        type(obj), action))


def _does_course_group_name_exist(name):
    return len(Group.objects.filter(name=name)) > 0


def _course_org_staff_group_name(location, course_context=None):
    """
    Get the name of the staff group for an organization which corresponds
    to the organization in the course id.

    location: something that can passed to Location
    course_context: A course_id that specifies the course run in which
                    the location occurs.
                    Required if location doesn't have category 'course'

    """
    loc = Location(location)
    if loc.category == 'course':
        course_id = loc.course_id
    else:
        if course_context is None:
            raise CourseContextRequired()
        course_id = course_context
    return 'staff_%s' % course_id.split('/')[0]


def group_names_for(role, location, course_context=None):
    """Returns the group names for a given role with this location. Plural
    because it will return both the name we expect now as well as the legacy
    group name we support for backwards compatibility. This should not check
    the DB for existence of a group (like some of its callers do) because that's
    a DB roundtrip, and we expect this might be invoked many times as we crawl
    an XModule tree."""
    loc = Location(location)
    legacy_group_name = '{0}_{1}'.format(role, loc.course)

    if loc.category == 'course':
        course_id = loc.course_id
    else:
        if course_context is None:
            raise CourseContextRequired()
        course_id = course_context

    group_name = '{0}_{1}'.format(role, course_id)

    return [group_name, legacy_group_name]

group_names_for_staff = partial(group_names_for, 'staff')
group_names_for_instructor = partial(group_names_for, 'instructor')

def _course_staff_group_name(location, course_context=None):
    """
    Get the name of the staff group for a location in the context of a course run.

    location: something that can passed to Location
    course_context: A course_id that specifies the course run in which the location occurs.
        Required if location doesn't have category 'course'

    cdodge: We're changing the name convention of the group to better epxress different runs of courses by
    using course_id rather than just the course number. So first check to see if the group name exists
    """
    loc = Location(location)
    group_name, legacy_group_name = group_names_for_staff(location, course_context)

    if _does_course_group_name_exist(legacy_group_name):
        return legacy_group_name

    return group_name

def _course_org_instructor_group_name(location, course_context=None):
    """
    Get the name of the instructor group for an organization which corresponds
    to the organization in the course id.

    location: something that can passed to Location
    course_context: A course_id that specifies the course run in which
                    the location occurs.
                    Required if location doesn't have category 'course'

    """
    loc = Location(location)
    if loc.category == 'course':
        course_id = loc.course_id
    else:
        if course_context is None:
            raise CourseContextRequired()
        course_id = course_context
    return 'instructor_%s' % course_id.split('/')[0]


def _course_instructor_group_name(location, course_context=None):
    """
    Get the name of the instructor group for a location, in the context of a course run.
    A course instructor has all staff privileges, but also can manage list of course staff (add, remove, list).

    location: something that can passed to Location.
    course_context: A course_id that specifies the course run in which the location occurs.
        Required if location doesn't have category 'course'

    cdodge: We're changing the name convention of the group to better epxress different runs of courses by
    using course_id rather than just the course number. So first check to see if the group name exists
    """
    loc = Location(location)
    group_name, legacy_group_name = group_names_for_instructor(location, course_context)

    if _does_course_group_name_exist(legacy_group_name):
        return legacy_group_name

    return group_name

def course_beta_test_group_name(location):
    """
    Get the name of the beta tester group for a location.  Right now, that's
    beta_testers_COURSE.

    location: something that can passed to Location.
    """
    return 'beta_testers_{0}'.format(Location(location).course)

# nosetests thinks that anything with _test_ in the name is a test.
# Correct this (https://nose.readthedocs.org/en/latest/finding_tests.html)
course_beta_test_group_name.__test__ = False



def _has_global_staff_access(user):
    if user.is_staff:
        debug("Allow: user.is_staff")
        return True
    else:
        debug("Deny: not user.is_staff")
        return False


def _adjust_start_date_for_beta_testers(user, descriptor):
    """
    If user is in a beta test group, adjust the start date by the appropriate number of
    days.

    Arguments:
       user: A django user.  May be anonymous.
       descriptor: the XModuleDescriptor the user is trying to get access to, with a
       non-None start date.

    Returns:
        A datetime.  Either the same as start, or earlier for beta testers.

    NOTE: number of days to adjust should be cached to avoid looking it up thousands of
    times per query.

    NOTE: For now, this function assumes that the descriptor's location is in the course
    the user is looking at.  Once we have proper usages and definitions per the XBlock
    design, this should use the course the usage is in.

    NOTE: If testing manually, make sure MITX_FEATURES['DISABLE_START_DATES'] = False
    in envs/dev.py!
    """
    if descriptor.lms.days_early_for_beta is None:
        # bail early if no beta testing is set up
        return descriptor.lms.start

    user_groups = [g.name for g in user.groups.all()]

    beta_group = course_beta_test_group_name(descriptor.location)
    if beta_group in user_groups:
        debug("Adjust start time: user in group %s", beta_group)
        delta = timedelta(descriptor.lms.days_early_for_beta)
        effective = descriptor.lms.start - delta
        return effective

    return descriptor.lms.start


def _has_instructor_access_to_location(user, location, course_context=None):
    return _has_access_to_location(user, location, 'instructor', course_context)


def _has_staff_access_to_location(user, location, course_context=None):
    return _has_access_to_location(user, location, 'staff', course_context)


def _has_access_to_location(user, location, access_level, course_context):
    '''
    Returns True if the given user has access_level (= staff or
    instructor) access to a location.  For now this is equivalent to
    having staff / instructor access to the course location.course.

    This means that user is in the staff_* group or instructor_* group, or is an overall admin.

    TODO (vshnayder): this needs to be changed to allow per-course_id permissions, not per-course
    (e.g. staff in 2012 is different from 2013, but maybe some people always have access)

    course is a string: the course field of the location being accessed.
    location = location
    access_level = string, either "staff" or "instructor"
    '''
    if user is None or (not user.is_authenticated()):
        debug("Deny: no user or anon user")
        return False

    if is_masquerading_as_student(user):
        return False

    if user.is_staff:
        debug("Allow: user.is_staff")
        return True

    # If not global staff, is the user in the Auth group for this class?
    user_groups = [g.name for g in user.groups.all()]

    if access_level == 'staff':
        staff_groups = group_names_for_staff(location, course_context) + \
                       [_course_org_staff_group_name(location, course_context)]
        for staff_group in staff_groups:
            if staff_group in user_groups:
                debug("Allow: user in group %s", staff_group)
                return True
        debug("Deny: user not in groups %s", staff_groups)

    if access_level == 'instructor' or access_level == 'staff':  # instructors get staff privileges
        instructor_groups = group_names_for_instructor(location, course_context) + \
                            [_course_org_instructor_group_name(location, course_context)]
        for instructor_group in instructor_groups:
            if instructor_group in user_groups:
                debug("Allow: user in group %s", instructor_group)
                return True
        debug("Deny: user not in groups %s", instructor_groups)
    else:
        log.debug("Error in access._has_access_to_location access_level=%s unknown" % access_level)
    return False


def _has_staff_access_to_course_id(user, course_id):
    """Helper method that takes a course_id instead of a course name"""
    loc = CourseDescriptor.id_to_location(course_id)
    return _has_staff_access_to_location(user, loc, course_id)


def _has_instructor_access_to_descriptor(user, descriptor, course_context=None):
    """Helper method that checks whether the user has staff access to
    the course of the location.

    descriptor: something that has a location attribute
    """
    return _has_instructor_access_to_location(user, descriptor.location, course_context)


def _has_staff_access_to_descriptor(user, descriptor, course_context=None):
    """Helper method that checks whether the user has staff access to
    the course of the location.

    descriptor: something that has a location attribute
    """
    return _has_staff_access_to_location(user, descriptor.location, course_context)
