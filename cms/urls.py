from django.conf import settings
from django.conf.urls import patterns, include, url

# Import this file so it can do its work, even though we don't use the name.
# pylint: disable=W0611
from . import one_time_startup

# Uncomment the next two lines to enable the admin:
# from django.contrib import admin
# admin.autodiscover()

urlpatterns = ('',  # nopep8
    url(r'^$', 'contentstore.views.howitworks', name='homepage'),
    url(r'^listing', 'contentstore.views.index', name='index'),
    url(r'^edit/(?P<location>.*?)$', 'contentstore.views.edit_unit', name='edit_unit'),
    url(r'^subsection/(?P<location>.*?)$', 'contentstore.views.edit_subsection', name='edit_subsection'),
    url(r'^preview_component/(?P<location>.*?)$', 'contentstore.views.preview_component', name='preview_component'),
    url(r'^save_item$', 'contentstore.views.save_item', name='save_item'),
    url(r'^delete_item$', 'contentstore.views.delete_item', name='delete_item'),
    url(r'^clone_item$', 'contentstore.views.clone_item', name='clone_item'),
    url(r'^create_draft$', 'contentstore.views.create_draft', name='create_draft'),
    url(r'^publish_draft$', 'contentstore.views.publish_draft', name='publish_draft'),
    url(r'^unpublish_unit$', 'contentstore.views.unpublish_unit', name='unpublish_unit'),
    url(r'^create_new_course', 'contentstore.views.create_new_course', name='create_new_course'),
    url(r'^reorder_static_tabs', 'contentstore.views.reorder_static_tabs', name='reorder_static_tabs'),

    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/course/(?P<name>[^/]+)$',
        'contentstore.views.course_index', name='course_index'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/import/(?P<name>[^/]+)$',
        'contentstore.views.import_course', name='import_course'),

    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/export/(?P<name>[^/]+)$',
        'contentstore.views.export_course', name='export_course'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/generate_export/(?P<name>[^/]+)$',
        'contentstore.views.generate_export_course', name='generate_export_course'),

    url(r'^preview/modx/(?P<preview_id>[^/]*)/(?P<location>.*?)/(?P<dispatch>[^/]*)$',
        'contentstore.views.preview_dispatch', name='preview_dispatch'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/course/(?P<coursename>[^/]+)/upload_asset$',
        'contentstore.views.upload_asset', name='upload_asset'),


    url(r'^manage_users/(?P<location>.*?)$', 'contentstore.views.manage_users', name='manage_users'),
    url(r'^add_user/(?P<location>.*?)$',
        'contentstore.views.add_user', name='add_user'),
    url(r'^remove_user/(?P<location>.*?)$',
        'contentstore.views.remove_user', name='remove_user'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/course/(?P<name>[^/]+)/remove_user$',
        'contentstore.views.remove_user', name='remove_user'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/info/(?P<name>[^/]+)$',
        'contentstore.views.course_info', name='course_info'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/course_info/updates/(?P<provided_id>.*)$',
        'contentstore.views.course_info_updates', name='course_info_json'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/settings-details/(?P<name>[^/]+)$',
        'contentstore.views.get_course_settings', name='settings_details'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/settings-grading/(?P<name>[^/]+)$',
        'contentstore.views.course_config_graders_page', name='settings_grading'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/settings-details/(?P<name>[^/]+)/section/(?P<section>[^/]+).*$',
        'contentstore.views.course_settings_updates', name='course_settings'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/settings-grading/(?P<name>[^/]+)/(?P<grader_index>.*)$',
        'contentstore.views.course_grader_updates', name='course_settings'),
    # This is the URL to initially render the course advanced settings.
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/settings-advanced/(?P<name>[^/]+)$',
        'contentstore.views.course_config_advanced_page', name='course_advanced_settings'),
    # This is the URL used by BackBone for updating and re-fetching the model.
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/settings-advanced/(?P<name>[^/]+)/update.*$',
        'contentstore.views.course_advanced_updates', name='course_advanced_settings_updates'),

    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/(?P<category>[^/]+)/(?P<name>[^/]+)/gradeas.*$',
        'contentstore.views.assignment_type_update', name='assignment_type_update'),

    url(r'^pages/(?P<org>[^/]+)/(?P<course>[^/]+)/course/(?P<coursename>[^/]+)$',
        'contentstore.views.static_pages',
        name='static_pages'),
    url(r'^edit_static/(?P<org>[^/]+)/(?P<course>[^/]+)/course/(?P<coursename>[^/]+)$',
        'contentstore.views.edit_static', name='edit_static'),
    url(r'^edit_tabs/(?P<org>[^/]+)/(?P<course>[^/]+)/course/(?P<coursename>[^/]+)$',
        'contentstore.views.edit_tabs', name='edit_tabs'),

    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/assets/(?P<name>[^/]+)$',
        'contentstore.views.asset_index', name='asset_index'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/assets/(?P<name>[^/]+)/remove$',
        'contentstore.views.assets.remove_asset', name='remove_asset'),

    # this is a generic method to return the data/metadata associated with a xmodule
    url(r'^module_info/(?P<module_location>.*)$',
        'contentstore.views.module_info', name='module_info'),


    # temporary landing page for a course
    url(r'^edge/(?P<org>[^/]+)/(?P<course>[^/]+)/course/(?P<coursename>[^/]+)$',
        'contentstore.views.landing', name='landing'),

    url(r'^not_found$', 'contentstore.views.not_found', name='not_found'),
    url(r'^server_error$', 'contentstore.views.server_error', name='server_error'),

    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/assets/(?P<name>[^/]+)$',
        'contentstore.views.asset_index', name='asset_index'),

    # temporary landing page for edge
    url(r'^edge$', 'contentstore.views.edge', name='edge'),
    # noop to squelch ajax errors
    url(r'^event$', 'contentstore.views.event', name='event'),

    url(r'^heartbeat$', include('heartbeat.urls')),
)

# User creation and updating views
urlpatterns += (
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/checklists/(?P<name>[^/]+)$', 'contentstore.views.get_checklists', name='checklists'),
    url(r'^(?P<org>[^/]+)/(?P<course>[^/]+)/checklists/(?P<name>[^/]+)/update(/)?(?P<checklist_index>.+)?.*$',
        'contentstore.views.update_checklist', name='checklists_updates'),
    url(r'^howitworks$', 'contentstore.views.howitworks', name='howitworks'),
    url(r'^signup$', 'contentstore.views.signup', name='signup'),

    url(r'^create_account$', 'student.views.create_account'),
    url(r'^activate/(?P<key>[^/]*)$', 'student.views.activate_account', name='activate'),

    # form page
    url(r'^login$', 'contentstore.views.old_login_redirect', name='old_login'),
    url(r'^signin$', 'contentstore.views.login_page', name='login'),
    # ajax view that actually does the work
    url(r'^login_post$', 'student.views.login_user', name='login_post'),

    url(r'^logout$', 'student.views.logout_user', name='logout'),
)

js_info_dict = {
    'domain': 'djangojs',
    'packages': ('cms',),
}

urlpatterns += (
    # Serve catalog of localized strings to be rendered by Javascript
    url(r'^jsi18n/$', 'django.views.i18n.javascript_catalog', js_info_dict),
)


if settings.ENABLE_JASMINE:
    # # Jasmine
    urlpatterns = urlpatterns + (url(r'^_jasmine/', include('django_jasmine.urls')),)


if settings.MITX_FEATURES.get('ENABLE_SERVICE_STATUS'):
    urlpatterns += (
        url(r'^status/', include('service_status.urls')),
    )

urlpatterns = patterns(*urlpatterns)

# Custom error pages
handler404 = 'contentstore.views.render_404'
handler500 = 'contentstore.views.render_500'
