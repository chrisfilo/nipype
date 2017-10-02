# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
'''
Created on 20 Apr 2010

logging options : INFO, DEBUG
hash_method : content, timestamp

@author: Chris Filo Gorgolewski
'''
from __future__ import print_function, division, unicode_literals, absolute_import
import os
import errno
from warnings import warn
from io import StringIO
from distutils.version import LooseVersion
import configparser
import numpy as np

from builtins import bytes, str, object, open

from simplejson import load, dump
from future import standard_library
from ..external import portalocker
from .misc import str2bool

standard_library.install_aliases()


CONFIG_DEPRECATIONS = {
    'profile_runtime': ('resource_monitor', '1.0'),
    'filemanip_level': ('utils_level', '1.0'),
}

NUMPY_MMAP = LooseVersion(np.__version__) >= LooseVersion('1.12.0')

# Get home directory in platform-agnostic way
homedir = os.path.expanduser('~')
default_cfg = """
[logging]
workflow_level = INFO
utils_level = INFO
interface_level = INFO
log_to_file = false
log_directory = %s
log_size = 16384000
log_rotate = 4

[execution]
create_report = true
crashdump_dir = %s
display_variable = :1
hash_method = timestamp
job_finished_timeout = 5
keep_inputs = false
local_hash_check = true
matplotlib_backend = Agg
plugin = Linear
remove_node_directories = false
remove_unnecessary_outputs = true
try_hard_link_datasink = true
single_thread_matlab = true
crashfile_format = pklz
stop_on_first_crash = false
stop_on_first_rerun = false
use_relative_paths = false
stop_on_unknown_version = false
write_provenance = false
parameterize_dirs = true
poll_sleep_duration = 2
xvfb_max_wait = 10
resource_monitor = false
resource_monitor_frequency = 1

[check]
interval = 1209600
""" % (homedir, os.getcwd())


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


class NipypeConfig(object):
    """Base nipype config class
    """

    def __init__(self, *args, **kwargs):
        self._config = configparser.ConfigParser()
        config_dir = os.path.expanduser('~/.nipype')
        config_file = os.path.join(config_dir, 'nipype.cfg')
        self.data_file = os.path.join(config_dir, 'nipype.json')
        self._config.readfp(StringIO(default_cfg))
        self._resource_monitor = None
        if os.path.exists(config_dir):
            self._config.read([config_file, 'nipype.cfg'])

        for option in CONFIG_DEPRECATIONS:
            for section in ['execution', 'logging']:
                if self.has_option(section, option):
                    new_option = CONFIG_DEPRECATIONS[option][0]
                    if not self.has_option(section, new_option):
                        # Warn implicit in get
                        self.set(section, new_option, self.get(section, option))

    def set_default_config(self):
        self._config.readfp(StringIO(default_cfg))

    def enable_debug_mode(self):
        """Enables debug configuration
        """
        self._config.set('execution', 'stop_on_first_crash', 'true')
        self._config.set('execution', 'remove_unnecessary_outputs', 'false')
        self._config.set('execution', 'keep_inputs', 'true')
        self._config.set('logging', 'workflow_level', 'DEBUG')
        self._config.set('logging', 'interface_level', 'DEBUG')

    def set_log_dir(self, log_dir):
        """Sets logging directory

        This should be the first thing that is done before any nipype class
        with logging is imported.
        """
        self._config.set('logging', 'log_directory', log_dir)

    def get(self, section, option, default=None):
        if option in CONFIG_DEPRECATIONS:
            msg = ('Config option "%s" has been deprecated as of nipype %s. Please use '
                   '"%s" instead.') % (option, CONFIG_DEPRECATIONS[option][1],
                                       CONFIG_DEPRECATIONS[option][0])
            warn(msg)
            option = CONFIG_DEPRECATIONS[option][0]

        if self._config.has_option(section, option):
            return self._config.get(section, option)
        return default

    def set(self, section, option, value):
        if isinstance(value, bool):
            value = str(value)

        if option in CONFIG_DEPRECATIONS:
            msg = ('Config option "%s" has been deprecated as of nipype %s. Please use '
                   '"%s" instead.') % (option, CONFIG_DEPRECATIONS[option][1],
                                       CONFIG_DEPRECATIONS[option][0])
            warn(msg)
            option = CONFIG_DEPRECATIONS[option][0]

        return self._config.set(section, option, value)

    def getboolean(self, section, option):
        return self._config.getboolean(section, option)

    def has_option(self, section, option):
        return self._config.has_option(section, option)

    @property
    def _sections(self):
        return self._config._sections

    def get_data(self, key):
        if not os.path.exists(self.data_file):
            return None
        with open(self.data_file, 'rt') as file:
            portalocker.lock(file, portalocker.LOCK_EX)
            datadict = load(file)
        if key in datadict:
            return datadict[key]
        return None

    def save_data(self, key, value):
        datadict = {}
        if os.path.exists(self.data_file):
            with open(self.data_file, 'rt') as file:
                portalocker.lock(file, portalocker.LOCK_EX)
                datadict = load(file)
        else:
            dirname = os.path.dirname(self.data_file)
            if not os.path.exists(dirname):
                mkdir_p(dirname)
        with open(self.data_file, 'wt') as file:
            portalocker.lock(file, portalocker.LOCK_EX)
            datadict[key] = value
            dump(datadict, file)

    def update_config(self, config_dict):
        for section in ['execution', 'logging', 'check']:
            if section in config_dict:
                for key, val in list(config_dict[section].items()):
                    if not key.startswith('__'):
                        self._config.set(section, key, str(val))

    def update_matplotlib(self):
        import matplotlib
        matplotlib.use(self.get('execution', 'matplotlib_backend'))

    def enable_provenance(self):
        self._config.set('execution', 'write_provenance', 'true')
        self._config.set('execution', 'hash_method', 'content')

    @property
    def resource_monitor(self):
        """Check if resource_monitor is available"""
        if self._resource_monitor is not None:
            return self._resource_monitor

        # Cache config from nipype config
        self.resource_monitor = self._config.get(
            'execution', 'resource_monitor') or False
        return self._resource_monitor

    @resource_monitor.setter
    def resource_monitor(self, value):
        # Accept string true/false values
        if isinstance(value, (str, bytes)):
            value = str2bool(value.lower())

        if value is False:
            self._resource_monitor = False
        elif value is True:
            if not self._resource_monitor:
                # Before setting self._resource_monitor check psutil availability
                self._resource_monitor = False
                try:
                    import psutil
                    self._resource_monitor = LooseVersion(
                        psutil.__version__) >= LooseVersion('5.0')
                except ImportError:
                    pass
                finally:
                    if not self._resource_monitor:
                        warn('Could not enable the resource monitor: psutil>=5.0'
                             ' could not be imported.')
                    self._config.set('execution', 'resource_monitor',
                                     ('%s' % self._resource_monitor).lower())

    def enable_resource_monitor(self):
        self.resource_monitor = True
