import json
import logging
import sys

from django.conf import settings
from django.core.validators import ValidationError, validate_email
from django.views.decorators.csrf import requires_csrf_token
from django.views.defaults import server_error
from django.http import (Http404, HttpResponse, HttpResponseNotAllowed,
                         HttpResponseServerError)
from dogapi import dog_stats_api
from mitxmako.shortcuts import render_to_response
import zendesk

import calc
import track.views


log = logging.getLogger(__name__)


@requires_csrf_token
def jsonable_server_error(request, template_name='500.html'):
    """
    500 error handler that serves JSON on an AJAX request, and proxies
    to the Django default `server_error` view otherwise.
    """
    if request.is_ajax():
        msg = {"error": "The edX servers encountered an error"}
        return HttpResponseServerError(json.dumps(msg))
    else:
        return server_error(request, template_name=template_name)


def calculate(request):
    ''' Calculator in footer of every page. '''
    equation = request.GET['equation']
    try:
        result = calc.evaluator({}, {}, equation)
    except:
        event = {'error': map(str, sys.exc_info()),
                 'equation': equation}
        track.views.server_track(request, 'error:calc', event, page='calc')
        return HttpResponse(json.dumps({'result': 'Invalid syntax'}))
    return HttpResponse(json.dumps({'result': str(result)}))


class _ZendeskApi(object):
    def __init__(self):
        """
        Instantiate the Zendesk API.

        All of `ZENDESK_URL`, `ZENDESK_USER`, and `ZENDESK_API_KEY` must be set
        in `django.conf.settings`.
        """
        self._zendesk_instance = zendesk.Zendesk(
            settings.ZENDESK_URL,
            settings.ZENDESK_USER,
            settings.ZENDESK_API_KEY,
            use_api_token=True,
            api_version=2,
            # As of 2012-05-08, Zendesk is using a CA that is not
            # installed on our servers
            client_args={"disable_ssl_certificate_validation": True}
        )

    def create_ticket(self, ticket):
        """
        Create the given `ticket` in Zendesk.

        The ticket should have the format specified by the zendesk package.
        """
        ticket_url = self._zendesk_instance.create_ticket(data=ticket)
        return zendesk.get_id_from_url(ticket_url)

    def update_ticket(self, ticket_id, update):
        """
        Update the Zendesk ticket with id `ticket_id` using the given `update`.

        The update should have the format specified by the zendesk package.
        """
        self._zendesk_instance.update_ticket(ticket_id=ticket_id, data=update)


def _record_feedback_in_zendesk(realname, email, subject, details, tags, additional_info):
    """
    Create a new user-requested Zendesk ticket.

    Once created, the ticket will be updated with a private comment containing
    additional information from the browser and server, such as HTTP headers
    and user state. Returns a boolean value indicating whether ticket creation
    was successful, regardless of whether the private comment update succeeded.
    """
    zendesk_api = _ZendeskApi()

    additional_info_string = (
        "Additional information:\n\n" +
        "\n".join("%s: %s" % (key, value) for (key, value) in additional_info.items() if value is not None)
    )

    # Tag all issues with LMS to distinguish channel in Zendesk; requested by student support team
    zendesk_tags = list(tags.values()) + ["LMS"]
    new_ticket = {
        "ticket": {
            "requester": {"name": realname, "email": email},
            "subject": subject,
            "comment": {"body": details},
            "tags": zendesk_tags
        }
    }
    try:
        ticket_id = zendesk_api.create_ticket(new_ticket)
    except zendesk.ZendeskError as err:
        log.error("Error creating Zendesk ticket: %s", str(err))
        return False

    # Additional information is provided as a private update so the information
    # is not visible to the user.
    ticket_update = {"ticket": {"comment": {"public": False, "body": additional_info_string}}}
    try:
        zendesk_api.update_ticket(ticket_id, ticket_update)
    except zendesk.ZendeskError as err:
        log.error("Error updating Zendesk ticket: %s", str(err))
        # The update is not strictly necessary, so do not indicate failure to the user
        pass

    return True


DATADOG_FEEDBACK_METRIC = "lms_feedback_submissions"


def _record_feedback_in_datadog(tags):
    datadog_tags = ["{k}:{v}".format(k=k, v=v) for k, v in tags.items()]
    dog_stats_api.increment(DATADOG_FEEDBACK_METRIC, tags=datadog_tags)


def submit_feedback(request):
    """
    Create a new user-requested ticket, currently implemented with Zendesk.

    If feedback submission is not enabled, any request will raise `Http404`.
    If any configuration parameter (`ZENDESK_URL`, `ZENDESK_USER`, or
    `ZENDESK_API_KEY`) is missing, any request will raise an `Exception`.
    The request must be a POST request specifying `subject` and `details`.
    If the user is not authenticated, the request must also specify `name` and
    `email`. If the user is authenticated, the `name` and `email` will be
    populated from the user's information. If any required parameter is
    missing, a 400 error will be returned indicating which field is missing and
    providing an error message. If Zendesk ticket creation fails, 500 error
    will be returned with no body; if ticket creation succeeds, an empty
    successful response (200) will be returned.
    """
    if not settings.MITX_FEATURES.get('ENABLE_FEEDBACK_SUBMISSION', False):
        raise Http404()
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if (
        not settings.ZENDESK_URL or
        not settings.ZENDESK_USER or
        not settings.ZENDESK_API_KEY
    ):
        raise Exception("Zendesk enabled but not configured")

    def build_error_response(status_code, field, err_msg):
        return HttpResponse(json.dumps({"field": field, "error": err_msg}), status=status_code)

    additional_info = {}

    required_fields = ["subject", "details"]
    if not request.user.is_authenticated():
        required_fields += ["name", "email"]
    required_field_errs = {
        "subject": "Please provide a subject.",
        "details": "Please provide details.",
        "name": "Please provide your name.",
        "email": "Please provide a valid e-mail.",
    }

    for field in required_fields:
        if field not in request.POST or not request.POST[field]:
            return build_error_response(400, field, required_field_errs[field])

    subject = request.POST["subject"]
    details = request.POST["details"]
    tags = dict(
        [(tag, request.POST[tag]) for tag in ["issue_type", "course_id"] if tag in request.POST]
    )

    if request.user.is_authenticated():
        realname = request.user.profile.name
        email = request.user.email
        additional_info["username"] = request.user.username
    else:
        realname = request.POST["name"]
        email = request.POST["email"]
        try:
            validate_email(email)
        except ValidationError:
            return build_error_response(400, "email", required_field_errs["email"])

    for header, pretty in [
        ("HTTP_REFERER", "Page"),
        ("HTTP_USER_AGENT", "Browser"),
        ("REMOTE_ADDR", "Client IP"),
        ("SERVER_NAME", "Host")
    ]:
        additional_info[pretty] = request.META.get(header)

    success = _record_feedback_in_zendesk(realname, email, subject, details, tags, additional_info)
    _record_feedback_in_datadog(tags)

    return HttpResponse(status=(200 if success else 500))


def info(request):
    ''' Info page (link from main header) '''
    return render_to_response("info.html", {})


# From http://djangosnippets.org/snippets/1042/
def parse_accept_header(accept):
    """Parse the Accept header *accept*, returning a list with pairs of
    (media_type, q_value), ordered by q values.
    """
    result = []
    for media_range in accept.split(","):
        parts = media_range.split(";")
        media_type = parts.pop(0)
        media_params = []
        q = 1.0
        for part in parts:
            (key, value) = part.lstrip().split("=", 1)
            if key == "q":
                q = float(value)
            else:
                media_params.append((key, value))
        result.append((media_type, tuple(media_params), q))
    result.sort(lambda x, y: -cmp(x[2], y[2]))
    return result


def accepts(request, media_type):
    """Return whether this request has an Accept header that matches type"""
    accept = parse_accept_header(request.META.get("HTTP_ACCEPT", ""))
    return media_type in [t for (t, p, q) in accept]
