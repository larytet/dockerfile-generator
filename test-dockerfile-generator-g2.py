#!/usr/bin/env python


dockerfile_generator = __import__("dockerfile-generator-g2")
import StringIO
import yaml
import logging


def test_init():
    logging.basicConfig()    
    logger = logging.getLogger('dockerfile_generator')
    logger.setLevel(logging.INFO)
    dockerfile_generator.logger = logger    
    
def test_no_containers():
    str_io = StringIO.StringIO("""help:
                                    - This YAML file contains definitions of the traffic server, CyDNS related containers
                               """)
    data_map = yaml.safe_load(str_io)
    root_generator = dockerfile_generator.RootGenerator("test", data_map)
    res, str = root_generator.do()
    assert(not res)
    assert(len(root_generator.dockerfiles) == 0)
    assert(len(root_generator.stages) == 0)
    
def test_containers():
    str_io = StringIO.StringIO("""containers:
                                    c1:
                                      packager: rpm
                                    c2:
                                      packager: rpm
                               """)
    data_map = yaml.safe_load(str_io)
    root_generator = dockerfile_generator.RootGenerator("test", data_map)
    res, str = root_generator.do()
    assert(not res)    
    assert(len(root_generator.dockerfiles) == 2)
    assert(len(root_generator.stages) == 2)
   
def test_containers1():
    str_io = StringIO.StringIO("""dockerfiles:
                                    c1:
                                      packager: rpm
                                    c2:
                                      packager: rpm
                               """)
    data_map = yaml.safe_load(str_io)
    root_generator = dockerfile_generator.RootGenerator("test", data_map)
    res, str = root_generator.do()
    assert(not res)    
    assert(len(root_generator.dockerfiles) == 2)
    assert(len(root_generator.stages) == 2)
    
def test_stages():
    str_io = StringIO.StringIO("""dockerfiles:
                                    c1:
                                      packager: rpm
                                      stages:
                                        - s1: 
                                        - s2: 
                                    c2:
                                      packager: rpm
                               """)
    data_map = yaml.safe_load(str_io)
    root_generator = dockerfile_generator.RootGenerator("test", data_map)
    res, str = root_generator.do()
    assert(not res)    
    assert(len(root_generator.dockerfiles) == 2)
    assert(len(root_generator.stages) == 3)
    