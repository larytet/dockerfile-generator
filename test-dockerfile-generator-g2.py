#!/usr/bin/env python
from __builtin__ import str


dockerfile_generator = __import__("dockerfile-generator-g2")
import StringIO
try:
    from ruamel.yaml import YAML
except Exception as e:
    print e
    print "Try pip install -r requirements.txt"
    exit(1)    
import logging


def test_init():
    logging.basicConfig()    
    logger = logging.getLogger('dockerfile_generator')
    logger.setLevel(logging.INFO)
    dockerfile_generator.logger = logger    

def load_yaml(str):    
    yaml=YAML(typ='rt') 
    data_map = yaml.load(str)
    root_generator = dockerfile_generator.RootGenerator("test", data_map)
    return root_generator

def test_no_containers():
    root_generator = load_yaml("""help:
                                    - This YAML file contains definitions of the traffic server, CyDNS related containers
                               """)
    res, str = root_generator.do()
    assert(not res)
    assert(len(root_generator.dockerfiles) == 0)
    assert(len(root_generator.stages) == 0)
    
def test_containers():
    root_generator = load_yaml("""containers:
                                    c1:
                                      packager: rpm
                                    c2:
                                      packager: rpm
                               """)
    res, str = root_generator.do()
    assert(not res)    
    assert(len(root_generator.dockerfiles) == 2)
    assert(len(root_generator.stages) == 2)
   
def test_containers1():
    root_generator = load_yaml("""dockerfiles:
                                    c1:
                                      packager: rpm
                                    c2:
                                      packager: rpm
                               """)
    res, str = root_generator.do()
    assert(not res)    
    assert(len(root_generator.dockerfiles) == 2)
    assert(len(root_generator.stages) == 2)
    
def test_all():
    root_generator = load_yaml("""
                                  macros:
                                   get_release:  # get_release comment
                                    - cat /etc/*release # cat comment
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
                                    centos7: # centos 7 comment
                                      base: centos:centos7
                                      packager: rpm
                                    ubuntu.16.04: # ubuntu.16.04 comment
                                      packager: deb
                                      stages:   # I nees multiple stages test
                                        - intermediate: # base stage
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
                                        - final: # final stage
                                              base: intermediate
                                              run:
                                                - echo "Final"
                               """)
    res, str = root_generator.do()
    assert(not res)    
    assert(len(root_generator.dockerfiles) == 2)
    assert(len(root_generator.stages) == 3)
    print str
    assert(False)
    