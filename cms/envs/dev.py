"""
This config file runs the simplest dev environment"""

# We intentionally define lots of variables that aren't used, and
# want to import all variables from base settings files
# pylint: disable=W0401, W0614

from .common import *
from logsettings import get_logger_config

DEBUG = True
TEMPLATE_DEBUG = DEBUG
LOGGING = get_logger_config(ENV_ROOT / "log",
                            logging_env="dev",
                            tracking_filename="tracking.log",
                            dev_env=True,
                            debug=True)

modulestore_options = {
    'default_class': 'xmodule.raw_module.RawDescriptor',
    'host': 'localhost',
    'db': 'xmodule',
    'collection': 'modulestore',
    'fs_root': GITHUB_REPO_ROOT,
    'render_template': 'mitxmako.shortcuts.render_to_string'
}

MODULESTORE = {
    'default': {
        'ENGINE': 'xmodule.modulestore.mongo.DraftMongoModuleStore',
        'OPTIONS': modulestore_options
    },
    'direct': {
        'ENGINE': 'xmodule.modulestore.mongo.MongoModuleStore',
        'OPTIONS': modulestore_options
    }
}

# cdodge: This is the specifier for the MongoDB (using GridFS) backed static content store
# This is for static content for courseware, not system static content (e.g. javascript, css, edX branding, etc)
CONTENTSTORE = {
    'ENGINE': 'xmodule.contentstore.mongo.MongoContentStore',
    'OPTIONS': {
        'host': 'localhost',
        'db': 'xcontent',
    },
    # allow for additional options that can be keyed on a name, e.g. 'trashcan'
    'ADDITIONAL_OPTIONS': {
        'trashcan': {
            'bucket': 'trash_fs'
        }
    }
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ENV_ROOT / "db" / "mitx.db",
    }
}

LMS_BASE = "localhost:8000"
MITX_FEATURES['PREVIEW_LMS_BASE'] = "localhost:8000"

REPOS = {
    'edx4edx': {
        'branch': 'master',
        'origin': 'git@github.com:MITx/edx4edx.git',
    },
    'content-mit-6002x': {
        'branch': 'master',
        # 'origin': 'git@github.com:MITx/6002x-fall-2012.git',
        'origin': 'git@github.com:MITx/content-mit-6002x.git',
    },
    '6.00x': {
        'branch': 'master',
        'origin': 'git@github.com:MITx/6.00x.git',
    },
    '7.00x': {
        'branch': 'master',
        'origin': 'git@github.com:MITx/7.00x.git',
    },
    '3.091x': {
        'branch': 'master',
        'origin': 'git@github.com:MITx/3.091x.git',
    },
}

CACHES = {
    # This is the cache used for most things. Askbot will not work without a
    # functioning cache -- it relies on caching to load its settings in places.
    # In staging/prod envs, the sessions also live here.
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'mitx_loc_mem_cache',
        'KEY_FUNCTION': 'util.memcache.safe_key',
    },

    # The general cache is what you get if you use our util.cache. It's used for
    # things like caching the course.xml file for different A/B test groups.
    # We set it to be a DummyCache to force reloading of course.xml in dev.
    # In staging environments, we would grab VERSION from data uploaded by the
    # push process.
    'general': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        'KEY_PREFIX': 'general',
        'VERSION': 4,
        'KEY_FUNCTION': 'util.memcache.safe_key',
    },

    'mongo_metadata_inheritance': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': '/var/tmp/mongo_metadata_inheritance',
        'TIMEOUT': 300,
        'KEY_FUNCTION': 'util.memcache.safe_key',
    }
}

# Make the keyedcache startup warnings go away
CACHE_TIMEOUT = 0

# Dummy secret key for dev
SECRET_KEY = '85920908f28904ed733fe576320db18cabd7b6cd'

################################ PIPELINE #################################

PIPELINE_SASS_ARGUMENTS = '--debug-info --require {proj_dir}/static/sass/bourbon/lib/bourbon.rb'.format(proj_dir=PROJECT_ROOT)

################################# CELERY ######################################

# By default don't use a worker, execute tasks as if they were local functions
CELERY_ALWAYS_EAGER = True

################################ DEBUG TOOLBAR #################################
INSTALLED_APPS += ('debug_toolbar', 'debug_toolbar_mongo')
MIDDLEWARE_CLASSES += ('debug_toolbar.middleware.DebugToolbarMiddleware',)
INTERNAL_IPS = ('127.0.0.1',)

DEBUG_TOOLBAR_PANELS = (
    'debug_toolbar.panels.version.VersionDebugPanel',
    'debug_toolbar.panels.timer.TimerDebugPanel',
    'debug_toolbar.panels.settings_vars.SettingsVarsDebugPanel',
    'debug_toolbar.panels.headers.HeaderDebugPanel',
    'debug_toolbar.panels.request_vars.RequestVarsDebugPanel',
    'debug_toolbar.panels.sql.SQLDebugPanel',
    'debug_toolbar.panels.signals.SignalDebugPanel',
    'debug_toolbar.panels.logger.LoggingPanel',
    'debug_toolbar_mongo.panel.MongoDebugPanel',

    #  Enabling the profiler has a weird bug as of django-debug-toolbar==0.9.4 and
    #  Django=1.3.1/1.4 where requests to views get duplicated (your method gets
    #  hit twice). So you can uncomment when you need to diagnose performance
    #  problems, but you shouldn't leave it on.
    #  'debug_toolbar.panels.profiling.ProfilingDebugPanel',
    )

DEBUG_TOOLBAR_CONFIG = {
    'INTERCEPT_REDIRECTS': False
}

# To see stacktraces for MongoDB queries, set this to True.
# Stacktraces slow down page loads drastically (for pages with lots of queries).
DEBUG_TOOLBAR_MONGO_STACKTRACES = True

# disable NPS survey in dev mode
MITX_FEATURES['STUDIO_NPS_SURVEY'] = False

# Enable URL that shows information about the status of variuous services
MITX_FEATURES['ENABLE_SERVICE_STATUS'] = True

############################# SEGMENT-IO ##################################

# If there's an environment variable set, grab it and turn on Segment.io
# Note that this is the Studio key. There is a separate key for the LMS.
import os
SEGMENT_IO_KEY = os.environ.get('SEGMENT_IO_KEY')
if SEGMENT_IO_KEY:
    MITX_FEATURES['SEGMENT_IO'] = True


#####################################################################
# Lastly, see if the developer has any local overrides.
try:
    from .private import *      # pylint: disable=F0401
except ImportError:
    pass
