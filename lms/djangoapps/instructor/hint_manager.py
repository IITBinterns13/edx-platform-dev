"""
Views for hint management.

Along with the crowdsource_hinter xmodule, this code is still
experimental, and should not be used in new courses, yet.
"""

import json
import re

from django.http import HttpResponse, Http404
from django_future.csrf import ensure_csrf_cookie

from mitxmako.shortcuts import render_to_response, render_to_string

from courseware.courses import get_course_with_access
from courseware.models import XModuleContentField
from xmodule.modulestore import Location
from xmodule.modulestore.django import modulestore


@ensure_csrf_cookie
def hint_manager(request, course_id):
    try:
        get_course_with_access(request.user, course_id, 'staff', depth=None)
    except Http404:
        out = 'Sorry, but students are not allowed to access the hint manager!'
        return HttpResponse(out)
    if request.method == 'GET':
        out = get_hints(request, course_id, 'mod_queue')
        return render_to_response('courseware/hint_manager.html', out)
    field = request.POST['field']
    if not (field == 'mod_queue' or field == 'hints'):
        # Invalid field.  (Don't let users continue - they may overwrite other db's)
        out = 'Error in hint manager - an invalid field was accessed.'
        return HttpResponse(out)

    if request.POST['op'] == 'delete hints':
        delete_hints(request, course_id, field)
    if request.POST['op'] == 'switch fields':
        pass
    if request.POST['op'] == 'change votes':
        change_votes(request, course_id, field)
    if request.POST['op'] == 'add hint':
        add_hint(request, course_id, field)
    if request.POST['op'] == 'approve':
        approve(request, course_id, field)
    rendered_html = render_to_string('courseware/hint_manager_inner.html', get_hints(request, course_id, field))
    return HttpResponse(json.dumps({'success': True, 'contents': rendered_html}))


def get_hints(request, course_id, field):
    """
    Load all of the hints submitted to the course.

    Args:
    `request` -- Django request object.
    `course_id` -- The course id, like 'Me/19.002/test_course'
    `field` -- Either 'hints' or 'mod_queue'; specifies which set of hints to load.

    Keys in returned dict:
        - 'field': Same as input
        - 'other_field': 'mod_queue' if `field` == 'hints'; and vice-versa.
        - 'field_label', 'other_field_label': English name for the above.
        - 'all_hints': A list of [answer, pk dict] pairs, representing all hints.
          Sorted by answer.
        - 'id_to_name': A dictionary mapping problem id to problem name.
    """
    if field == 'mod_queue':
        other_field = 'hints'
        field_label = 'Hints Awaiting Moderation'
        other_field_label = 'Approved Hints'
    elif field == 'hints':
        other_field = 'mod_queue'
        field_label = 'Approved Hints'
        other_field_label = 'Hints Awaiting Moderation'
    # The course_id is of the form school/number/classname.
    # We want to use the course_id to find all matching definition_id's.
    # To do this, just take the school/number part - leave off the classname.
    chopped_id = '/'.join(course_id.split('/')[:-1])
    chopped_id = re.escape(chopped_id)
    all_hints = XModuleContentField.objects.filter(field_name=field, definition_id__regex=chopped_id)
    # big_out_dict[problem id] = [[answer, {pk: [hint, votes]}], sorted by answer]
    # big_out_dict maps a problem id to a list of [answer, hints] pairs, sorted in order of answer.
    big_out_dict = {}
    # id_to name maps a problem id to the name of the problem.
    # id_to_name[problem id] = Display name of problem
    id_to_name = {}

    for hints_by_problem in all_hints:
        loc = Location(hints_by_problem.definition_id)
        name = location_to_problem_name(loc)
        if name is None:
            continue
        id_to_name[hints_by_problem.definition_id] = name

        def answer_sorter(thing):
            """
            `thing` is a tuple, where `thing[0]` contains an answer, and `thing[1]` contains
            a dict of hints.  This function returns an index based on `thing[0]`, which
            is used as a key to sort the list of things.
            """
            try:
                return float(thing[0])
            except ValueError:
                # Put all non-numerical answers first.
                return float('-inf')

        # Answer list contains [answer, dict_of_hints] pairs.
        answer_list = sorted(json.loads(hints_by_problem.value).items(), key=answer_sorter)
        big_out_dict[hints_by_problem.definition_id] = answer_list

    render_dict = {'field': field,
                   'other_field': other_field,
                   'field_label': field_label,
                   'other_field_label': other_field_label,
                   'all_hints': big_out_dict,
                   'id_to_name': id_to_name}
    return render_dict


def location_to_problem_name(loc):
    """
    Given the location of a crowdsource_hinter module, try to return the name of the
    problem it wraps around.  Return None if the hinter no longer exists.
    """
    try:
        descriptor = modulestore().get_items(loc)[0]
        return descriptor.get_children()[0].display_name
    except IndexError:
        # Sometimes, the problem is no longer in the course.  Just
        # don't include said problem.
        return None


def delete_hints(request, course_id, field):
    """
    Deletes the hints specified.

    `request.POST` contains some fields keyed by integers.  Each such field contains a
    [problem_defn_id, answer, pk] tuple.  These tuples specify the hints to be deleted.

    Example `request.POST`:
    {'op': 'delete_hints',
     'field': 'mod_queue',
      1: ['problem_whatever', '42.0', '3'],
      2: ['problem_whatever', '32.5', '12']}
    """

    for key in request.POST:
        if key == 'op' or key == 'field':
            continue
        problem_id, answer, pk = request.POST.getlist(key)
        # Can be optimized - sort the delete list by problem_id, and load each problem
        # from the database only once.
        this_problem = XModuleContentField.objects.get(field_name=field, definition_id=problem_id)
        problem_dict = json.loads(this_problem.value)
        del problem_dict[answer][pk]
        this_problem.value = json.dumps(problem_dict)
        this_problem.save()


def change_votes(request, course_id, field):
    """
    Updates the number of votes.

    The numbered fields of `request.POST` contain [problem_id, answer, pk, new_votes] tuples.
    - Very similar to `delete_hints`.  Is there a way to merge them?  Nah, too complicated.
    """

    for key in request.POST:
        if key == 'op' or key == 'field':
            continue
        problem_id, answer, pk, new_votes = request.POST.getlist(key)
        this_problem = XModuleContentField.objects.get(field_name=field, definition_id=problem_id)
        problem_dict = json.loads(this_problem.value)
        # problem_dict[answer][pk] points to a [hint_text, #votes] pair.
        problem_dict[answer][pk][1] = int(new_votes)
        this_problem.value = json.dumps(problem_dict)
        this_problem.save()


def add_hint(request, course_id, field):
    """
    Add a new hint.  `request.POST`:
    op
    field
    problem - The problem id
    answer - The answer to which a hint will be added
    hint - The text of the hint
    """

    problem_id = request.POST['problem']
    answer = request.POST['answer']
    hint_text = request.POST['hint']
    this_problem = XModuleContentField.objects.get(field_name=field, definition_id=problem_id)

    hint_pk_entry = XModuleContentField.objects.get(field_name='hint_pk', definition_id=problem_id)
    this_pk = int(hint_pk_entry.value)
    hint_pk_entry.value = this_pk + 1
    hint_pk_entry.save()

    problem_dict = json.loads(this_problem.value)
    if answer not in problem_dict:
        problem_dict[answer] = {}
    problem_dict[answer][this_pk] = [hint_text, 1]
    this_problem.value = json.dumps(problem_dict)
    this_problem.save()


def approve(request, course_id, field):
    """
    Approve a list of hints, moving them from the mod_queue to the real
    hint list.  POST:
    op, field
    (some number) -> [problem, answer, pk]
    """

    for key in request.POST:
        if key == 'op' or key == 'field':
            continue
        problem_id, answer, pk = request.POST.getlist(key)
        # Can be optimized - sort the delete list by problem_id, and load each problem
        # from the database only once.
        problem_in_mod = XModuleContentField.objects.get(field_name=field, definition_id=problem_id)
        problem_dict = json.loads(problem_in_mod.value)
        hint_to_move = problem_dict[answer][pk]
        del problem_dict[answer][pk]
        problem_in_mod.value = json.dumps(problem_dict)
        problem_in_mod.save()

        problem_in_hints = XModuleContentField.objects.get(field_name='hints', definition_id=problem_id)
        problem_dict = json.loads(problem_in_hints.value)
        if answer not in problem_dict:
            problem_dict[answer] = {}
        problem_dict[answer][pk] = hint_to_move
        problem_in_hints.value = json.dumps(problem_dict)
        problem_in_hints.save()
