from django.contrib.auth.models import User, Group
from django.core.exceptions import PermissionDenied
from django.conf import settings

from xmodule.modulestore import Location

'''
This code is somewhat duplicative of access.py in the LMS. We will unify the code as a separate story
but this implementation should be data compatible with the LMS implementation
'''

# define a couple of simple roles, we just need ADMIN and EDITOR now for our purposes
INSTRUCTOR_ROLE_NAME = 'instructor'
STAFF_ROLE_NAME = 'staff'

# This is the group of people who have permission to create new courses on edge or edx.
COURSE_CREATOR_GROUP_NAME = "course_creator_group"

# we're just making a Django group for each location/role combo
# to do this we're just creating a Group name which is a formatted string
# of those two variables


def get_course_groupname_for_role(location, role):
    loc = Location(location)
    # hack: check for existence of a group name in the legacy LMS format <role>_<course>
    # if it exists, then use that one, otherwise use a <role>_<course_id> which contains
    # more information
    groupname = '{0}_{1}'.format(role, loc.course)

    if len(Group.objects.filter(name=groupname)) == 0:
        groupname = '{0}_{1}'.format(role, loc.course_id)

    return groupname


def get_users_in_course_group_by_role(location, role):
    groupname = get_course_groupname_for_role(location, role)
    (group, _created) = Group.objects.get_or_create(name=groupname)
    return group.user_set.all()


def create_all_course_groups(creator, location):
    """
    Create all permission groups for a new course and subscribe the caller into those roles
    """
    create_new_course_group(creator, location, INSTRUCTOR_ROLE_NAME)
    create_new_course_group(creator, location, STAFF_ROLE_NAME)


def create_new_course_group(creator, location, role):
    groupname = get_course_groupname_for_role(location, role)
    (group, created) = Group.objects.get_or_create(name=groupname)
    if created:
        group.save()

    creator.groups.add(group)
    creator.save()

    return


def _delete_course_group(location):
    """
    This is to be called only by either a command line code path or through a app which has already
    asserted permissions
    """
    # remove all memberships
    instructors = Group.objects.get(name=get_course_groupname_for_role(location, INSTRUCTOR_ROLE_NAME))
    for user in instructors.user_set.all():
        user.groups.remove(instructors)
        user.save()

    staff = Group.objects.get(name=get_course_groupname_for_role(location, STAFF_ROLE_NAME))
    for user in staff.user_set.all():
        user.groups.remove(staff)
        user.save()


def _copy_course_group(source, dest):
    """
    This is to be called only by either a command line code path or through an app which has already
    asserted permissions to do this action
    """
    instructors = Group.objects.get(name=get_course_groupname_for_role(source, INSTRUCTOR_ROLE_NAME))
    new_instructors_group = Group.objects.get(name=get_course_groupname_for_role(dest, INSTRUCTOR_ROLE_NAME))
    for user in instructors.user_set.all():
        user.groups.add(new_instructors_group)
        user.save()

    staff = Group.objects.get(name=get_course_groupname_for_role(source, STAFF_ROLE_NAME))
    new_staff_group = Group.objects.get(name=get_course_groupname_for_role(dest, STAFF_ROLE_NAME))
    for user in staff.user_set.all():
        user.groups.add(new_staff_group)
        user.save()


def add_user_to_course_group(caller, user, location, role):
    # only admins can add/remove other users
    if not is_user_in_course_group_role(caller, location, INSTRUCTOR_ROLE_NAME):
        raise PermissionDenied

    group = Group.objects.get(name=get_course_groupname_for_role(location, role))
    return _add_user_to_group(user, group)


def add_user_to_creator_group(caller, user):
    """
    Adds the user to the group of course creators.

    The caller must have staff access to perform this operation.

    Note that on the edX site, we currently limit course creators to edX staff, and this
    method is a no-op in that environment.
    """
    if not caller.is_active or not caller.is_authenticated or not caller.is_staff:
        raise PermissionDenied

    (group, created) = Group.objects.get_or_create(name=COURSE_CREATOR_GROUP_NAME)
    if created:
        group.save()
    return _add_user_to_group(user, group)


def _add_user_to_group(user, group):
    """
    This is to be called only by either a command line code path or through an app which has already
    asserted permissions to do this action
    """
    if user.is_active and user.is_authenticated:
        user.groups.add(group)
        user.save()
        return True

    return False


def get_user_by_email(email):
    user = None
    # try to look up user, return None if not found
    try:
        user = User.objects.get(email=email)
    except:
        pass

    return user


def remove_user_from_course_group(caller, user, location, role):
    # only admins can add/remove other users
    if not is_user_in_course_group_role(caller, location, INSTRUCTOR_ROLE_NAME):
        raise PermissionDenied

    # see if the user is actually in that role, if not then we don't have to do anything
    if is_user_in_course_group_role(user, location, role):
        _remove_user_from_group(user, get_course_groupname_for_role(location, role))


def remove_user_from_creator_group(caller, user):
    """
    Removes user from the course creator group.

    The caller must have staff access to perform this operation.
    """
    if not caller.is_active or not caller.is_authenticated or not caller.is_staff:
        raise PermissionDenied

    _remove_user_from_group(user, COURSE_CREATOR_GROUP_NAME)


def _remove_user_from_group(user, group_name):
    """
    This is to be called only by either a command line code path or through an app which has already
    asserted permissions to do this action
    """
    group = Group.objects.get(name=group_name)
    user.groups.remove(group)
    user.save()


def is_user_in_course_group_role(user, location, role):
    if user.is_active and user.is_authenticated:
        # all "is_staff" flagged accounts belong to all groups
        return user.is_staff or user.groups.filter(name=get_course_groupname_for_role(location, role)).count() > 0

    return False


def is_user_in_creator_group(user):
    """
    Returns true if the user has permissions to create a course.

    Will always return True if user.is_staff is True.

    Note that on the edX site, we currently limit course creators to edX staff. On
    other sites, this method checks that the user is in the course creator group.
    """
    if user.is_staff:
        return True

    # On edx, we only allow edX staff to create courses. This may be relaxed in the future.
    if settings.MITX_FEATURES.get('DISABLE_COURSE_CREATION', False):
        return False

    # Feature flag for using the creator group setting. Will be removed once the feature is complete.
    if settings.MITX_FEATURES.get('ENABLE_CREATOR_GROUP', False):
        return user.groups.filter(name=COURSE_CREATOR_GROUP_NAME).count() > 0

    return True


def _grant_instructors_creator_access(caller):
    """
    This is to be called only by either a command line code path or through an app which has already
    asserted permissions to do this action.

    Gives all users with instructor role course creator rights.
    This is only intended to be run once on a given environment.
    """
    for group in Group.objects.all():
        if group.name.startswith(INSTRUCTOR_ROLE_NAME + "_"):
            for user in group.user_set.all():
                add_user_to_creator_group(caller, user)
