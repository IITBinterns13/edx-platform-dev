import json
import shutil
from django.test.client import Client
from django.test.utils import override_settings
from django.conf import settings
from django.core.urlresolvers import reverse
from path import path
from tempdir import mkdtemp_clean
from fs.osfs import OSFS
import copy
from json import loads
from datetime import timedelta

from django.contrib.auth.models import User
from django.dispatch import Signal
from contentstore.utils import get_modulestore
from contentstore.tests.utils import parse_json

from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory

from xmodule.modulestore import Location
from xmodule.modulestore.store_utilities import clone_course
from xmodule.modulestore.store_utilities import delete_course
from xmodule.modulestore.django import modulestore
from xmodule.contentstore.django import contentstore
from xmodule.templates import update_templates
from xmodule.modulestore.xml_exporter import export_to_xml
from xmodule.modulestore.xml_importer import import_from_xml, perform_xlint
from xmodule.modulestore.inheritance import own_metadata
from xmodule.contentstore.content import StaticContent
from xmodule.contentstore.utils import restore_asset_from_trashcan, empty_asset_trashcan

from xmodule.capa_module import CapaDescriptor
from xmodule.course_module import CourseDescriptor
from xmodule.seq_module import SequenceDescriptor
from xmodule.modulestore.exceptions import ItemNotFoundError

from contentstore.views.component import ADVANCED_COMPONENT_TYPES
from xmodule.exceptions import NotFoundError

from django_comment_common.utils import are_permissions_roles_seeded
from xmodule.exceptions import InvalidVersionError
import datetime
from pytz import UTC

TEST_DATA_MODULESTORE = copy.deepcopy(settings.MODULESTORE)
TEST_DATA_MODULESTORE['default']['OPTIONS']['fs_root'] = path('common/test/data')
TEST_DATA_MODULESTORE['direct']['OPTIONS']['fs_root'] = path('common/test/data')


class MongoCollectionFindWrapper(object):
    def __init__(self, original):
        self.original = original
        self.counter = 0

    def find(self, query, *args, **kwargs):
        self.counter = self.counter + 1
        return self.original(query, *args, **kwargs)


@override_settings(MODULESTORE=TEST_DATA_MODULESTORE)
class ContentStoreToyCourseTest(ModuleStoreTestCase):
    """
    Tests that rely on the toy courses.
    TODO: refactor using CourseFactory so they do not.
    """
    def setUp(self):
        uname = 'testuser'
        email = 'test+courses@edx.org'
        password = 'foo'

        # Create the use so we can log them in.
        self.user = User.objects.create_user(uname, email, password)

        # Note that we do not actually need to do anything
        # for registration if we directly mark them active.
        self.user.is_active = True
        # Staff has access to view all courses
        self.user.is_staff = True
        self.user.save()

        self.client = Client()
        self.client.login(username=uname, password=password)

    def check_components_on_page(self, component_types, expected_types):
        """
        Ensure that the right types end up on the page.

        component_types is the list of advanced components.

        expected_types is the list of elements that should appear on the page.

        expected_types and component_types should be similar, but not
        exactly the same -- for example, 'videoalpha' in
        component_types should cause 'Video Alpha' to be present.
        """
        store = modulestore('direct')
        import_from_xml(store, 'common/test/data/', ['simple'])

        course = store.get_item(Location(['i4x', 'edX', 'simple',
                                          'course', '2012_Fall', None]), depth=None)

        course.advanced_modules = component_types

        store.update_metadata(course.location, own_metadata(course))

        # just pick one vertical
        descriptor = store.get_items(Location('i4x', 'edX', 'simple', 'vertical', None, None))[0]

        resp = self.client.get(reverse('edit_unit', kwargs={'location': descriptor.location.url()}))
        self.assertEqual(resp.status_code, 200)

        for expected in expected_types:
            self.assertIn(expected, resp.content)

    def test_advanced_components_in_edit_unit(self):
        # This could be made better, but for now let's just assert that we see the advanced modules mentioned in the page
        # response HTML
        self.check_components_on_page(ADVANCED_COMPONENT_TYPES, ['Video Alpha',
                                                                 'Word cloud',
                                                                 'Annotation',
                                                                 'Open Ended Response',
                                                                 'Peer Grading Interface'])

    def test_advanced_components_require_two_clicks(self):
        self.check_components_on_page(['videoalpha'], ['Video Alpha'])

    def test_malformed_edit_unit_request(self):
        store = modulestore('direct')
        import_from_xml(store, 'common/test/data/', ['simple'])

        # just pick one vertical
        descriptor = store.get_items(Location('i4x', 'edX', 'simple', 'vertical', None, None))[0]
        location = descriptor.location.replace(name='.' + descriptor.location.name)

        resp = self.client.get(reverse('edit_unit', kwargs={'location': location.url()}))
        self.assertEqual(resp.status_code, 400)

    def check_edit_unit(self, test_course_name):
        import_from_xml(modulestore('direct'), 'common/test/data/', [test_course_name])

        for descriptor in modulestore().get_items(Location(None, None, 'vertical', None, None)):
            print "Checking ", descriptor.location.url()
            print descriptor.__class__, descriptor.location
            resp = self.client.get(reverse('edit_unit', kwargs={'location': descriptor.location.url()}))
            self.assertEqual(resp.status_code, 200)

    def test_edit_unit_toy(self):
        self.check_edit_unit('toy')

    def test_edit_unit_full(self):
        self.check_edit_unit('full')

    def _get_draft_counts(self, item):
        cnt = 1 if getattr(item, 'is_draft', False) else 0
        for child in item.get_children():
            cnt = cnt + self._get_draft_counts(child)

        return cnt

    def test_get_items(self):
        '''
        This verifies a bug we had where the None setting in get_items() meant 'wildcard'
        Unfortunately, None = published for the revision field, so get_items() would return
        both draft and non-draft copies.
        '''
        store = modulestore('direct')
        draft_store = modulestore('draft')
        import_from_xml(store, 'common/test/data/', ['simple'])

        html_module = draft_store.get_item(['i4x', 'edX', 'simple', 'html', 'test_html', None])

        draft_store.clone_item(html_module.location, html_module.location)

        # now query get_items() to get this location with revision=None, this should just
        # return back a single item (not 2)

        items = store.get_items(['i4x', 'edX', 'simple', 'html', 'test_html', None])
        self.assertEqual(len(items), 1)
        self.assertFalse(getattr(items[0], 'is_draft', False))

        # now refetch from the draft store. Note that even though we pass
        # None in the revision field, the draft store will replace that with 'draft'
        items = draft_store.get_items(['i4x', 'edX', 'simple', 'html', 'test_html', None])
        self.assertEqual(len(items), 1)
        self.assertTrue(getattr(items[0], 'is_draft', False))

    def test_draft_metadata(self):
        '''
        This verifies a bug we had where inherited metadata was getting written to the
        module as 'own-metadata' when publishing. Also verifies the metadata inheritance is
        properly computed
        '''
        store = modulestore('direct')
        draft_store = modulestore('draft')
        import_from_xml(store, 'common/test/data/', ['simple'])

        course = draft_store.get_item(Location(['i4x', 'edX', 'simple',
                                               'course', '2012_Fall', None]), depth=None)
        html_module = draft_store.get_item(['i4x', 'edX', 'simple', 'html', 'test_html', None])

        self.assertEqual(html_module.lms.graceperiod, course.lms.graceperiod)
        self.assertNotIn('graceperiod', own_metadata(html_module))

        draft_store.clone_item(html_module.location, html_module.location)

        # refetch to check metadata
        html_module = draft_store.get_item(['i4x', 'edX', 'simple', 'html', 'test_html', None])

        self.assertEqual(html_module.lms.graceperiod, course.lms.graceperiod)
        self.assertNotIn('graceperiod', own_metadata(html_module))

        # publish module
        draft_store.publish(html_module.location, 0)

        # refetch to check metadata
        html_module = draft_store.get_item(['i4x', 'edX', 'simple', 'html', 'test_html', None])

        self.assertEqual(html_module.lms.graceperiod, course.lms.graceperiod)
        self.assertNotIn('graceperiod', own_metadata(html_module))

        # put back in draft and change metadata and see if it's now marked as 'own_metadata'
        draft_store.clone_item(html_module.location, html_module.location)
        html_module = draft_store.get_item(['i4x', 'edX', 'simple', 'html', 'test_html', None])

        new_graceperiod = timedelta(hours=1)

        self.assertNotIn('graceperiod', own_metadata(html_module))
        html_module.lms.graceperiod = new_graceperiod
        self.assertIn('graceperiod', own_metadata(html_module))
        self.assertEqual(html_module.lms.graceperiod, new_graceperiod)

        draft_store.update_metadata(html_module.location, own_metadata(html_module))

        # read back to make sure it reads as 'own-metadata'
        html_module = draft_store.get_item(['i4x', 'edX', 'simple', 'html', 'test_html', None])

        self.assertIn('graceperiod', own_metadata(html_module))
        self.assertEqual(html_module.lms.graceperiod, new_graceperiod)

        # republish
        draft_store.publish(html_module.location, 0)

        # and re-read and verify 'own-metadata'
        draft_store.clone_item(html_module.location, html_module.location)
        html_module = draft_store.get_item(['i4x', 'edX', 'simple', 'html', 'test_html', None])

        self.assertIn('graceperiod', own_metadata(html_module))
        self.assertEqual(html_module.lms.graceperiod, new_graceperiod)

    def test_get_depth_with_drafts(self):
        import_from_xml(modulestore('direct'), 'common/test/data/', ['simple'])

        course = modulestore('draft').get_item(
            Location(['i4x', 'edX', 'simple', 'course', '2012_Fall', None]),
            depth=None
        )

        # make sure no draft items have been returned
        num_drafts = self._get_draft_counts(course)
        self.assertEqual(num_drafts, 0)

        problem = modulestore('draft').get_item(
            Location(['i4x', 'edX', 'simple', 'problem', 'ps01-simple', None])
        )

        # put into draft
        modulestore('draft').clone_item(problem.location, problem.location)

        # make sure we can query that item and verify that it is a draft
        draft_problem = modulestore('draft').get_item(
            Location(['i4x', 'edX', 'simple', 'problem', 'ps01-simple', None])
        )
        self.assertTrue(getattr(draft_problem, 'is_draft', False))

        # now requery with depth
        course = modulestore('draft').get_item(
            Location(['i4x', 'edX', 'simple', 'course', '2012_Fall', None]),
            depth=None
        )

        # make sure just one draft item have been returned
        num_drafts = self._get_draft_counts(course)
        self.assertEqual(num_drafts, 1)

    def test_import_textbook_as_content_element(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        course = module_store.get_item(Location(['i4x', 'edX', 'full', 'course', '6.002_Spring_2012', None]))

        self.assertGreater(len(course.textbooks), 0)

    def test_static_tab_reordering(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        course = module_store.get_item(Location(['i4x', 'edX', 'full', 'course', '6.002_Spring_2012', None]))

        # reverse the ordering
        reverse_tabs = []
        for tab in course.tabs:
            if tab['type'] == 'static_tab':
                reverse_tabs.insert(0, 'i4x://edX/full/static_tab/{0}'.format(tab['url_slug']))

        self.client.post(reverse('reorder_static_tabs'), json.dumps({'tabs': reverse_tabs}), "application/json")

        course = module_store.get_item(Location(['i4x', 'edX', 'full', 'course', '6.002_Spring_2012', None]))

        # compare to make sure that the tabs information is in the expected order after the server call
        course_tabs = []
        for tab in course.tabs:
            if tab['type'] == 'static_tab':
                course_tabs.append('i4x://edX/full/static_tab/{0}'.format(tab['url_slug']))

        self.assertEqual(reverse_tabs, course_tabs)

    def test_import_polls(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        items = module_store.get_items(['i4x', 'edX', 'full', 'poll_question', None, None])
        found = len(items) > 0

        self.assertTrue(found)
        # check that there's actually content in the 'question' field
        self.assertGreater(len(items[0].question), 0)

    def test_xlint_fails(self):
        err_cnt = perform_xlint('common/test/data', ['full'])
        self.assertGreater(err_cnt, 0)

    def test_delete(self):
        direct_store = modulestore('direct')
        import_from_xml(direct_store, 'common/test/data/', ['full'])

        sequential = direct_store.get_item(Location(['i4x', 'edX', 'full', 'sequential', 'Administrivia_and_Circuit_Elements', None]))

        chapter = direct_store.get_item(Location(['i4x', 'edX', 'full', 'chapter', 'Week_1', None]))

        # make sure the parent points to the child object which is to be deleted
        self.assertTrue(sequential.location.url() in chapter.children)

        self.client.post(
            reverse('delete_item'),
            json.dumps({'id': sequential.location.url(), 'delete_children': 'true', 'delete_all_versions': 'true'}),
            "application/json"
        )

        found = False
        try:
            direct_store.get_item(Location(['i4x', 'edX', 'full', 'sequential', 'Administrivia_and_Circuit_Elements', None]))
            found = True
        except ItemNotFoundError:
            pass

        self.assertFalse(found)

        chapter = direct_store.get_item(Location(['i4x', 'edX', 'full', 'chapter', 'Week_1', None]))

        # make sure the parent no longer points to the child object which was deleted
        self.assertFalse(sequential.location.url() in chapter.children)

    def test_about_overrides(self):
        '''
        This test case verifies that a course can use specialized override for about data, e.g. /about/Fall_2012/effort.html
        while there is a base definition in /about/effort.html
        '''
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])
        effort = module_store.get_item(Location(['i4x', 'edX', 'full', 'about', 'effort', None]))
        self.assertEqual(effort.data, '6 hours')

        # this one should be in a non-override folder
        effort = module_store.get_item(Location(['i4x', 'edX', 'full', 'about', 'end_date', None]))
        self.assertEqual(effort.data, 'TBD')

    def test_remove_hide_progress_tab(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        source_location = CourseDescriptor.id_to_location('edX/full/6.002_Spring_2012')
        course = module_store.get_item(source_location)
        self.assertFalse(course.hide_progress_tab)

    def test_asset_import(self):
        '''
        This test validates that an image asset is imported and a thumbnail was generated for a .gif
        '''
        content_store = contentstore()

        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'], static_content_store=content_store)

        course_location = CourseDescriptor.id_to_location('edX/full/6.002_Spring_2012')
        course = module_store.get_item(course_location)

        self.assertIsNotNone(course)

        # make sure we have some assets in our contentstore
        all_assets = content_store.get_all_content_for_course(course_location)
        self.assertGreater(len(all_assets), 0)

        # make sure we have some thumbnails in our contentstore
        all_thumbnails = content_store.get_all_content_thumbnails_for_course(course_location)

        #
        # cdodge: temporarily comment out assertion on thumbnails because many environments
        # will not have the jpeg converter installed and this test will fail
        #
        #
        # self.assertGreater(len(all_thumbnails), 0)

        content = None
        try:
            location = StaticContent.get_location_from_path('/c4x/edX/full/asset/circuits_duality.gif')
            content = content_store.find(location)
        except NotFoundError:
            pass

        self.assertIsNotNone(content)

        #
        # cdodge: temporarily comment out assertion on thumbnails because many environments
        # will not have the jpeg converter installed and this test will fail
        #
        # self.assertIsNotNone(content.thumbnail_location)
        #
        # thumbnail = None
        # try:
        #    thumbnail = content_store.find(content.thumbnail_location)
        # except:
        #    pass
        #
        # self.assertIsNotNone(thumbnail)

    def test_asset_delete_and_restore(self):
        '''
        This test will exercise the soft delete/restore functionality of the assets
        '''
        content_store = contentstore()
        trash_store = contentstore('trashcan')
        module_store = modulestore('direct')

        import_from_xml(module_store, 'common/test/data/', ['full'], static_content_store=content_store)

        # look up original (and thumbnail) in content store, should be there after import
        location = StaticContent.get_location_from_path('/c4x/edX/full/asset/circuits_duality.gif')
        content = content_store.find(location, throw_on_not_found=False)
        thumbnail_location = content.thumbnail_location
        self.assertIsNotNone(content)

        #
        # cdodge: temporarily comment out assertion on thumbnails because many environments
        # will not have the jpeg converter installed and this test will fail
        #
        # self.assertIsNotNone(thumbnail_location)

        # go through the website to do the delete, since the soft-delete logic is in the view

        url = reverse('remove_asset', kwargs={'org': 'edX', 'course': 'full', 'name': '6.002_Spring_2012'})
        resp = self.client.post(url, {'location': '/c4x/edX/full/asset/circuits_duality.gif'})
        self.assertEqual(resp.status_code, 200)

        asset_location = StaticContent.get_location_from_path('/c4x/edX/full/asset/circuits_duality.gif')

        # now try to find it in store, but they should not be there any longer
        content = content_store.find(asset_location, throw_on_not_found=False)
        self.assertIsNone(content)

        if thumbnail_location:
            thumbnail = content_store.find(thumbnail_location, throw_on_not_found=False)
            self.assertIsNone(thumbnail)

        # now try to find it and the thumbnail in trashcan - should be in there
        content = trash_store.find(asset_location, throw_on_not_found=False)
        self.assertIsNotNone(content)

        if thumbnail_location:
            thumbnail = trash_store.find(thumbnail_location, throw_on_not_found=False)
            self.assertIsNotNone(thumbnail)

        # let's restore the asset
        restore_asset_from_trashcan('/c4x/edX/full/asset/circuits_duality.gif')

        # now try to find it in courseware store, and they should be back after restore
        content = content_store.find(asset_location, throw_on_not_found=False)
        self.assertIsNotNone(content)

        if thumbnail_location:
            thumbnail = content_store.find(thumbnail_location, throw_on_not_found=False)
            self.assertIsNotNone(thumbnail)

    def test_empty_trashcan(self):
        '''
        This test will exercise the empting of the asset trashcan
        '''
        content_store = contentstore()
        trash_store = contentstore('trashcan')
        module_store = modulestore('direct')

        import_from_xml(module_store, 'common/test/data/', ['full'], static_content_store=content_store)

        course_location = CourseDescriptor.id_to_location('edX/full/6.002_Spring_2012')

        location = StaticContent.get_location_from_path('/c4x/edX/full/asset/circuits_duality.gif')
        content = content_store.find(location, throw_on_not_found=False)
        self.assertIsNotNone(content)

        # go through the website to do the delete, since the soft-delete logic is in the view

        url = reverse('remove_asset', kwargs={'org': 'edX', 'course': 'full', 'name': '6.002_Spring_2012'})
        resp = self.client.post(url, {'location': '/c4x/edX/full/asset/circuits_duality.gif'})
        self.assertEqual(resp.status_code, 200)

        # make sure there's something in the trashcan
        all_assets = trash_store.get_all_content_for_course(course_location)
        self.assertGreater(len(all_assets), 0)

        # make sure we have some thumbnails in our trashcan
        all_thumbnails = trash_store.get_all_content_thumbnails_for_course(course_location)
        #
        # cdodge: temporarily comment out assertion on thumbnails because many environments
        # will not have the jpeg converter installed and this test will fail
        #
        # self.assertGreater(len(all_thumbnails), 0)

        # empty the trashcan
        empty_asset_trashcan([course_location])

        # make sure trashcan is empty
        all_assets = trash_store.get_all_content_for_course(course_location)
        self.assertEqual(len(all_assets), 0)


        all_thumbnails = trash_store.get_all_content_thumbnails_for_course(course_location)
        self.assertEqual(len(all_thumbnails), 0)

    def test_clone_course(self):

        course_data = {
            'template': 'i4x://edx/templates/course/Empty',
            'org': 'MITx',
            'number': '999',
            'display_name': 'Robot Super Course',
        }

        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        resp = self.client.post(reverse('create_new_course'), course_data)
        self.assertEqual(resp.status_code, 200)
        data = parse_json(resp)
        self.assertEqual(data['id'], 'i4x://MITx/999/course/Robot_Super_Course')

        content_store = contentstore()

        source_location = CourseDescriptor.id_to_location('edX/full/6.002_Spring_2012')
        dest_location = CourseDescriptor.id_to_location('MITx/999/Robot_Super_Course')

        clone_course(module_store, content_store, source_location, dest_location)

        # now loop through all the units in the course and verify that the clone can render them, which
        # means the objects are at least present
        items = module_store.get_items(Location(['i4x', 'edX', 'full', 'vertical', None]))
        self.assertGreater(len(items), 0)
        clone_items = module_store.get_items(Location(['i4x', 'MITx', '999', 'vertical', None]))
        self.assertGreater(len(clone_items), 0)
        for descriptor in items:
            new_loc = descriptor.location.replace(org='MITx', course='999')
            print "Checking {0} should now also be at {1}".format(descriptor.location.url(), new_loc.url())
            resp = self.client.get(reverse('edit_unit', kwargs={'location': new_loc.url()}))
            self.assertEqual(resp.status_code, 200)

    def test_illegal_draft_crud_ops(self):
        draft_store = modulestore('draft')
        direct_store = modulestore('direct')

        CourseFactory.create(org='MITx', course='999', display_name='Robot Super Course')

        location = Location('i4x://MITx/999/chapter/neuvo')
        self.assertRaises(InvalidVersionError, draft_store.clone_item, 'i4x://edx/templates/chapter/Empty',
            location)
        direct_store.clone_item('i4x://edx/templates/chapter/Empty', location)
        self.assertRaises(InvalidVersionError, draft_store.clone_item, location,
            location)

        self.assertRaises(InvalidVersionError, draft_store.update_item, location,
            'chapter data')

        # taking advantage of update_children and other functions never checking that the ids are valid
        self.assertRaises(InvalidVersionError, draft_store.update_children, location,
            ['i4x://MITx/999/problem/doesntexist'])

        self.assertRaises(InvalidVersionError, draft_store.update_metadata, location,
            {'due': datetime.datetime.now(UTC)})

        self.assertRaises(InvalidVersionError, draft_store.unpublish, location)


    def test_bad_contentstore_request(self):
        resp = self.client.get('http://localhost:8001/c4x/CDX/123123/asset/&images_circuits_Lab7Solution2.png')
        self.assertEqual(resp.status_code, 400)

    def test_delete_course(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        content_store = contentstore()

        location = CourseDescriptor.id_to_location('edX/full/6.002_Spring_2012')

        delete_course(module_store, content_store, location, commit=True)

        items = module_store.get_items(Location(['i4x', 'edX', 'full', 'vertical', None]))
        self.assertEqual(len(items), 0)

    def verify_content_existence(self, store, root_dir, location, dirname, category_name, filename_suffix=''):
        filesystem = OSFS(root_dir / 'test_export')
        self.assertTrue(filesystem.exists(dirname))

        query_loc = Location('i4x', location.org, location.course, category_name, None)
        items = store.get_items(query_loc)

        for item in items:
            filesystem = OSFS(root_dir / ('test_export/' + dirname))
            self.assertTrue(filesystem.exists(item.location.name + filename_suffix))

    def test_export_course(self):
        module_store = modulestore('direct')
        draft_store = modulestore('draft')
        content_store = contentstore()

        import_from_xml(module_store, 'common/test/data/', ['full'])
        location = CourseDescriptor.id_to_location('edX/full/6.002_Spring_2012')

        # get a vertical (and components in it) to put into 'draft'
        vertical = module_store.get_item(Location(['i4x', 'edX', 'full',
                                         'vertical', 'vertical_66', None]), depth=1)

        draft_store.clone_item(vertical.location, vertical.location)

        # We had a bug where orphaned draft nodes caused export to fail. This is here to cover that case.
        draft_store.clone_item(vertical.location, Location(['i4x', 'edX', 'full',
                                                            'vertical', 'no_references', 'draft']))

        for child in vertical.get_children():
            draft_store.clone_item(child.location, child.location)

        root_dir = path(mkdtemp_clean())

        # now create a private vertical
        private_vertical = draft_store.clone_item(vertical.location,
                                                  Location(['i4x', 'edX', 'full', 'vertical', 'a_private_vertical', None]))

        # add private to list of children
        sequential = module_store.get_item(Location(['i4x', 'edX', 'full',
                                           'sequential', 'Administrivia_and_Circuit_Elements', None]))
        private_location_no_draft = private_vertical.location.replace(revision=None)
        module_store.update_children(sequential.location, sequential.children +
                                     [private_location_no_draft.url()])

        # read back the sequential, to make sure we have a pointer to
        sequential = module_store.get_item(Location(['i4x', 'edX', 'full',
                                                     'sequential', 'Administrivia_and_Circuit_Elements', None]))

        self.assertIn(private_location_no_draft.url(), sequential.children)

        print 'Exporting to tempdir = {0}'.format(root_dir)

        # export out to a tempdir
        export_to_xml(module_store, content_store, location, root_dir, 'test_export', draft_modulestore=draft_store)

        # check for static tabs
        self.verify_content_existence(module_store, root_dir, location, 'tabs', 'static_tab', '.html')

        # check for custom_tags
        self.verify_content_existence(module_store, root_dir, location, 'info', 'course_info', '.html')

        # check for custom_tags
        self.verify_content_existence(module_store, root_dir, location, 'custom_tags', 'custom_tag_template')

        # check for about content
        self.verify_content_existence(module_store, root_dir, location, 'about', 'about', '.html')

        # check for graiding_policy.json
        filesystem = OSFS(root_dir / 'test_export/policies/6.002_Spring_2012')
        self.assertTrue(filesystem.exists('grading_policy.json'))

        course = module_store.get_item(location)
        # compare what's on disk compared to what we have in our course
        with filesystem.open('grading_policy.json', 'r') as grading_policy:
            on_disk = loads(grading_policy.read())
            self.assertEqual(on_disk, course.grading_policy)

        # check for policy.json
        self.assertTrue(filesystem.exists('policy.json'))

        # compare what's on disk to what we have in the course module
        with filesystem.open('policy.json', 'r') as course_policy:
            on_disk = loads(course_policy.read())
            self.assertIn('course/6.002_Spring_2012', on_disk)
            self.assertEqual(on_disk['course/6.002_Spring_2012'], own_metadata(course))

        # remove old course
        delete_course(module_store, content_store, location)

        # reimport
        import_from_xml(module_store, root_dir, ['test_export'], draft_store=draft_store)

        items = module_store.get_items(Location(['i4x', 'edX', 'full', 'vertical', None]))
        self.assertGreater(len(items), 0)
        for descriptor in items:
            # don't try to look at private verticals. Right now we're running
            # the service in non-draft aware
            if getattr(descriptor, 'is_draft', False):
                print "Checking {0}....".format(descriptor.location.url())
                resp = self.client.get(reverse('edit_unit', kwargs={'location': descriptor.location.url()}))
                self.assertEqual(resp.status_code, 200)

        # verify that we have the content in the draft store as well
        vertical = draft_store.get_item(Location(['i4x', 'edX', 'full',
                                                  'vertical', 'vertical_66', None]), depth=1)

        self.assertTrue(getattr(vertical, 'is_draft', False))
        for child in vertical.get_children():
            self.assertTrue(getattr(child, 'is_draft', False))

        # make sure that we don't have a sequential that is in draft mode
        sequential = draft_store.get_item(Location(['i4x', 'edX', 'full',
                                                    'sequential', 'Administrivia_and_Circuit_Elements', None]))

        self.assertFalse(getattr(sequential, 'is_draft', False))

        # verify that we have the private vertical
        test_private_vertical = draft_store.get_item(Location(['i4x', 'edX', 'full',
                                                               'vertical', 'vertical_66', None]))

        self.assertTrue(getattr(test_private_vertical, 'is_draft', False))

        # make sure the textbook survived the export/import
        course = module_store.get_item(Location(['i4x', 'edX', 'full', 'course', '6.002_Spring_2012', None]))

        self.assertGreater(len(course.textbooks), 0)

        shutil.rmtree(root_dir)

    def test_course_handouts_rewrites(self):
        module_store = modulestore('direct')

        # import a test course
        import_from_xml(module_store, 'common/test/data/', ['full'])

        handout_location = Location(['i4x', 'edX', 'full', 'course_info', 'handouts'])

        # get module info
        resp = self.client.get(reverse('module_info', kwargs={'module_location': handout_location}))

        # make sure we got a successful response
        self.assertEqual(resp.status_code, 200)

        # check that /static/ has been converted to the full path
        # note, we know the link it should be because that's what in the 'full' course in the test data
        self.assertContains(resp, '/c4x/edX/full/asset/handouts_schematic_tutorial.pdf')

    def test_prefetch_children(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])
        location = CourseDescriptor.id_to_location('edX/full/6.002_Spring_2012')

        wrapper = MongoCollectionFindWrapper(module_store.collection.find)
        module_store.collection.find = wrapper.find
        course = module_store.get_item(location, depth=2)

        # make sure we haven't done too many round trips to DB
        # note we say 4 round trips here for 1) the course, 2 & 3) for the chapters and sequentials, and
        # 4) because of the RT due to calculating the inherited metadata
        self.assertEqual(wrapper.counter, 4)

        # make sure we pre-fetched a known sequential which should be at depth=2
        self.assertTrue(Location(['i4x', 'edX', 'full', 'sequential',
                                  'Administrivia_and_Circuit_Elements', None]) in course.system.module_data)

        # make sure we don't have a specific vertical which should be at depth=3
        self.assertFalse(Location(['i4x', 'edX', 'full', 'vertical', 'vertical_58', None])
                         in course.system.module_data)

    def test_export_course_with_unknown_metadata(self):
        module_store = modulestore('direct')
        content_store = contentstore()

        import_from_xml(module_store, 'common/test/data/', ['full'])
        location = CourseDescriptor.id_to_location('edX/full/6.002_Spring_2012')

        root_dir = path(mkdtemp_clean())

        course = module_store.get_item(location)

        metadata = own_metadata(course)
        # add a bool piece of unknown metadata so we can verify we don't throw an exception
        metadata['new_metadata'] = True

        module_store.update_metadata(location, metadata)

        print 'Exporting to tempdir = {0}'.format(root_dir)

        # export out to a tempdir
        export_to_xml(module_store, content_store, location, root_dir, 'test_export')


class ContentStoreTest(ModuleStoreTestCase):
    """
    Tests for the CMS ContentStore application.
    """
    def setUp(self):
        """
        These tests need a user in the DB so that the django Test Client
        can log them in.
        They inherit from the ModuleStoreTestCase class so that the mongodb collection
        will be cleared out before each test case execution and deleted
        afterwards.
        """
        uname = 'testuser'
        email = 'test+courses@edx.org'
        password = 'foo'

        # Create the use so we can log them in.
        self.user = User.objects.create_user(uname, email, password)

        # Note that we do not actually need to do anything
        # for registration if we directly mark them active.
        self.user.is_active = True
        # Staff has access to view all courses
        self.user.is_staff = True
        self.user.save()

        self.client = Client()
        self.client.login(username=uname, password=password)

        self.course_data = {
            'template': 'i4x://edx/templates/course/Empty',
            'org': 'MITx',
            'number': '999',
            'display_name': 'Robot Super Course',
        }

    def test_create_course(self):
        """Test new course creation - happy path"""
        resp = self.client.post(reverse('create_new_course'), self.course_data)
        self.assertEqual(resp.status_code, 200)
        data = parse_json(resp)
        self.assertEqual(data['id'], 'i4x://MITx/999/course/Robot_Super_Course')

    def test_create_course_check_forum_seeding(self):
        """Test new course creation and verify forum seeding """
        resp = self.client.post(reverse('create_new_course'), self.course_data)
        self.assertEqual(resp.status_code, 200)
        data = parse_json(resp)
        self.assertEqual(data['id'], 'i4x://MITx/999/course/Robot_Super_Course')
        self.assertTrue(are_permissions_roles_seeded('MITx/999/Robot_Super_Course'))

    def test_create_course_duplicate_course(self):
        """Test new course creation - error path"""
        self.client.post(reverse('create_new_course'), self.course_data)
        resp = self.client.post(reverse('create_new_course'), self.course_data)
        data = parse_json(resp)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['ErrMsg'], 'There is already a course defined with this name.')

    def test_create_course_duplicate_number(self):
        """Test new course creation - error path"""
        self.client.post(reverse('create_new_course'), self.course_data)
        self.course_data['display_name'] = 'Robot Super Course Two'

        resp = self.client.post(reverse('create_new_course'), self.course_data)
        data = parse_json(resp)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['ErrMsg'],
                         'There is already a course defined with the same organization and course number.')

    def test_create_course_with_bad_organization(self):
        """Test new course creation - error path for bad organization name"""
        self.course_data['org'] = 'University of California, Berkeley'
        resp = self.client.post(reverse('create_new_course'), self.course_data)
        data = parse_json(resp)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['ErrMsg'],
                         "Unable to create course 'Robot Super Course'.\n\nInvalid characters in 'University of California, Berkeley'.")

    def test_course_index_view_with_no_courses(self):
        """Test viewing the index page with no courses"""
        # Create a course so there is something to view
        resp = self.client.get(reverse('index'))
        self.assertContains(
            resp,
            '<h1 class="page-header">My Courses</h1>',
            status_code=200,
            html=True
        )

    def test_course_factory(self):
        """Test that the course factory works correctly."""
        course = CourseFactory.create()
        self.assertIsInstance(course, CourseDescriptor)

    def test_item_factory(self):
        """Test that the item factory works correctly."""
        course = CourseFactory.create()
        item = ItemFactory.create(parent_location=course.location)
        self.assertIsInstance(item, SequenceDescriptor)

    def test_course_index_view_with_course(self):
        """Test viewing the index page with an existing course"""
        CourseFactory.create(display_name='Robot Super Educational Course')
        resp = self.client.get(reverse('index'))
        self.assertContains(
            resp,
            '<span class="class-name">Robot Super Educational Course</span>',
            status_code=200,
            html=True
        )

    def test_course_overview_view_with_course(self):
        """Test viewing the course overview page with an existing course"""
        CourseFactory.create(org='MITx', course='999', display_name='Robot Super Course')

        data = {
            'org': 'MITx',
            'course': '999',
            'name': Location.clean('Robot Super Course'),
        }

        resp = self.client.get(reverse('course_index', kwargs=data))
        self.assertContains(
            resp,
            '<article class="courseware-overview" data-course-id="i4x://MITx/999/course/Robot_Super_Course">',
            status_code=200,
            html=True
        )

    def test_clone_item(self):
        """Test cloning an item. E.g. creating a new section"""
        CourseFactory.create(org='MITx', course='999', display_name='Robot Super Course')

        section_data = {
            'parent_location': 'i4x://MITx/999/course/Robot_Super_Course',
            'template': 'i4x://edx/templates/chapter/Empty',
            'display_name': 'Section One',
        }

        resp = self.client.post(reverse('clone_item'), section_data)

        self.assertEqual(resp.status_code, 200)
        data = parse_json(resp)
        self.assertRegexpMatches(
            data['id'],
            r"^i4x://MITx/999/chapter/([0-9]|[a-f]){32}$"
        )

    def test_capa_module(self):
        """Test that a problem treats markdown specially."""
        CourseFactory.create(org='MITx', course='999', display_name='Robot Super Course')

        problem_data = {
            'parent_location': 'i4x://MITx/999/course/Robot_Super_Course',
            'template': 'i4x://edx/templates/problem/Blank_Common_Problem'
        }

        resp = self.client.post(reverse('clone_item'), problem_data)

        self.assertEqual(resp.status_code, 200)
        payload = parse_json(resp)
        problem_loc = payload['id']
        problem = get_modulestore(problem_loc).get_item(problem_loc)
        # should be a CapaDescriptor
        self.assertIsInstance(problem, CapaDescriptor, "New problem is not a CapaDescriptor")
        context = problem.get_context()
        self.assertIn('markdown', context, "markdown is missing from context")
        self.assertNotIn('markdown', problem.editable_metadata_fields, "Markdown slipped into the editable metadata fields")

    def test_cms_imported_course_walkthrough(self):
        """
        Import and walk through some common URL endpoints. This just verifies non-500 and no other
        correct behavior, so it is not a deep test
        """
        import_from_xml(modulestore('direct'), 'common/test/data/', ['simple'])
        loc = Location(['i4x', 'edX', 'simple', 'course', '2012_Fall', None])
        resp = self.client.get(reverse('course_index',
                                       kwargs={'org': loc.org,
                                               'course': loc.course,
                                               'name': loc.name}))

        self.assertEqual(200, resp.status_code)
        self.assertContains(resp, 'Chapter 2')

        # go to various pages

        # import page
        resp = self.client.get(reverse('import_course',
                                       kwargs={'org': loc.org,
                                               'course': loc.course,
                                               'name': loc.name}))
        self.assertEqual(200, resp.status_code)

        # export page
        resp = self.client.get(reverse('export_course',
                                       kwargs={'org': loc.org,
                                               'course': loc.course,
                                               'name': loc.name}))
        self.assertEqual(200, resp.status_code)

        # manage users
        resp = self.client.get(reverse('manage_users',
                                       kwargs={'location': loc.url()}))
        self.assertEqual(200, resp.status_code)

        # course info
        resp = self.client.get(reverse('course_info',
                                       kwargs={'org': loc.org,
                                               'course': loc.course,
                                               'name': loc.name}))
        self.assertEqual(200, resp.status_code)

        # settings_details
        resp = self.client.get(reverse('settings_details',
                                       kwargs={'org': loc.org,
                                               'course': loc.course,
                                               'name': loc.name}))
        self.assertEqual(200, resp.status_code)

        # settings_details
        resp = self.client.get(reverse('settings_grading',
                                       kwargs={'org': loc.org,
                                               'course': loc.course,
                                               'name': loc.name}))
        self.assertEqual(200, resp.status_code)

        # static_pages
        resp = self.client.get(reverse('static_pages',
                                       kwargs={'org': loc.org,
                                               'course': loc.course,
                                               'coursename': loc.name}))
        self.assertEqual(200, resp.status_code)

        # static_pages
        resp = self.client.get(reverse('asset_index',
                                       kwargs={'org': loc.org,
                                               'course': loc.course,
                                               'name': loc.name}))
        self.assertEqual(200, resp.status_code)

        # go look at a subsection page
        subsection_location = loc.replace(category='sequential', name='test_sequence')
        resp = self.client.get(reverse('edit_subsection',
                                       kwargs={'location': subsection_location.url()}))
        self.assertEqual(200, resp.status_code)

        # go look at the Edit page
        unit_location = loc.replace(category='vertical', name='test_vertical')
        resp = self.client.get(reverse('edit_unit',
                                       kwargs={'location': unit_location.url()}))
        self.assertEqual(200, resp.status_code)

        # delete a component
        del_loc = loc.replace(category='html', name='test_html')
        resp = self.client.post(reverse('delete_item'),
                                json.dumps({'id': del_loc.url()}), "application/json")
        self.assertEqual(200, resp.status_code)

        # delete a unit
        del_loc = loc.replace(category='vertical', name='test_vertical')
        resp = self.client.post(reverse('delete_item'),
                                json.dumps({'id': del_loc.url()}), "application/json")
        self.assertEqual(200, resp.status_code)

        # delete a unit
        del_loc = loc.replace(category='sequential', name='test_sequence')
        resp = self.client.post(reverse('delete_item'),
                                json.dumps({'id': del_loc.url()}), "application/json")
        self.assertEqual(200, resp.status_code)

        # delete a chapter
        del_loc = loc.replace(category='chapter', name='chapter_2')
        resp = self.client.post(reverse('delete_item'),
                                json.dumps({'id': del_loc.url()}), "application/json")
        self.assertEqual(200, resp.status_code)

    def test_import_metadata_with_attempts_empty_string(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['simple'])
        did_load_item = False
        try:
            module_store.get_item(Location(['i4x', 'edX', 'simple', 'problem', 'ps01-simple', None]))
            did_load_item = True
        except ItemNotFoundError:
            pass

        # make sure we found the item (e.g. it didn't error while loading)
        self.assertTrue(did_load_item)

    def test_forum_id_generation(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        new_component_location = Location('i4x', 'edX', 'full', 'discussion', 'new_component')
        source_template_location = Location('i4x', 'edx', 'templates', 'discussion', 'Discussion_Tag')

        # crate a new module and add it as a child to a vertical
        module_store.clone_item(source_template_location, new_component_location)

        new_discussion_item = module_store.get_item(new_component_location)

        self.assertNotEquals(new_discussion_item.discussion_id, '$$GUID$$')

    def test_update_modulestore_signal_did_fire(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        try:
            module_store.modulestore_update_signal = Signal(providing_args=['modulestore', 'course_id', 'location'])

            self.got_signal = False

            def _signal_hander(modulestore=None, course_id=None, location=None, **kwargs):
                self.got_signal = True

            module_store.modulestore_update_signal.connect(_signal_hander)

            new_component_location = Location('i4x', 'edX', 'full', 'html', 'new_component')
            source_template_location = Location('i4x', 'edx', 'templates', 'html', 'Blank_HTML_Page')

            # crate a new module
            module_store.clone_item(source_template_location, new_component_location)

        finally:
            module_store.modulestore_update_signal = None

        self.assertTrue(self.got_signal)

    def test_metadata_inheritance(self):
        module_store = modulestore('direct')
        import_from_xml(module_store, 'common/test/data/', ['full'])

        course = module_store.get_item(Location(['i4x', 'edX', 'full', 'course', '6.002_Spring_2012', None]))

        verticals = module_store.get_items(['i4x', 'edX', 'full', 'vertical', None, None])

        # let's assert on the metadata_inheritance on an existing vertical
        for vertical in verticals:
            self.assertEqual(course.lms.xqa_key, vertical.lms.xqa_key)

        self.assertGreater(len(verticals), 0)

        new_component_location = Location('i4x', 'edX', 'full', 'html', 'new_component')
        source_template_location = Location('i4x', 'edx', 'templates', 'html', 'Blank_HTML_Page')

        # crate a new module and add it as a child to a vertical
        module_store.clone_item(source_template_location, new_component_location)
        parent = verticals[0]
        module_store.update_children(parent.location, parent.children + [new_component_location.url()])

        # flush the cache
        module_store.refresh_cached_metadata_inheritance_tree(new_component_location)
        new_module = module_store.get_item(new_component_location)

        # check for grace period definition which should be defined at the course level
        self.assertEqual(parent.lms.graceperiod, new_module.lms.graceperiod)

        self.assertEqual(course.lms.xqa_key, new_module.lms.xqa_key)

        #
        # now let's define an override at the leaf node level
        #
        new_module.lms.graceperiod = timedelta(1)
        module_store.update_metadata(new_module.location, own_metadata(new_module))

        # flush the cache and refetch
        module_store.refresh_cached_metadata_inheritance_tree(new_component_location)
        new_module = module_store.get_item(new_component_location)

        self.assertEqual(timedelta(1), new_module.lms.graceperiod)


class TemplateTestCase(ModuleStoreTestCase):

    def test_template_cleanup(self):
        module_store = modulestore('direct')

        # insert a bogus template in the store
        bogus_template_location = Location('i4x', 'edx', 'templates', 'html', 'bogus')
        source_template_location = Location('i4x', 'edx', 'templates', 'html', 'Blank_HTML_Page')

        module_store.clone_item(source_template_location, bogus_template_location)

        verify_create = module_store.get_item(bogus_template_location)
        self.assertIsNotNone(verify_create)

        # now run cleanup
        update_templates(modulestore('direct'))

        # now try to find dangling template, it should not be in DB any longer
        asserted = False
        try:
            verify_create = module_store.get_item(bogus_template_location)
        except ItemNotFoundError:
            asserted = True

        self.assertTrue(asserted)
