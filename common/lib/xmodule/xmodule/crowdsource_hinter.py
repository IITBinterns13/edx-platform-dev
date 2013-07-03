"""
Adds crowdsourced hinting functionality to lon-capa numerical response problems.

Currently experimental - not for instructor use, yet.
"""

import logging
import json
import random

from pkg_resources import resource_string

from lxml import etree

from xmodule.x_module import XModule
from xmodule.xml_module import XmlDescriptor
from xblock.core import Scope, String, Integer, Boolean, Dict, List

from django.utils.html import escape

log = logging.getLogger(__name__)


class CrowdsourceHinterFields(object):
    """Defines fields for the crowdsource hinter module."""
    has_children = True

    moderate = String(help='String "True"/"False" - activates moderation', scope=Scope.content,
                      default='False')
    debug = String(help='String "True"/"False" - allows multiple voting', scope=Scope.content,
                   default='False')
    # Usage: hints[answer] = {str(pk): [hint_text, #votes]}
    # hints is a dictionary that takes answer keys.
    # Each value is itself a dictionary, accepting hint_pk strings as keys,
    # and returning [hint text, #votes] pairs as values
    hints = Dict(help='A dictionary containing all the active hints.', scope=Scope.content, default={})
    mod_queue = Dict(help='A dictionary containing hints still awaiting approval', scope=Scope.content,
                     default={})
    hint_pk = Integer(help='Used to index hints.', scope=Scope.content, default=0)
    # A list of previous answers this student made to this problem.
    # Of the form [answer, [hint_pk_1, hint_pk_2, hint_pk_3]] for each problem.  hint_pk's are
    # None if the hint was not given.
    previous_answers = List(help='A list of previous submissions.', scope=Scope.user_state, default=[])
    user_voted = Boolean(help='Specifies if the user has voted on this problem or not.',
                         scope=Scope.user_state, default=False)


class CrowdsourceHinterModule(CrowdsourceHinterFields, XModule):
    """
    An Xmodule that makes crowdsourced hints.
    Currently, only works on capa problems with exactly one numerical response,
    and no other parts.

    Example usage:
    <crowdsource_hinter>
        <problem blah blah />
    </crowdsource_hinter>

    XML attributes:
    -moderate="True" will not display hints until staff approve them in the hint manager.
    -debug="True" will let users vote as often as they want.
    """
    icon_class = 'crowdsource_hinter'
    css = {'scss': [resource_string(__name__, 'css/crowdsource_hinter/display.scss')]}
    js = {'coffee': [resource_string(__name__, 'js/src/crowdsource_hinter/display.coffee')],
          'js': []}
    js_module_name = "Hinter"

    def __init__(self, *args, **kwargs):
        XModule.__init__(self, *args, **kwargs)

    def get_html(self):
        """
        Puts a wrapper around the problem html.  This wrapper includes ajax urls of the
        hinter and of the problem.
        - Dependent on lon-capa problem.
        """
        if self.debug == 'True':
            # Reset the user vote, for debugging only!
            self.user_voted = False
        if self.hints == {}:
            # Force self.hints to be written into the database.  (When an xmodule is initialized,
            # fields are not added to the db until explicitly changed at least once.)
            self.hints = {}

        try:
            child = self.get_display_items()[0]
            out = child.get_html()
            # The event listener uses the ajax url to find the child.
            child_url = child.system.ajax_url
        except IndexError:
            out = 'Error in loading crowdsourced hinter - can\'t find child problem.'
            child_url = ''

        # Wrap the module in a <section>.  This lets us pass data attributes to the javascript.
        out += '<section class="crowdsource-wrapper" data-url="' + self.system.ajax_url +\
            '" data-child-url = "' + child_url + '"> </section>'

        return out

    def capa_answer_to_str(self, answer):
        """
        Converts capa answer format to a string representation
        of the answer.
        -Lon-capa dependent.
        -Assumes that the problem only has one part.
        """
        return str(float(answer.values()[0]))

    def handle_ajax(self, dispatch, get):
        """
        This is the landing method for AJAX calls.
        """
        if dispatch == 'get_hint':
            out = self.get_hint(get)
        elif dispatch == 'get_feedback':
            out = self.get_feedback(get)
        elif dispatch == 'vote':
            out = self.tally_vote(get)
        elif dispatch == 'submit_hint':
            out = self.submit_hint(get)
        else:
            return json.dumps({'contents': 'Error - invalid operation.'})

        if out is None:
            out = {'op': 'empty'}
        else:
            out.update({'op': dispatch})
        return json.dumps({'contents': self.system.render_template('hinter_display.html', out)})

    def get_hint(self, get):
        """
        The student got the incorrect answer found in get.  Give him a hint.

        Called by hinter javascript after a problem is graded as incorrect.
        Args:
        `get` -- must be interpretable by capa_answer_to_str.
        Output keys:
            - 'best_hint' is the hint text with the most votes.
            - 'rand_hint_1' and 'rand_hint_2' are two random hints to the answer in `get`.
            - 'answer' is the parsed answer that was submitted.
        """
        answer = self.capa_answer_to_str(get)
        # Look for a hint to give.
        # Make a local copy of self.hints - this means we only need to do one json unpacking.
        # (This is because xblocks storage makes the following command a deep copy.)
        local_hints = self.hints
        if (answer not in local_hints) or (len(local_hints[answer]) == 0):
            # No hints to give.  Return.
            self.previous_answers += [[answer, [None, None, None]]]
            return
        # Get the top hint, plus two random hints.
        n_hints = len(local_hints[answer])
        best_hint_index = max(local_hints[answer], key=lambda key: local_hints[answer][key][1])
        best_hint = local_hints[answer][best_hint_index][0]
        if len(local_hints[answer]) == 1:
            rand_hint_1 = ''
            rand_hint_2 = ''
            self.previous_answers += [[answer, [best_hint_index, None, None]]]
        elif n_hints == 2:
            best_hint = local_hints[answer].values()[0][0]
            best_hint_index = local_hints[answer].keys()[0]
            rand_hint_1 = local_hints[answer].values()[1][0]
            hint_index_1 = local_hints[answer].keys()[1]
            rand_hint_2 = ''
            self.previous_answers += [[answer, [best_hint_index, hint_index_1, None]]]
        else:
            (hint_index_1, rand_hint_1), (hint_index_2, rand_hint_2) =\
                random.sample(local_hints[answer].items(), 2)
            rand_hint_1 = rand_hint_1[0]
            rand_hint_2 = rand_hint_2[0]
            self.previous_answers += [[answer, [best_hint_index, hint_index_1, hint_index_2]]]

        return {'best_hint': best_hint,
                'rand_hint_1': rand_hint_1,
                'rand_hint_2': rand_hint_2,
                'answer': answer}

    def get_feedback(self, get):
        """
        The student got it correct.  Ask him to vote on hints, or submit a hint.

        Args:
        `get` -- not actually used.  (It is assumed that the answer is correct.)
        Output keys:
            - 'index_to_hints' maps previous answer indices to hints that the user saw earlier.
            - 'index_to_answer' maps previous answer indices to the actual answer submitted.
        """
        # The student got it right.
        # Did he submit at least one wrong answer?
        if len(self.previous_answers) == 0:
            # No.  Nothing to do here.
            return
        # Make a hint-voting interface for each wrong answer.  The student will only
        # be allowed to make one vote / submission, but he can choose which wrong answer
        # he wants to look at.
        # index_to_hints[previous answer #] = [(hint text, hint pk), + ]
        index_to_hints = {}
        # index_to_answer[previous answer #] = answer text
        index_to_answer = {}

        # Go through each previous answer, and populate index_to_hints and index_to_answer.
        for i in xrange(len(self.previous_answers)):
            answer, hints_offered = self.previous_answers[i]
            index_to_hints[i] = []
            index_to_answer[i] = answer
            if answer in self.hints:
                # Go through each hint, and add to index_to_hints
                for hint_id in hints_offered:
                    if hint_id is not None:
                        try:
                            index_to_hints[i].append((self.hints[answer][str(hint_id)][0], hint_id))
                        except KeyError:
                            # Sometimes, the hint that a user saw will have been deleted by the instructor.
                            continue

        return {'index_to_hints': index_to_hints, 'index_to_answer': index_to_answer}

    def tally_vote(self, get):
        """
        Tally a user's vote on his favorite hint.

        Args:
        `get` -- expected to have the following keys:
            'answer': ans_no (index in previous_answers)
            'hint': hint_pk
        Returns key 'hint_and_votes', a list of (hint_text, #votes) pairs.
        """
        if self.user_voted:
            return json.dumps({'contents': 'Sorry, but you have already voted!'})
        ans_no = int(get['answer'])
        hint_no = str(get['hint'])
        answer = self.previous_answers[ans_no][0]
        # We use temp_dict because we need to do a direct write for the database to update.
        temp_dict = self.hints
        temp_dict[answer][hint_no][1] += 1
        self.hints = temp_dict
        # Don't let the user vote again!
        self.user_voted = True

        # Return a list of how many votes each hint got.
        hint_and_votes = []
        for hint_no in self.previous_answers[ans_no][1]:
            if hint_no is None:
                continue
            hint_and_votes.append(temp_dict[answer][str(hint_no)])

        # Reset self.previous_answers.
        self.previous_answers = []
        return {'hint_and_votes': hint_and_votes}

    def submit_hint(self, get):
        """
        Take a hint submission and add it to the database.

        Args:
        `get` -- expected to have the following keys:
            'answer': answer index in previous_answers
            'hint': text of the new hint that the user is adding
        Returns a thank-you message.
        """
        # Do html escaping.  Perhaps in the future do profanity filtering, etc. as well.
        hint = escape(get['hint'])
        answer = self.previous_answers[int(get['answer'])][0]
        # Only allow a student to vote or submit a hint once.
        if self.user_voted:
            return {'message': 'Sorry, but you have already voted!'}
        # Add the new hint to self.hints or self.mod_queue.  (Awkward because a direct write
        # is necessary.)
        if self.moderate == 'True':
            temp_dict = self.mod_queue
        else:
            temp_dict = self.hints
        if answer in temp_dict:
            temp_dict[answer][self.hint_pk] = [hint, 1]     # With one vote (the user himself).
        else:
            temp_dict[answer] = {self.hint_pk: [hint, 1]}
        self.hint_pk += 1
        if self.moderate == 'True':
            self.mod_queue = temp_dict
        else:
            self.hints = temp_dict
        # Mark the user has having voted; reset previous_answers
        self.user_voted = True
        self.previous_answers = []
        return {'message': 'Thank you for your hint!'}


class CrowdsourceHinterDescriptor(CrowdsourceHinterFields, XmlDescriptor):
    module_class = CrowdsourceHinterModule
    stores_state = True

    @classmethod
    def definition_from_xml(cls, xml_object, system):
        children = []
        for child in xml_object:
            try:
                children.append(system.process_xml(etree.tostring(child, encoding='unicode')).location.url())
            except Exception as e:
                log.exception("Unable to load child when parsing CrowdsourceHinter. Continuing...")
                if system.error_tracker is not None:
                    system.error_tracker("ERROR: " + str(e))
                continue
        return {}, children

    def definition_to_xml(self, resource_fs):
        xml_object = etree.Element('crowdsource_hinter')
        for child in self.get_children():
            xml_object.append(
                etree.fromstring(child.export_to_xml(resource_fs)))
        return xml_object
