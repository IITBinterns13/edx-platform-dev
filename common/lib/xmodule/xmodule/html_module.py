import copy
from fs.errors import ResourceNotFoundError
import logging
import os
import sys
from lxml import etree
from path import path

from pkg_resources import resource_string
from xblock.core import Scope, String
from xmodule.editing_module import EditingDescriptor
from xmodule.html_checker import check_html
from xmodule.stringify import stringify_children
from xmodule.x_module import XModule
from xmodule.xml_module import XmlDescriptor, name_to_pathname

log = logging.getLogger("mitx.courseware")


class HtmlFields(object):
    data = String(help="Html contents to display for this module", scope=Scope.content)
    source_code = String(help="Source code for LaTeX documents. This feature is not well-supported.", scope=Scope.settings)


class HtmlModule(HtmlFields, XModule):
    js = {'coffee': [resource_string(__name__, 'js/src/javascript_loader.coffee'),
                     resource_string(__name__, 'js/src/collapsible.coffee'),
                     resource_string(__name__, 'js/src/html/display.coffee')
                    ]
         }
    js_module_name = "HTMLModule"
    css = {'scss': [resource_string(__name__, 'css/html/display.scss')]}

    def get_html(self):
        if self.system.anonymous_student_id: 
            return self.data.replace("%%USER_ID%%", self.system.anonymous_student_id)
        return self.data


class HtmlDescriptor(HtmlFields, XmlDescriptor, EditingDescriptor):
    """
    Module for putting raw html in a course
    """
    mako_template = "widgets/html-edit.html"
    module_class = HtmlModule
    filename_extension = "xml"
    template_dir_name = "html"

    js = {'coffee': [resource_string(__name__, 'js/src/html/edit.coffee')]}
    js_module_name = "HTMLEditingDescriptor"
    css = {'scss': [resource_string(__name__, 'css/editor/edit.scss'), resource_string(__name__, 'css/html/edit.scss')]}

    # VS[compat] TODO (cpennington): Delete this method once all fall 2012 course
    # are being edited in the cms
    @classmethod
    def backcompat_paths(cls, path):
        if path.endswith('.html.xml'):
            path = path[:-9] + '.html'  # backcompat--look for html instead of xml
        if path.endswith('.html.html'):
            path = path[:-5]  # some people like to include .html in filenames..
        candidates = []
        while os.sep in path:
            candidates.append(path)
            _, _, path = path.partition(os.sep)

        # also look for .html versions instead of .xml
        nc = []
        for candidate in candidates:
            if candidate.endswith('.xml'):
                nc.append(candidate[:-4] + '.html')
        return candidates + nc

    # NOTE: html descriptors are special.  We do not want to parse and
    # export them ourselves, because that can break things (e.g. lxml
    # adds body tags when it exports, but they should just be html
    # snippets that will be included in the middle of pages.

    @classmethod
    def load_definition(cls, xml_object, system, location):
        '''Load a descriptor from the specified xml_object:

        If there is a filename attribute, load it as a string, and
        log a warning if it is not parseable by etree.HTMLParser.

        If there is not a filename attribute, the definition is the body
        of the xml_object, without the root tag (do not want <html> in the
        middle of a page)
        '''
        filename = xml_object.get('filename')
        if filename is None:
            definition_xml = copy.deepcopy(xml_object)
            cls.clean_metadata_from_xml(definition_xml)
            return {'data': stringify_children(definition_xml)}, []
        else:
            # html is special.  cls.filename_extension is 'xml', but
            # if 'filename' is in the definition, that means to load
            # from .html
            # 'filename' in html pointers is a relative path
            # (not same as 'html/blah.html' when the pointer is in a directory itself)
            pointer_path = "{category}/{url_path}".format(category='html',
                                                  url_path=name_to_pathname(location.name))
            base = path(pointer_path).dirname()
            # log.debug("base = {0}, base.dirname={1}, filename={2}".format(base, base.dirname(), filename))
            filepath = "{base}/{name}.html".format(base=base, name=filename)
            # log.debug("looking for html file for {0} at {1}".format(location, filepath))

            # VS[compat]
            # TODO (cpennington): If the file doesn't exist at the right path,
            # give the class a chance to fix it up. The file will be written out
            # again in the correct format.  This should go away once the CMS is
            # online and has imported all current (fall 2012) courses from xml
            if not system.resources_fs.exists(filepath):
                candidates = cls.backcompat_paths(filepath)
                # log.debug("candidates = {0}".format(candidates))
                for candidate in candidates:
                    if system.resources_fs.exists(candidate):
                        filepath = candidate
                        break

            try:
                with system.resources_fs.open(filepath) as file:
                    html = file.read().decode('utf-8')
                    # Log a warning if we can't parse the file, but don't error
                    if not check_html(html) and len(html) > 0:
                        msg = "Couldn't parse html in {0}, content = {1}".format(filepath, html)
                        log.warning(msg)
                        system.error_tracker("Warning: " + msg)

                    definition = {'data': html}

                    # TODO (ichuang): remove this after migration
                    # for Fall 2012 LMS migration: keep filename (and unmangled filename)
                    definition['filename'] = [filepath, filename]

                    return definition, []

            except (ResourceNotFoundError) as err:
                msg = 'Unable to load file contents at path {0}: {1} '.format(
                    filepath, err)
                # add more info and re-raise
                raise Exception(msg), None, sys.exc_info()[2]

    # TODO (vshnayder): make export put things in the right places.

    def definition_to_xml(self, resource_fs):
        '''If the contents are valid xml, write them to filename.xml.  Otherwise,
        write just <html filename="" [meta-attrs="..."]> to filename.xml, and the html
        string to filename.html.
        '''
        try:
            return etree.fromstring(self.data)
        except etree.XMLSyntaxError:
            pass

        # Not proper format.  Write html to file, return an empty tag
        pathname = name_to_pathname(self.url_name)
        filepath = u'{category}/{pathname}.html'.format(category=self.category,
                                                    pathname=pathname)

        resource_fs.makedir(os.path.dirname(filepath), recursive=True, allow_recreate=True)
        with resource_fs.open(filepath, 'w') as file:
            html_data = self.data.encode('utf-8')
            file.write(html_data)

        # write out the relative name
        relname = path(pathname).basename()

        elt = etree.Element('html')
        elt.set("filename", relname)
        return elt


class AboutDescriptor(HtmlDescriptor):
    """
    These pieces of course content are treated as HtmlModules but we need to overload where the templates are located
    in order to be able to create new ones
    """
    template_dir_name = "about"


class StaticTabDescriptor(HtmlDescriptor):
    """
    These pieces of course content are treated as HtmlModules but we need to overload where the templates are located
    in order to be able to create new ones
    """
    template_dir_name = "statictab"


class CourseInfoDescriptor(HtmlDescriptor):
    """
    These pieces of course content are treated as HtmlModules but we need to overload where the templates are located
    in order to be able to create new ones
    """
    template_dir_name = "courseinfo"
