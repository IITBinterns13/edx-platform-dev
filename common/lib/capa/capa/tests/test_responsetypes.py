"""
Tests of responsetypes
"""

from datetime import datetime
import json
import os
import random
import unittest
import textwrap
import mock

from . import new_loncapa_problem, test_system

from capa.responsetypes import LoncapaProblemError, \
    StudentInputError, ResponseError
from capa.correctmap import CorrectMap
from capa.util import convert_files_to_filenames
from capa.xqueue_interface import dateformat


class ResponseTest(unittest.TestCase):
    """ Base class for tests of capa responses."""

    xml_factory_class = None

    def setUp(self):
        if self.xml_factory_class:
            self.xml_factory = self.xml_factory_class()

    def build_problem(self, system=None, **kwargs):
        xml = self.xml_factory.build_xml(**kwargs)
        return new_loncapa_problem(xml, system=system)

    def assert_grade(self, problem, submission, expected_correctness, msg=None):
        input_dict = {'1_2_1': submission}
        correct_map = problem.grade_answers(input_dict)
        if msg is None:
            self.assertEquals(correct_map.get_correctness('1_2_1'), expected_correctness)
        else:
            self.assertEquals(correct_map.get_correctness('1_2_1'), expected_correctness, msg)

    def assert_answer_format(self, problem):
        answers = problem.get_question_answers()
        self.assertTrue(answers['1_2_1'] is not None)

    def assert_multiple_grade(self, problem, correct_answers, incorrect_answers):
        for input_str in correct_answers:
            result = problem.grade_answers({'1_2_1': input_str}).get_correctness('1_2_1')
            self.assertEqual(result, 'correct',
                             msg="%s should be marked correct" % str(input_str))

        for input_str in incorrect_answers:
            result = problem.grade_answers({'1_2_1': input_str}).get_correctness('1_2_1')
            self.assertEqual(result, 'incorrect',
                             msg="%s should be marked incorrect" % str(input_str))

    def _get_random_number_code(self):
        """Returns code to be used to generate a random result."""
        return "str(random.randint(0, 1e9))"

    def _get_random_number_result(self, seed_value):
        """Returns a result that should be generated using the random_number_code."""
        rand = random.Random(seed_value)
        return str(rand.randint(0, 1e9))


class MultiChoiceResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import MultipleChoiceResponseXMLFactory
    xml_factory_class = MultipleChoiceResponseXMLFactory

    def test_multiple_choice_grade(self):
        problem = self.build_problem(choices=[False, True, False])

        # Ensure that we get the expected grades
        self.assert_grade(problem, 'choice_0', 'incorrect')
        self.assert_grade(problem, 'choice_1', 'correct')
        self.assert_grade(problem, 'choice_2', 'incorrect')

    def test_named_multiple_choice_grade(self):
        problem = self.build_problem(choices=[False, True, False],
                                     choice_names=["foil_1", "foil_2", "foil_3"])

        # Ensure that we get the expected grades
        self.assert_grade(problem, 'choice_foil_1', 'incorrect')
        self.assert_grade(problem, 'choice_foil_2', 'correct')
        self.assert_grade(problem, 'choice_foil_3', 'incorrect')


class TrueFalseResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import TrueFalseResponseXMLFactory
    xml_factory_class = TrueFalseResponseXMLFactory

    def test_true_false_grade(self):
        problem = self.build_problem(choices=[False, True, True])

        # Check the results
        # Mark correct if and only if ALL (and only) correct choices selected
        self.assert_grade(problem, 'choice_0', 'incorrect')
        self.assert_grade(problem, 'choice_1', 'incorrect')
        self.assert_grade(problem, 'choice_2', 'incorrect')
        self.assert_grade(problem, ['choice_0', 'choice_1', 'choice_2'], 'incorrect')
        self.assert_grade(problem, ['choice_0', 'choice_2'], 'incorrect')
        self.assert_grade(problem, ['choice_0', 'choice_1'], 'incorrect')
        self.assert_grade(problem, ['choice_1', 'choice_2'], 'correct')

        # Invalid choices should be marked incorrect (we have no choice 3)
        self.assert_grade(problem, 'choice_3', 'incorrect')
        self.assert_grade(problem, 'not_a_choice', 'incorrect')

    def test_named_true_false_grade(self):
        problem = self.build_problem(choices=[False, True, True],
                                     choice_names=['foil_1', 'foil_2', 'foil_3'])

        # Check the results
        # Mark correct if and only if ALL (and only) correct chocies selected
        self.assert_grade(problem, 'choice_foil_1', 'incorrect')
        self.assert_grade(problem, 'choice_foil_2', 'incorrect')
        self.assert_grade(problem, 'choice_foil_3', 'incorrect')
        self.assert_grade(problem, ['choice_foil_1', 'choice_foil_2', 'choice_foil_3'], 'incorrect')
        self.assert_grade(problem, ['choice_foil_1', 'choice_foil_3'], 'incorrect')
        self.assert_grade(problem, ['choice_foil_1', 'choice_foil_2'], 'incorrect')
        self.assert_grade(problem, ['choice_foil_2', 'choice_foil_3'], 'correct')

        # Invalid choices should be marked incorrect
        self.assert_grade(problem, 'choice_foil_4', 'incorrect')
        self.assert_grade(problem, 'not_a_choice', 'incorrect')


class ImageResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import ImageResponseXMLFactory
    xml_factory_class = ImageResponseXMLFactory

    def test_rectangle_grade(self):
        # Define a rectangle with corners (10,10) and (20,20)
        problem = self.build_problem(rectangle="(10,10)-(20,20)")

        # Anything inside the rectangle (and along the borders) is correct
        # Everything else is incorrect
        correct_inputs = ["[12,19]", "[10,10]", "[20,20]",
                          "[10,15]", "[20,15]", "[15,10]", "[15,20]"]
        incorrect_inputs = ["[4,6]", "[25,15]", "[15,40]", "[15,4]"]
        self.assert_multiple_grade(problem, correct_inputs, incorrect_inputs)

    def test_multiple_rectangles_grade(self):
        # Define two rectangles
        rectangle_str = "(10,10)-(20,20);(100,100)-(200,200)"

        # Expect that only points inside the rectangles are marked correct
        problem = self.build_problem(rectangle=rectangle_str)
        correct_inputs = ["[12,19]", "[120, 130]"]
        incorrect_inputs = ["[4,6]", "[25,15]", "[15,40]", "[15,4]",
                            "[50,55]", "[300, 14]", "[120, 400]"]
        self.assert_multiple_grade(problem, correct_inputs, incorrect_inputs)

    def test_region_grade(self):
        # Define a triangular region with corners (0,0), (5,10), and (0, 10)
        region_str = "[ [1,1], [5,10], [0,10] ]"

        # Expect that only points inside the triangle are marked correct
        problem = self.build_problem(regions=region_str)
        correct_inputs = ["[2,4]", "[1,3]"]
        incorrect_inputs = ["[0,0]", "[3,5]", "[5,15]", "[30, 12]"]
        self.assert_multiple_grade(problem, correct_inputs, incorrect_inputs)

    def test_multiple_regions_grade(self):
        # Define multiple regions that the user can select
        region_str = "[[[10,10], [20,10], [20, 30]], [[100,100], [120,100], [120,150]]]"

        # Expect that only points inside the regions are marked correct
        problem = self.build_problem(regions=region_str)
        correct_inputs = ["[15,12]", "[110,112]"]
        incorrect_inputs = ["[0,0]", "[600,300]"]
        self.assert_multiple_grade(problem, correct_inputs, incorrect_inputs)

    def test_region_and_rectangle_grade(self):
        rectangle_str = "(100,100)-(200,200)"
        region_str = "[[10,10], [20,10], [20, 30]]"

        # Expect that only points inside the rectangle or region are marked correct
        problem = self.build_problem(regions=region_str, rectangle=rectangle_str)
        correct_inputs = ["[13,12]", "[110,112]"]
        incorrect_inputs = ["[0,0]", "[600,300]"]
        self.assert_multiple_grade(problem, correct_inputs, incorrect_inputs)

    def test_show_answer(self):
        rectangle_str = "(100,100)-(200,200)"
        region_str = "[[10,10], [20,10], [20, 30]]"

        problem = self.build_problem(regions=region_str, rectangle=rectangle_str)
        self.assert_answer_format(problem)


class SymbolicResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import SymbolicResponseXMLFactory
    xml_factory_class = SymbolicResponseXMLFactory

    def test_grade_single_input(self):
        problem = self.build_problem(math_display=True,
                                     expect="2*x+3*y")

        # Correct answers
        correct_inputs = [
            ('2x+3y', textwrap.dedent("""
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                    <mstyle displaystyle="true">
                    <mn>2</mn><mo>*</mo><mi>x</mi><mo>+</mo><mn>3</mn><mo>*</mo><mi>y</mi>
                    </mstyle></math>""")),

            ('x+x+3y', textwrap.dedent("""
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                    <mstyle displaystyle="true">
                    <mi>x</mi><mo>+</mo><mi>x</mi><mo>+</mo><mn>3</mn><mo>*</mo><mi>y</mi>
                    </mstyle></math>""")),
        ]

        for (input_str, input_mathml) in correct_inputs:
            self._assert_symbolic_grade(problem, input_str, input_mathml, 'correct')

        # Incorrect answers
        incorrect_inputs = [
            ('0', ''),
            ('4x+3y', textwrap.dedent("""
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                    <mstyle displaystyle="true">
                    <mn>4</mn><mo>*</mo><mi>x</mi><mo>+</mo><mn>3</mn><mo>*</mo><mi>y</mi>
                    </mstyle></math>""")),
        ]

        for (input_str, input_mathml) in incorrect_inputs:
            self._assert_symbolic_grade(problem, input_str, input_mathml, 'incorrect')

    def test_complex_number_grade(self):
        problem = self.build_problem(math_display=True,
                                     expect="[[cos(theta),i*sin(theta)],[i*sin(theta),cos(theta)]]",
                                     options=["matrix", "imaginary"])

        # For LaTeX-style inputs, symmath_check() will try to contact
        # a server to convert the input to MathML.
        # We mock out the server, simulating the response that it would give
        # for this input.
        import requests
        dirpath = os.path.dirname(__file__)
        correct_snuggletex_response = open(os.path.join(dirpath, "test_files/snuggletex_correct.html")).read().decode('utf8')
        wrong_snuggletex_response = open(os.path.join(dirpath, "test_files/snuggletex_wrong.html")).read().decode('utf8')

        # Correct answer
        with mock.patch.object(requests, 'post') as mock_post:

            # Simulate what the LaTeX-to-MathML server would
            # send for the correct response input
            mock_post.return_value.text = correct_snuggletex_response

            self._assert_symbolic_grade(problem,
                "cos(theta)*[[1,0],[0,1]] + i*sin(theta)*[[0,1],[1,0]]",
                textwrap.dedent("""
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                  <mstyle displaystyle="true">
                    <mrow>
                      <mi>cos</mi>
                      <mrow><mo>(</mo><mi>&#x3B8;</mi><mo>)</mo></mrow>
                    </mrow>
                    <mo>&#x22C5;</mo>
                    <mrow>
                      <mo>[</mo>
                      <mtable>
                        <mtr>
                          <mtd><mn>1</mn></mtd><mtd><mn>0</mn></mtd>
                        </mtr>
                        <mtr>
                          <mtd><mn>0</mn></mtd><mtd><mn>1</mn></mtd>
                        </mtr>
                      </mtable>
                      <mo>]</mo>
                    </mrow>
                    <mo>+</mo>
                    <mi>i</mi>
                    <mo>&#x22C5;</mo>
                    <mrow>
                      <mi>sin</mi>
                      <mrow>
                        <mo>(</mo><mi>&#x3B8;</mi><mo>)</mo>
                      </mrow>
                    </mrow>
                    <mo>&#x22C5;</mo>
                    <mrow>
                      <mo>[</mo>
                      <mtable>
                        <mtr>
                          <mtd><mn>0</mn></mtd><mtd><mn>1</mn></mtd>
                        </mtr>
                        <mtr>
                          <mtd><mn>1</mn></mtd><mtd><mn>0</mn></mtd>
                        </mtr>
                      </mtable>
                      <mo>]</mo>
                    </mrow>
                  </mstyle>
                </math>
                """),
                'correct')

        # Incorrect answer
        with mock.patch.object(requests, 'post') as mock_post:

            # Simulate what the LaTeX-to-MathML server would
            # send for the incorrect response input
            mock_post.return_value.text = wrong_snuggletex_response

            self._assert_symbolic_grade(problem, "2",
                    textwrap.dedent("""
                    <math xmlns="http://www.w3.org/1998/Math/MathML">
                      <mstyle displaystyle="true"><mn>2</mn></mstyle>
                    </math>
                    """),
                'incorrect')

    def test_multiple_inputs_exception(self):

        # Should not allow multiple inputs, since we specify
        # only one "expect" value
        with self.assertRaises(Exception):
            self.build_problem(math_display=True,
                               expect="2*x+3*y",
                               num_inputs=3)

    def _assert_symbolic_grade(self, problem,
                               student_input,
                               dynamath_input,
                               expected_correctness):
        input_dict = {'1_2_1': str(student_input),
                      '1_2_1_dynamath': str(dynamath_input)}

        correct_map = problem.grade_answers(input_dict)

        self.assertEqual(correct_map.get_correctness('1_2_1'),
                        expected_correctness)


class OptionResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import OptionResponseXMLFactory
    xml_factory_class = OptionResponseXMLFactory

    def test_grade(self):
        problem = self.build_problem(options=["first", "second", "third"],
                                     correct_option="second")

        # Assert that we get the expected grades
        self.assert_grade(problem, "first", "incorrect")
        self.assert_grade(problem, "second", "correct")
        self.assert_grade(problem, "third", "incorrect")

        # Options not in the list should be marked incorrect
        self.assert_grade(problem, "invalid_option", "incorrect")


class FormulaResponseTest(ResponseTest):
    """
    Test the FormulaResponse class
    """
    from capa.tests.response_xml_factory import FormulaResponseXMLFactory
    xml_factory_class = FormulaResponseXMLFactory

    def test_grade(self):
        """
        Test basic functionality of FormulaResponse

        Specifically, if it can understand equivalence of formulae
        """
        # Sample variables x and y in the range [-10, 10]
        sample_dict = {'x': (-10, 10), 'y': (-10, 10)}

        # The expected solution is numerically equivalent to x+2y
        problem = self.build_problem(sample_dict=sample_dict,
                                     num_samples=10,
                                     tolerance=0.01,
                                     answer="x+2*y")

        # Expect an equivalent formula to be marked correct
        # 2x - x + y + y = x + 2y
        input_formula = "2*x - x + y + y"
        self.assert_grade(problem, input_formula, "correct")

        # Expect an incorrect formula to be marked incorrect
        # x + y != x + 2y
        input_formula = "x + y"
        self.assert_grade(problem, input_formula, "incorrect")

    def test_hint(self):
        """
        Test the hint-giving functionality of FormulaResponse
        """
        # Sample variables x and y in the range [-10, 10]
        sample_dict = {'x': (-10, 10), 'y': (-10, 10)}

        # Give a hint if the user leaves off the coefficient
        # or leaves out x
        hints = [('x + 3*y', 'y_coefficient', 'Check the coefficient of y'),
                 ('2*y', 'missing_x', 'Try including the variable x')]

        # The expected solution is numerically equivalent to x+2y
        problem = self.build_problem(sample_dict=sample_dict,
                                     num_samples=10,
                                     tolerance=0.01,
                                     answer="x+2*y",
                                     hints=hints)

        # Expect to receive a hint  if we add an extra y
        input_dict = {'1_2_1': "x + 2*y + y"}
        correct_map = problem.grade_answers(input_dict)
        self.assertEquals(correct_map.get_hint('1_2_1'),
                          'Check the coefficient of y')

        # Expect to receive a hint if we leave out x
        input_dict = {'1_2_1': "2*y"}
        correct_map = problem.grade_answers(input_dict)
        self.assertEquals(correct_map.get_hint('1_2_1'),
                          'Try including the variable x')

    def test_script(self):
        """
        Test if python script can be used to generate answers
        """

        # Calculate the answer using a script
        script = "calculated_ans = 'x+x'"

        # Sample x in the range [-10,10]
        sample_dict = {'x': (-10, 10)}

        # The expected solution is numerically equivalent to 2*x
        problem = self.build_problem(sample_dict=sample_dict,
                                     num_samples=10,
                                     tolerance=0.01,
                                     answer="$calculated_ans",
                                     script=script)

        # Expect that the inputs are graded correctly
        self.assert_grade(problem, '2*x', 'correct')
        self.assert_grade(problem, '3*x', 'incorrect')

    def test_parallel_resistors(self):
        """
        Test parallel resistors
        """
        sample_dict = {'R1': (10, 10), 'R2': (2, 2), 'R3': (5, 5), 'R4': (1, 1)}

        # Test problem
        problem = self.build_problem(sample_dict=sample_dict,
                                     num_samples=10,
                                     tolerance=0.01,
                                     answer="R1||R2")
        # Expect answer to be marked correct
        input_formula = "R1||R2"
        self.assert_grade(problem, input_formula, "correct")

        # Expect random number to be marked incorrect
        input_formula = "13"
        self.assert_grade(problem, input_formula, "incorrect")

        # Expect incorrect answer marked incorrect
        input_formula = "R3||R4"
        self.assert_grade(problem, input_formula, "incorrect")

    def test_default_variables(self):
        """
        Test the default variables provided in calc.py

        which are: j (complex number), e, pi, k, c, T, q
        """

        # Sample x in the range [-10,10]
        sample_dict = {'x': (-10, 10)}
        default_variables = [('j', 2, 3), ('e', 2, 3), ('pi', 2, 3), ('c', 2, 3), ('T', 2, 3),
                             ('k', 2 * 10 ** 23, 3 * 10 ** 23),   # note k = scipy.constants.k = 1.3806488e-23
                             ('q', 2 * 10 ** 19, 3 * 10 ** 19)]   # note k = scipy.constants.e = 1.602176565e-19
        for (var, cscalar, iscalar) in default_variables:
            # The expected solution is numerically equivalent to cscalar*var
            correct = '{0}*x*{1}'.format(cscalar, var)
            incorrect = '{0}*x*{1}'.format(iscalar, var)
            problem = self.build_problem(sample_dict=sample_dict,
                                         num_samples=10,
                                         tolerance=0.01,
                                         answer=correct)

            # Expect that the inputs are graded correctly
            self.assert_grade(problem, correct, 'correct',
                              msg="Failed on variable {0}; the given, correct answer was {1} but graded 'incorrect'".format(var, correct))
            self.assert_grade(problem, incorrect, 'incorrect',
                              msg="Failed on variable {0}; the given, incorrect answer was {1} but graded 'correct'".format(var, incorrect))

    def test_default_functions(self):
        """
        Test the default functions provided in common/lib/capa/capa/calc.py

        which are:
          sin, cos, tan, sqrt, log10, log2, ln,
          arccos, arcsin, arctan, abs,
          fact, factorial
        """
        w = random.randint(3, 10)
        sample_dict = {'x': (-10, 10),  # Sample x in the range [-10,10]
                       'y': (1, 10),    # Sample y in the range [1,10] - logs, arccos need positive inputs
                       'z': (-1, 1),    # Sample z in the range [1,10] - for arcsin, arctan
                       'w': (w, w)}     # Sample w is a random, positive integer - factorial needs a positive, integer input,
                                        # and the way formularesponse is defined, we can only specify a float range

        default_functions = [('sin', 2, 3, 'x'), ('cos', 2, 3, 'x'), ('tan', 2, 3, 'x'), ('sqrt', 2, 3, 'y'), ('log10', 2, 3, 'y'),
                             ('log2', 2, 3, 'y'), ('ln', 2, 3, 'y'), ('arccos', 2, 3, 'z'), ('arcsin', 2, 3, 'z'), ('arctan', 2, 3, 'x'),
                             ('abs', 2, 3, 'x'), ('fact', 2, 3, 'w'), ('factorial', 2, 3, 'w')]
        for (func, cscalar, iscalar, var) in default_functions:
            print 'func is: {0}'.format(func)
            # The expected solution is numerically equivalent to cscalar*func(var)
            correct = '{0}*{1}({2})'.format(cscalar, func, var)
            incorrect = '{0}*{1}({2})'.format(iscalar, func, var)
            problem = self.build_problem(sample_dict=sample_dict,
                                         num_samples=10,
                                         tolerance=0.01,
                                         answer=correct)

            # Expect that the inputs are graded correctly
            self.assert_grade(problem, correct, 'correct',
                              msg="Failed on function {0}; the given, correct answer was {1} but graded 'incorrect'".format(func, correct))
            self.assert_grade(problem, incorrect, 'incorrect',
                              msg="Failed on function {0}; the given, incorrect answer was {1} but graded 'correct'".format(func, incorrect))

    def test_grade_infinity(self):
        """
        Test that a large input on a problem with relative tolerance isn't
        erroneously marked as correct.
        """

        sample_dict = {'x': (1, 2)}

        # Test problem
        problem = self.build_problem(sample_dict=sample_dict,
                                     num_samples=10,
                                     tolerance="1%",
                                     answer="x")
        # Expect such a large answer to be marked incorrect
        input_formula = "x*1e999"
        self.assert_grade(problem, input_formula, "incorrect")
        # Expect such a large negative answer to be marked incorrect
        input_formula = "-x*1e999"
        self.assert_grade(problem, input_formula, "incorrect")

    def test_grade_nan(self):
        """
        Test that expressions that evaluate to NaN are not marked as correct.
        """

        sample_dict = {'x': (1, 2)}

        # Test problem
        problem = self.build_problem(sample_dict=sample_dict,
                                     num_samples=10,
                                     tolerance="1%",
                                     answer="x")
        # Expect an incorrect answer (+ nan) to be marked incorrect
        # Right now this evaluates to 'nan' for a given x (Python implementation-dependent)
        input_formula = "10*x + 0*1e999"
        self.assert_grade(problem, input_formula, "incorrect")
        # Expect an correct answer (+ nan) to be marked incorrect
        input_formula = "x + 0*1e999"
        self.assert_grade(problem, input_formula, "incorrect")

    def test_raises_zero_division_err(self):
        """
        See if division by zero raises an error.
        """
        sample_dict = {'x': (1, 2)}
        problem = self.build_problem(sample_dict=sample_dict,
                                     num_samples=10,
                                     tolerance="1%",
                                     answer="x")  # Answer doesn't matter
        input_dict = {'1_2_1': '1/0'}
        self.assertRaises(StudentInputError, problem.grade_answers, input_dict)


class StringResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import StringResponseXMLFactory
    xml_factory_class = StringResponseXMLFactory

    def test_case_sensitive(self):
        problem = self.build_problem(answer="Second", case_sensitive=True)

        # Exact string should be correct
        self.assert_grade(problem, "Second", "correct")

        # Other strings and the lowercase version of the string are incorrect
        self.assert_grade(problem, "Other String", "incorrect")
        self.assert_grade(problem, "second", "incorrect")

    def test_case_insensitive(self):
        problem = self.build_problem(answer="Second", case_sensitive=False)

        # Both versions of the string should be allowed, regardless
        # of capitalization
        self.assert_grade(problem, "Second", "correct")
        self.assert_grade(problem, "second", "correct")

        # Other strings are not allowed
        self.assert_grade(problem, "Other String", "incorrect")

    def test_hints(self):
        hints = [("wisconsin", "wisc", "The state capital of Wisconsin is Madison"),
                 ("minnesota", "minn", "The state capital of Minnesota is St. Paul")]

        problem = self.build_problem(answer="Michigan",
                                     case_sensitive=False,
                                     hints=hints)

        # We should get a hint for Wisconsin
        input_dict = {'1_2_1': 'Wisconsin'}
        correct_map = problem.grade_answers(input_dict)
        self.assertEquals(correct_map.get_hint('1_2_1'),
                          "The state capital of Wisconsin is Madison")

        # We should get a hint for Minnesota
        input_dict = {'1_2_1': 'Minnesota'}
        correct_map = problem.grade_answers(input_dict)
        self.assertEquals(correct_map.get_hint('1_2_1'),
                          "The state capital of Minnesota is St. Paul")

        # We should NOT get a hint for Michigan (the correct answer)
        input_dict = {'1_2_1': 'Michigan'}
        correct_map = problem.grade_answers(input_dict)
        self.assertEquals(correct_map.get_hint('1_2_1'), "")

        # We should NOT get a hint for any other string
        input_dict = {'1_2_1': 'California'}
        correct_map = problem.grade_answers(input_dict)
        self.assertEquals(correct_map.get_hint('1_2_1'), "")

    def test_computed_hints(self):
        problem = self.build_problem(
            answer="Michigan",
            hintfn="gimme_a_hint",
            script=textwrap.dedent("""
                def gimme_a_hint(answer_ids, student_answers, new_cmap, old_cmap):
                    aid = answer_ids[0]
                    answer = student_answers[aid]
                    new_cmap.set_hint_and_mode(aid, answer+"??", "always")
            """)
        )

        input_dict = {'1_2_1': 'Hello'}
        correct_map = problem.grade_answers(input_dict)
        self.assertEquals(correct_map.get_hint('1_2_1'), "Hello??")

    def test_hint_function_randomization(self):
        # The hint function should get the seed from the problem.
        problem = self.build_problem(
            answer="1",
            hintfn="gimme_a_random_hint",
            script=textwrap.dedent("""
                def gimme_a_random_hint(answer_ids, student_answers, new_cmap, old_cmap):
                    answer = {code}
                    new_cmap.set_hint_and_mode(answer_ids[0], answer, "always")

            """.format(code=self._get_random_number_code()))
        )
        correct_map = problem.grade_answers({'1_2_1': '2'})
        hint = correct_map.get_hint('1_2_1')
        self.assertEqual(hint, self._get_random_number_result(problem.seed))


class CodeResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import CodeResponseXMLFactory
    xml_factory_class = CodeResponseXMLFactory

    def setUp(self):
        super(CodeResponseTest, self).setUp()

        grader_payload = json.dumps({"grader": "ps04/grade_square.py"})
        self.problem = self.build_problem(initial_display="def square(x):",
                                          answer_display="answer",
                                          grader_payload=grader_payload,
                                          num_responses=2)

    @staticmethod
    def make_queuestate(key, time):
        """Create queuestate dict"""
        timestr = datetime.strftime(time, dateformat)
        return {'key': key, 'time': timestr}

    def test_is_queued(self):
        """
        Simple test of whether LoncapaProblem knows when it's been queued
        """

        answer_ids = sorted(self.problem.get_question_answers())

        # CodeResponse requires internal CorrectMap state. Build it now in the unqueued state
        cmap = CorrectMap()
        for answer_id in answer_ids:
            cmap.update(CorrectMap(answer_id=answer_id, queuestate=None))
        self.problem.correct_map.update(cmap)

        self.assertEquals(self.problem.is_queued(), False)

        # Now we queue the LCP
        cmap = CorrectMap()
        for i, answer_id in enumerate(answer_ids):
            queuestate = CodeResponseTest.make_queuestate(i, datetime.now())
            cmap.update(CorrectMap(answer_id=answer_ids[i], queuestate=queuestate))
        self.problem.correct_map.update(cmap)

        self.assertEquals(self.problem.is_queued(), True)

    def test_update_score(self):
        '''
        Test whether LoncapaProblem.update_score can deliver queued result to the right subproblem
        '''
        answer_ids = sorted(self.problem.get_question_answers())

        # CodeResponse requires internal CorrectMap state. Build it now in the queued state
        old_cmap = CorrectMap()
        for i, answer_id in enumerate(answer_ids):
            queuekey = 1000 + i
            queuestate = CodeResponseTest.make_queuestate(queuekey, datetime.now())
            old_cmap.update(CorrectMap(answer_id=answer_ids[i], queuestate=queuestate))

        # Message format common to external graders
        grader_msg = '<span>MESSAGE</span>'   # Must be valid XML
        correct_score_msg = json.dumps({'correct': True, 'score': 1, 'msg': grader_msg})
        incorrect_score_msg = json.dumps({'correct': False, 'score': 0, 'msg': grader_msg})

        xserver_msgs = {'correct': correct_score_msg,
                        'incorrect': incorrect_score_msg, }

        # Incorrect queuekey, state should not be updated
        for correctness in ['correct', 'incorrect']:
            self.problem.correct_map = CorrectMap()
            self.problem.correct_map.update(old_cmap)  # Deep copy

            self.problem.update_score(xserver_msgs[correctness], queuekey=0)
            self.assertEquals(self.problem.correct_map.get_dict(), old_cmap.get_dict())  # Deep comparison

            for answer_id in answer_ids:
                self.assertTrue(self.problem.correct_map.is_queued(answer_id))  # Should be still queued, since message undelivered

        # Correct queuekey, state should be updated
        for correctness in ['correct', 'incorrect']:
            for i, answer_id in enumerate(answer_ids):
                self.problem.correct_map = CorrectMap()
                self.problem.correct_map.update(old_cmap)

                new_cmap = CorrectMap()
                new_cmap.update(old_cmap)
                npoints = 1 if correctness == 'correct' else 0
                new_cmap.set(answer_id=answer_id, npoints=npoints, correctness=correctness, msg=grader_msg, queuestate=None)

                self.problem.update_score(xserver_msgs[correctness], queuekey=1000 + i)
                self.assertEquals(self.problem.correct_map.get_dict(), new_cmap.get_dict())

                for j, test_id in enumerate(answer_ids):
                    if j == i:
                        self.assertFalse(self.problem.correct_map.is_queued(test_id))  # Should be dequeued, message delivered
                    else:
                        self.assertTrue(self.problem.correct_map.is_queued(test_id))  # Should be queued, message undelivered

    def test_recentmost_queuetime(self):
        '''
        Test whether the LoncapaProblem knows about the time of queue requests
        '''
        answer_ids = sorted(self.problem.get_question_answers())

        # CodeResponse requires internal CorrectMap state. Build it now in the unqueued state
        cmap = CorrectMap()
        for answer_id in answer_ids:
            cmap.update(CorrectMap(answer_id=answer_id, queuestate=None))
        self.problem.correct_map.update(cmap)

        self.assertEquals(self.problem.get_recentmost_queuetime(), None)

        # CodeResponse requires internal CorrectMap state. Build it now in the queued state
        cmap = CorrectMap()
        for i, answer_id in enumerate(answer_ids):
            queuekey = 1000 + i
            latest_timestamp = datetime.now()
            queuestate = CodeResponseTest.make_queuestate(queuekey, latest_timestamp)
            cmap.update(CorrectMap(answer_id=answer_id, queuestate=queuestate))
        self.problem.correct_map.update(cmap)

        # Queue state only tracks up to second
        latest_timestamp = datetime.strptime(datetime.strftime(latest_timestamp, dateformat), dateformat)

        self.assertEquals(self.problem.get_recentmost_queuetime(), latest_timestamp)

    def test_convert_files_to_filenames(self):
        '''
        Test whether file objects are converted to filenames without altering other structures
        '''
        problem_file = os.path.join(os.path.dirname(__file__), "test_files/filename_convert_test.txt")
        with open(problem_file) as fp:
            answers_with_file = {'1_2_1': 'String-based answer',
                                 '1_3_1': ['answer1', 'answer2', 'answer3'],
                                 '1_4_1': [fp, fp]}
            answers_converted = convert_files_to_filenames(answers_with_file)
            self.assertEquals(answers_converted['1_2_1'], 'String-based answer')
            self.assertEquals(answers_converted['1_3_1'], ['answer1', 'answer2', 'answer3'])
            self.assertEquals(answers_converted['1_4_1'], [fp.name, fp.name])


class ChoiceResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import ChoiceResponseXMLFactory
    xml_factory_class = ChoiceResponseXMLFactory

    def test_radio_group_grade(self):
        problem = self.build_problem(choice_type='radio',
                                     choices=[False, True, False])

        # Check that we get the expected results
        self.assert_grade(problem, 'choice_0', 'incorrect')
        self.assert_grade(problem, 'choice_1', 'correct')
        self.assert_grade(problem, 'choice_2', 'incorrect')

        # No choice 3 exists --> mark incorrect
        self.assert_grade(problem, 'choice_3', 'incorrect')

    def test_checkbox_group_grade(self):
        problem = self.build_problem(choice_type='checkbox',
                                     choices=[False, True, True])

        # Check that we get the expected results
        # (correct if and only if BOTH correct choices chosen)
        self.assert_grade(problem, ['choice_1', 'choice_2'], 'correct')
        self.assert_grade(problem, 'choice_1', 'incorrect')
        self.assert_grade(problem, 'choice_2', 'incorrect')
        self.assert_grade(problem, ['choice_0', 'choice_1'], 'incorrect')
        self.assert_grade(problem, ['choice_0', 'choice_2'], 'incorrect')

        # No choice 3 exists --> mark incorrect
        self.assert_grade(problem, 'choice_3', 'incorrect')


class JavascriptResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import JavascriptResponseXMLFactory
    xml_factory_class = JavascriptResponseXMLFactory

    def test_grade(self):
        # Compile coffee files into javascript used by the response
        coffee_file_path = os.path.dirname(__file__) + "/test_files/js/*.coffee"
        os.system("node_modules/.bin/coffee -c %s" % (coffee_file_path))

        system = test_system()
        system.can_execute_unsafe_code = lambda: True
        problem = self.build_problem(
            system=system,
            generator_src="test_problem_generator.js",
            grader_src="test_problem_grader.js",
            display_class="TestProblemDisplay",
            display_src="test_problem_display.js",
            param_dict={'value': '4'},
        )

        # Test that we get graded correctly
        self.assert_grade(problem, json.dumps({0: 4}), "correct")
        self.assert_grade(problem, json.dumps({0: 5}), "incorrect")

    def test_cant_execute_javascript(self):
        # If the system says to disallow unsafe code execution, then making
        # this problem will raise an exception.
        system = test_system()
        system.can_execute_unsafe_code = lambda: False

        with self.assertRaises(LoncapaProblemError):
            self.build_problem(
                system=system,
                generator_src="test_problem_generator.js",
                grader_src="test_problem_grader.js",
                display_class="TestProblemDisplay",
                display_src="test_problem_display.js",
                param_dict={'value': '4'},
            )


class NumericalResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import NumericalResponseXMLFactory
    xml_factory_class = NumericalResponseXMLFactory

    def test_grade_exact(self):
        problem = self.build_problem(question_text="What is 2 + 2?",
                                     explanation="The answer is 4",
                                     answer=4)
        correct_responses = ["4", "4.0", "4.00"]
        incorrect_responses = ["", "3.9", "4.1", "0"]
        self.assert_multiple_grade(problem, correct_responses, incorrect_responses)

    def test_grade_decimal_tolerance(self):
        problem = self.build_problem(question_text="What is 2 + 2 approximately?",
                                     explanation="The answer is 4",
                                     answer=4,
                                     tolerance=0.1)
        correct_responses = ["4.0", "4.00", "4.09", "3.91"]
        incorrect_responses = ["", "4.11", "3.89", "0"]
        self.assert_multiple_grade(problem, correct_responses, incorrect_responses)

    def test_grade_percent_tolerance(self):
        problem = self.build_problem(question_text="What is 2 + 2 approximately?",
                                     explanation="The answer is 4",
                                     answer=4,
                                     tolerance="10%")
        correct_responses = ["4.0", "4.3", "3.7", "4.30", "3.70"]
        incorrect_responses = ["", "4.5", "3.5", "0"]
        self.assert_multiple_grade(problem, correct_responses, incorrect_responses)

    def test_grade_infinity(self):
        # This resolves a bug where a problem with relative tolerance would
        # pass with any arbitrarily large student answer.
        problem = self.build_problem(question_text="What is 2 + 2 approximately?",
                                     explanation="The answer is 4",
                                     answer=4,
                                     tolerance="10%")
        correct_responses = []
        incorrect_responses = ["1e999", "-1e999"]
        self.assert_multiple_grade(problem, correct_responses, incorrect_responses)

    def test_grade_nan(self):
        # Attempt to produce a value which causes the student's answer to be
        # evaluated to nan. See if this is resolved correctly.
        problem = self.build_problem(question_text="What is 2 + 2 approximately?",
                                     explanation="The answer is 4",
                                     answer=4,
                                     tolerance="10%")
        correct_responses = []
        # Right now these evaluate to `nan`
        # `4 + nan` should be incorrect
        incorrect_responses = ["0*1e999", "4 + 0*1e999"]
        self.assert_multiple_grade(problem, correct_responses, incorrect_responses)

    def test_grade_with_script(self):
        script_text = "computed_response = math.sqrt(4)"
        problem = self.build_problem(question_text="What is sqrt(4)?",
                                     explanation="The answer is 2",
                                     answer="$computed_response",
                                     script=script_text)
        correct_responses = ["2", "2.0"]
        incorrect_responses = ["", "2.01", "1.99", "0"]
        self.assert_multiple_grade(problem, correct_responses, incorrect_responses)

    def test_grade_with_script_and_tolerance(self):
        script_text = "computed_response = math.sqrt(4)"
        problem = self.build_problem(question_text="What is sqrt(4)?",
                                     explanation="The answer is 2",
                                     answer="$computed_response",
                                     tolerance="0.1",
                                     script=script_text)
        correct_responses = ["2", "2.0", "2.05", "1.95"]
        incorrect_responses = ["", "2.11", "1.89", "0"]
        self.assert_multiple_grade(problem, correct_responses, incorrect_responses)

    def test_exponential_answer(self):
        problem = self.build_problem(question_text="What 5 * 10?",
                                     explanation="The answer is 50",
                                     answer="5e+1")
        correct_responses = ["50", "50.0", "5e1", "5e+1", "50e0", "500e-1"]
        incorrect_responses = ["", "3.9", "4.1", "0", "5.01e1"]
        self.assert_multiple_grade(problem, correct_responses, incorrect_responses)

    def test_raises_zero_division_err(self):
        """See if division by zero is handled correctly"""
        problem = self.build_problem(question_text="What 5 * 10?",
                                     explanation="The answer is 50",
                                     answer="5e+1")  # Answer doesn't matter
        input_dict = {'1_2_1': '1/0'}
        self.assertRaises(StudentInputError, problem.grade_answers, input_dict)


class CustomResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import CustomResponseXMLFactory
    xml_factory_class = CustomResponseXMLFactory

    def test_inline_code(self):
        # For inline code, we directly modify global context variables
        # 'answers' is a list of answers provided to us
        # 'correct' is a list we fill in with True/False
        # 'expect' is given to us (if provided in the XML)
        inline_script = """correct[0] = 'correct' if (answers['1_2_1'] == expect) else 'incorrect'"""
        problem = self.build_problem(answer=inline_script, expect="42")

        # Check results
        self.assert_grade(problem, '42', 'correct')
        self.assert_grade(problem, '0', 'incorrect')

    def test_inline_message(self):
        # Inline code can update the global messages list
        # to pass messages to the CorrectMap for a particular input
        # The code can also set the global overall_message (str)
        # to pass a message that applies to the whole response
        inline_script = textwrap.dedent("""
            messages[0] = "Test Message"
            overall_message = "Overall message"
            """)
        problem = self.build_problem(answer=inline_script)

        input_dict = {'1_2_1': '0'}
        correctmap = problem.grade_answers(input_dict)

        # Check that the message for the particular input was received
        input_msg = correctmap.get_msg('1_2_1')
        self.assertEqual(input_msg, "Test Message")

        # Check that the overall message (for the whole response) was received
        overall_msg = correctmap.get_overall_message()
        self.assertEqual(overall_msg, "Overall message")

    def test_inline_randomization(self):
        # Make sure the seed from the problem gets fed into the script execution.
        inline_script = "messages[0] = {code}".format(code=self._get_random_number_code())
        problem = self.build_problem(answer=inline_script)

        input_dict = {'1_2_1': '0'}
        correctmap = problem.grade_answers(input_dict)

        input_msg = correctmap.get_msg('1_2_1')
        self.assertEqual(input_msg, self._get_random_number_result(problem.seed))

    def test_function_code_single_input(self):
        # For function code, we pass in these arguments:
        #
        #   'expect' is the expect attribute of the <customresponse>
        #
        #   'answer_given' is the answer the student gave (if there is just one input)
        #       or an ordered list of answers (if there are multiple inputs)
        #
        # The function should return a dict of the form
        # { 'ok': BOOL, 'msg': STRING }
        #
        script = textwrap.dedent("""
            def check_func(expect, answer_given):
                return {'ok': answer_given == expect, 'msg': 'Message text'}
        """)

        problem = self.build_problem(script=script, cfn="check_func", expect="42")

        # Correct answer
        input_dict = {'1_2_1': '42'}
        correct_map = problem.grade_answers(input_dict)

        correctness = correct_map.get_correctness('1_2_1')
        msg = correct_map.get_msg('1_2_1')

        self.assertEqual(correctness, 'correct')
        self.assertEqual(msg, "Message text")

        # Incorrect answer
        input_dict = {'1_2_1': '0'}
        correct_map = problem.grade_answers(input_dict)

        correctness = correct_map.get_correctness('1_2_1')
        msg = correct_map.get_msg('1_2_1')

        self.assertEqual(correctness, 'incorrect')
        self.assertEqual(msg, "Message text")

    def test_function_code_multiple_input_no_msg(self):

        # Check functions also have the option of returning
        # a single boolean value
        # If true, mark all the inputs correct
        # If false, mark all the inputs incorrect
        script = textwrap.dedent("""
            def check_func(expect, answer_given):
                return (answer_given[0] == expect and
                        answer_given[1] == expect)
        """)

        problem = self.build_problem(script=script, cfn="check_func",
                                     expect="42", num_inputs=2)

        # Correct answer -- expect both inputs marked correct
        input_dict = {'1_2_1': '42', '1_2_2': '42'}
        correct_map = problem.grade_answers(input_dict)

        correctness = correct_map.get_correctness('1_2_1')
        self.assertEqual(correctness, 'correct')

        correctness = correct_map.get_correctness('1_2_2')
        self.assertEqual(correctness, 'correct')

        # One answer incorrect -- expect both inputs marked incorrect
        input_dict = {'1_2_1': '0', '1_2_2': '42'}
        correct_map = problem.grade_answers(input_dict)

        correctness = correct_map.get_correctness('1_2_1')
        self.assertEqual(correctness, 'incorrect')

        correctness = correct_map.get_correctness('1_2_2')
        self.assertEqual(correctness, 'incorrect')

    def test_function_code_multiple_inputs(self):

        # If the <customresponse> has multiple inputs associated with it,
        # the check function can return a dict of the form:
        #
        # {'overall_message': STRING,
        #  'input_list': [{'ok': BOOL, 'msg': STRING}, ...] }
        #
        # 'overall_message' is displayed at the end of the response
        #
        # 'input_list' contains dictionaries representing the correctness
        #           and message for each input.
        script = textwrap.dedent("""
            def check_func(expect, answer_given):
                check1 = (int(answer_given[0]) == 1)
                check2 = (int(answer_given[1]) == 2)
                check3 = (int(answer_given[2]) == 3)
                return {'overall_message': 'Overall message',
                        'input_list': [
                            {'ok': check1,  'msg': 'Feedback 1'},
                            {'ok': check2,  'msg': 'Feedback 2'},
                            {'ok': check3,  'msg': 'Feedback 3'} ] }
            """)

        problem = self.build_problem(script=script,
                                     cfn="check_func", num_inputs=3)

        # Grade the inputs (one input incorrect)
        input_dict = {'1_2_1': '-999', '1_2_2': '2', '1_2_3': '3'}
        correct_map = problem.grade_answers(input_dict)

        # Expect that we receive the overall message (for the whole response)
        self.assertEqual(correct_map.get_overall_message(), "Overall message")

        # Expect that the inputs were graded individually
        self.assertEqual(correct_map.get_correctness('1_2_1'), 'incorrect')
        self.assertEqual(correct_map.get_correctness('1_2_2'), 'correct')
        self.assertEqual(correct_map.get_correctness('1_2_3'), 'correct')

        # Expect that we received messages for each individual input
        self.assertEqual(correct_map.get_msg('1_2_1'), 'Feedback 1')
        self.assertEqual(correct_map.get_msg('1_2_2'), 'Feedback 2')
        self.assertEqual(correct_map.get_msg('1_2_3'), 'Feedback 3')

    def test_function_code_with_extra_args(self):
        script = textwrap.dedent("""\
                    def check_func(expect, answer_given, options, dynamath):
                        assert options == "xyzzy", "Options was %r" % options
                        return {'ok': answer_given == expect, 'msg': 'Message text'}
                    """)

        problem = self.build_problem(script=script, cfn="check_func", expect="42", options="xyzzy", cfn_extra_args="options dynamath")

        # Correct answer
        input_dict = {'1_2_1': '42'}
        correct_map = problem.grade_answers(input_dict)

        correctness = correct_map.get_correctness('1_2_1')
        msg = correct_map.get_msg('1_2_1')

        self.assertEqual(correctness, 'correct')
        self.assertEqual(msg, "Message text")

        # Incorrect answer
        input_dict = {'1_2_1': '0'}
        correct_map = problem.grade_answers(input_dict)

        correctness = correct_map.get_correctness('1_2_1')
        msg = correct_map.get_msg('1_2_1')

        self.assertEqual(correctness, 'incorrect')
        self.assertEqual(msg, "Message text")

    def test_multiple_inputs_return_one_status(self):
        # When given multiple inputs, the 'answer_given' argument
        # to the check_func() is a list of inputs
        #
        # The sample script below marks the problem as correct
        # if and only if it receives answer_given=[1,2,3]
        # (or string values ['1','2','3'])
        #
        # Since we return a dict describing the status of one input,
        # we expect that the same 'ok' value is applied to each
        # of the inputs.
        script = textwrap.dedent("""
            def check_func(expect, answer_given):
                check1 = (int(answer_given[0]) == 1)
                check2 = (int(answer_given[1]) == 2)
                check3 = (int(answer_given[2]) == 3)
                return {'ok': (check1 and check2 and check3),
                        'msg': 'Message text'}
            """)

        problem = self.build_problem(script=script,
                                     cfn="check_func", num_inputs=3)

        # Grade the inputs (one input incorrect)
        input_dict = {'1_2_1': '-999', '1_2_2': '2', '1_2_3': '3'}
        correct_map = problem.grade_answers(input_dict)

        # Everything marked incorrect
        self.assertEqual(correct_map.get_correctness('1_2_1'), 'incorrect')
        self.assertEqual(correct_map.get_correctness('1_2_2'), 'incorrect')
        self.assertEqual(correct_map.get_correctness('1_2_3'), 'incorrect')

        # Grade the inputs (everything correct)
        input_dict = {'1_2_1': '1', '1_2_2': '2', '1_2_3': '3'}
        correct_map = problem.grade_answers(input_dict)

        # Everything marked incorrect
        self.assertEqual(correct_map.get_correctness('1_2_1'), 'correct')
        self.assertEqual(correct_map.get_correctness('1_2_2'), 'correct')
        self.assertEqual(correct_map.get_correctness('1_2_3'), 'correct')

        # Message is interpreted as an "overall message"
        self.assertEqual(correct_map.get_overall_message(), 'Message text')

    def test_script_exception_function(self):

        # Construct a script that will raise an exception
        script = textwrap.dedent("""
            def check_func(expect, answer_given):
                raise Exception("Test")
            """)

        problem = self.build_problem(script=script, cfn="check_func")

        # Expect that an exception gets raised when we check the answer
        with self.assertRaises(ResponseError):
            problem.grade_answers({'1_2_1': '42'})

    def test_script_exception_inline(self):

        # Construct a script that will raise an exception
        script = 'raise Exception("Test")'
        problem = self.build_problem(answer=script)

        # Expect that an exception gets raised when we check the answer
        with self.assertRaises(ResponseError):
            problem.grade_answers({'1_2_1': '42'})

    def test_invalid_dict_exception(self):

        # Construct a script that passes back an invalid dict format
        script = textwrap.dedent("""
            def check_func(expect, answer_given):
                return {'invalid': 'test'}
            """)

        problem = self.build_problem(script=script, cfn="check_func")

        # Expect that an exception gets raised when we check the answer
        with self.assertRaises(ResponseError):
            problem.grade_answers({'1_2_1': '42'})

    def test_setup_randomization(self):
        # Ensure that the problem setup script gets the random seed from the problem.
        script = textwrap.dedent("""
            num = {code}
            """.format(code=self._get_random_number_code()))
        problem = self.build_problem(script=script)
        self.assertEqual(problem.context['num'], self._get_random_number_result(problem.seed))

    def test_check_function_randomization(self):
        # The check function should get random-seeded from the problem.
        script = textwrap.dedent("""
            def check_func(expect, answer_given):
                return {{'ok': True, 'msg': {code} }}
        """.format(code=self._get_random_number_code()))

        problem = self.build_problem(script=script, cfn="check_func", expect="42")
        input_dict = {'1_2_1': '42'}
        correct_map = problem.grade_answers(input_dict)
        msg = correct_map.get_msg('1_2_1')
        self.assertEqual(msg, self._get_random_number_result(problem.seed))

    def test_random_isnt_none(self):
        # Bug LMS-500 says random.seed(10) fails with:
        #     File "<string>", line 61, in <module>
        #     File "/usr/lib/python2.7/random.py", line 116, in seed
        #       super(Random, self).seed(a)
        #   TypeError: must be type, not None

        r = random.Random()
        r.seed(10)
        num = r.randint(0, 1e9)

        script = textwrap.dedent("""
            random.seed(10)
            num = random.randint(0, 1e9)
            """)
        problem = self.build_problem(script=script)
        self.assertEqual(problem.context['num'], num)

    def test_module_imports_inline(self):
        '''
        Check that the correct modules are available to custom
        response scripts
        '''

        for module_name in ['random', 'numpy', 'math', 'scipy',
                            'calc', 'eia', 'chemcalc', 'chemtools',
                            'miller', 'draganddrop']:

            # Create a script that checks that the name is defined
            # If the name is not defined, then the script
            # will raise an exception
            script = textwrap.dedent('''
            correct[0] = 'correct'
            assert('%s' in globals())''' % module_name)

            # Create the problem
            problem = self.build_problem(answer=script)

            # Expect that we can grade an answer without
            # getting an exception
            try:
                problem.grade_answers({'1_2_1': '42'})

            except ResponseError:
                self.fail("Could not use name '{0}s' in custom response".format(module_name))

    def test_module_imports_function(self):
        '''
        Check that the correct modules are available to custom
        response scripts
        '''

        for module_name in ['random', 'numpy', 'math', 'scipy',
                            'calc', 'eia', 'chemcalc', 'chemtools',
                            'miller', 'draganddrop']:

            # Create a script that checks that the name is defined
            # If the name is not defined, then the script
            # will raise an exception
            script = textwrap.dedent('''
            def check_func(expect, answer_given):
                assert('%s' in globals())
                return True''' % module_name)

            # Create the problem
            problem = self.build_problem(script=script, cfn="check_func")

            # Expect that we can grade an answer without
            # getting an exception
            try:
                problem.grade_answers({'1_2_1': '42'})

            except ResponseError:
                self.fail("Could not use name '{0}s' in custom response".format(module_name))


class SchematicResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import SchematicResponseXMLFactory
    xml_factory_class = SchematicResponseXMLFactory

    def test_grade(self):
        # Most of the schematic-specific work is handled elsewhere
        # (in client-side JavaScript)
        # The <schematicresponse> is responsible only for executing the
        # Python code in <answer> with *submission* (list)
        # in the global context.

        # To test that the context is set up correctly,
        # we create a script that sets *correct* to true
        # if and only if we find the *submission* (list)
        script = "correct = ['correct' if 'test' in submission[0] else 'incorrect']"
        problem = self.build_problem(answer=script)

        # The actual dictionary would contain schematic information
        # sent from the JavaScript simulation
        submission_dict = {'test': 'the_answer'}
        input_dict = {'1_2_1': json.dumps(submission_dict)}
        correct_map = problem.grade_answers(input_dict)

        # Expect that the problem is graded as true
        # (That is, our script verifies that the context
        # is what we expect)
        self.assertEqual(correct_map.get_correctness('1_2_1'), 'correct')

    def test_check_function_randomization(self):
        # The check function should get a random seed from the problem.
        script = "correct = ['correct' if (submission[0]['num'] == {code}) else 'incorrect']".format(code=self._get_random_number_code())
        problem = self.build_problem(answer=script)

        submission_dict = {'num': self._get_random_number_result(problem.seed)}
        input_dict = {'1_2_1': json.dumps(submission_dict)}
        correct_map = problem.grade_answers(input_dict)

        self.assertEqual(correct_map.get_correctness('1_2_1'), 'correct')

    def test_script_exception(self):
        # Construct a script that will raise an exception
        script = "raise Exception('test')"
        problem = self.build_problem(answer=script)

        # Expect that an exception gets raised when we check the answer
        with self.assertRaises(ResponseError):
            submission_dict = {'test': 'test'}
            input_dict = {'1_2_1': json.dumps(submission_dict)}
            problem.grade_answers(input_dict)


class AnnotationResponseTest(ResponseTest):
    from capa.tests.response_xml_factory import AnnotationResponseXMLFactory
    xml_factory_class = AnnotationResponseXMLFactory

    def test_grade(self):
        (correct, partially, incorrect) = ('correct', 'partially-correct', 'incorrect')

        answer_id = '1_2_1'
        options = (('x', correct), ('y', partially), ('z', incorrect))
        make_answer = lambda option_ids: {answer_id: json.dumps({'options': option_ids})}

        tests = [
            {'correctness': correct, 'points': 2, 'answers': make_answer([0])},
            {'correctness': partially, 'points': 1, 'answers': make_answer([1])},
            {'correctness': incorrect, 'points': 0, 'answers': make_answer([2])},
            {'correctness': incorrect, 'points': 0, 'answers': make_answer([0, 1, 2])},
            {'correctness': incorrect, 'points': 0, 'answers': make_answer([])},
            {'correctness': incorrect, 'points': 0, 'answers': make_answer('')},
            {'correctness': incorrect, 'points': 0, 'answers': make_answer(None)},
            {'correctness': incorrect, 'points': 0, 'answers': {answer_id: 'null'}},
        ]

        for test in tests:
            expected_correctness = test['correctness']
            expected_points = test['points']
            answers = test['answers']

            problem = self.build_problem(options=options)
            correct_map = problem.grade_answers(answers)
            actual_correctness = correct_map.get_correctness(answer_id)
            actual_points = correct_map.get_npoints(answer_id)

            self.assertEqual(expected_correctness, actual_correctness,
                             msg="%s should be marked %s" % (answer_id, expected_correctness))
            self.assertEqual(expected_points, actual_points,
                             msg="%s should have %d points" % (answer_id, expected_points))
