from functools import wraps
import copy
import json


def expect_json(view_function):
    """
    View decorator for simplifying handing of requests that expect json.  If the request's
    CONTENT_TYPE is application/json, parses the json dict from request.body, and updates
    request.POST with the contents.
    """
    @wraps(view_function)
    def expect_json_with_cloned_request(request, *args, **kwargs):
        # cdodge: fix postback errors in CMS. The POST 'content-type' header can include additional information
        # e.g. 'charset', so we can't do a direct string compare
        if request.META.get('CONTENT_TYPE', '').lower().startswith("application/json"):
            cloned_request = copy.copy(request)
            cloned_request.POST = json.loads(request.body)
            return view_function(cloned_request, *args, **kwargs)
        else:
            return view_function(request, *args, **kwargs)

    return expect_json_with_cloned_request
