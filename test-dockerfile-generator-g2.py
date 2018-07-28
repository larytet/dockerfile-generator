#!/usr/bin/env python


dockerfile_generator = __import__("dockerfile-generator-g2")
import StringIO
import yaml


def test_no_containers():
    str_io = StringIO.StringIO("""help:
                                    - This YAML file contains definitions of the traffic server, CyDNS related containers
                               """)
    data_map = yaml.safe_load(str_io)
    root_generator = dockerfile_generator.RootGenerator(data_map)
    res, str = root_generator.do()
    assert(res)