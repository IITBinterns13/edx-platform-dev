"""
This file contains the logic for cohort groups, as exposed internally to the
forums, and to the cohort admin views.
"""

from django.http import Http404
import logging
import random

from courseware import courses
from student.models import get_user_by_username_or_email
from .models import CourseUserGroup

log = logging.getLogger(__name__)


# tl;dr: global state is bad.  capa reseeds random every time a problem is loaded.  Even
# if and when that's fixed, it's a good idea to have a local generator to avoid any other
# code that messes with the global random module.
_local_random = None

def local_random():
    """
    Get the local random number generator.  In a function so that we don't run
    random.Random() at import time.
    """
    # ironic, isn't it?
    global _local_random

    if _local_random is None:
        _local_random = random.Random()

    return _local_random

def is_course_cohorted(course_id):
    """
    Given a course id, return a boolean for whether or not the course is
    cohorted.

    Raises:
       Http404 if the course doesn't exist.
    """
    return courses.get_course_by_id(course_id).is_cohorted


def get_cohort_id(user, course_id):
    """
    Given a course id and a user, return the id of the cohort that user is
    assigned to in that course.  If they don't have a cohort, return None.
    """
    cohort = get_cohort(user, course_id)
    return None if cohort is None else cohort.id


def is_commentable_cohorted(course_id, commentable_id):
    """
    Args:
        course_id: string
        commentable_id: string

    Returns:
        Bool: is this commentable cohorted?

    Raises:
        Http404 if the course doesn't exist.
    """
    course = courses.get_course_by_id(course_id)

    if not course.is_cohorted:
        # this is the easy case :)
        ans = False
    elif commentable_id in course.top_level_discussion_topic_ids:
        # top level discussions have to be manually configured as cohorted
        # (default is not)
        ans = commentable_id in course.cohorted_discussions
    else:
        # inline discussions are cohorted by default
        ans = True

    log.debug("is_commentable_cohorted({0}, {1}) = {2}".format(course_id,
                                                               commentable_id,
                                                               ans))
    return ans


def get_cohorted_commentables(course_id):
    """
    Given a course_id return a list of strings representing cohorted commentables
    """

    course = courses.get_course_by_id(course_id)

    if not course.is_cohorted:
        # this is the easy case :)
        ans = []
    else:
        ans = course.cohorted_discussions

    return ans


def get_cohort(user, course_id):
    """
    Given a django User and a course_id, return the user's cohort in that
    cohort.

    Arguments:
        user: a Django User object.
        course_id: string in the format 'org/course/run'

    Returns:
        A CourseUserGroup object if the course is cohorted and the User has a
        cohort, else None.

    Raises:
       ValueError if the course_id doesn't exist.
    """
    # First check whether the course is cohorted (users shouldn't be in a cohort
    # in non-cohorted courses, but settings can change after course starts)
    try:
        course = courses.get_course_by_id(course_id)
    except Http404:
        raise ValueError("Invalid course_id")

    if not course.is_cohorted:
        return None

    try:
        return CourseUserGroup.objects.get(course_id=course_id,
                                            group_type=CourseUserGroup.COHORT,
                                            users__id=user.id)
    except CourseUserGroup.DoesNotExist:
        # Didn't find the group.  We'll go on to create one if needed.
        pass

    if not course.auto_cohort:
        return None

    choices = course.auto_cohort_groups
    n = len(choices)
    if n == 0:
        # Nowhere to put user
        log.warning("Course %s is auto-cohorted, but there are no"
                    " auto_cohort_groups specified",
                    course_id)
        return None

    # Put user in a random group, creating it if needed
    group_name = local_random().choice(choices)

    group, created = CourseUserGroup.objects.get_or_create(
        course_id=course_id,
        group_type=CourseUserGroup.COHORT,
        name=group_name)

    user.course_groups.add(group)
    return group


def get_course_cohorts(course_id):
    """
    Get a list of all the cohorts in the given course.

    Arguments:
        course_id: string in the format 'org/course/run'

    Returns:
        A list of CourseUserGroup objects.  Empty if there are no cohorts. Does
        not check whether the course is cohorted.
    """
    return list(CourseUserGroup.objects.filter(course_id=course_id,
                                               group_type=CourseUserGroup.COHORT))

### Helpers for cohort management views


def get_cohort_by_name(course_id, name):
    """
    Return the CourseUserGroup object for the given cohort.  Raises DoesNotExist
    it isn't present.
    """
    return CourseUserGroup.objects.get(course_id=course_id,
                                       group_type=CourseUserGroup.COHORT,
                                       name=name)


def get_cohort_by_id(course_id, cohort_id):
    """
    Return the CourseUserGroup object for the given cohort.  Raises DoesNotExist
    it isn't present.  Uses the course_id for extra validation...
    """
    return CourseUserGroup.objects.get(course_id=course_id,
                                       group_type=CourseUserGroup.COHORT,
                                       id=cohort_id)


def add_cohort(course_id, name):
    """
    Add a cohort to a course.  Raises ValueError if a cohort of the same name already
    exists.
    """
    log.debug("Adding cohort %s to %s", name, course_id)
    if CourseUserGroup.objects.filter(course_id=course_id,
                                      group_type=CourseUserGroup.COHORT,
                                      name=name).exists():
        raise ValueError("Can't create two cohorts with the same name")

    return CourseUserGroup.objects.create(course_id=course_id,
                                          group_type=CourseUserGroup.COHORT,
                                          name=name)


class CohortConflict(Exception):
    """
    Raised when user to be added is already in another cohort in same course.
    """
    pass


def add_user_to_cohort(cohort, username_or_email):
    """
    Look up the given user, and if successful, add them to the specified cohort.

    Arguments:
        cohort: CourseUserGroup
        username_or_email: string.  Treated as email if has '@'

    Returns:
        User object.

    Raises:
        User.DoesNotExist if can't find user.

        ValueError if user already present in this cohort.

        CohortConflict if user already in another cohort.
    """
    user = get_user_by_username_or_email(username_or_email)

    # If user in any cohorts in this course already, complain
    course_cohorts = CourseUserGroup.objects.filter(
        course_id=cohort.course_id,
        users__id=user.id,
        group_type=CourseUserGroup.COHORT)
    if course_cohorts.exists():
        if course_cohorts[0] == cohort:
            raise ValueError("User {0} already present in cohort {1}".format(
                user.username,
                cohort.name))
        else:
            raise CohortConflict("User {0} is in another cohort {1} in course"
                                 .format(user.username,
                                         course_cohorts[0].name))

    cohort.users.add(user)
    return user


def get_course_cohort_names(course_id):
    """
    Return a list of the cohort names in a course.
    """
    return [c.name for c in get_course_cohorts(course_id)]


def delete_empty_cohort(course_id, name):
    """
    Remove an empty cohort.  Raise ValueError if cohort is not empty.
    """
    cohort = get_cohort_by_name(course_id, name)
    if cohort.users.exists():
        raise ValueError(
            "Can't delete non-empty cohort {0} in course {1}".format(
                name, course_id))

    cohort.delete()
