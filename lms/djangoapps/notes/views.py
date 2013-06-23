from django.contrib.auth.decorators import login_required
from django.http import Http404
from mitxmako.shortcuts import render_to_response
from courseware.courses import get_course_with_access
from notes.models import Note
from notes.utils import notes_enabled_for_course


@login_required
def notes(request, course_id):
    ''' Displays the student's notes. '''

    course = get_course_with_access(request.user, course_id, 'load')
    if not notes_enabled_for_course(course):
        raise Http404

    notes = Note.objects.filter(course_id=course_id, user=request.user).order_by('-created', 'uri')
    context = {
        'course': course,
        'notes': notes
    }

    return render_to_response('notes.html', context)
