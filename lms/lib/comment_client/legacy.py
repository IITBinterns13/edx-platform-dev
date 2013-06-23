def delete_threads(commentable_id, *args, **kwargs):
    return _perform_request('delete', _url_for_commentable_threads(commentable_id), *args, **kwargs)


def get_threads(commentable_id, recursive=False, query_params={}, *args, **kwargs):
    default_params = {'page': 1, 'per_page': 20, 'recursive': recursive}
    attributes = dict(default_params.items() + query_params.items())
    response = _perform_request('get', _url_for_threads(commentable_id), attributes, *args, **kwargs)
    return response.get('collection', []), response.get('page', 1), response.get('num_pages', 1)


def search_threads(course_id, recursive=False, query_params={}, *args, **kwargs):
    default_params = {'page': 1, 'per_page': 20, 'course_id': course_id, 'recursive': recursive}
    attributes = dict(default_params.items() + query_params.items())
    response = _perform_request('get', _url_for_search_threads(), attributes, *args, **kwargs)
    return response.get('collection', []), response.get('page', 1), response.get('num_pages', 1)


def search_similar_threads(course_id, recursive=False, query_params={}, *args, **kwargs):
    default_params = {'course_id': course_id, 'recursive': recursive}
    attributes = dict(default_params.items() + query_params.items())
    return _perform_request('get', _url_for_search_similar_threads(), attributes, *args, **kwargs)


def search_recent_active_threads(course_id, recursive=False, query_params={}, *args, **kwargs):
    default_params = {'course_id': course_id, 'recursive': recursive}
    attributes = dict(default_params.items() + query_params.items())
    return _perform_request('get', _url_for_search_recent_active_threads(), attributes, *args, **kwargs)


def search_trending_tags(course_id, query_params={}, *args, **kwargs):
    default_params = {'course_id': course_id}
    attributes = dict(default_params.items() + query_params.items())
    return _perform_request('get', _url_for_search_trending_tags(), attributes, *args, **kwargs)


def create_user(attributes, *args, **kwargs):
    return _perform_request('post', _url_for_users(), attributes, *args, **kwargs)


def update_user(user_id, attributes, *args, **kwargs):
    return _perform_request('put', _url_for_user(user_id), attributes, *args, **kwargs)


def get_threads_tags(*args, **kwargs):
    return _perform_request('get', _url_for_threads_tags(), {}, *args, **kwargs)


def tags_autocomplete(value, *args, **kwargs):
    return _perform_request('get', _url_for_threads_tags_autocomplete(), {'value': value}, *args, **kwargs)


def create_thread(commentable_id, attributes, *args, **kwargs):
    return _perform_request('post', _url_for_threads(commentable_id), attributes, *args, **kwargs)


def get_thread(thread_id, recursive=False, *args, **kwargs):
    return _perform_request('get', _url_for_thread(thread_id), {'recursive': recursive}, *args, **kwargs)


def update_thread(thread_id, attributes, *args, **kwargs):
    return _perform_request('put', _url_for_thread(thread_id), attributes, *args, **kwargs)


def create_comment(thread_id, attributes, *args, **kwargs):
    return _perform_request('post', _url_for_thread_comments(thread_id), attributes, *args, **kwargs)


def delete_thread(thread_id, *args, **kwargs):
    return _perform_request('delete', _url_for_thread(thread_id), *args, **kwargs)


def get_comment(comment_id, recursive=False, *args, **kwargs):
    return _perform_request('get', _url_for_comment(comment_id), {'recursive': recursive}, *args, **kwargs)


def update_comment(comment_id, attributes, *args, **kwargs):
    return _perform_request('put', _url_for_comment(comment_id), attributes, *args, **kwargs)


def create_sub_comment(comment_id, attributes, *args, **kwargs):
    return _perform_request('post', _url_for_comment(comment_id), attributes, *args, **kwargs)


def delete_comment(comment_id, *args, **kwargs):
    return _perform_request('delete', _url_for_comment(comment_id), *args, **kwargs)


def vote_for_comment(comment_id, user_id, value, *args, **kwargs):
    return _perform_request('put', _url_for_vote_comment(comment_id), {'user_id': user_id, 'value': value}, *args, **kwargs)


def undo_vote_for_comment(comment_id, user_id, *args, **kwargs):
    return _perform_request('delete', _url_for_vote_comment(comment_id), {'user_id': user_id}, *args, **kwargs)


def vote_for_thread(thread_id, user_id, value, *args, **kwargs):
    return _perform_request('put', _url_for_vote_thread(thread_id), {'user_id': user_id, 'value': value}, *args, **kwargs)


def undo_vote_for_thread(thread_id, user_id, *args, **kwargs):
    return _perform_request('delete', _url_for_vote_thread(thread_id), {'user_id': user_id}, *args, **kwargs)


def get_notifications(user_id, *args, **kwargs):
    return _perform_request('get', _url_for_notifications(user_id), *args, **kwargs)


def get_user_info(user_id, complete=True, *args, **kwargs):
    return _perform_request('get', _url_for_user(user_id), {'complete': complete}, *args, **kwargs)


def subscribe(user_id, subscription_detail, *args, **kwargs):
    return _perform_request('post', _url_for_subscription(user_id), subscription_detail, *args, **kwargs)


def subscribe_user(user_id, followed_user_id, *args, **kwargs):
    return subscribe(user_id, {'source_type': 'user', 'source_id': followed_user_id})

follow = subscribe_user


def subscribe_thread(user_id, thread_id, *args, **kwargs):
    return subscribe(user_id, {'source_type': 'thread', 'source_id': thread_id})


def subscribe_commentable(user_id, commentable_id, *args, **kwargs):
    return subscribe(user_id, {'source_type': 'other', 'source_id': commentable_id})


def unsubscribe(user_id, subscription_detail, *args, **kwargs):
    return _perform_request('delete', _url_for_subscription(user_id), subscription_detail, *args, **kwargs)


def unsubscribe_user(user_id, followed_user_id, *args, **kwargs):
    return unsubscribe(user_id, {'source_type': 'user', 'source_id': followed_user_id})

unfollow = unsubscribe_user


def unsubscribe_thread(user_id, thread_id, *args, **kwargs):
    return unsubscribe(user_id, {'source_type': 'thread', 'source_id': thread_id})


def unsubscribe_commentable(user_id, commentable_id, *args, **kwargs):
    return unsubscribe(user_id, {'source_type': 'other', 'source_id': commentable_id})


def _perform_request(method, url, data_or_params=None, *args, **kwargs):
    if method in ['post', 'put', 'patch']:
        response = requests.request(method, url, data=data_or_params)
    else:
        response = requests.request(method, url, params=data_or_params)
    if 200 < response.status_code < 500:
        raise CommentClientError(response.text)
    elif response.status_code == 500:
        raise CommentClientUnknownError(response.text)
    else:
        if kwargs.get("raw", False):
            return response.text
        else:
            return json.loads(response.text)


def _url_for_threads(commentable_id):
    return "{prefix}/{commentable_id}/threads".format(prefix=PREFIX, commentable_id=commentable_id)


def _url_for_thread(thread_id):
    return "{prefix}/threads/{thread_id}".format(prefix=PREFIX, thread_id=thread_id)


def _url_for_thread_comments(thread_id):
    return "{prefix}/threads/{thread_id}/comments".format(prefix=PREFIX, thread_id=thread_id)


def _url_for_comment(comment_id):
    return "{prefix}/comments/{comment_id}".format(prefix=PREFIX, comment_id=comment_id)


def _url_for_vote_comment(comment_id):
    return "{prefix}/comments/{comment_id}/votes".format(prefix=PREFIX, comment_id=comment_id)


def _url_for_vote_thread(thread_id):
    return "{prefix}/threads/{thread_id}/votes".format(prefix=PREFIX, thread_id=thread_id)


def _url_for_notifications(user_id):
    return "{prefix}/users/{user_id}/notifications".format(prefix=PREFIX, user_id=user_id)


def _url_for_subscription(user_id):
    return "{prefix}/users/{user_id}/subscriptions".format(prefix=PREFIX, user_id=user_id)


def _url_for_user(user_id):
    return "{prefix}/users/{user_id}".format(prefix=PREFIX, user_id=user_id)


def _url_for_search_threads():
    return "{prefix}/search/threads".format(prefix=PREFIX)


def _url_for_search_similar_threads():
    return "{prefix}/search/threads/more_like_this".format(prefix=PREFIX)


def _url_for_search_recent_active_threads():
    return "{prefix}/search/threads/recent_active".format(prefix=PREFIX)


def _url_for_search_trending_tags():
    return "{prefix}/search/tags/trending".format(prefix=PREFIX)


def _url_for_threads_tags():
    return "{prefix}/threads/tags".format(prefix=PREFIX)


def _url_for_threads_tags_autocomplete():
    return "{prefix}/threads/tags/autocomplete".format(prefix=PREFIX)


def _url_for_users():
    return "{prefix}/users".format(prefix=PREFIX)
