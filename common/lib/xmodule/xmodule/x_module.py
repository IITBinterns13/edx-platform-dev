import logging
import copy
import yaml
import os

from lxml import etree
from collections import namedtuple
from pkg_resources import resource_listdir, resource_string, resource_isdir

from xmodule.modulestore import Location
from xmodule.modulestore.exceptions import ItemNotFoundError

from xblock.core import XBlock, Scope, String, Integer, Float, ModelType

log = logging.getLogger(__name__)


def dummy_track(_event_type, _event):
    pass


class LocationField(ModelType):
    """
    XBlock field for storing Location values
    """
    def from_json(self, value):
        """
        Parse the json value as a Location
        """
        return Location(value)

    def to_json(self, value):
        """
        Store the Location as a url string in json
        """
        return value.url()


class HTMLSnippet(object):
    """
    A base class defining an interface for an object that is able to present an
    html snippet, along with associated javascript and css
    """

    js = {}
    js_module_name = None

    css = {}

    @classmethod
    def get_javascript(cls):
        """
        Return a dictionary containing some of the following keys:

            coffee: A list of coffeescript fragments that should be compiled and
                    placed on the page

            js: A list of javascript fragments that should be included on the
            page

        All of these will be loaded onto the page in the CMS
        """
        # cdodge: We've moved the xmodule.coffee script from an outside directory into the xmodule area of common
        # this means we need to make sure that all xmodules include this dependency which had been previously implicitly
        # fulfilled in a different area of code
        coffee = cls.js.setdefault('coffee', [])
        fragment = resource_string(__name__, 'js/src/xmodule.coffee')

        if fragment not in coffee:
            coffee.insert(0, fragment)

        return cls.js

    @classmethod
    def get_css(cls):
        """
        Return a dictionary containing some of the following keys:

            css: A list of css fragments that should be applied to the html
                 contents of the snippet

            sass: A list of sass fragments that should be applied to the html
                  contents of the snippet

            scss: A list of scss fragments that should be applied to the html
                  contents of the snippet
        """
        return cls.css

    def get_html(self):
        """
        Return the html used to display this snippet
        """
        raise NotImplementedError(
            "get_html() must be provided by specific modules - not present in {0}"
            .format(self.__class__))


class XModuleFields(object):
    display_name = String(
        display_name="Display Name",
        help="This name appears in the horizontal navigation at the top of the page.",
        scope=Scope.settings,
        default=None
    )

    # Please note that in order to be compatible with XBlocks more generally,
    # the LMS and CMS shouldn't be using this field. It's only for internal
    # consumption by the XModules themselves
    location = LocationField(
        display_name="Location",
        help="This is the location id for the XModule.",
        scope=Scope.content,
        default=Location(None),
    )


class XModule(XModuleFields, HTMLSnippet, XBlock):
    ''' Implements a generic learning module.

        Subclasses must at a minimum provide a definition for get_html in order
        to be displayed to users.

        See the HTML module for a simple example.
    '''

    # The default implementation of get_icon_class returns the icon_class
    # attribute of the class
    #
    # This attribute can be overridden by subclasses, and
    # the function can also be overridden if the icon class depends on the data
    # in the module
    icon_class = 'other'


    def __init__(self, runtime, descriptor, model_data):
        '''
        Construct a new xmodule

        runtime: An XBlock runtime allowing access to external resources

        descriptor: the XModuleDescriptor that this module is an instance of.

        model_data: A dictionary-like object that maps field names to values
            for those fields.
        '''
        super(XModule, self).__init__(runtime, model_data)
        self._model_data = model_data
        self.system = runtime
        self.descriptor = descriptor
        self.url_name = self.location.name
        self.category = self.location.category
        self._loaded_children = None

    @property
    def id(self):
        return self.location.url()

    @property
    def display_name_with_default(self):
        '''
        Return a display name for the module: use display_name if defined in
        metadata, otherwise convert the url name.
        '''
        name = self.display_name
        if name is None:
            name = self.url_name.replace('_', ' ')
        return name

    def get_children(self):
        '''
        Return module instances for all the children of this module.
        '''
        if self._loaded_children is None:
            child_descriptors = self.get_child_descriptors()
            children = [self.system.get_module(descriptor) for descriptor in child_descriptors]
            # get_module returns None if the current user doesn't have access
            # to the location.
            self._loaded_children = [c for c in children if c is not None]

        return self._loaded_children

    def __unicode__(self):
        return '<x_module(id={0})>'.format(self.id)

    def get_child_descriptors(self):
        '''
        Returns the descriptors of the child modules

        Overriding this changes the behavior of get_children and
        anything that uses get_children, such as get_display_items.

        This method will not instantiate the modules of the children
        unless absolutely necessary, so it is cheaper to call than get_children

        These children will be the same children returned by the
        descriptor unless descriptor.has_dynamic_children() is true.
        '''
        return self.descriptor.get_children()

    def get_child_by(self, selector):
        """
        Return a child XModuleDescriptor with the specified url_name, if it exists, and None otherwise.
        """
        for child in self.get_children():
            if selector(child):
                return child
        return None

    def get_display_items(self):
        '''
        Returns a list of descendent module instances that will display
        immediately inside this module.
        '''
        items = []
        for child in self.get_children():
            items.extend(child.displayable_items())

        return items

    def displayable_items(self):
        '''
        Returns list of displayable modules contained by this module. If this
        module is visible, should return [self].
        '''
        return [self]

    def get_icon_class(self):
        '''
        Return a css class identifying this module in the context of an icon
        '''
        return self.icon_class

    # Functions used in the LMS

    def get_score(self):
        """
        Score the student received on the problem, or None if there is no
        score.

        Returns:
          dictionary
             {'score': integer, from 0 to get_max_score(),
              'total': get_max_score()}

          NOTE (vshnayder): not sure if this was the intended return value, but
          that's what it's doing now.  I suspect that we really want it to just
          return a number.  Would need to change (at least) capa and
          modx_dispatch to match if we did that.
        """
        return None

    def max_score(self):
        ''' Maximum score. Two notes:

            * This is generic; in abstract, a problem could be 3/5 points on one
              randomization, and 5/7 on another

            * In practice, this is a Very Bad Idea, and (a) will break some code
              in place (although that code should get fixed), and (b) break some
              analytics we plan to put in place.
        '''
        return None

    def get_progress(self):
        ''' Return a progress.Progress object that represents how far the
        student has gone in this module.  Must be implemented to get correct
        progress tracking behavior in nesting modules like sequence and
        vertical.

        If this module has no notion of progress, return None.
        '''
        return None

    def handle_ajax(self, _dispatch, _get):
        ''' dispatch is last part of the URL.
            get is a dictionary-like object '''
        return ""


def policy_key(location):
    """
    Get the key for a location in a policy file.  (Since the policy file is
    specific to a course, it doesn't need the full location url).
    """
    return '{cat}/{name}'.format(cat=location.category, name=location.name)


Template = namedtuple("Template", "metadata data children")


class ResourceTemplates(object):
    @classmethod
    def templates(cls):
        """
        Returns a list of Template objects that describe possible templates that can be used
        to create a module of this type.
        If no templates are provided, there will be no way to create a module of
        this type

        Expects a class attribute template_dir_name that defines the directory
        inside the 'templates' resource directory to pull templates from
        """
        templates = []
        dirname = os.path.join('templates', cls.template_dir_name)
        if not resource_isdir(__name__, dirname):
            log.warning("No resource directory {dir} found when loading {cls_name} templates".format(
                dir=dirname,
                cls_name=cls.__name__,
            ))
            return []

        for template_file in resource_listdir(__name__, dirname):
            if not template_file.endswith('.yaml'):
                log.warning("Skipping unknown template file %s" % template_file)
                continue
            template_content = resource_string(__name__, os.path.join(dirname, template_file))
            template = yaml.safe_load(template_content)
            templates.append(Template(**template))

        return templates


class XModuleDescriptor(XModuleFields, HTMLSnippet, ResourceTemplates, XBlock):
    """
    An XModuleDescriptor is a specification for an element of a course. This
    could be a problem, an organizational element (a group of content), or a
    segment of video, for example.

    XModuleDescriptors are independent and agnostic to the current student state
    on a problem. They handle the editing interface used by instructors to
    create a problem, and can generate XModules (which do know about student
    state).
    """
    entry_point = "xmodule.v1"
    module_class = XModule

    # Attributes for inspection of the descriptor

    # This indicates whether the xmodule is a problem-type.
    # It should respond to max_score() and grade(). It can be graded or ungraded
    # (like a practice problem).
    has_score = False

    # A list of descriptor attributes that must be equal for the descriptors to
    # be equal
    equality_attributes = ('_model_data', 'location')

    # Name of resource directory to load templates from
    template_dir_name = "default"

    # Class level variable

    # True if this descriptor always requires recalculation of grades, for
    # example if the score can change via an extrnal service, not just when the
    # student interacts with the module on the page.  A specific example is
    # FoldIt, which posts grade-changing updates through a separate API.
    always_recalculate_grades = False

    # VS[compat].  Backwards compatibility code that can go away after
    # importing 2012 courses.
    # A set of metadata key conversions that we want to make
    metadata_translations = {
        'slug': 'url_name',
        'name': 'display_name',
    }

    # ============================= STRUCTURAL MANIPULATION ===================
    def __init__(self, *args, **kwargs):
        """
        Construct a new XModuleDescriptor. The only required arguments are the
        system, used for interaction with external resources, and the
        definition, which specifies all the data needed to edit and display the
        problem (but none of the associated metadata that handles recordkeeping
        around the problem).

        This allows for maximal flexibility to add to the interface while
        preserving backwards compatibility.

        runtime: A DescriptorSystem for interacting with external resources

        model_data: A dictionary-like object that maps field names to values
            for those fields.

        XModuleDescriptor.__init__ takes the same arguments as xblock.core:XBlock.__init__
        """
        super(XModuleDescriptor, self).__init__(*args, **kwargs)
        self.system = self.runtime
        self.url_name = self.location.name
        self.category = self.location.category
        self._child_instances = None

    @property
    def id(self):
        return self.location.url()

    @property
    def display_name_with_default(self):
        '''
        Return a display name for the module: use display_name if defined in
        metadata, otherwise convert the url name.
        '''
        name = self.display_name
        if name is None:
            name = self.url_name.replace('_', ' ')
        return name

    def get_required_module_descriptors(self):
        """Returns a list of XModuleDescritpor instances upon which this module depends, but are
        not children of this module"""
        return []

    def get_children(self):
        """Returns a list of XModuleDescriptor instances for the children of
        this module"""
        if not self.has_children:
            return []

        if self._child_instances is None:
            self._child_instances = []
            for child_loc in self.children:
                try:
                    child = self.system.load_item(child_loc)
                except ItemNotFoundError:
                    log.exception('Unable to load item {loc}, skipping'.format(loc=child_loc))
                    continue
                self._child_instances.append(child)

        return self._child_instances

    def get_child_by(self, selector):
        """
        Return a child XModuleDescriptor with the specified url_name, if it exists, and None otherwise.
        """
        for child in self.get_children():
            if selector(child):
                return child
        return None

    def xmodule(self, system):
        """
        Returns an XModule.

        system: Module system
        """
        return self.module_class(
            system,
            self,
            system.xblock_model_data(self),
        )

    def has_dynamic_children(self):
        """
        Returns True if this descriptor has dynamic children for a given
        student when the module is created.

        Returns False if the children of this descriptor are the same
        children that the module will return for any student.
        """
        return False

    # ================================= JSON PARSING ===========================
    @staticmethod
    def load_from_json(json_data, system, default_class=None):
        """
        This method instantiates the correct subclass of XModuleDescriptor based
        on the contents of json_data.

        json_data must contain a 'location' element, and must be suitable to be
        passed into the subclasses `from_json` method as model_data
        """
        class_ = XModuleDescriptor.load_class(
            json_data['location']['category'],
            default_class
        )
        return class_.from_json(json_data, system)

    @classmethod
    def from_json(cls, json_data, system):
        """
        Creates an instance of this descriptor from the supplied json_data.
        This may be overridden by subclasses

        json_data: A json object with the keys 'definition' and 'metadata',
            definition: A json object with the keys 'data' and 'children'
                data: A json value
                children: A list of edX Location urls
            metadata: A json object with any keys

        This json_data is transformed to model_data using the following rules:
            1) The model data contains all of the fields from metadata
            2) The model data contains the 'children' array
            3) If 'definition.data' is a json object, model data contains all of its fields
               Otherwise, it contains the single field 'data'
            4) Any value later in this list overrides a value earlier in this list

        system: A DescriptorSystem for interacting with external resources
        """
        model_data = {}

        for key, value in json_data.get('metadata', {}).items():
            model_data[cls._translate(key)] = value

        model_data.update(json_data.get('metadata', {}))

        definition = json_data.get('definition', {})
        if 'children' in definition:
            model_data['children'] = definition['children']

        if 'data' in definition:
            if isinstance(definition['data'], dict):
                model_data.update(definition['data'])
            else:
                model_data['data'] = definition['data']

        model_data['location'] = json_data['location']

        return cls(system, model_data)

    @classmethod
    def _translate(cls, key):
        'VS[compat]'
        return cls.metadata_translations.get(key, key)

    # ================================= XML PARSING ============================
    @staticmethod
    def load_from_xml(xml_data,
                      system,
                      org=None,
                      course=None,
                      default_class=None):
        """
        This method instantiates the correct subclass of XModuleDescriptor based
        on the contents of xml_data.

        xml_data must be a string containing valid xml

        system is an XMLParsingSystem

        org and course are optional strings that will be used in the generated
            module's url identifiers
        """
        class_ = XModuleDescriptor.load_class(
            etree.fromstring(xml_data).tag,
            default_class
        )
        # leave next line, commented out - useful for low-level debugging
        # log.debug('[XModuleDescriptor.load_from_xml] tag=%s, class_=%s' % (
        #        etree.fromstring(xml_data).tag,class_))

        return class_.from_xml(xml_data, system, org, course)

    @classmethod
    def from_xml(cls, xml_data, system, org=None, course=None):
        """
        Creates an instance of this descriptor from the supplied xml_data.
        This may be overridden by subclasses

        xml_data: A string of xml that will be translated into data and children
            for this module

        system is an XMLParsingSystem

        org and course are optional strings that will be used in the generated
            module's url identifiers
        """
        raise NotImplementedError(
            'Modules must implement from_xml to be parsable from xml')

    def export_to_xml(self, resource_fs):
        """
        Returns an xml string representing this module, and all modules
        underneath it.  May also write required resources out to resource_fs

        Assumes that modules have single parentage (that no module appears twice
        in the same course), and that it is thus safe to nest modules as xml
        children as appropriate.

        The returned XML should be able to be parsed back into an identical
        XModuleDescriptor using the from_xml method with the same system, org,
        and course
        """
        raise NotImplementedError(
            'Modules must implement export_to_xml to enable xml export')

    # =============================== Testing ==================================
    def get_sample_state(self):
        """
        Return a list of tuples of instance_state, shared_state. Each tuple
        defines a sample case for this module
        """
        return [('{}', '{}')]

    # =============================== BUILTIN METHODS ==========================
    def __eq__(self, other):
        eq = (self.__class__ == other.__class__ and
                all(getattr(self, attr, None) == getattr(other, attr, None)
                    for attr in self.equality_attributes))

        return eq

    def __repr__(self):
        return ("{class_}({system!r}, location={location!r},"
                " model_data={model_data!r})".format(
            class_=self.__class__.__name__,
            system=self.system,
            location=self.location,
            model_data=self._model_data,
        ))

    @property
    def non_editable_metadata_fields(self):
        """
        Return the list of fields that should not be editable in Studio.

        When overriding, be sure to append to the superclasses' list.
        """
        # We are not allowing editing of xblock tag and name fields at this time (for any component).
        return [XBlock.tags, XBlock.name]

    @property
    def editable_metadata_fields(self):
        """
        Returns the metadata fields to be edited in Studio. These are fields with scope `Scope.settings`.

        Can be limited by extending `non_editable_metadata_fields`.
        """
        inherited_metadata = getattr(self, '_inherited_metadata', {})
        inheritable_metadata = getattr(self, '_inheritable_metadata', {})
        metadata_fields = {}
        for field in self.fields:

            if field.scope != Scope.settings or field in self.non_editable_metadata_fields:
                continue

            inheritable = False
            value = getattr(self, field.name)
            default_value = field.default
            explicitly_set = field.name in self._model_data
            if field.name in inheritable_metadata:
                inheritable = True
                default_value = field.from_json(inheritable_metadata.get(field.name))
                if field.name in inherited_metadata:
                    explicitly_set = False

            # We support the following editors:
            # 1. A select editor for fields with a list of possible values (includes Booleans).
            # 2. Number editors for integers and floats.
            # 3. A generic string editor for anything else (editing JSON representation of the value).
            editor_type = "Generic"
            values = [] if field.values is None else copy.deepcopy(field.values)
            if isinstance(values, tuple):
                values = list(values)
            if isinstance(values, list):
                if len(values) > 0:
                    editor_type = "Select"
                for index, choice in enumerate(values):
                    json_choice = copy.deepcopy(choice)
                    if isinstance(json_choice, dict) and 'value' in json_choice:
                        json_choice['value'] = field.to_json(json_choice['value'])
                    else:
                        json_choice = field.to_json(json_choice)
                    values[index] = json_choice
            elif isinstance(field, Integer):
                editor_type = "Integer"
            elif isinstance(field, Float):
                editor_type = "Float"
            metadata_fields[field.name] = {'field_name': field.name,
                                           'type': editor_type,
                                           'display_name': field.display_name,
                                           'value': field.to_json(value),
                                           'options': values,
                                           'default_value': field.to_json(default_value),
                                           'inheritable': inheritable,
                                           'explicitly_set': explicitly_set,
                                           'help': field.help}

        return metadata_fields


class DescriptorSystem(object):
    def __init__(self, load_item, resources_fs, error_tracker, **kwargs):
        """
        load_item: Takes a Location and returns an XModuleDescriptor

        resources_fs: A Filesystem object that contains all of the
            resources needed for the course

        error_tracker: A hook for tracking errors in loading the descriptor.
            Used for example to get a list of all non-fatal problems on course
            load, and display them to the user.

            A function of (error_msg). errortracker.py provides a
            handy make_error_tracker() function.

            Patterns for using the error handler:
               try:
                  x = access_some_resource()
                  check_some_format(x)
               except SomeProblem as err:
                  msg = 'Grommet {0} is broken: {1}'.format(x, str(err))
                  log.warning(msg)  # don't rely on tracker to log
                        # NOTE: we generally don't want content errors logged as errors
                  self.system.error_tracker(msg)
                  # work around
                  return 'Oops, couldn't load grommet'

               OR, if not in an exception context:

               if not check_something(thingy):
                  msg = "thingy {0} is broken".format(thingy)
                  log.critical(msg)
                  self.system.error_tracker(msg)

               NOTE: To avoid duplication, do not call the tracker on errors
               that you're about to re-raise---let the caller track them.
        """

        self.load_item = load_item
        self.resources_fs = resources_fs
        self.error_tracker = error_tracker


class XMLParsingSystem(DescriptorSystem):
    def __init__(self, load_item, resources_fs, error_tracker, process_xml, policy, **kwargs):
        """
        load_item, resources_fs, error_tracker: see DescriptorSystem

        policy: a policy dictionary for overriding xml metadata

        process_xml: Takes an xml string, and returns a XModuleDescriptor
            created from that xml
        """
        DescriptorSystem.__init__(self, load_item, resources_fs, error_tracker,
                                  **kwargs)
        self.process_xml = process_xml
        self.policy = policy


class ModuleSystem(object):
    '''
    This is an abstraction such that x_modules can function independent
    of the courseware (e.g. import into other types of courseware, LMS,
    or if we want to have a sandbox server for user-contributed content)

    ModuleSystem objects are passed to x_modules to provide access to system
    functionality.

    Note that these functions can be closures over e.g. a django request
    and user, or other environment-specific info.
    '''
    def __init__(self,
                 ajax_url,
                 track_function,
                 get_module,
                 render_template,
                 replace_urls,
                 xblock_model_data,
                 user=None,
                 filestore=None,
                 debug=False,
                 xqueue=None,
                 publish=None,
                 node_path="",
                 anonymous_student_id='',
                 course_id=None,
                 open_ended_grading_interface=None,
                 s3_interface=None,
                 cache=None,
                 can_execute_unsafe_code=None,
    ):
        '''
        Create a closure around the system environment.

        ajax_url - the url where ajax calls to the encapsulating module go.

        track_function - function of (event_type, event), intended for logging
                         or otherwise tracking the event.
                         TODO: Not used, and has inconsistent args in different
                         files.  Update or remove.

        get_module - function that takes a descriptor and returns a corresponding
                         module instance object.  If the current user does not have
                         access to that location, returns None.

        render_template - a function that takes (template_file, context), and
                         returns rendered html.

        user - The user to base the random number generator seed off of for this
                         request

        filestore - A filestore ojbect.  Defaults to an instance of OSFS based
                         at settings.DATA_DIR.

        xqueue - Dict containing XqueueInterface object, as well as parameters
                    for the specific StudentModule:
                    xqueue = {'interface': XQueueInterface object,
                              'callback_url': Callback into the LMS,
                              'queue_name': Target queuename in Xqueue}

        replace_urls - TEMPORARY - A function like static_replace.replace_urls
                         that capa_module can use to fix up the static urls in
                         ajax results.

        anonymous_student_id - Used for tracking modules with student id

        course_id - the course_id containing this module

        publish(event) - A function that allows XModules to publish events (such as grade changes)

        xblock_model_data - A dict-like object containing the all data available to this
            xblock

        cache - A cache object with two methods:
            .get(key) returns an object from the cache or None.
            .set(key, value, timeout_secs=None) stores a value in the cache with a timeout.

        can_execute_unsafe_code - A function returning a boolean, whether or
            not to allow the execution of unsafe, unsandboxed code.

        '''
        self.ajax_url = ajax_url
        self.xqueue = xqueue
        self.track_function = track_function
        self.filestore = filestore
        self.get_module = get_module
        self.render_template = render_template
        self.DEBUG = self.debug = debug
        self.seed = user.id if user is not None else 0
        self.replace_urls = replace_urls
        self.node_path = node_path
        self.anonymous_student_id = anonymous_student_id
        self.course_id = course_id
        self.user_is_staff = user is not None and user.is_staff
        self.xblock_model_data = xblock_model_data

        if publish is None:
            publish = lambda e: None

        self.publish = publish

        self.open_ended_grading_interface = open_ended_grading_interface
        self.s3_interface = s3_interface

        self.cache = cache or DoNothingCache()
        self.can_execute_unsafe_code = can_execute_unsafe_code or (lambda: False)

    def get(self, attr):
        '''	provide uniform access to attributes (like etree).'''
        return self.__dict__.get(attr)

    def set(self, attr, val):
        '''provide uniform access to attributes (like etree)'''
        self.__dict__[attr] = val

    def __repr__(self):
        return repr(self.__dict__)

    def __str__(self):
        return str(self.__dict__)


class DoNothingCache(object):
    """A duck-compatible object to use in ModuleSystem when there's no cache."""
    def get(self, _key):
        return None

    def set(self, key, value, timeout=None):
        pass
