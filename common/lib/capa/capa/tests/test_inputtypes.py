"""
Tests of input types.

TODO:
- refactor: so much repetive code (have factory methods that build xml elements directly, etc)

- test error cases

- check rendering -- e.g. msg should appear in the rendered output.  If possible, test that
  templates are escaping things properly.


- test unicode in values, parameters, etc.
- test various html escapes
- test funny xml chars -- should never get xml parse error if things are escaped properly.

"""

import json
from lxml import etree
import unittest
import xml.sax.saxutils as saxutils

from . import test_system
from capa import inputtypes
from mock import ANY

# just a handy shortcut
lookup_tag = inputtypes.registry.get_class_for_tag


def quote_attr(s):
    return saxutils.quoteattr(s)[1:-1]  # don't want the outer quotes


class OptionInputTest(unittest.TestCase):
    '''
    Make sure option inputs work
    '''

    def test_rendering(self):
        xml_str = """<optioninput options="('Up','Down')" id="sky_input" correct="Up"/>"""
        element = etree.fromstring(xml_str)

        state = {'value': 'Down',
                 'id': 'sky_input',
                 'status': 'answered'}
        option_input = lookup_tag('optioninput')(test_system(), element, state)

        context = option_input._get_render_context()

        expected = {'value': 'Down',
                    'options': [('Up', 'Up'), ('Down', 'Down')],
                    'status': 'answered',
                    'msg': '',
                    'inline': '',
                    'id': 'sky_input'}

        self.assertEqual(context, expected)

    def test_option_parsing(self):
        f = inputtypes.OptionInput.parse_options

        def check(input, options):
            """Take list of options, confirm that output is in the silly doubled format"""
            expected = [(o, o) for o in options]
            self.assertEqual(f(input), expected)

        check("('a','b')", ['a', 'b'])
        check("('a', 'b')", ['a', 'b'])
        check("('a b','b')", ['a b', 'b'])
        check("('My \"quoted\"place','b')", ['My \"quoted\"place', 'b'])


class ChoiceGroupTest(unittest.TestCase):
    '''
    Test choice groups, radio groups, and checkbox groups
    '''

    def check_group(self, tag, expected_input_type, expected_suffix):
        xml_str = """
  <{tag}>
    <choice correct="false" name="foil1"><text>This is foil One.</text></choice>
    <choice correct="false" name="foil2"><text>This is foil Two.</text></choice>
    <choice correct="true" name="foil3">This is foil Three.</choice>
  </{tag}>
        """.format(tag=tag)

        element = etree.fromstring(xml_str)

        state = {'value': 'foil3',
                 'id': 'sky_input',
                 'status': 'answered'}

        the_input = lookup_tag(tag)(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'sky_input',
                    'value': 'foil3',
                    'status': 'answered',
                    'msg': '',
                    'input_type': expected_input_type,
                    'choices': [('foil1', '<text>This is foil One.</text>'),
                                ('foil2', '<text>This is foil Two.</text>'),
                                ('foil3', 'This is foil Three.'), ],
                    'show_correctness': 'always',
                    'submitted_message': 'Answer received.',
                    'name_array_suffix': expected_suffix,   # what is this for??
                    }

        self.assertEqual(context, expected)

    def test_choicegroup(self):
        self.check_group('choicegroup', 'radio', '')

    def test_radiogroup(self):
        self.check_group('radiogroup', 'radio', '[]')

    def test_checkboxgroup(self):
        self.check_group('checkboxgroup', 'checkbox', '[]')


class JavascriptInputTest(unittest.TestCase):
    '''
    The javascript input is a pretty straightforward pass-thru, but test it anyway
    '''

    def test_rendering(self):
        params = "(1,2,3)"

        problem_state = "abc12',12&hi<there>"
        display_class = "a_class"
        display_file = "my_files/hi.js"

        xml_str = """<javascriptinput id="prob_1_2" params="{params}" problem_state="{ps}"
                                      display_class="{dc}" display_file="{df}"/>""".format(
                                          params=params,
                                          ps=quote_attr(problem_state),
                                          dc=display_class, df=display_file)

        element = etree.fromstring(xml_str)

        state = {'value': '3', }
        the_input = lookup_tag('javascriptinput')(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'status': 'unanswered',
                    'msg': '',
                    'value': '3',
                    'params': params,
                    'display_file': display_file,
                    'display_class': display_class,
                    'problem_state': problem_state, }

        self.assertEqual(context, expected)


class TextLineTest(unittest.TestCase):
    '''
    Check that textline inputs work, with and without math.
    '''

    def test_rendering(self):
        size = "42"
        xml_str = """<textline id="prob_1_2" size="{size}"/>""".format(size=size)

        element = etree.fromstring(xml_str)

        state = {'value': 'BumbleBee', }
        the_input = lookup_tag('textline')(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': 'BumbleBee',
                    'status': 'unanswered',
                    'size': size,
                    'msg': '',
                    'hidden': False,
                    'inline': False,
                    'do_math': False,
                    'trailing_text': '',
                    'preprocessor': None}
        self.assertEqual(context, expected)

    def test_math_rendering(self):
        size = "42"
        preprocessorClass = "preParty"
        script = "foo/party.js"

        xml_str = """<textline math="True" id="prob_1_2" size="{size}"
        preprocessorClassName="{pp}"
        preprocessorSrc="{sc}"/>""".format(size=size, pp=preprocessorClass, sc=script)

        element = etree.fromstring(xml_str)

        state = {'value': 'BumbleBee', }
        the_input = lookup_tag('textline')(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': 'BumbleBee',
                    'status': 'unanswered',
                    'size': size,
                    'msg': '',
                    'hidden': False,
                    'inline': False,
                    'trailing_text': '',
                    'do_math': True,
                    'preprocessor': {'class_name': preprocessorClass,
                                     'script_src': script}}
        self.assertEqual(context, expected)

    def test_trailing_text_rendering(self):
        size = "42"
        # store (xml_text, expected)
        trailing_text = []
        # standard trailing text
        trailing_text.append(('m/s', 'm/s'))
        # unicode trailing text
        trailing_text.append((u'\xc3', u'\xc3'))
        # html escaped trailing text
        # this is the only one we expect to change
        trailing_text.append(('a &lt; b', 'a < b'))

        for xml_text, expected_text in trailing_text:
            xml_str = u"""<textline id="prob_1_2"
                            size="{size}"
                            trailing_text="{tt}"
                            />""".format(size=size, tt=xml_text)

            element = etree.fromstring(xml_str)

            state = {'value': 'BumbleBee', }
            the_input = lookup_tag('textline')(test_system(), element, state)

            context = the_input._get_render_context()

            expected = {'id': 'prob_1_2',
                        'value': 'BumbleBee',
                        'status': 'unanswered',
                        'size': size,
                        'msg': '',
                        'hidden': False,
                        'inline': False,
                        'do_math': False,
                        'trailing_text': expected_text,
                        'preprocessor': None}
            self.assertEqual(context, expected)


class FileSubmissionTest(unittest.TestCase):
    '''
    Check that file submission inputs work
    '''

    def test_rendering(self):
        allowed_files = "runme.py nooooo.rb ohai.java"
        required_files = "cookies.py"

        xml_str = """<filesubmission id="prob_1_2"
        allowed_files="{af}"
        required_files="{rf}"
        />""".format(af=allowed_files,
                     rf=required_files,)

        element = etree.fromstring(xml_str)

        state = {'value': 'BumbleBee.py',
                 'status': 'incomplete',
                 'feedback': {'message': '3'}, }
        input_class = lookup_tag('filesubmission')
        the_input = input_class(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'status': 'queued',
                    'msg': input_class.submitted_msg,
                    'value': 'BumbleBee.py',
                    'queue_len': '3',
                    'allowed_files': '["runme.py", "nooooo.rb", "ohai.java"]',
                    'required_files': '["cookies.py"]'}

        self.assertEqual(context, expected)


class CodeInputTest(unittest.TestCase):
    '''
    Check that codeinput inputs work
    '''

    def test_rendering(self):
        mode = "parrot"
        linenumbers = 'false'
        rows = '37'
        cols = '11'
        tabsize = '7'

        xml_str = """<codeinput id="prob_1_2"
        mode="{m}"
        cols="{c}"
        rows="{r}"
        linenumbers="{ln}"
        tabsize="{ts}"
        />""".format(m=mode, c=cols, r=rows, ln=linenumbers, ts=tabsize)

        element = etree.fromstring(xml_str)

        escapedict = {'"': '&quot;'}
        esc = lambda s: saxutils.escape(s, escapedict)

        state = {'value': 'print "good evening"',
                 'status': 'incomplete',
                 'feedback': {'message': '3'}, }

        input_class = lookup_tag('codeinput')
        the_input = input_class(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': 'print "good evening"',
                    'status': 'queued',
                    'msg': input_class.submitted_msg,
                    'mode': mode,
                    'linenumbers': linenumbers,
                    'rows': rows,
                    'cols': cols,
                    'hidden': '',
                    'tabsize': int(tabsize),
                    'queue_len': '3'}

        self.assertEqual(context, expected)


class MatlabTest(unittest.TestCase):
    '''
    Test Matlab input types
    '''
    def setUp(self):
        self.rows = '10'
        self.cols = '80'
        self.tabsize = '4'
        self.mode = ""
        self.payload = "payload"
        self.linenumbers = 'true'
        self.xml = """<matlabinput id="prob_1_2"
            rows="{r}" cols="{c}"
            tabsize="{tabsize}" mode="{m}"
            linenumbers="{ln}">
                <plot_payload>
                    {payload}
                </plot_payload>
            </matlabinput>""".format(r=self.rows,
                                     c=self.cols,
                                     tabsize=self.tabsize,
                                     m=self.mode,
                                     payload=self.payload,
                                     ln=self.linenumbers)
        elt = etree.fromstring(self.xml)
        state = {'value': 'print "good evening"',
                 'status': 'incomplete',
                 'feedback': {'message': '3'}, }

        self.input_class = lookup_tag('matlabinput')
        self.the_input = self.input_class(test_system(), elt, state)

    def test_rendering(self):
        context = self.the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': 'print "good evening"',
                    'status': 'queued',
                    'msg': self.input_class.submitted_msg,
                    'mode': self.mode,
                    'rows': self.rows,
                    'cols': self.cols,
                    'queue_msg': '',
                    'linenumbers': 'true',
                    'hidden': '',
                    'tabsize': int(self.tabsize),
                    'button_enabled': True,
                    'queue_len': '3'}

        self.assertEqual(context, expected)

    def test_rendering_with_state(self):
        state = {'value': 'print "good evening"',
                 'status': 'incomplete',
                 'input_state': {'queue_msg': 'message'},
                 'feedback': {'message': '3'}, }
        elt = etree.fromstring(self.xml)

        the_input = self.input_class(test_system(), elt, state)
        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': 'print "good evening"',
                    'status': 'queued',
                    'msg': self.input_class.submitted_msg,
                    'mode': self.mode,
                    'rows': self.rows,
                    'cols': self.cols,
                    'queue_msg': 'message',
                    'linenumbers': 'true',
                    'hidden': '',
                    'tabsize': int(self.tabsize),
                    'button_enabled': True,
                    'queue_len': '3'}

        self.assertEqual(context, expected)

    def test_rendering_when_completed(self):
        for status in ['correct', 'incorrect']:
            state = {'value': 'print "good evening"',
                     'status': status,
                     'input_state': {},
                     }
            elt = etree.fromstring(self.xml)

            the_input = self.input_class(test_system(), elt, state)
            context = the_input._get_render_context()
            expected = {'id': 'prob_1_2',
                        'value': 'print "good evening"',
                        'status': status,
                        'msg': '',
                        'mode': self.mode,
                        'rows': self.rows,
                        'cols': self.cols,
                        'queue_msg': '',
                        'linenumbers': 'true',
                        'hidden': '',
                        'tabsize': int(self.tabsize),
                        'button_enabled': False,
                        'queue_len': '0'}

            self.assertEqual(context, expected)

    def test_rendering_while_queued(self):
        state = {'value': 'print "good evening"',
                 'status': 'incomplete',
                 'input_state': {'queuestate': 'queued'},
                 }
        elt = etree.fromstring(self.xml)

        the_input = self.input_class(test_system(), elt, state)
        context = the_input._get_render_context()
        expected = {'id': 'prob_1_2',
                    'value': 'print "good evening"',
                    'status': 'queued',
                    'msg': self.input_class.plot_submitted_msg,
                    'mode': self.mode,
                    'rows': self.rows,
                    'cols': self.cols,
                    'queue_msg': '',
                    'linenumbers': 'true',
                    'hidden': '',
                    'tabsize': int(self.tabsize),
                    'button_enabled': True,
                    'queue_len': '1'}

        self.assertEqual(context, expected)

    def test_plot_data(self):
        data = {'submission': 'x = 1234;'}
        response = self.the_input.handle_ajax("plot", data)

        test_system().xqueue['interface'].send_to_queue.assert_called_with(header=ANY, body=ANY)

        self.assertTrue(response['success'])
        self.assertTrue(self.the_input.input_state['queuekey'] is not None)
        self.assertEqual(self.the_input.input_state['queuestate'], 'queued')

    def test_plot_data_failure(self):
        data = {'submission': 'x = 1234;'}
        error_message = 'Error message!'
        test_system().xqueue['interface'].send_to_queue.return_value = (1, error_message)
        response = self.the_input.handle_ajax("plot", data)
        self.assertFalse(response['success'])
        self.assertEqual(response['message'], error_message)
        self.assertTrue('queuekey' not in self.the_input.input_state)
        self.assertTrue('queuestate' not in self.the_input.input_state)

    def test_ungraded_response_success(self):
        queuekey = 'abcd'
        input_state = {'queuekey': queuekey, 'queuestate': 'queued'}
        state = {'value': 'print "good evening"',
                 'status': 'incomplete',
                 'input_state': input_state,
                 'feedback': {'message': '3'}, }
        elt = etree.fromstring(self.xml)

        the_input = self.input_class(test_system(), elt, state)
        inner_msg = 'hello!'
        queue_msg = json.dumps({'msg': inner_msg})

        the_input.ungraded_response(queue_msg, queuekey)
        self.assertTrue(input_state['queuekey'] is None)
        self.assertTrue(input_state['queuestate'] is None)
        self.assertEqual(input_state['queue_msg'], inner_msg)

    def test_ungraded_response_key_mismatch(self):
        queuekey = 'abcd'
        input_state = {'queuekey': queuekey, 'queuestate': 'queued'}
        state = {'value': 'print "good evening"',
                 'status': 'incomplete',
                 'input_state': input_state,
                 'feedback': {'message': '3'}, }
        elt = etree.fromstring(self.xml)

        the_input = self.input_class(test_system(), elt, state)
        inner_msg = 'hello!'
        queue_msg = json.dumps({'msg': inner_msg})

        the_input.ungraded_response(queue_msg, 'abc')
        self.assertEqual(input_state['queuekey'], queuekey)
        self.assertEqual(input_state['queuestate'], 'queued')
        self.assertFalse('queue_msg' in input_state)


class SchematicTest(unittest.TestCase):
    '''
    Check that schematic inputs work
    '''

    def test_rendering(self):
        height = '12'
        width = '33'
        parts = 'resistors, capacitors, and flowers'
        analyses = 'fast, slow, and pink'
        initial_value = 'two large batteries'
        submit_analyses = 'maybe'

        xml_str = """<schematic id="prob_1_2"
        height="{h}"
        width="{w}"
        parts="{p}"
        analyses="{a}"
        initial_value="{iv}"
        submit_analyses="{sa}"
        />""".format(h=height, w=width, p=parts, a=analyses,
                     iv=initial_value, sa=submit_analyses)

        element = etree.fromstring(xml_str)

        value = 'three resistors and an oscilating pendulum'
        state = {'value': value,
                 'status': 'unsubmitted'}

        the_input = lookup_tag('schematic')(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': value,
                    'status': 'unsubmitted',
                    'msg': '',
                    'initial_value': initial_value,
                    'width': width,
                    'height': height,
                    'parts': parts,
                    'analyses': analyses,
                    'submit_analyses': submit_analyses}

        self.assertEqual(context, expected)


class ImageInputTest(unittest.TestCase):
    '''
    Check that image inputs work
    '''

    def check(self, value, egx, egy):
        height = '78'
        width = '427'
        src = 'http://www.edx.org/cowclicker.jpg'

        xml_str = """<imageinput id="prob_1_2"
        src="{s}"
        height="{h}"
        width="{w}"
        />""".format(s=src, h=height, w=width)

        element = etree.fromstring(xml_str)

        state = {'value': value,
                 'status': 'unsubmitted'}

        the_input = lookup_tag('imageinput')(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': value,
                    'status': 'unsubmitted',
                    'width': width,
                    'height': height,
                    'src': src,
                    'gx': egx,
                    'gy': egy,
                    'msg': ''}

        self.assertEqual(context, expected)

    def test_with_value(self):
        # Check that compensating for the dot size works properly.
        self.check('[50,40]', 35, 25)

    def test_without_value(self):
        self.check('', 0, 0)

    def test_corrupt_values(self):
        self.check('[12', 0, 0)
        self.check('[12, a]', 0, 0)
        self.check('[12 10]', 0, 0)
        self.check('[12]', 0, 0)
        self.check('[12 13 14]', 0, 0)


class CrystallographyTest(unittest.TestCase):
    '''
    Check that crystallography inputs work
    '''

    def test_rendering(self):
        height = '12'
        width = '33'

        xml_str = """<crystallography id="prob_1_2"
        height="{h}"
        width="{w}"
        />""".format(h=height, w=width)

        element = etree.fromstring(xml_str)

        value = 'abc'
        state = {'value': value,
                 'status': 'unsubmitted'}

        the_input = lookup_tag('crystallography')(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': value,
                    'status': 'unsubmitted',
                    'msg': '',
                    'width': width,
                    'height': height}

        self.assertEqual(context, expected)


class VseprTest(unittest.TestCase):
    '''
    Check that vsepr inputs work
    '''

    def test_rendering(self):
        height = '12'
        width = '33'
        molecules = "H2O, C2O"
        geometries = "AX12,TK421"

        xml_str = """<vsepr id="prob_1_2"
        height="{h}"
        width="{w}"
        molecules="{m}"
        geometries="{g}"
        />""".format(h=height, w=width, m=molecules, g=geometries)

        element = etree.fromstring(xml_str)

        value = 'abc'
        state = {'value': value,
                 'status': 'unsubmitted'}

        the_input = lookup_tag('vsepr_input')(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': value,
                    'status': 'unsubmitted',
                    'msg': '',
                    'width': width,
                    'height': height,
                    'molecules': molecules,
                    'geometries': geometries}

        self.assertEqual(context, expected)


class ChemicalEquationTest(unittest.TestCase):
    '''
    Check that chemical equation inputs work.
    '''
    def setUp(self):
        self.size = "42"
        xml_str = """<chemicalequationinput id="prob_1_2" size="{size}"/>""".format(size=self.size)

        element = etree.fromstring(xml_str)

        state = {'value': 'H2OYeah', }
        self.the_input = lookup_tag('chemicalequationinput')(test_system(), element, state)

    def test_rendering(self):
        ''' Verify that the render context matches the expected render context'''
        context = self.the_input._get_render_context()

        expected = {'id': 'prob_1_2',
                    'value': 'H2OYeah',
                    'status': 'unanswered',
                    'msg': '',
                    'size': self.size,
                    'previewer': '/static/js/capa/chemical_equation_preview.js',
                    }
        self.assertEqual(context, expected)

    def test_chemcalc_ajax_sucess(self):
        ''' Verify that using the correct dispatch and valid data produces a valid response'''
        data = {'formula': "H"}
        response = self.the_input.handle_ajax("preview_chemcalc", data)

        self.assertTrue('preview' in response)
        self.assertNotEqual(response['preview'], '')
        self.assertEqual(response['error'], "")


class DragAndDropTest(unittest.TestCase):
    '''
    Check that drag and drop inputs work
    '''

    def test_rendering(self):
        path_to_images = '/static/images/'

        xml_str = """
        <drag_and_drop_input id="prob_1_2" img="{path}about_1.png" target_outline="false">
            <draggable id="1" label="Label 1"/>
            <draggable id="name_with_icon" label="cc" icon="{path}cc.jpg"/>
            <draggable id="with_icon" label="arrow-left" icon="{path}arrow-left.png" />
            <draggable id="5" label="Label2" />
            <draggable id="2" label="Mute" icon="{path}mute.png" />
            <draggable id="name_label_icon3" label="spinner" icon="{path}spinner.gif" />
            <draggable id="name4" label="Star" icon="{path}volume.png" />
            <draggable id="7" label="Label3" />

            <target id="t1" x="210" y="90" w="90" h="90"/>
            <target id="t2" x="370" y="160" w="90" h="90"/>

        </drag_and_drop_input>
        """.format(path=path_to_images)

        element = etree.fromstring(xml_str)

        value = 'abc'
        state = {'value': value,
                 'status': 'unsubmitted'}

        user_input = {  # order matters, for string comparison
                        "target_outline": "false",
                        "base_image": "/static/images/about_1.png",
                        "draggables": [
{"can_reuse": "", "label": "Label 1", "id": "1", "icon": "", "target_fields": []},
{"can_reuse": "", "label": "cc", "id": "name_with_icon", "icon": "/static/images/cc.jpg", "target_fields": []},
{"can_reuse": "", "label": "arrow-left", "id": "with_icon", "icon": "/static/images/arrow-left.png", "can_reuse": "", "target_fields": []},
{"can_reuse": "", "label": "Label2", "id": "5", "icon": "", "can_reuse": "", "target_fields": []},
{"can_reuse": "", "label": "Mute", "id": "2", "icon": "/static/images/mute.png", "can_reuse": "", "target_fields": []},
{"can_reuse": "", "label": "spinner", "id": "name_label_icon3", "icon": "/static/images/spinner.gif", "can_reuse": "", "target_fields": []},
{"can_reuse": "", "label": "Star", "id": "name4", "icon": "/static/images/volume.png", "can_reuse": "", "target_fields": []},
{"can_reuse": "", "label": "Label3", "id": "7", "icon": "", "can_reuse": "", "target_fields": []}],
                        "one_per_target": "True",
                        "targets": [
                {"y": "90", "x": "210", "id": "t1", "w": "90", "h": "90"},
                {"y": "160", "x": "370", "id": "t2", "w": "90", "h": "90"}
                                    ]
                    }

        the_input = lookup_tag('drag_and_drop_input')(test_system(), element, state)

        context = the_input._get_render_context()
        expected = {'id': 'prob_1_2',
                    'value': value,
                    'status': 'unsubmitted',
                    'msg': '',
                    'drag_and_drop_json': json.dumps(user_input)
                    }

        # as we are dumping 'draggables' dicts while dumping user_input, string
        # comparison will fail, as order of keys is random.
        self.assertEqual(json.loads(context['drag_and_drop_json']), user_input)
        context.pop('drag_and_drop_json')
        expected.pop('drag_and_drop_json')
        self.assertEqual(context, expected)


class AnnotationInputTest(unittest.TestCase):
    '''
    Make sure option inputs work
    '''
    def test_rendering(self):
        xml_str = '''
<annotationinput>
    <title>foo</title>
    <text>bar</text>
    <comment>my comment</comment>
    <comment_prompt>type a commentary</comment_prompt>
    <tag_prompt>select a tag</tag_prompt>
    <options>
        <option choice="correct">x</option>
        <option choice="incorrect">y</option>
        <option choice="partially-correct">z</option>
    </options>
</annotationinput>
'''
        element = etree.fromstring(xml_str)

        value = {"comment": "blah blah", "options": [1]}
        json_value = json.dumps(value)
        state = {
            'value': json_value,
            'id': 'annotation_input',
            'status': 'answered'
        }

        tag = 'annotationinput'

        the_input = lookup_tag(tag)(test_system(), element, state)

        context = the_input._get_render_context()

        expected = {
            'id': 'annotation_input',
            'value': value,
            'status': 'answered',
            'msg': '',
            'title': 'foo',
            'text': 'bar',
            'comment': 'my comment',
            'comment_prompt': 'type a commentary',
            'tag_prompt': 'select a tag',
            'options': [
                {'id': 0, 'description': 'x', 'choice': 'correct'},
                {'id': 1, 'description': 'y', 'choice': 'incorrect'},
                {'id': 2, 'description': 'z', 'choice': 'partially-correct'}
            ],
            'value': json_value,
            'options_value': value['options'],
            'has_options_value': len(value['options']) > 0,
            'comment_value': value['comment'],
            'debug': False,
            'return_to_annotation': True
        }

        self.maxDiff = None
        self.assertDictEqual(context, expected)
