#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''dockerfile_generator

Read YAML configuration file and generate required dockerfiles. 
The goal is to generate numerous and very similar 
dockerfiles for different distributions, build toolchains versions  
 
Usage:
  dockerfile_generator.py -h | --help
  dockerfile_generator.py -c <FILENAME> [-a <PATH>] [--disable_help]

Example:
    dockerfile_generator.py -c containers.yml
   
Options:
  -h --help                 Show this screen.
  -c --config=<FILENAME>    YAML configuration file
  -a --add_path=<PATH>      Where to look for additional files used in the dockerfile command ADD 
  --disable_help            Disable show help  
'''

'''
Example of the YAML file:
 
macros:
 get_release:
  - cat /etc/*release
  - gcc --version

 build_essential_centos:
  - gcc 
  - gcc-c++ 
  - make
 
 make_dir:
  - mkdir -p /etc/docker
 
 environment_vars:
   # I need an env variable referencing a persistent folder
   - SHARED_FOLDER /etc/docker  

dockerfiles:

 centos7:
    base: centos:centos7
    packager: rpm
    help_disable: false  # optional flags controlling the Dockerfile L&F 
    readme_disable: false
    build_trace_disable: false
    comments_disable: false
    
    install:
      - $build_essential_centos 
      - rpm-build
    run:
      - $get_release
    env:
      - $environment_vars

 ubuntu.16.04:
    packager: deb
    stages:
      - intermediate: 
         base: ubuntu:16.04
         sections:
           - section:
             expose:
               - 8080/TCP
             install:
               - build-essential    
           - section:
             run:
               - $get_release
             env:
               - $environment_vars
      - final: 
            base: intermediate
            run:
              - echo "Final"
'''

import yaml
import logging
import sys
import os
import re
from docopt import docopt
import glob
import socket
import string
import collections 

def open_file(filename, flags, print_error=True):
    '''
    Open a text file 
    Returns handle to the open file and result code False/True
    '''
    try:
        file_handle = open(filename, flags) 
    except Exception:
        if print_error:
            print sys.exc_info()
            logger.error('Failed to open file {0}'.format(filename))
        return (False, None)
    else:
        return (True, file_handle)    

def looks_like_macro(token):
    res = True
    res &= len(token) > len("$")
    res &= token.startswith("$")
    res &= not token.startswith("${")
    return res, token[1:]
    
def match_macro(macros, token):
    '''
    If the token is a macro - starts form dollar sign - extend the macro
    otherwise return the token
    '''
    res, macro_key = looks_like_macro(token)
    if res:
        macro = macros.get(macro_key, None)
        if macro:
            return macro
        else:
            logger.warning("Macro '{0}' not found. Skip macro substitution".format(token))
    return [token]

class RootGenerator(object):
    '''
    One object of this type for every Dockerfile
    '''  
    def __init__(self, config_filename, data_map):
        object.__init__(RootGenerator)
        self.config_filename, self.data_map = config_filename, data_map
        self.dockerfiles = []

    def get_dockerfiles(self):
        '''
        return a list of found containers definitions
        '''
        return self.dockerfiles
    
    def do(self):
        res = False
        output_string = ""
        while True:
            dockerfiles = self.data_map.get("dockerfiles", None)
        
            if not dockerfiles:
                # backward compatibility, try "containers"
                dockerfiles = self.data_map.get("containers", None)

            if not dockerfiles:
                logger.info("No containers specified in the '{0}'".format(self.config_filename))
                break
            
            self.dockerfiles = dockerfiles

            break
            
        return res, output_string
        
def show_help(data_map):
    for help in data_map.get("help", []):
        print("{0}".format(help))

if __name__ == '__main__':
    arguments = docopt(__doc__, version='0.1')
    logging.basicConfig()    
    logger = logging.getLogger('dockerfile_generator')
    logger.setLevel(logging.INFO)    
    
    config_file = arguments['--config']
    add_path = arguments['--add_path']
    if not add_path:
        add_path = "./"
    
    while True:
        
        if config_file is None:
            logger.info("Nothing to do")
            break
        
        result, f = open_file(config_file, "r")
        if not result:
            break

        confile_file_abspath = os.path.abspath(config_file)
        confile_file_folder = os.path.dirname(confile_file_abspath)
      
        # parse the YAML file specified by --config flag 
        data_map = yaml.safe_load(f)
        root_generator = RootGenerator(data_map)
        if not arguments["--disable_help"]:
            show_help(data_map)
        
        break