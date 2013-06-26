import functools
import json
import logging
import random
import re
import string       # pylint: disable=W0402
import fnmatch

from textwrap import dedent
from external_auth.models import ExternalAuthMap
from external_auth.djangostore import DjangoOpenIDStore

from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME, authenticate, login
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from student.models import UserProfile, TestCenterUser, TestCenterRegistration

from django.http import HttpResponse, HttpResponseRedirect, HttpRequest
from django.utils.http import urlquote
from django.shortcuts import redirect
from django.utils.translation import ugettext as _

from mitxmako.shortcuts import render_to_response, render_to_string
try:
    from django.views.decorators.csrf import csrf_exempt
except ImportError:
    from django.contrib.csrf.middleware import csrf_exempt
from django_future.csrf import ensure_csrf_cookie
from util.cache import cache_if_anonymous

import django_openid_auth.views as openid_views
from django_openid_auth import auth as openid_auth
from openid.consumer.consumer import SUCCESS

from openid.server.server import Server
from openid.server.trustroot import TrustRoot
from openid.extensions import ax, sreg

import student.views as student_views
# Required for Pearson
from courseware.views import get_module_for_descriptor, jump_to
from courseware.model_data import ModelDataCache
from xmodule.modulestore.django import modulestore
from xmodule.course_module import CourseDescriptor
from xmodule.modulestore import Location
from xmodule.modulestore.exceptions import ItemNotFoundError

log = logging.getLogger("mitx.external_auth")


# -----------------------------------------------------------------------------
# OpenID Common
# -----------------------------------------------------------------------------


@csrf_exempt
def default_render_failure(request,
                           message,
                           status=403,
                           template_name='extauth_failure.html',
                           exception=None):
    """Render an Openid error page to the user"""

    log.debug("In openid_failure " + message)

    data = render_to_string(template_name,
                            dict(message=message, exception=exception))

    return HttpResponse(data, status=status)


# -----------------------------------------------------------------------------
# OpenID Authentication
# -----------------------------------------------------------------------------


def generate_password(length=12, chars=string.letters + string.digits):
    """Generate internal password for externally authenticated user"""
    choice = random.SystemRandom().choice
    return ''.join([choice(chars) for i in range(length)])


@csrf_exempt
def openid_login_complete(request,
                          redirect_field_name=REDIRECT_FIELD_NAME,
                          render_failure=None):
    """Complete the openid login process"""

    render_failure = (render_failure or default_render_failure)

    openid_response = openid_views.parse_openid_response(request)
    if not openid_response:
        return render_failure(request,
                              'This is an OpenID relying party endpoint.')

    if openid_response.status == SUCCESS:
        external_id = openid_response.identity_url
        oid_backend = openid_auth.OpenIDBackend()
        details = oid_backend._extract_user_details(openid_response)

        log.debug('openid success, details=%s' % details)

        url = getattr(settings, 'OPENID_SSO_SERVER_URL', None)
        external_domain = "openid:%s" % url
        fullname = '%s %s' % (details.get('first_name', ''),
                              details.get('last_name', ''))

        return external_login_or_signup(request,
                                        external_id,
                                        external_domain,
                                        details,
                                        details.get('email', ''),
                                        fullname)

    return render_failure(request, 'Openid failure')


def external_login_or_signup(request,
                             external_id,
                             external_domain,
                             credentials,
                             email,
                             fullname,
                             retfun=None):
    """Generic external auth login or signup"""

    # see if we have a map from this external_id to an edX username
    try:
        eamap = ExternalAuthMap.objects.get(external_id=external_id,
                                            external_domain=external_domain)
        log.debug('Found eamap=%s' % eamap)
    except ExternalAuthMap.DoesNotExist:
        # go render form for creating edX user
        eamap = ExternalAuthMap(external_id=external_id,
                                external_domain=external_domain,
                                external_credentials=json.dumps(credentials))
        eamap.external_email = email
        eamap.external_name = fullname
        eamap.internal_password = generate_password()
        log.debug('Created eamap=%s' % eamap)

        eamap.save()

    log.info("External_Auth login_or_signup for %s : %s : %s : %s" % (external_domain, external_id, email, fullname))
    internal_user = eamap.user
    if internal_user is None:
        if settings.MITX_FEATURES.get('AUTH_USE_SHIB'):
            # if we are using shib, try to link accounts using email
            try:
                link_user = User.objects.get(email=eamap.external_email)
                if not ExternalAuthMap.objects.filter(user=link_user).exists():
                    # if there's no pre-existing linked eamap, we link the user
                    eamap.user = link_user
                    eamap.save()
                    internal_user = link_user
                    log.info('SHIB: Linking existing account for %s' % eamap.external_email)
                    # now pass through to log in
                else:
                    # otherwise, there must have been an error, b/c we've already linked a user with these external
                    # creds
                    failure_msg = _(dedent("""
                        You have already created an account using an external login like WebAuth or Shibboleth.
                        Please contact %s for support """
                                           % getattr(settings, 'TECH_SUPPORT_EMAIL', 'techsupport@class.stanford.edu')))
                    return default_render_failure(request, failure_msg)
            except User.DoesNotExist:
                log.info('SHIB: No user for %s yet, doing signup' % eamap.external_email)
                return signup(request, eamap)
        else:
            log.info('No user for %s yet, doing signup' % eamap.external_email)
            return signup(request, eamap)

    # We trust shib's authentication, so no need to authenticate using the password again
    if settings.MITX_FEATURES.get('AUTH_USE_SHIB'):
        user = internal_user
        # Assuming this 'AUTHENTICATION_BACKENDS' is set in settings, which I think is safe
        if settings.AUTHENTICATION_BACKENDS:
            auth_backend = settings.AUTHENTICATION_BACKENDS[0]
        else:
            auth_backend = 'django.contrib.auth.backends.ModelBackend'
        user.backend = auth_backend
        log.info('SHIB: Logging in linked user %s' % user.email)
    else:
        uname = internal_user.username
        user = authenticate(username=uname, password=eamap.internal_password)
    if user is None:
        log.warning("External Auth Login failed for %s / %s" %
                    (uname, eamap.internal_password))
        return signup(request, eamap)

    if not user.is_active:
        log.warning("User %s is not active" % (uname))
        # TODO: improve error page
        msg = 'Account not yet activated: please look for link in your email'
        return default_render_failure(request, msg)
    login(request, user)
    request.session.set_expiry(0)

    # Now to try enrollment
    # Need to special case Shibboleth here because it logs in via a GET.
    # testing request.method for extra paranoia
    if settings.MITX_FEATURES.get('AUTH_USE_SHIB') and 'shib:' in external_domain and request.method == 'GET':
        enroll_request = make_shib_enrollment_request(request)
        student_views.try_change_enrollment(enroll_request)
    else:
        student_views.try_change_enrollment(request)
    log.info("Login success - {0} ({1})".format(user.username, user.email))
    if retfun is None:
        return redirect('/')
    return retfun()


@ensure_csrf_cookie
@cache_if_anonymous
def signup(request, eamap=None):
    """
    Present form to complete for signup via external authentication.
    Even though the user has external credentials, he/she still needs
    to create an account on the edX system, and fill in the user
    registration form.

    eamap is an ExteralAuthMap object, specifying the external user
    for which to complete the signup.
    """

    if eamap is None:
        pass

    # save this for use by student.views.create_account
    request.session['ExternalAuthMap'] = eamap

    # default conjoin name, no spaces
    username = eamap.external_name.replace(' ', '')

    context = {'has_extauth_info': True,
               'show_signup_immediately': True,
               'extauth_id': eamap.external_id,
               'extauth_email': eamap.external_email,
               'extauth_username': username,
               'extauth_name': eamap.external_name,
               'ask_for_tos': True,
               }

    # Some openEdX instances can't have terms of service for shib users, like
    # according to Stanford's Office of General Counsel
    if settings.MITX_FEATURES.get('AUTH_USE_SHIB') and settings.MITX_FEATURES.get('SHIB_DISABLE_TOS') and \
       ('shib' in eamap.external_domain):
        context['ask_for_tos'] = False

    # detect if full name is blank and ask for it from user
    context['ask_for_fullname'] = eamap.external_name.strip() == ''

    # validate provided mail and if it's not valid ask the user
    try:
        validate_email(eamap.external_email)
        context['ask_for_email'] = False
    except ValidationError:
        context['ask_for_email'] = True

    log.info('EXTAUTH: Doing signup for %s' % eamap.external_id)

    return student_views.register_user(request, extra_context=context)


# -----------------------------------------------------------------------------
# MIT SSL
# -----------------------------------------------------------------------------


def ssl_dn_extract_info(dn):
    """
    Extract username, email address (may be anyuser@anydomain.com) and
    full name from the SSL DN string.  Return (user,email,fullname) if
    successful, and None otherwise.
    """
    ss = re.search('/emailAddress=(.*)@([^/]+)', dn)
    if ss:
        user = ss.group(1)
        email = "%s@%s" % (user, ss.group(2))
    else:
        return None
    ss = re.search('/CN=([^/]+)/', dn)
    if ss:
        fullname = ss.group(1)
    else:
        return None
    return (user, email, fullname)


def ssl_get_cert_from_request(request):
    """
    Extract user information from certificate, if it exists, returning (user, email, fullname).
    Else return None.
    """
    certkey = "SSL_CLIENT_S_DN"  # specify the request.META field to use

    cert = request.META.get(certkey, '')
    if not cert:
        cert = request.META.get('HTTP_' + certkey, '')
    if not cert:
        try:
            # try the direct apache2 SSL key
            cert = request._req.subprocess_env.get(certkey, '')
        except Exception:
            return ''

    return cert

    (user, email, fullname) = ssl_dn_extract_info(cert)
    return (user, email, fullname)


def ssl_login_shortcut(fn):
    """
    Python function decorator for login procedures, to allow direct login
    based on existing ExternalAuth record and MIT ssl certificate.
    """
    def wrapped(*args, **kwargs):
        if not settings.MITX_FEATURES['AUTH_USE_MIT_CERTIFICATES']:
            return fn(*args, **kwargs)
        request = args[0]
        cert = ssl_get_cert_from_request(request)
        if not cert:		# no certificate information - show normal login window
            return fn(*args, **kwargs)

        (user, email, fullname) = ssl_dn_extract_info(cert)
        return external_login_or_signup(request,
                                        external_id=email,
                                        external_domain="ssl:MIT",
                                        credentials=cert,
                                        email=email,
                                        fullname=fullname)
    return wrapped


@csrf_exempt
def ssl_login(request):
    """
    This is called by student.views.index when
    MITX_FEATURES['AUTH_USE_MIT_CERTIFICATES'] = True

    Used for MIT user authentication.  This presumes the web server
    (nginx) has been configured to require specific client
    certificates.

    If the incoming protocol is HTTPS (SSL) then authenticate via
    client certificate.  The certificate provides user email and
    fullname; this populates the ExternalAuthMap.  The user is
    nevertheless still asked to complete the edX signup.

    Else continues on with student.views.index, and no authentication.
    """
    cert = ssl_get_cert_from_request(request)

    if not cert:
        # no certificate information - go onward to main index
        return student_views.index(request)

    (user, email, fullname) = ssl_dn_extract_info(cert)

    retfun = functools.partial(student_views.index, request)
    return external_login_or_signup(request,
                                    external_id=email,
                                    external_domain="ssl:MIT",
                                    credentials=cert,
                                    email=email,
                                    fullname=fullname,
                                    retfun=retfun)


# -----------------------------------------------------------------------------
# Shibboleth (Stanford and others.  Uses *Apache* environment variables)
# -----------------------------------------------------------------------------
def shib_login(request):
    """
        Uses Apache's REMOTE_USER environment variable as the external id.
        This in turn typically uses EduPersonPrincipalName
        http://www.incommonfederation.org/attributesummary.html#eduPersonPrincipal
        but the configuration is in the shibboleth software.
    """
    shib_error_msg = _(dedent(
        """
        Your university identity server did not return your ID information to us.
        Please try logging in again.  (You may need to restart your browser.)
        """))

    if not request.META.get('REMOTE_USER'):
        log.error("SHIB: no REMOTE_USER found in request.META")
        return default_render_failure(request, shib_error_msg)
    elif not request.META.get('Shib-Identity-Provider'):
        log.error("SHIB: no Shib-Identity-Provider in request.META")
        return default_render_failure(request, shib_error_msg)
    else:
        #if we get here, the user has authenticated properly
        shib = {attr: request.META.get(attr, '')
                for attr in ['REMOTE_USER', 'givenName', 'sn', 'mail', 'Shib-Identity-Provider']}

        #Clean up first name, last name, and email address
        #TODO: Make this less hardcoded re: format, but split will work
        #even if ";" is not present since we are accessing 1st element
        shib['sn'] = shib['sn'].split(";")[0].strip().capitalize().decode('utf-8')
        shib['givenName'] = shib['givenName'].split(";")[0].strip().capitalize().decode('utf-8')

    log.info("SHIB creds returned: %r" % shib)

    return external_login_or_signup(request,
                                    external_id=shib['REMOTE_USER'],
                                    external_domain="shib:" + shib['Shib-Identity-Provider'],
                                    credentials=shib,
                                    email=shib['mail'],
                                    fullname=u'%s %s' % (shib['givenName'], shib['sn']),
                                    )


def make_shib_enrollment_request(request):
    """
        Need this hack function because shibboleth logins don't happen over POST
        but change_enrollment expects its request to be a POST, with
        enrollment_action and course_id POST parameters.
    """
    enroll_request = HttpRequest()
    enroll_request.user = request.user
    enroll_request.session = request.session
    enroll_request.method = "POST"

    # copy() also makes GET and POST mutable
    # See https://docs.djangoproject.com/en/dev/ref/request-response/#django.http.QueryDict.update
    enroll_request.GET = request.GET.copy()
    enroll_request.POST = request.POST.copy()

    # also have to copy these GET parameters over to POST
    if "enrollment_action" not in enroll_request.POST and "enrollment_action" in enroll_request.GET:
        enroll_request.POST.setdefault('enrollment_action', enroll_request.GET.get('enrollment_action'))
    if "course_id" not in enroll_request.POST and "course_id" in enroll_request.GET:
        enroll_request.POST.setdefault('course_id', enroll_request.GET.get('course_id'))

    return enroll_request


def course_specific_login(request, course_id):
    """
       Dispatcher function for selecting the specific login method
       required by the course
    """
    query_string = request.META.get("QUERY_STRING", '')

    try:
        course = course_from_id(course_id)
    except ItemNotFoundError:
        #couldn't find the course, will just return vanilla signin page
        return redirect_with_querystring('signin_user', query_string)

    #now the dispatching conditionals.  Only shib for now
    if settings.MITX_FEATURES.get('AUTH_USE_SHIB') and 'shib:' in course.enrollment_domain:
        return redirect_with_querystring('shib-login', query_string)

    #Default fallthrough to normal signin page
    return redirect_with_querystring('signin_user', query_string)


def course_specific_register(request, course_id):
    """
        Dispatcher function for selecting the specific registration method
        required by the course
    """
    query_string = request.META.get("QUERY_STRING", '')

    try:
        course = course_from_id(course_id)
    except ItemNotFoundError:
        #couldn't find the course, will just return vanilla registration page
        return redirect_with_querystring('register_user', query_string)

    #now the dispatching conditionals.  Only shib for now
    if settings.MITX_FEATURES.get('AUTH_USE_SHIB') and 'shib:' in course.enrollment_domain:
        #shib-login takes care of both registration and login flows
        return redirect_with_querystring('shib-login', query_string)

    #Default fallthrough to normal registration page
    return redirect_with_querystring('register_user', query_string)


def redirect_with_querystring(view_name, query_string):
    """
        Helper function to add query string to redirect views
    """
    if query_string:
        return redirect("%s?%s" % (reverse(view_name), query_string))
    return redirect(view_name)


# -----------------------------------------------------------------------------
# OpenID Provider
# -----------------------------------------------------------------------------


def get_xrds_url(resource, request):
    """
    Return the XRDS url for a resource
    """
    host = request.get_host()

    location = host + '/openid/provider/' + resource + '/'

    if request.is_secure():
        return 'https://' + location
    else:
        return 'http://' + location


def add_openid_simple_registration(request, response, data):
    sreg_data = {}
    sreg_request = sreg.SRegRequest.fromOpenIDRequest(request)
    sreg_fields = sreg_request.allRequestedFields()

    # if consumer requested simple registration fields, add them
    if sreg_fields:
        for field in sreg_fields:
            if field == 'email' and 'email' in data:
                sreg_data['email'] = data['email']
            elif field == 'fullname' and 'fullname' in data:
                sreg_data['fullname'] = data['fullname']
            elif field == 'nickname' and 'nickname' in data:
                sreg_data['nickname'] = data['nickname']

        # construct sreg response
        sreg_response = sreg.SRegResponse.extractResponse(sreg_request,
                                                          sreg_data)
        sreg_response.toMessage(response.fields)


def add_openid_attribute_exchange(request, response, data):
    try:
        ax_request = ax.FetchRequest.fromOpenIDRequest(request)
    except ax.AXError:
        #  not using OpenID attribute exchange extension
        pass
    else:
        ax_response = ax.FetchResponse()

        # if consumer requested attribute exchange fields, add them
        if ax_request and ax_request.requested_attributes:
            for type_uri in ax_request.requested_attributes.iterkeys():
                email_schema = 'http://axschema.org/contact/email'
                name_schema = 'http://axschema.org/namePerson'
                if type_uri == email_schema and 'email' in data:
                    ax_response.addValue(email_schema, data['email'])
                elif type_uri == name_schema and 'fullname' in data:
                    ax_response.addValue(name_schema, data['fullname'])

            # construct ax response
            ax_response.toMessage(response.fields)


def provider_respond(server, request, response, data):
    """
    Respond to an OpenID request
    """
    # get and add extensions
    add_openid_simple_registration(request, response, data)
    add_openid_attribute_exchange(request, response, data)

    # create http response from OpenID response
    webresponse = server.encodeResponse(response)
    http_response = HttpResponse(webresponse.body)
    http_response.status_code = webresponse.code

    # add OpenID headers to response
    for k, v in webresponse.headers.iteritems():
        http_response[k] = v

    return http_response


def validate_trust_root(openid_request):
    """
    Only allow OpenID requests from valid trust roots
    """

    trusted_roots = getattr(settings, 'OPENID_PROVIDER_TRUSTED_ROOT', None)

    if not trusted_roots:
        # not using trusted roots
        return True

    # don't allow empty trust roots
    if (not hasattr(openid_request, 'trust_root') or
            not openid_request.trust_root):
        log.error('no trust_root')
        return False

    # ensure trust root parses cleanly (one wildcard, of form *.foo.com, etc.)
    trust_root = TrustRoot.parse(openid_request.trust_root)
    if not trust_root:
        log.error('invalid trust_root')
        return False

    # don't allow empty return tos
    if (not hasattr(openid_request, 'return_to') or
            not openid_request.return_to):
        log.error('empty return_to')
        return False

    # ensure return to is within trust root
    if not trust_root.validateURL(openid_request.return_to):
        log.error('invalid return_to')
        return False

    # check that the root matches the ones we trust
    if not any(r for r in trusted_roots if fnmatch.fnmatch(trust_root, r)):
        log.error('non-trusted root')
        return False

    return True


@csrf_exempt
def provider_login(request):
    """
    OpenID login endpoint
    """

    # make and validate endpoint
    endpoint = get_xrds_url('login', request)
    if not endpoint:
        return default_render_failure(request, "Invalid OpenID request")

    # initialize store and server
    store = DjangoOpenIDStore()
    server = Server(store, endpoint)

    # first check to see if the request is an OpenID request.
    # If so, the client will have specified an 'openid.mode' as part
    # of the request.
    querydict = dict(request.REQUEST.items())
    error = False
    if 'openid.mode' in request.GET or 'openid.mode' in request.POST:
        # decode request
        openid_request = server.decodeRequest(querydict)

        if not openid_request:
            return default_render_failure(request, "Invalid OpenID request")

        # don't allow invalid and non-trusted trust roots
        if not validate_trust_root(openid_request):
            return default_render_failure(request, "Invalid OpenID trust root")

        # checkid_immediate not supported, require user interaction
        if openid_request.mode == 'checkid_immediate':
            return provider_respond(server, openid_request,
                                    openid_request.answer(False), {})

        # checkid_setup, so display login page
        # (by falling through to the provider_login at the
        # bottom of this method).
        elif openid_request.mode == 'checkid_setup':
            if openid_request.idSelect():
                # remember request and original path
                request.session['openid_setup'] = {
                    'request': openid_request,
                    'url': request.get_full_path()
                }

                # user failed login on previous attempt
                if 'openid_error' in request.session:
                    error = True
                    del request.session['openid_error']

        # OpenID response
        else:
            return provider_respond(server, openid_request,
                                    server.handleRequest(openid_request), {})

    # handle login redirection:  these are also sent to this view function,
    # but are distinguished by lacking the openid mode.  We also know that
    # they are posts, because they come from the popup
    elif request.method == 'POST' and 'openid_setup' in request.session:
        # get OpenID request from session
        openid_setup = request.session['openid_setup']
        openid_request = openid_setup['request']
        openid_request_url = openid_setup['url']
        del request.session['openid_setup']

        # don't allow invalid trust roots
        if not validate_trust_root(openid_request):
            return default_render_failure(request, "Invalid OpenID trust root")

        # check if user with given email exists
        # Failure is redirected to this method (by using the original URL),
        # which will bring up the login dialog.
        email = request.POST.get('email', None)
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            request.session['openid_error'] = True
            msg = "OpenID login failed - Unknown user email: {0}".format(email)
            log.warning(msg)
            return HttpResponseRedirect(openid_request_url)

        # attempt to authenticate user (but not actually log them in...)
        # Failure is again redirected to the login dialog.
        username = user.username
        password = request.POST.get('password', None)
        user = authenticate(username=username, password=password)
        if user is None:
            request.session['openid_error'] = True
            msg = "OpenID login failed - password for {0} is invalid"
            msg = msg.format(email)
            log.warning(msg)
            return HttpResponseRedirect(openid_request_url)

        # authentication succeeded, so fetch user information
        # that was requested
        if user is not None and user.is_active:
            # remove error from session since login succeeded
            if 'openid_error' in request.session:
                del request.session['openid_error']

            # fullname field comes from user profile
            profile = UserProfile.objects.get(user=user)
            log.info("OpenID login success - {0} ({1})".format(user.username,
                                                               user.email))

            # redirect user to return_to location
            url = endpoint + urlquote(user.username)
            response = openid_request.answer(True, None, url)

            # TODO: for CS50 we are forcibly returning the username
            # instead of fullname. In the OpenID simple registration
            # extension, we don't have to return any fields we don't
            # want to, even if they were marked as required by the
            # Consumer. The behavior of what to do when there are
            # missing fields is up to the Consumer. The proper change
            # should only return the username, however this will likely
            # break the CS50 client. Temporarily we will be returning
            # username filling in for fullname in addition to username
            # as sreg nickname.

            # Note too that this is hardcoded, and not really responding to
            # the extensions that were registered in the first place.
            results = {
                'nickname': user.username,
                'email': user.email,
                'fullname': user.username
            }

            # the request succeeded:
            return provider_respond(server, openid_request, response, results)

        # the account is not active, so redirect back to the login page:
        request.session['openid_error'] = True
        msg = "Login failed - Account not active for user {0}".format(username)
        log.warning(msg)
        return HttpResponseRedirect(openid_request_url)

    # determine consumer domain if applicable
    return_to = ''
    if 'openid.return_to' in request.REQUEST:
        return_to = request.REQUEST['openid.return_to']
        matches = re.match(r'\w+:\/\/([\w\.-]+)', return_to)
        return_to = matches.group(1)

    # display login page
    response = render_to_response('provider_login.html', {
        'error': error,
        'return_to': return_to
    })

    # add custom XRDS header necessary for discovery process
    response['X-XRDS-Location'] = get_xrds_url('xrds', request)
    return response


def provider_identity(request):
    """
    XRDS for identity discovery
    """

    response = render_to_response('identity.xml',
                                  {'url': get_xrds_url('login', request)},
                                  mimetype='text/xml')

    # custom XRDS header necessary for discovery process
    response['X-XRDS-Location'] = get_xrds_url('identity', request)
    return response


def provider_xrds(request):
    """
    XRDS for endpoint discovery
    """

    response = render_to_response('xrds.xml',
                                  {'url': get_xrds_url('login', request)},
                                  mimetype='text/xml')

    # custom XRDS header necessary for discovery process
    response['X-XRDS-Location'] = get_xrds_url('xrds', request)
    return response


#-------------------
# Pearson
#-------------------
def course_from_id(course_id):
    """Return the CourseDescriptor corresponding to this course_id"""
    course_loc = CourseDescriptor.id_to_location(course_id)
    return modulestore().get_instance(course_id, course_loc)


@csrf_exempt
def test_center_login(request):
    ''' Log in students taking exams via Pearson

    Takes a POST request that contains the following keys:
        - code - a security code provided by  Pearson
        - clientCandidateID
        - registrationID
        - exitURL - the url that we redirect to once we're done
        - vueExamSeriesCode - a code that indicates the exam that we're using
    '''
    # errors are returned by navigating to the error_url, adding a query parameter named "code"
    # which contains the error code describing the exceptional condition.
    def makeErrorURL(error_url, error_code):
        log.error("generating error URL with error code {}".format(error_code))
        return "{}?code={}".format(error_url, error_code)

    # get provided error URL, which will be used as a known prefix for returning error messages to the
    # Pearson shell.
    error_url = request.POST.get("errorURL")

    # TODO: check that the parameters have not been tampered with, by comparing the code provided by Pearson
    # with the code we calculate for the same parameters.
    if 'code' not in request.POST:
        return HttpResponseRedirect(makeErrorURL(error_url, "missingSecurityCode"))
    code = request.POST.get("code")

    # calculate SHA for query string
    # TODO: figure out how to get the original query string, so we can hash it and compare.

    if 'clientCandidateID' not in request.POST:
        return HttpResponseRedirect(makeErrorURL(error_url, "missingClientCandidateID"))
    client_candidate_id = request.POST.get("clientCandidateID")

    # TODO: check remaining parameters, and maybe at least log if they're not matching
    # expected values....
    # registration_id = request.POST.get("registrationID")
    # exit_url = request.POST.get("exitURL")

    # find testcenter_user that matches the provided ID:
    try:
        testcenteruser = TestCenterUser.objects.get(client_candidate_id=client_candidate_id)
    except TestCenterUser.DoesNotExist:
        log.error("not able to find demographics for cand ID {}".format(client_candidate_id))
        return HttpResponseRedirect(makeErrorURL(error_url, "invalidClientCandidateID"))

    # find testcenter_registration that matches the provided exam code:
    # Note that we could rely in future on either the registrationId or the exam code,
    # or possibly both.  But for now we know what to do with an ExamSeriesCode,
    # while we currently have no record of RegistrationID values at all.
    if 'vueExamSeriesCode' not in request.POST:
        # we are not allowed to make up a new error code, according to Pearson,
        # so instead of "missingExamSeriesCode", we use a valid one that is
        # inaccurate but at least distinct.  (Sigh.)
        log.error("missing exam series code for cand ID {}".format(client_candidate_id))
        return HttpResponseRedirect(makeErrorURL(error_url, "missingPartnerID"))
    exam_series_code = request.POST.get('vueExamSeriesCode')

    registrations = TestCenterRegistration.objects.filter(testcenter_user=testcenteruser, exam_series_code=exam_series_code)
    if not registrations:
        log.error("not able to find exam registration for exam {} and cand ID {}".format(exam_series_code, client_candidate_id))
        return HttpResponseRedirect(makeErrorURL(error_url, "noTestsAssigned"))

    # TODO: figure out what to do if there are more than one registrations....
    # for now, just take the first...
    registration = registrations[0]

    course_id = registration.course_id
    course = course_from_id(course_id)  # assume it will be found....
    if not course:
        log.error("not able to find course from ID {} for cand ID {}".format(course_id, client_candidate_id))
        return HttpResponseRedirect(makeErrorURL(error_url, "incorrectCandidateTests"))
    exam = course.get_test_center_exam(exam_series_code)
    if not exam:
        log.error("not able to find exam {} for course ID {} and cand ID {}".format(exam_series_code, course_id, client_candidate_id))
        return HttpResponseRedirect(makeErrorURL(error_url, "incorrectCandidateTests"))
    location = exam.exam_url
    log.info("proceeding with test of cand {} on exam {} for course {}: URL = {}".format(client_candidate_id, exam_series_code, course_id, location))

    # check if the test has already been taken
    timelimit_descriptor = modulestore().get_instance(course_id, Location(location))
    if not timelimit_descriptor:
        log.error("cand {} on exam {} for course {}: descriptor not found for location {}".format(client_candidate_id, exam_series_code, course_id, location))
        return HttpResponseRedirect(makeErrorURL(error_url, "missingClientProgram"))

    timelimit_module_cache = ModelDataCache.cache_for_descriptor_descendents(course_id, testcenteruser.user,
                                                                             timelimit_descriptor, depth=None)
    timelimit_module = get_module_for_descriptor(request.user, request, timelimit_descriptor,
                                                 timelimit_module_cache, course_id, position=None)
    if not timelimit_module.category == 'timelimit':
        log.error("cand {} on exam {} for course {}: non-timelimit module at location {}".format(client_candidate_id, exam_series_code, course_id, location))
        return HttpResponseRedirect(makeErrorURL(error_url, "missingClientProgram"))

    if timelimit_module and timelimit_module.has_ended:
        log.warning("cand {} on exam {} for course {}: test already over at {}".format(client_candidate_id, exam_series_code, course_id, timelimit_module.ending_at))
        return HttpResponseRedirect(makeErrorURL(error_url, "allTestsTaken"))

    # check if we need to provide an accommodation:
    time_accommodation_mapping = {'ET12ET': 'ADDHALFTIME',
                                  'ET30MN': 'ADD30MIN',
                                  'ETDBTM': 'ADDDOUBLE', }

    time_accommodation_code = None
    for code in registration.get_accommodation_codes():
        if code in time_accommodation_mapping:
            time_accommodation_code = time_accommodation_mapping[code]

    if time_accommodation_code:
        timelimit_module.accommodation_code = time_accommodation_code
        log.info("cand {} on exam {} for course {}: receiving accommodation {}".format(client_candidate_id, exam_series_code, course_id, time_accommodation_code))

    # UGLY HACK!!!
    # Login assumes that authentication has occurred, and that there is a
    # backend annotation on the user object, indicating which backend
    # against which the user was authenticated.  We're authenticating here
    # against the registration entry, and assuming that the request given
    # this information is correct, we allow the user to be logged in
    # without a password.  This could all be formalized in a backend object
    # that does the above checking.
    # TODO: (brian) create a backend class to do this.
    # testcenteruser.user.backend = "%s.%s" % (backend.__module__, backend.__class__.__name__)
    testcenteruser.user.backend = "%s.%s" % ("TestcenterAuthenticationModule", "TestcenterAuthenticationClass")
    login(request, testcenteruser.user)

    # And start the test:
    return jump_to(request, course_id, location)
