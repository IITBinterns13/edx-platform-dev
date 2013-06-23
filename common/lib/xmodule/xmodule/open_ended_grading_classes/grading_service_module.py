# This class gives a common interface for logging into the grading controller
import json
import logging
import requests
from requests.exceptions import RequestException, ConnectionError, HTTPError

from .combined_open_ended_rubric import CombinedOpenEndedRubric
from lxml import etree

log = logging.getLogger(__name__)


class GradingServiceError(Exception):
    pass


class GradingService(object):
    """
    Interface to staff grading backend.
    """

    def __init__(self, config):
        self.username = config['username']
        self.password = config['password']
        self.session = requests.session()
        self.system = config['system']

    def _login(self):
        """
        Log into the staff grading service.

        Raises requests.exceptions.HTTPError if something goes wrong.

        Returns the decoded json dict of the response.
        """
        response = self.session.post(self.login_url,
                                     {'username': self.username,
                                      'password': self.password, })

        response.raise_for_status()

        return response.json

    def post(self, url, data, allow_redirects=False):
        """
        Make a post request to the grading controller
        """
        try:
            op = lambda: self.session.post(url, data=data,
                                           allow_redirects=allow_redirects)
            r = self._try_with_login(op)
        except (RequestException, ConnectionError, HTTPError) as err:
            # reraise as promised GradingServiceError, but preserve stacktrace.
            #This is a dev_facing_error
            error_string = "Problem posting data to the grading controller.  URL: {0}, data: {1}".format(url, data)
            log.error(error_string)
            raise GradingServiceError(error_string)

        return r.text

    def get(self, url, params, allow_redirects=False):
        """
        Make a get request to the grading controller
        """
        log.debug(params)
        op = lambda: self.session.get(url,
                                      allow_redirects=allow_redirects,
                                      params=params)
        try:
            r = self._try_with_login(op)
        except (RequestException, ConnectionError, HTTPError) as err:
            # reraise as promised GradingServiceError, but preserve stacktrace.
            #This is a dev_facing_error
            error_string = "Problem getting data from the grading controller.  URL: {0}, params: {1}".format(url, params)
            log.error(error_string)
            raise GradingServiceError(error_string)

        return r.text

    def _try_with_login(self, operation):
        """
        Call operation(), which should return a requests response object.  If
        the request fails with a 'login_required' error, call _login() and try
        the operation again.

        Returns the result of operation().  Does not catch exceptions.
        """
        response = operation()
        if (response.json
            and response.json.get('success') is False
            and response.json.get('error') == 'login_required'):
            # apparrently we aren't logged in.  Try to fix that.
            r = self._login()
            if r and not r.get('success'):
                log.warning("Couldn't log into staff_grading backend. Response: %s",
                            r)
                # try again
            response = operation()
            response.raise_for_status()

        return response

    def _render_rubric(self, response, view_only=False):
        """
        Given an HTTP Response with the key 'rubric', render out the html
        required to display the rubric and put it back into the response

        returns the updated response as a dictionary that can be serialized later

        """
        try:
            response_json = json.loads(response)
        except:
            response_json = response

        try:
            if 'rubric' in response_json:
                rubric = response_json['rubric']
                rubric_renderer = CombinedOpenEndedRubric(self.system, view_only)
                rubric_dict = rubric_renderer.render_rubric(rubric)
                success = rubric_dict['success']
                rubric_html = rubric_dict['html']
                response_json['rubric'] = rubric_html
            return response_json
        # if we can't parse the rubric into HTML,
        except etree.XMLSyntaxError, RubricParsingError:
            #This is a dev_facing_error
            log.exception("Cannot parse rubric string. Raw string: {0}"
            .format(rubric))
            return {'success': False,
                    'error': 'Error displaying submission'}
        except ValueError:
            #This is a dev_facing_error
            log.exception("Error parsing response: {0}".format(response))
            return {'success': False,
                    'error': "Error displaying submission"}
