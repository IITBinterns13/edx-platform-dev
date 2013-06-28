from django.test import TestCase
from django.test.utils import override_settings

from xmodule.modulestore.django import modulestore
from xmodule.modulestore import Location

from modulestore_config import TEST_DATA_DRAFT_MONGO_MODULESTORE


@override_settings(MODULESTORE=TEST_DATA_DRAFT_MONGO_MODULESTORE)
class TestDraftModuleStore(TestCase):
    def test_get_items_with_course_items(self):
        store = modulestore()

        # fix was to allow get_items() to take the course_id parameter
        store.get_items(Location(None, None, 'vertical', None, None),
                        course_id='abc', depth=0)

        # test success is just getting through the above statement.
        # The bug was that 'course_id' argument was
        # not allowed to be passed in (i.e. was throwing exception)
