import logging
from cStringIO import StringIO
from math import exp
from lxml import etree
from path import path  # NOTE (THK): Only used for detecting presence of syllabus
import requests
from datetime import datetime

import dateutil.parser

from xmodule.modulestore import Location
from xmodule.seq_module import SequenceDescriptor, SequenceModule
from xmodule.util.decorators import lazyproperty
from xmodule.graders import grader_from_conf
import json

from xblock.core import Scope, List, String, Dict, Boolean
from .fields import Date
from django.utils.timezone import UTC
from xmodule.util import date_utils


log = logging.getLogger(__name__)


class StringOrDate(Date):
    def from_json(self, value):
        """
        Parse an optional metadata key containing a time or a string:
        if present, assume it's a string if it doesn't parse.
        """
        try:
            result = super(StringOrDate, self).from_json(value)
        except ValueError:
            return value
        if result is None:
            return value
        else:
            return result

    def to_json(self, value):
        """
        Convert a time struct or string to a string.
        """
        try:
            result = super(StringOrDate, self).to_json(value)
        except:
            return value
        if result is None:
            return value
        else:
            return result


edx_xml_parser = etree.XMLParser(dtd_validation=False, load_dtd=False,
                                 remove_comments=True, remove_blank_text=True)

_cached_toc = {}


class Textbook(object):
    def __init__(self, title, book_url):
        self.title = title
        self.book_url = book_url
        self.start_page = int(self.table_of_contents[0].attrib['page'])

        # The last page should be the last element in the table of contents,
        # but it may be nested. So recurse all the way down the last element
        last_el = self.table_of_contents[-1]
        while last_el.getchildren():
            last_el = last_el[-1]

        self.end_page = int(last_el.attrib['page'])

    @lazyproperty
    def table_of_contents(self):
        """
        Accesses the textbook's table of contents (default name "toc.xml") at the URL self.book_url

        Returns XML tree representation of the table of contents
        """
        toc_url = self.book_url + 'toc.xml'

        # cdodge: I've added this caching of TOC because in Mongo-backed instances (but not Filesystem stores)
        # course modules have a very short lifespan and are constantly being created and torn down.
        # Since this module in the __init__() method does a synchronous call to AWS to get the TOC
        # this is causing a big performance problem. So let's be a bit smarter about this and cache
        # each fetch and store in-mem for 10 minutes.
        # NOTE: I have to get this onto sandbox ASAP as we're having runtime failures. I'd like to swing back and
        # rewrite to use the traditional Django in-memory cache.
        try:
            # see if we already fetched this
            if toc_url in _cached_toc:
                (table_of_contents, timestamp) = _cached_toc[toc_url]
                age = datetime.now(UTC) - timestamp
                # expire every 10 minutes
                if age.seconds < 600:
                    return table_of_contents
        except Exception as err:
            pass

        # Get the table of contents from S3
        log.info("Retrieving textbook table of contents from %s" % toc_url)
        try:
            r = requests.get(toc_url)
        except Exception as err:
            msg = 'Error %s: Unable to retrieve textbook table of contents at %s' % (err, toc_url)
            log.error(msg)
            raise Exception(msg)

        # TOC is XML. Parse it
        try:
            table_of_contents = etree.fromstring(r.text)
        except Exception as err:
            msg = 'Error %s: Unable to parse XML for textbook table of contents at %s' % (err, toc_url)
            log.error(msg)
            raise Exception(msg)

        return table_of_contents


class TextbookList(List):
    def from_json(self, values):
        textbooks = []
        for title, book_url in values:
            try:
                textbooks.append(Textbook(title, book_url))
            except:
                # If we can't get to S3 (e.g. on a train with no internet), don't break
                # the rest of the courseware.
                log.exception("Couldn't load textbook ({0}, {1})".format(title, book_url))
                continue

        return textbooks

    def to_json(self, values):
        json_data = []
        for val in values:
            if isinstance(val, Textbook):
                json_data.append((val.title, val.book_url))
            elif isinstance(val, tuple):
                json_data.append(val)
            else:
                continue
        return json_data


class CourseFields(object):
    textbooks = TextbookList(help="List of pairs of (title, url) for textbooks used in this course", scope=Scope.content)
    wiki_slug = String(help="Slug that points to the wiki for this course", scope=Scope.content)
    enrollment_start = Date(help="Date that enrollment for this class is opened", scope=Scope.settings)
    enrollment_end = Date(help="Date that enrollment for this class is closed", scope=Scope.settings)
    start = Date(help="Start time when this module is visible", scope=Scope.settings)
    end = Date(help="Date that this class ends", scope=Scope.settings)
    advertised_start = String(help="Date that this course is advertised to start", scope=Scope.settings)
    grading_policy = Dict(help="Grading policy definition for this class", scope=Scope.content)
    show_calculator = Boolean(help="Whether to show the calculator in this course", default=False, scope=Scope.settings)
    display_name = String(help="Display name for this module", scope=Scope.settings)
    tabs = List(help="List of tabs to enable in this course", scope=Scope.settings)
    end_of_course_survey_url = String(help="Url for the end-of-course survey", scope=Scope.settings)
    discussion_blackouts = List(help="List of pairs of start/end dates for discussion blackouts", scope=Scope.settings)
    discussion_topics = Dict(
        help="Map of topics names to ids",
        scope=Scope.settings
        )
    testcenter_info = Dict(help="Dictionary of Test Center info", scope=Scope.settings)
    announcement = Date(help="Date this course is announced", scope=Scope.settings)
    cohort_config = Dict(help="Dictionary defining cohort configuration", scope=Scope.settings)
    is_new = Boolean(help="Whether this course should be flagged as new", scope=Scope.settings)
    no_grade = Boolean(help="True if this course isn't graded", default=False, scope=Scope.settings)
    disable_progress_graph = Boolean(help="True if this course shouldn't display the progress graph", default=False, scope=Scope.settings)
    pdf_textbooks = List(help="List of dictionaries containing pdf_textbook configuration", scope=Scope.settings)
    html_textbooks = List(help="List of dictionaries containing html_textbook configuration", scope=Scope.settings)
    remote_gradebook = Dict(scope=Scope.settings)
    allow_anonymous = Boolean(scope=Scope.settings, default=True)
    allow_anonymous_to_peers = Boolean(scope=Scope.settings, default=False)
    advanced_modules = List(help="Beta modules used in your course", scope=Scope.settings)
    has_children = True
    checklists = List(scope=Scope.settings)
    info_sidebar_name = String(scope=Scope.settings, default='Course Handouts')
    show_timezone = Boolean(help="True if timezones should be shown on dates in the courseware", scope=Scope.settings, default=True)
    enrollment_domain = String(help="External login method associated with user accounts allowed to register in course",
                        scope=Scope.settings)

    # An extra property is used rather than the wiki_slug/number because
    # there are courses that change the number for different runs. This allows
    # courses to share the same css_class across runs even if they have
    # different numbers.
    #
    # TODO get rid of this as soon as possible or potentially build in a robust
    # way to add in course-specific styling. There needs to be a discussion
    # about the right way to do this, but arjun will address this ASAP. Also
    # note that the courseware template needs to change when this is removed.
    css_class = String(help="DO NOT USE THIS", scope=Scope.settings)

    # TODO: This is a quick kludge to allow CS50 (and other courses) to
    # specify their own discussion forums as external links by specifying a
    # "discussion_link" in their policy JSON file. This should later get
    # folded in with Syllabus, Course Info, and additional Custom tabs in a
    # more sensible framework later.
    discussion_link = String(help="DO NOT USE THIS", scope=Scope.settings)

    # TODO: same as above, intended to let internal CS50 hide the progress tab
    # until we get grade integration set up.
    # Explicit comparison to True because we always want to return a bool.
    hide_progress_tab = Boolean(help="DO NOT USE THIS", scope=Scope.settings)


class CourseDescriptor(CourseFields, SequenceDescriptor):
    module_class = SequenceModule

    template_dir_name = 'course'

    def __init__(self, *args, **kwargs):
        """
        Expects the same arguments as XModuleDescriptor.__init__
        """
        super(CourseDescriptor, self).__init__(*args, **kwargs)

        if self.wiki_slug is None:
            self.wiki_slug = self.location.course

        msg = None
        if self.start is None:
            msg = "Course loaded without a valid start date. id = %s" % self.id
            self.start = datetime.now(UTC())
            log.critical(msg)
            self.system.error_tracker(msg)

        # NOTE: relies on the modulestore to call set_grading_policy() right after
        # init.  (Modulestore is in charge of figuring out where to load the policy from)

        # NOTE (THK): This is a last-minute addition for Fall 2012 launch to dynamically
        #   disable the syllabus content for courses that do not provide a syllabus
        self.syllabus_present = self.system.resources_fs.exists(path('syllabus'))
        self._grading_policy = {}

        self.set_grading_policy(self.grading_policy)
        if self.discussion_topics == {}:
            self.discussion_topics = {'General': {'id': self.location.html_id()}}

        self.test_center_exams = []
        test_center_info = self.testcenter_info
        if test_center_info is not None:
            for exam_name in test_center_info:
                try:
                    exam_info = test_center_info[exam_name]
                    self.test_center_exams.append(self.TestCenterExam(self.id, exam_name, exam_info))
                except Exception as err:
                    # If we can't parse the test center exam info, don't break
                    # the rest of the courseware.
                    msg = 'Error %s: Unable to load test-center exam info for exam "%s" of course "%s"' % (err, exam_name, self.id)
                    log.error(msg)
                    continue

    def default_grading_policy(self):
        """
        Return a dict which is a copy of the default grading policy
        """
        return {"GRADER": [
                {
                    "type": "Homework",
                    "min_count": 12,
                    "drop_count": 2,
                    "short_label": "HW",
                    "weight": 0.15
                },
                {
                    "type": "Lab",
                    "min_count": 12,
                    "drop_count": 2,
                    "weight": 0.15
                },
                {
                    "type": "Midterm Exam",
                    "short_label": "Midterm",
                    "min_count": 1,
                    "drop_count": 0,
                    "weight": 0.3
                },
                {
                    "type": "Final Exam",
                    "short_label": "Final",
                    "min_count": 1,
                    "drop_count": 0,
                    "weight": 0.4
                }
            ],
            "GRADE_CUTOFFS": {
                "Pass": 0.5
            }}

    def set_grading_policy(self, course_policy):
        """
        The JSON object can have the keys GRADER and GRADE_CUTOFFS. If either is
        missing, it reverts to the default.
        """
        if course_policy is None:
            course_policy = {}

        # Load the global settings as a dictionary
        grading_policy = self.default_grading_policy()

        # Override any global settings with the course settings
        grading_policy.update(course_policy)

        # Here is where we should parse any configurations, so that we can fail early
        # Use setters so that side effecting to .definitions works
        self.raw_grader = grading_policy['GRADER']  # used for cms access
        self.grade_cutoffs = grading_policy['GRADE_CUTOFFS']

    @classmethod
    def read_grading_policy(cls, paths, system):
        """Load a grading policy from the specified paths, in order, if it exists."""
        # Default to a blank policy dict
        policy_str = '{}'

        for policy_path in paths:
            if not system.resources_fs.exists(policy_path):
                continue
            log.debug("Loading grading policy from {0}".format(policy_path))
            try:
                with system.resources_fs.open(policy_path) as grading_policy_file:
                    policy_str = grading_policy_file.read()
                    # if we successfully read the file, stop looking at backups
                    break
            except (IOError):
                msg = "Unable to load course settings file from '{0}'".format(policy_path)
                log.warning(msg)

        return policy_str

    @classmethod
    def from_xml(cls, xml_data, system, org=None, course=None):
        instance = super(CourseDescriptor, cls).from_xml(xml_data, system, org, course)

        # bleh, have to parse the XML here to just pull out the url_name attribute
        # I don't think it's stored anywhere in the instance.
        course_file = StringIO(xml_data.encode('ascii', 'ignore'))
        xml_obj = etree.parse(course_file, parser=edx_xml_parser).getroot()

        policy_dir = None
        url_name = xml_obj.get('url_name', xml_obj.get('slug'))
        if url_name:
            policy_dir = 'policies/' + url_name

        # Try to load grading policy
        paths = ['grading_policy.json']
        if policy_dir:
            paths = [policy_dir + '/grading_policy.json'] + paths

        try:
            policy = json.loads(cls.read_grading_policy(paths, system))
        except ValueError:
            system.error_tracker("Unable to decode grading policy as json")
            policy = {}

        # cdodge: import the grading policy information that is on disk and put into the
        # descriptor 'definition' bucket as a dictionary so that it is persisted in the DB
        instance.grading_policy = policy

        # now set the current instance. set_grading_policy() will apply some inheritance rules
        instance.set_grading_policy(policy)

        return instance

    @classmethod
    def definition_from_xml(cls, xml_object, system):
        textbooks = []
        for textbook in xml_object.findall("textbook"):
            textbooks.append((textbook.get('title'), textbook.get('book_url')))
            xml_object.remove(textbook)

        # Load the wiki tag if it exists
        wiki_slug = None
        wiki_tag = xml_object.find("wiki")
        if wiki_tag is not None:
            wiki_slug = wiki_tag.attrib.get("slug", default=None)
            xml_object.remove(wiki_tag)

        definition, children = super(CourseDescriptor, cls).definition_from_xml(xml_object, system)

        definition['textbooks'] = textbooks
        definition['wiki_slug'] = wiki_slug

        return definition, children

    def definition_to_xml(self, resource_fs):
        xml_object = super(CourseDescriptor, self).definition_to_xml(resource_fs)

        if len(self.textbooks) > 0:
            textbook_xml_object = etree.Element('textbook')
            for textbook in self.textbooks:
                textbook_xml_object.set('title', textbook.title)
                textbook_xml_object.set('book_url', textbook.book_url)

            xml_object.append(textbook_xml_object)

        return xml_object

    def has_ended(self):
        """
        Returns True if the current time is after the specified course end date.
        Returns False if there is no end date specified.
        """
        if self.end is None:
            return False

        return datetime.now(UTC()) > self.end

    def has_started(self):
        return datetime.now(UTC()) > self.start

    @property
    def grader(self):
        return grader_from_conf(self.raw_grader)

    @property
    def raw_grader(self):
        return self._grading_policy['RAW_GRADER']

    @raw_grader.setter
    def raw_grader(self, value):
        # NOTE WELL: this change will not update the processed graders. If we need that, this needs to call grader_from_conf
        self._grading_policy['RAW_GRADER'] = value
        self.grading_policy['GRADER'] = value

    @property
    def grade_cutoffs(self):
        return self._grading_policy['GRADE_CUTOFFS']

    @grade_cutoffs.setter
    def grade_cutoffs(self, value):
        self._grading_policy['GRADE_CUTOFFS'] = value

        # XBlock fields don't update after mutation
        policy = self.grading_policy
        policy['GRADE_CUTOFFS'] = value
        self.grading_policy = policy

    @property
    def lowest_passing_grade(self):
        return min(self._grading_policy['GRADE_CUTOFFS'].values())

    @property
    def is_cohorted(self):
        """
        Return whether the course is cohorted.
        """
        config = self.cohort_config
        if config is None:
            return False

        return bool(config.get("cohorted"))

    @property
    def auto_cohort(self):
        """
        Return whether the course is auto-cohorted.
        """
        if not self.is_cohorted:
            return False

        return bool(self.cohort_config.get(
            "auto_cohort", False))

    @property
    def auto_cohort_groups(self):
        """
        Return the list of groups to put students into.  Returns [] if not
        specified. Returns specified list even if is_cohorted and/or auto_cohort are
        false.
        """
        if self.cohort_config is None:
            return []
        else:
            return self.cohort_config.get("auto_cohort_groups", [])

    @property
    def top_level_discussion_topic_ids(self):
        """
        Return list of topic ids defined in course policy.
        """
        topics = self.discussion_topics
        return [d["id"] for d in topics.values()]

    @property
    def cohorted_discussions(self):
        """
        Return the set of discussions that is explicitly cohorted.  It may be
        the empty set.  Note that all inline discussions are automatically
        cohorted based on the course's is_cohorted setting.
        """
        config = self.cohort_config
        if config is None:
            return set()

        return set(config.get("cohorted_discussions", []))

    @property
    def is_newish(self):
        """
        Returns if the course has been flagged as new. If
        there is no flag, return a heuristic value considering the
        announcement and the start dates.
        """
        flag = self.is_new
        if flag is None:
            # Use a heuristic if the course has not been flagged
            announcement, start, now = self._sorting_dates()
            if announcement and (now - announcement).days < 30:
                # The course has been announced for less that month
                return True
            elif (now - start).days < 1:
                # The course has not started yet
                return True
            else:
                return False
        elif isinstance(flag, basestring):
            return flag.lower() in ['true', 'yes', 'y']
        else:
            return bool(flag)

    @property
    def sorting_score(self):
        """
        Returns a tuple that can be used to sort the courses according
        the how "new" they are. The "newness" score is computed using a
        heuristic that takes into account the announcement and
        (advertized) start dates of the course if available.

        The lower the number the "newer" the course.
        """
        # Make courses that have an announcement date shave a lower
        # score than courses than don't, older courses should have a
        # higher score.
        announcement, start, now = self._sorting_dates()
        scale = 300.0  # about a year
        if announcement:
            days = (now - announcement).days
            score = -exp(-days / scale)
        else:
            days = (now - start).days
            score = exp(days / scale)
        return score

    def _sorting_dates(self):
        # utility function to get datetime objects for dates used to
        # compute the is_new flag and the sorting_score

        announcement = self.announcement
        if announcement is not None:
            announcement = announcement

        try:
            start = dateutil.parser.parse(self.advertised_start)
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC())
        except (ValueError, AttributeError):
            start = self.start

        now = datetime.now(UTC())

        return announcement, start, now

    @lazyproperty
    def grading_context(self):
        """
        This returns a dictionary with keys necessary for quickly grading
        a student. They are used by grades.grade()

        The grading context has two keys:
        graded_sections - This contains the sections that are graded, as
            well as all possible children modules that can affect the
            grading. This allows some sections to be skipped if the student
            hasn't seen any part of it.

            The format is a dictionary keyed by section-type. The values are
            arrays of dictionaries containing
                "section_descriptor" : The section descriptor
                "xmoduledescriptors" : An array of xmoduledescriptors that
                    could possibly be in the section, for any student

        all_descriptors - This contains a list of all xmodules that can
            effect grading a student. This is used to efficiently fetch
            all the xmodule state for a ModelDataCache without walking
            the descriptor tree again.


        """

        all_descriptors = []
        graded_sections = {}

        def yield_descriptor_descendents(module_descriptor):
            for child in module_descriptor.get_children():
                yield child
                for module_descriptor in yield_descriptor_descendents(child):
                    yield module_descriptor

        for c in self.get_children():
            for s in c.get_children():
                if s.lms.graded:
                    xmoduledescriptors = list(yield_descriptor_descendents(s))
                    xmoduledescriptors.append(s)

                    # The xmoduledescriptors included here are only the ones that have scores.
                    section_description = {'section_descriptor': s, 'xmoduledescriptors': filter(lambda child: child.has_score, xmoduledescriptors)}

                    section_format = s.lms.format if s.lms.format is not None else ''
                    graded_sections[section_format] = graded_sections.get(section_format, []) + [section_description]

                    all_descriptors.extend(xmoduledescriptors)
                    all_descriptors.append(s)

        return {'graded_sections': graded_sections,
                'all_descriptors': all_descriptors, }

    @staticmethod
    def make_id(org, course, url_name):
        return '/'.join([org, course, url_name])

    @staticmethod
    def id_to_location(course_id):
        '''Convert the given course_id (org/course/name) to a location object.
        Throws ValueError if course_id is of the wrong format.
        '''
        org, course, name = course_id.split('/')
        return Location('i4x', org, course, 'course', name)

    @staticmethod
    def location_to_id(location):
        '''Convert a location of a course to a course_id.  If location category
        is not "course", raise a ValueError.

        location: something that can be passed to Location
        '''
        loc = Location(location)
        if loc.category != "course":
            raise ValueError("{0} is not a course location".format(loc))
        return "/".join([loc.org, loc.course, loc.name])

    @property
    def id(self):
        """Return the course_id for this course"""
        return self.location_to_id(self.location)

    @property
    def start_date_text(self):
        def try_parse_iso_8601(text):
            try:
                result = Date().from_json(text)
                if result is None:
                    result = text.title()
                else:
                    result = result.strftime("%b %d, %Y")
            except ValueError:
                result = text.title()

            return result

        if isinstance(self.advertised_start, basestring):
            return try_parse_iso_8601(self.advertised_start)
        elif self.advertised_start is None and self.start is None:
            return 'TBD'
        else:
            return (self.advertised_start or self.start).strftime("%b %d, %Y")

    @property
    def end_date_text(self):
        """
        Returns the end date for the course formatted as a string.

        If the course does not have an end date set (course.end is None), an empty string will be returned.
        """
        return '' if self.end is None else self.end.strftime("%b %d, %Y")

    @property
    def forum_posts_allowed(self):
        date_proxy = Date()
        try:
            blackout_periods = [(date_proxy.from_json(start),
                                 date_proxy.from_json(end))
                                for start, end
                                in self.discussion_blackouts]
            now = datetime.now(UTC())
            for start, end in blackout_periods:
                if start <= now <= end:
                    return False
        except:
            log.exception("Error parsing discussion_blackouts for course {0}".format(self.id))

        return True

    class TestCenterExam(object):
        def __init__(self, course_id, exam_name, exam_info):
            self.course_id = course_id
            self.exam_name = exam_name
            self.exam_info = exam_info
            self.exam_series_code = exam_info.get('Exam_Series_Code') or exam_name
            self.display_name = exam_info.get('Exam_Display_Name') or self.exam_series_code
            self.first_eligible_appointment_date = self._try_parse_time('First_Eligible_Appointment_Date')
            if self.first_eligible_appointment_date is None:
                raise ValueError("First appointment date must be specified")
            # TODO: If defaulting the last appointment date, it should be the
            # *end* of the same day, not the same time.  It's going to be used as the
            # end of the exam overall, so we don't want the exam to disappear too soon.
            # It's also used optionally as the registration end date, so time matters there too.
            self.last_eligible_appointment_date = self._try_parse_time('Last_Eligible_Appointment_Date')  # or self.first_eligible_appointment_date
            if self.last_eligible_appointment_date is None:
                raise ValueError("Last appointment date must be specified")
            self.registration_start_date = (self._try_parse_time('Registration_Start_Date') or
                datetime.fromtimestamp(0, UTC()))
            self.registration_end_date = self._try_parse_time('Registration_End_Date') or self.last_eligible_appointment_date
            # do validation within the exam info:
            if self.registration_start_date > self.registration_end_date:
                raise ValueError("Registration start date must be before registration end date")
            if self.first_eligible_appointment_date > self.last_eligible_appointment_date:
                raise ValueError("First appointment date must be before last appointment date")
            if self.registration_end_date > self.last_eligible_appointment_date:
                raise ValueError("Registration end date must be before last appointment date")
            self.exam_url = exam_info.get('Exam_URL')

        def _try_parse_time(self, key):
            """
            Parse an optional metadata key containing a time: if present, complain
            if it doesn't parse.
            Return None if not present or invalid.
            """
            if key in self.exam_info:
                try:
                    return Date().from_json(self.exam_info[key])
                except ValueError as e:
                    msg = "Exam {0} in course {1} loaded with a bad exam_info key '{2}': '{3}'".format(self.exam_name, self.course_id, self.exam_info[key], e)
                    log.warning(msg)
                return None

        def has_started(self):
            return datetime.now(UTC()) > self.first_eligible_appointment_date

        def has_ended(self):
            return datetime.now(UTC()) > self.last_eligible_appointment_date

        def has_started_registration(self):
            return datetime.now(UTC()) > self.registration_start_date

        def has_ended_registration(self):
            return datetime.now(UTC()) > self.registration_end_date

        def is_registering(self):
            now = datetime.now(UTC())
            return now >= self.registration_start_date and now <= self.registration_end_date

        @property
        def first_eligible_appointment_date_text(self):
            return self.first_eligible_appointment_date.strftime("%b %d, %Y")

        @property
        def last_eligible_appointment_date_text(self):
            return self.last_eligible_appointment_date.strftime("%b %d, %Y")

        @property
        def registration_end_date_text(self):
            return date_utils.get_default_time_display(self.registration_end_date)

    @property
    def current_test_center_exam(self):
        exams = [exam for exam in self.test_center_exams if exam.has_started_registration() and not exam.has_ended()]
        if len(exams) > 1:
            # TODO: output some kind of warning.  This should already be
            # caught if we decide to do validation at load time.
            return exams[0]
        elif len(exams) == 1:
            return exams[0]
        else:
            return None

    def get_test_center_exam(self, exam_series_code):
        exams = [exam for exam in self.test_center_exams if exam.exam_series_code == exam_series_code]
        return exams[0] if len(exams) == 1 else None

    @property
    def number(self):
        return self.location.course

    @property
    def org(self):
        return self.location.org
