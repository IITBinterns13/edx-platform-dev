'''
Created on Jan 18, 2013

@author: brian
'''
import openid
from openid.fetchers import HTTPFetcher, HTTPResponse
from urlparse import parse_qs

from django.conf import settings
from django.test import TestCase, LiveServerTestCase
from django.test.utils import override_settings
# from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test.client import RequestFactory
from unittest import skipUnless


class MyFetcher(HTTPFetcher):
    """A fetcher that uses server-internal calls for performing HTTP
    requests.
    """

    def __init__(self, client):
        """@param client: A test client object"""

        super(MyFetcher, self).__init__()
        self.client = client

    def fetch(self, url, body=None, headers=None):
        """Perform an HTTP request

        @raises Exception: Any exception that can be raised by Django

        @see: C{L{HTTPFetcher.fetch}}
        """
        if body:
            # method = 'POST'
            # undo the URL encoding of the POST arguments
            data = parse_qs(body)
            response = self.client.post(url, data)
        else:
            # method = 'GET'
            data = {}
            if headers and 'Accept' in headers:
                data['CONTENT_TYPE'] = headers['Accept']
            response = self.client.get(url, data)

        # Translate the test client response to the fetcher's HTTP response abstraction
        content = response.content
        final_url = url
        response_headers = {}
        if 'Content-Type' in response:
            response_headers['content-type'] = response['Content-Type']
        if 'X-XRDS-Location' in response:
            response_headers['x-xrds-location'] = response['X-XRDS-Location']
        status = response.status_code

        return HTTPResponse(
            body=content,
            final_url=final_url,
            headers=response_headers,
            status=status,
        )


class OpenIdProviderTest(TestCase):
    """
    Tests of the OpenId login
    """

    @skipUnless(settings.MITX_FEATURES.get('AUTH_USE_OPENID') or
                settings.MITX_FEATURES.get('AUTH_USE_OPENID_PROVIDER'), True)
    def test_begin_login_with_xrds_url(self):

        # the provider URL must be converted to an absolute URL in order to be
        # used as an openid provider.
        provider_url = reverse('openid-provider-xrds')
        factory = RequestFactory()
        request = factory.request()
        abs_provider_url = request.build_absolute_uri(location=provider_url)

        # In order for this absolute URL to work (i.e. to get xrds, then authentication)
        # in the test environment, we either need a live server that works with the default
        # fetcher (i.e. urlopen2), or a test server that is reached through a custom fetcher.
        # Here we do the latter:
        fetcher = MyFetcher(self.client)
        openid.fetchers.setDefaultFetcher(fetcher, wrap_exceptions=False)

        # now we can begin the login process by invoking a local openid client,
        # with a pointer to the (also-local) openid provider:
        with self.settings(OPENID_SSO_SERVER_URL=abs_provider_url):
            url = reverse('openid-login')
            resp = self.client.post(url)
            code = 200
            self.assertEqual(resp.status_code, code,
                             "got code {0} for url '{1}'. Expected code {2}"
                             .format(resp.status_code, url, code))

    @skipUnless(settings.MITX_FEATURES.get('AUTH_USE_OPENID') or
                settings.MITX_FEATURES.get('AUTH_USE_OPENID_PROVIDER'), True)
    def test_begin_login_with_login_url(self):

        # the provider URL must be converted to an absolute URL in order to be
        # used as an openid provider.
        provider_url = reverse('openid-provider-login')
        factory = RequestFactory()
        request = factory.request()
        abs_provider_url = request.build_absolute_uri(location=provider_url)

        # In order for this absolute URL to work (i.e. to get xrds, then authentication)
        # in the test environment, we either need a live server that works with the default
        # fetcher (i.e. urlopen2), or a test server that is reached through a custom fetcher.
        # Here we do the latter:
        fetcher = MyFetcher(self.client)
        openid.fetchers.setDefaultFetcher(fetcher, wrap_exceptions=False)

        # now we can begin the login process by invoking a local openid client,
        # with a pointer to the (also-local) openid provider:
        with self.settings(OPENID_SSO_SERVER_URL=abs_provider_url):
            url = reverse('openid-login')
            resp = self.client.post(url)
            code = 200
            self.assertEqual(resp.status_code, code,
                             "got code {0} for url '{1}'. Expected code {2}"
                             .format(resp.status_code, url, code))
            self.assertContains(resp, '<input name="openid.mode" type="hidden" value="checkid_setup" />', html=True)
            self.assertContains(resp, '<input name="openid.ns" type="hidden" value="http://specs.openid.net/auth/2.0" />', html=True)
            self.assertContains(resp, '<input name="openid.identity" type="hidden" value="http://specs.openid.net/auth/2.0/identifier_select" />', html=True)
            self.assertContains(resp, '<input name="openid.claimed_id" type="hidden" value="http://specs.openid.net/auth/2.0/identifier_select" />', html=True)
            self.assertContains(resp, '<input name="openid.ns.ax" type="hidden" value="http://openid.net/srv/ax/1.0" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.mode" type="hidden" value="fetch_request" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.required" type="hidden" value="email,fullname,old_email,firstname,old_nickname,lastname,old_fullname,nickname" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.type.fullname" type="hidden" value="http://axschema.org/namePerson" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.type.lastname" type="hidden" value="http://axschema.org/namePerson/last" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.type.firstname" type="hidden" value="http://axschema.org/namePerson/first" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.type.nickname" type="hidden" value="http://axschema.org/namePerson/friendly" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.type.email" type="hidden" value="http://axschema.org/contact/email" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.type.old_email" type="hidden" value="http://schema.openid.net/contact/email" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.type.old_nickname" type="hidden" value="http://schema.openid.net/namePerson/friendly" />', html=True)
            self.assertContains(resp, '<input name="openid.ax.type.old_fullname" type="hidden" value="http://schema.openid.net/namePerson" />', html=True)
            self.assertContains(resp, '<input type="submit" value="Continue" />', html=True)
            # this should work on the server:
            self.assertContains(resp, '<input name="openid.realm" type="hidden" value="http://testserver/" />', html=True)

            # not included here are elements that will vary from run to run:
            # <input name="openid.return_to" type="hidden" value="http://testserver/openid/complete/?janrain_nonce=2013-01-23T06%3A20%3A17ZaN7j6H" />
            # <input name="openid.assoc_handle" type="hidden" value="{HMAC-SHA1}{50ff8120}{rh87+Q==}" />

    def attempt_login(self, expected_code, **kwargs):
        """ Attempt to log in through the open id provider login """
        url = reverse('openid-provider-login')
        post_args = {
            "openid.mode": "checkid_setup",
            "openid.return_to": "http://testserver/openid/complete/?janrain_nonce=2013-01-23T06%3A20%3A17ZaN7j6H",
            "openid.assoc_handle": "{HMAC-SHA1}{50ff8120}{rh87+Q==}",
            "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
            "openid.ns": "http://specs.openid.net/auth/2.0",
            "openid.realm": "http://testserver/",
            "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
            "openid.ns.ax": "http://openid.net/srv/ax/1.0",
            "openid.ax.mode": "fetch_request",
            "openid.ax.required": "email,fullname,old_email,firstname,old_nickname,lastname,old_fullname,nickname",
            "openid.ax.type.fullname": "http://axschema.org/namePerson",
            "openid.ax.type.lastname": "http://axschema.org/namePerson/last",
            "openid.ax.type.firstname": "http://axschema.org/namePerson/first",
            "openid.ax.type.nickname": "http://axschema.org/namePerson/friendly",
            "openid.ax.type.email": "http://axschema.org/contact/email",
            "openid.ax.type.old_email": "http://schema.openid.net/contact/email",
            "openid.ax.type.old_nickname": "http://schema.openid.net/namePerson/friendly",
            "openid.ax.type.old_fullname": "http://schema.openid.net/namePerson",
        }
        # override the default args with any given arguments
        for key in kwargs:
            post_args["openid." + key] = kwargs[key]

        resp = self.client.post(url, post_args)
        code = expected_code
        self.assertEqual(resp.status_code, code,
                         "got code {0} for url '{1}'. Expected code {2}"
                         .format(resp.status_code, url, code))

    @skipUnless(settings.MITX_FEATURES.get('AUTH_USE_OPENID') or
                settings.MITX_FEATURES.get('AUTH_USE_OPENID_PROVIDER'), True)
    def test_open_id_setup(self):
        """ Attempt a standard successful login """
        self.attempt_login(200)

    @skipUnless(settings.MITX_FEATURES.get('AUTH_USE_OPENID') or
                settings.MITX_FEATURES.get('AUTH_USE_OPENID_PROVIDER'), True)
    def test_invalid_namespace(self):
        """ Test for 403 error code when the namespace of the request is invalid"""
        self.attempt_login(403, ns="http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")

    @override_settings(OPENID_PROVIDER_TRUSTED_ROOTS=['http://apps.cs50.edx.org'])
    @skipUnless(settings.MITX_FEATURES.get('AUTH_USE_OPENID') or
                settings.MITX_FEATURES.get('AUTH_USE_OPENID_PROVIDER'), True)
    def test_invalid_return_url(self):
        """ Test for 403 error code when the url"""
        self.attempt_login(403, return_to="http://apps.cs50.edx.or")


class OpenIdProviderLiveServerTest(LiveServerTestCase):
    """
    In order for this absolute URL to work (i.e. to get xrds, then authentication)
    in the test environment, we either need a live server that works with the default
    fetcher (i.e. urlopen2), or a test server that is reached through a custom fetcher.
    Here we do the former.
    """

    @skipUnless(settings.MITX_FEATURES.get('AUTH_USE_OPENID') or
                settings.MITX_FEATURES.get('AUTH_USE_OPENID_PROVIDER'), True)
    def test_begin_login(self):
        # the provider URL must be converted to an absolute URL in order to be
        # used as an openid provider.
        provider_url = reverse('openid-provider-xrds')
        factory = RequestFactory()
        request = factory.request()
        abs_provider_url = request.build_absolute_uri(location=provider_url)

        # now we can begin the login process by invoking a local openid client,
        # with a pointer to the (also-local) openid provider:
        with self.settings(OPENID_SSO_SERVER_URL=abs_provider_url):
            url = reverse('openid-login')
            resp = self.client.post(url)
            code = 200
            self.assertEqual(resp.status_code, code,
                             "got code {0} for url '{1}'. Expected code {2}"
                             .format(resp.status_code, url, code))
