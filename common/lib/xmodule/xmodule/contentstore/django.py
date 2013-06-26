from __future__ import absolute_import
from importlib import import_module

from django.conf import settings

_CONTENTSTORE = {}


def load_function(path):
    """
    Load a function by name.

    path is a string of the form "path.to.module.function"
    returns the imported python object `function` from `path.to.module`
    """
    module_path, _, name = path.rpartition('.')
    return getattr(import_module(module_path), name)


def contentstore(name='default'):
    if name not in _CONTENTSTORE:
        class_ = load_function(settings.CONTENTSTORE['ENGINE'])
        options = {}
        options.update(settings.CONTENTSTORE['OPTIONS'])
        if 'ADDITIONAL_OPTIONS' in settings.CONTENTSTORE:
            if name in settings.CONTENTSTORE['ADDITIONAL_OPTIONS']:
                options.update(settings.CONTENTSTORE['ADDITIONAL_OPTIONS'][name])
        _CONTENTSTORE[name] = class_(**options)

    return _CONTENTSTORE[name]
