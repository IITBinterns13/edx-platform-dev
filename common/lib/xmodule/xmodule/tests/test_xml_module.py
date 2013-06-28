# disable missing docstring
#pylint: disable=C0111

from xmodule.x_module import XModuleFields
from xblock.core import Scope, String, Dict, Boolean, Integer, Float, Any, List
from xmodule.fields import Date, Timedelta
from xmodule.xml_module import XmlDescriptor, serialize_field, deserialize_field
import unittest
from .import get_test_system
from nose.tools import assert_equals
from mock import Mock


class CrazyJsonString(String):
    def to_json(self, value):
        return value + " JSON"


class TestFields(object):
    # Will be returned by editable_metadata_fields.
    max_attempts = Integer(scope=Scope.settings, default=1000, values={'min': 1, 'max': 10})
    # Will not be returned by editable_metadata_fields because filtered out by non_editable_metadata_fields.
    due = Date(scope=Scope.settings)
    # Will not be returned by editable_metadata_fields because is not Scope.settings.
    student_answers = Dict(scope=Scope.user_state)
    # Will be returned, and can override the inherited value from XModule.
    display_name = String(scope=Scope.settings, default='local default', display_name='Local Display Name',
                          help='local help')
    # Used for testing select type, effect of to_json method
    string_select = CrazyJsonString(
        scope=Scope.settings,
        default='default value',
        values=[{'display_name': 'first', 'value': 'value a'},
                {'display_name': 'second', 'value': 'value b'}]
    )
    # Used for testing select type
    float_select = Float(scope=Scope.settings, default=.999, values=[1.23, 0.98])
    # Used for testing float type
    float_non_select = Float(scope=Scope.settings, default=.999, values={'min': 0, 'step': .3})
    # Used for testing that Booleans get mapped to select type
    boolean_select = Boolean(scope=Scope.settings)


class EditableMetadataFieldsTest(unittest.TestCase):
    def test_display_name_field(self):
        editable_fields = self.get_xml_editable_fields({})
        # Tests that the xblock fields (currently tags and name) get filtered out.
        # Also tests that xml_attributes is filtered out of XmlDescriptor.
        self.assertEqual(1, len(editable_fields), "Expected only 1 editable field for xml descriptor.")
        self.assert_field_values(
            editable_fields, 'display_name', XModuleFields.display_name,
            explicitly_set=False, inheritable=False, value=None, default_value=None
        )

    def test_override_default(self):
        # Tests that explicitly_set is correct when a value overrides the default (not inheritable).
        editable_fields = self.get_xml_editable_fields({'display_name': 'foo'})
        self.assert_field_values(
            editable_fields, 'display_name', XModuleFields.display_name,
            explicitly_set=True, inheritable=False, value='foo', default_value=None
        )

    def test_integer_field(self):
        descriptor = self.get_descriptor({'max_attempts': '7'})
        editable_fields = descriptor.editable_metadata_fields
        self.assertEqual(6, len(editable_fields))
        self.assert_field_values(
            editable_fields, 'max_attempts', TestFields.max_attempts,
            explicitly_set=True, inheritable=False, value=7, default_value=1000, type='Integer',
            options=TestFields.max_attempts.values
        )
        self.assert_field_values(
            editable_fields, 'display_name', TestFields.display_name,
            explicitly_set=False, inheritable=False, value='local default', default_value='local default'
        )

        editable_fields = self.get_descriptor({}).editable_metadata_fields
        self.assert_field_values(
            editable_fields, 'max_attempts', TestFields.max_attempts,
            explicitly_set=False, inheritable=False, value=1000, default_value=1000, type='Integer',
            options=TestFields.max_attempts.values
        )

    def test_inherited_field(self):
        model_val = {'display_name': 'inherited'}
        descriptor = self.get_descriptor(model_val)
        # Mimic an inherited value for display_name (inherited and inheritable are the same in this case).
        descriptor._inherited_metadata = model_val
        descriptor._inheritable_metadata = model_val
        editable_fields = descriptor.editable_metadata_fields
        self.assert_field_values(
            editable_fields, 'display_name', TestFields.display_name,
            explicitly_set=False, inheritable=True, value='inherited', default_value='inherited'
        )

        descriptor = self.get_descriptor({'display_name': 'explicit'})
        # Mimic the case where display_name WOULD have been inherited, except we explicitly set it.
        descriptor._inheritable_metadata = {'display_name': 'inheritable value'}
        descriptor._inherited_metadata = {}
        editable_fields = descriptor.editable_metadata_fields
        self.assert_field_values(
            editable_fields, 'display_name', TestFields.display_name,
            explicitly_set=True, inheritable=True, value='explicit', default_value='inheritable value'
        )

    def test_type_and_options(self):
        # test_display_name_field verifies that a String field is of type "Generic".
        # test_integer_field verifies that a Integer field is of type "Integer".

        descriptor = self.get_descriptor({})
        editable_fields = descriptor.editable_metadata_fields

        # Tests for select
        self.assert_field_values(
            editable_fields, 'string_select', TestFields.string_select,
            explicitly_set=False, inheritable=False, value='default value', default_value='default value',
            type='Select', options=[{'display_name': 'first', 'value': 'value a JSON'},
                                    {'display_name': 'second', 'value': 'value b JSON'}]
        )

        self.assert_field_values(
            editable_fields, 'float_select', TestFields.float_select,
            explicitly_set=False, inheritable=False, value=.999, default_value=.999,
            type='Select', options=[1.23, 0.98]
        )

        self.assert_field_values(
            editable_fields, 'boolean_select', TestFields.boolean_select,
            explicitly_set=False, inheritable=False, value=None, default_value=None,
            type='Select', options=[{'display_name': "True", "value": True}, {'display_name': "False", "value": False}]
        )

        # Test for float
        self.assert_field_values(
            editable_fields, 'float_non_select', TestFields.float_non_select,
            explicitly_set=False, inheritable=False, value=.999, default_value=.999,
            type='Float', options={'min': 0, 'step': .3}
        )


    # Start of helper methods
    def get_xml_editable_fields(self, model_data):
        system = get_test_system()
        system.render_template = Mock(return_value="<div>Test Template HTML</div>")
        return XmlDescriptor(runtime=system, model_data=model_data).editable_metadata_fields

    def get_descriptor(self, model_data):
        class TestModuleDescriptor(TestFields, XmlDescriptor):
            @property
            def non_editable_metadata_fields(self):
                non_editable_fields = super(TestModuleDescriptor, self).non_editable_metadata_fields
                non_editable_fields.append(TestModuleDescriptor.due)
                return non_editable_fields

        system = get_test_system()
        system.render_template = Mock(return_value="<div>Test Template HTML</div>")
        return TestModuleDescriptor(runtime=system, model_data=model_data)

    def assert_field_values(self, editable_fields, name, field, explicitly_set, inheritable, value, default_value,
                            type='Generic', options=[]):
        test_field = editable_fields[name]

        self.assertEqual(field.name, test_field['field_name'])
        self.assertEqual(field.display_name, test_field['display_name'])
        self.assertEqual(field.help, test_field['help'])

        self.assertEqual(field.to_json(value), test_field['value'])
        self.assertEqual(field.to_json(default_value), test_field['default_value'])

        self.assertEqual(options, test_field['options'])
        self.assertEqual(type, test_field['type'])

        self.assertEqual(explicitly_set, test_field['explicitly_set'])
        self.assertEqual(inheritable, test_field['inheritable'])


class TestSerialize(unittest.TestCase):
    """ Tests the serialize, method, which is not dependent on type. """
    def test_serialize(self):
        assert_equals('null', serialize_field(None))
        assert_equals('-2', serialize_field(-2))
        assert_equals('"2"', serialize_field('2'))
        assert_equals('-3.41', serialize_field(-3.41))
        assert_equals('"2.589"', serialize_field('2.589'))
        assert_equals('false', serialize_field(False))
        assert_equals('"false"', serialize_field('false'))
        assert_equals('"fAlse"', serialize_field('fAlse'))
        assert_equals('"hat box"', serialize_field('hat box'))
        assert_equals('{"bar": "hat", "frog": "green"}', serialize_field({'bar': 'hat', 'frog' : 'green'}))
        assert_equals('[3.5, 5.6]', serialize_field([3.5, 5.6]))
        assert_equals('["foo", "bar"]', serialize_field(['foo', 'bar']))
        assert_equals('"2012-12-31T23:59:59Z"', serialize_field("2012-12-31T23:59:59Z"))
        assert_equals('"1 day 12 hours 59 minutes 59 seconds"',
            serialize_field("1 day 12 hours 59 minutes 59 seconds"))


class TestDeserialize(unittest.TestCase):
    def assertDeserializeEqual(self, expected, arg):
        """
        Asserts the result of deserialize_field.
        """
        assert_equals(expected, deserialize_field(self.test_field(), arg))


    def assertDeserializeNonString(self):
        """
        Asserts input value is returned for None or something that is not a string.
        For all types, 'null' is also always returned as None.
        """
        self.assertDeserializeEqual(None, None)
        self.assertDeserializeEqual(3.14, 3.14)
        self.assertDeserializeEqual(True, True)
        self.assertDeserializeEqual([10], [10])
        self.assertDeserializeEqual({}, {})
        self.assertDeserializeEqual([], [])
        self.assertDeserializeEqual(None, 'null')


class TestDeserializeInteger(TestDeserialize):
    """ Tests deserialize as related to Integer type. """

    test_field = Integer

    def test_deserialize(self):
        self.assertDeserializeEqual(-2, '-2')
        self.assertDeserializeEqual("450", '"450"')

        # False can be parsed as a int (converts to 0)
        self.assertDeserializeEqual(False, 'false')
        # True can be parsed as a int (converts to 1)
        self.assertDeserializeEqual(True, 'true')
        # 2.78 can be converted to int, so the string will be deserialized
        self.assertDeserializeEqual(-2.78, '-2.78')


    def test_deserialize_unsupported_types(self):
        self.assertDeserializeEqual('[3]', '[3]')
        # '2.78' cannot be converted to int, so input value is returned
        self.assertDeserializeEqual('"-2.78"', '"-2.78"')
        # 'false' cannot be converted to int, so input value is returned
        self.assertDeserializeEqual('"false"', '"false"')
        self.assertDeserializeNonString()


class TestDeserializeFloat(TestDeserialize):
    """ Tests deserialize as related to Float type. """

    test_field = Float

    def test_deserialize(self):
        self.assertDeserializeEqual(-2, '-2')
        self.assertDeserializeEqual("450", '"450"')
        self.assertDeserializeEqual(-2.78, '-2.78')
        self.assertDeserializeEqual("0.45", '"0.45"')

        # False can be parsed as a float (converts to 0)
        self.assertDeserializeEqual(False, 'false')
        # True can be parsed as a float (converts to 1)
        self.assertDeserializeEqual(True, 'true')

    def test_deserialize_unsupported_types(self):
        self.assertDeserializeEqual('[3]', '[3]')
        # 'false' cannot be converted to float, so input value is returned
        self.assertDeserializeEqual('"false"', '"false"')
        self.assertDeserializeNonString()


class TestDeserializeBoolean(TestDeserialize):
    """ Tests deserialize as related to Boolean type. """

    test_field = Boolean

    def test_deserialize(self):
        # json.loads converts the value to Python bool
        self.assertDeserializeEqual(False, 'false')
        self.assertDeserializeEqual(True, 'true')

        # json.loads fails, string value is returned.
        self.assertDeserializeEqual('False', 'False')
        self.assertDeserializeEqual('True', 'True')

        # json.loads deserializes as a string
        self.assertDeserializeEqual('false', '"false"')
        self.assertDeserializeEqual('fAlse', '"fAlse"')
        self.assertDeserializeEqual("TruE", '"TruE"')

        # 2.78 can be converted to a bool, so the string will be deserialized
        self.assertDeserializeEqual(-2.78, '-2.78')

        self.assertDeserializeNonString()


class TestDeserializeString(TestDeserialize):
    """ Tests deserialize as related to String type. """

    test_field = String

    def test_deserialize(self):
        self.assertDeserializeEqual('hAlf', '"hAlf"')
        self.assertDeserializeEqual('false', '"false"')
        self.assertDeserializeEqual('single quote', 'single quote')

    def test_deserialize_unsupported_types(self):
        self.assertDeserializeEqual('3.4', '3.4')
        self.assertDeserializeEqual('false', 'false')
        self.assertDeserializeEqual('2', '2')
        self.assertDeserializeEqual('[3]', '[3]')
        self.assertDeserializeNonString()


class TestDeserializeAny(TestDeserialize):
    """ Tests deserialize as related to Any type. """

    test_field = Any

    def test_deserialize(self):
        self.assertDeserializeEqual('hAlf', '"hAlf"')
        self.assertDeserializeEqual('false', '"false"')
        self.assertDeserializeEqual({'bar': 'hat', 'frog' : 'green'}, '{"bar": "hat", "frog": "green"}')
        self.assertDeserializeEqual([3.5, 5.6], '[3.5, 5.6]')
        self.assertDeserializeEqual('[', '[')
        self.assertDeserializeEqual(False, 'false')
        self.assertDeserializeEqual(3.4, '3.4')
        self.assertDeserializeNonString()


class TestDeserializeList(TestDeserialize):
    """ Tests deserialize as related to List type. """

    test_field = List

    def test_deserialize(self):
        self.assertDeserializeEqual(['foo', 'bar'], '["foo", "bar"]')
        self.assertDeserializeEqual([3.5, 5.6], '[3.5, 5.6]')
        self.assertDeserializeEqual([], '[]')

    def test_deserialize_unsupported_types(self):
        self.assertDeserializeEqual('3.4', '3.4')
        self.assertDeserializeEqual('false', 'false')
        self.assertDeserializeEqual('2', '2')
        self.assertDeserializeNonString()


class TestDeserializeDate(TestDeserialize):
    """ Tests deserialize as related to Date type. """

    test_field = Date

    def test_deserialize(self):
        self.assertDeserializeEqual('2012-12-31T23:59:59Z', "2012-12-31T23:59:59Z")
        self.assertDeserializeEqual('2012-12-31T23:59:59Z', '"2012-12-31T23:59:59Z"')
        self.assertDeserializeNonString()


class TestDeserializeTimedelta(TestDeserialize):
    """ Tests deserialize as related to Timedelta type. """

    test_field = Timedelta

    def test_deserialize(self):
        self.assertDeserializeEqual('1 day 12 hours 59 minutes 59 seconds',
            '1 day 12 hours 59 minutes 59 seconds')
        self.assertDeserializeEqual('1 day 12 hours 59 minutes 59 seconds',
            '"1 day 12 hours 59 minutes 59 seconds"')
        self.assertDeserializeNonString()
