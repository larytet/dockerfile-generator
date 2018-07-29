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

import logging
import sys
import os
import re
try:
    from ruamel.yaml import YAML
    from docopt import docopt
except:
    print "Try pip install -r requirements.txt"
    exit(1)    
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
            return True, macro
        else:
            logger.warning("Macro '{0}' not found. Skip macro substitution".format(token))
    return False, [token]

def split_env_definition(s):
    '''
    I do not support all legal file paths here
    '''
    patterns = ['"(.+)" +"(.+)"', r'(\S+) +(\S+)']
    pattern_match = None
    for pattern in patterns:
        pattern_match = re.match(pattern, s)
        if pattern_match:
            break
        
    if pattern_match:
        return pattern_match.group(1), pattern_match.group(2)

    return s, ""

def find_folder(folder, default_res=None):
    '''
    Try to figure out where the specified folder is
    Limit number of searches
    '''
    START_FOLDERS = [os.path.expanduser("~")]
    count = 0
    for start_folder in START_FOLDERS:
        for root, dirs, _ in os.walk(start_folder):
            if folder in dirs:
                return replace_home(os.path.join(root, folder))
            count += 1
            if count > 10*1000:
                break

    return default_res

def substitute_env_variables(s, env_variables):
    '''
    Replace simple cases of ${NAME}
    '''
    replaced = False
    for env_variable in env_variables:
        s_new = string.replace(s, "${{{0}}}".format(env_variable), env_variables[env_variable].value)
        replaced |= s != s_new
        s = s_new
    return replaced, s 

def substitute_env_variables_deep(s, env_variables):
    '''
    Try to substitue variables until nothing changes
    '''
    while True:
        res, s = substitute_env_variables(s, env_variables)
        if not res:
            break
    return s

def split_file_paths(s):
    '''
    I do not support all legal file paths here
    '''
    patterns = ['"(.+)" +"(.+)"', r'(\S+) +(\S+)']
    pattern_match = None
    for pattern in patterns:
        pattern_match = re.match(pattern, s)
        if pattern_match:
            break
        
    if pattern_match:
        return pattern_match.group(1), pattern_match.group(2)

    return None, None

def generate_section_separator():
    return "\n" 

def get_yaml_comment(obj):
    if not obj.ca.comment:
        return ""
    comment = obj.ca.comment[0]
    if not comment:
        return ""
    return "{0}".format(comment.value[1:].strip())

def convert_to_list(v):
    if not v:
        return []
    if (type(v) != list) and not isinstance(v, list):
        return [v]
    return v

def replace_home(s):
    home_folder = os.path.expanduser("~")
    if s.startswith(home_folder):
        s = s.replace(home_folder, "$HOME")
    return s

DockerfileContent = collections.namedtuple('DockerfileContent', ['name', 'help', 'content', 'stages'])
StageContent = collections.namedtuple('StageContent', ['name', 'help', 'content'])
VolumeDefinitions = collections.namedtuple('VolumeDefinitions', ['src', 'dst', 'abs_path'])
ExposedPort = collections.namedtuple('ExposedPort', ['port', 'protocol'])
GeneratedFile = collections.namedtuple('GeneratedFile', ['filename', 'help', 'publish'])
EnvironmentVariable = collections.namedtuple('EnvironmentVariable', ['name', 'value', 'help', 'publish'])
class RootGenerator(object):
    '''
    One object of this type for every Dockerfile
    '''  
    def __init__(self, data_map):
        object.__init__(RootGenerator)
        self.data_map = data_map
        self.dockerfiles = []
        self.dockerfile_contents = []
        self.env_variables = {}
        self.shells = []
        self.ports = {}
        self.macros = data_map.get("macros", {})
        self.warning_folder_does_not_exist = False

    def do(self):
        res = False
        dockerfile_contents = []
        while True:
            dockerfiles = self.data_map.get("dockerfiles", None)
        
            if not dockerfiles:
                # backward compatibility, try "containers"
                dockerfiles = self.data_map.get("containers", None)

            if not dockerfiles:
                logger.info("No containers specified")
                break
            self.dockerfiles = dockerfiles
            for dockerfile_name, dockerfile_config in dockerfiles.items():
                res, dockerfile_content = self.__do_dockerfile(dockerfile_name, dockerfile_config)
                dockerfile_contents.append(dockerfile_content)
            break
            
        return res, dockerfile_contents

    def __get_dockerfile_help(self, dockerfile_name, dockerfile_config):
        '''
        Print help and examples for the container
        '''
        s_out = ""
        return s_out        
    
    def __do_dockerfile(self, dockerfile_name, dockerfile_config):
        '''
        Generate a dockerfile for one of the dockerfiles definitons in the YAML configuration file
        2. build different parts of the Dockerfile 
        3. output the collected string to the Dockerfile  
        '''
        res = False
        dockerfile_content = ""
        dockerfile_help = ""
        # A container contains one or more stage
        stages = dockerfile_config.get("stages", None)
        anonymous = False
        if not stages:
            stages = [{None:dockerfile_config}]
            anonymous = True

        dockerfile_stages = []
        for stage in stages:
            stage_name, stage_config = stage.popitem()
            dockerfile_stages.append({stage_name:stage_config})
            stage_config.volumes = [] 
            res, dockerfile_stage_content = self.__do_dockerfile_stage(dockerfile_name, dockerfile_config, stage_name, stage_config, anonymous)
            if not res:
                break
            dockerfile_content += dockerfile_stage_content.content
        dockerfile_help = self.__get_dockerfile_help(dockerfile_name, dockerfile_config)

        content = DockerfileContent(dockerfile_name, dockerfile_help, dockerfile_content, dockerfile_stages)
        self.dockerfile_contents.append(content)
        return res, content 
        
    def __get_comment(self, dockerfile_config, fmt, *args):
        if dockerfile_config.get("comments_disable", False):
            return ""
        return fmt.format(*args)
        
    def __do_dockerfile_stage(self, dockerfile_name, dockerfile_config, stage_name, stage_config, anonymous):
        res = False
        dockerfile_stage_content = ""
        dockerfile_stage_help = ""

        if not anonymous and stage_name:
            dockerfile_stage_content += self.__get_comment(dockerfile_config, "\n# {0}", get_yaml_comment(stage_config))
            
        dockerfile_stage_content += self.__generate_header(stage_config, stage_name)
        dockerfile_stage_content += self.__generate_entrypoint(stage_config)
            
        sections = stage_config.get("sections", None)
        anonymous = False
        if not sections:
            sections = [stage_config]
            anonymous = True
        for section_config in sections:
            res, dockerfile_stage_section_content = self.__do_dockerfile_stage_section(dockerfile_name, dockerfile_config, stage_name, stage_config, section_config, anonymous)
            if not res:
                break
            dockerfile_stage_content += dockerfile_stage_section_content
        
        return res, StageContent(stage_name, dockerfile_stage_help, dockerfile_stage_content)
    
    def __generate_entrypoint(self, stage_config):
        '''
        Add CMD 
        '''
        s_out = ""
        entrypoint = stage_config.get("entrypoint", None)
        if not entrypoint:
            return s_out
        
        command = "\nENTRYPOINT"
        command += " {0}".format(entrypoint) 
        s_out += command
        return s_out
        
    def __generate_header(self, stage_config, stage_name):
        s_out = ""
        stage_config_base = stage_config.get("base", "centos:centos7")
        if stage_name:
            s_out += "\nFROM {0} as {1}".format(stage_config_base, stage_name)
        else:
            s_out += "\nFROM {0}".format(stage_config_base)
        return s_out

    def __do_dockerfile_stage_section(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config, anonymous):
        generators = [self.__generate_dockerfile_expose, 
                      self.__generate_dockerfile_env,           
                      self.__generate_dockerfile_env_extended,           
                      self.__generate_dockerfile_volume, 
                      self.__generate_dockerfile_copy, 
                      self.__generate_dockerfile_copy_f, 
                      self.__generate_shell,
                      self.__generate_dockerfile_packages,          
                      self.__generate_file,
                      self.__generate_dockerfile_run]
        
        s_out = ""
        if not anonymous and section_config.ca.comment:
            s_out += self.__get_comment(dockerfile_config, "\n# Section {0}", get_yaml_comment(section_config))
        for generator in generators:
            res, s_tmp = generator(dockerfile_name, dockerfile_config, stage_name, stage_config, section_config)
            # print a separator after non-empty blocks
            if res: 
                s_out += s_tmp
                s_out += generate_section_separator()

        return True, s_out


    def __generate_dockerfile_expose(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAML 'expose' - EXPOSE command in the Dockerfile
        '''
        s_out = ""
        ports = section_config.get("expose", None)
        if not ports:
            return False, ""
        command = "\nEXPOSE"
        ports_list = self.ports.get(dockerfile_name, [])
        for port in ports:
            words = port.split("/")
            if len(words) == 1:
                isTcp = True
                ports_list.append(ExposedPort(words[0], "TCP"))
            else:
                ports_list.append(ExposedPort(words[0], words[1]))
                isTcp = (words[1] == "TCP")
            if isTcp:
                command += " {0}".format(words[0])
            else: 
                command += " {0}".format(port)
        self.ports[dockerfile_name] = ports_list
        s_out += command
    
        return True, s_out


    def __generate_dockerfile_volume(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAML 'volume' - VOLUME command in the Dockerfile
        '''
        s_out = ""
        volumes = section_config.get("volumes", None)
        if not volumes:
            return False, ""
        command = "\nVOLUME ["
        env_dict = self.env_variables.get(dockerfile_name, {})
        for volume in volumes:
            src, dst = split_file_paths(volume)
            dst = substitute_env_variables_deep(dst, env_dict)
            command += ' "{0}",'.format(dst)
            src_abs_path = find_folder(src, src)
            if src_abs_path == src:
                logger.warning("I did not find folder {0} in your home directory".format(src))
            stage_config.volumes.append(VolumeDefinitions(src, dst, src_abs_path))
        command = command[:-1]
        command += ' ]' 
        s_out += command
        return True, s_out

    def __generate_dockerfile_copy_f(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAML 'copy_f' - COPY command in the Dockerfile
        '''
        return self.__generate_dockerfile_copy_do(section_config, "copy_f", True)

    def __generate_dockerfile_packages_rpm(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Use yum to install missing packages
        I force all packages in a single yum command to reduce the container image size
        '''
        s_out = ""
        packages = section_config.get("install", None)
        if not packages:
            return False, ""
        
        if dockerfile_config.get("build_trace_disable", False):
            command = "\nRUN "
        else:
            command = "\nRUN `# Install packages` && set -x && "
        command += " \\\n\tyum -y -v install"
        for package in packages:
            _, words = match_macro(self.macros, package)
            for w in words:
                command += " {0}".format(w)
        
        command += " && \\\n\tyum clean all && yum -y clean packages"
        
        s_out += command 
        return True, s_out
            
    def __generate_dockerfile_packages_deb(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Use apt-get to install missing packages
        I force all packages in a single apt command to reduce the container image size
        '''
        s_out = ""
        packages = section_config.get("install", None)
        if not packages:
            return False, ""
        
        if dockerfile_config.get("build_trace_disable", False):
            command = "\nRUN "
        else:
            command = "\nRUN `# Install packages` && set -x &&"
        command += " \\\n\tapt-get update && \\\n\tapt-get -y install"
        for package in packages:
            _, words = match_macro(self.macros, package)
            for w in words:
                command += " {0}".format(w)
            
        command += " && \\\n\tapt-get -y clean"
        
        s_out += command 
        return True, s_out
        
    def __generate_dockerfile_packages(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Depending on 'packager' call apt-get or yum
        '''
        s_out = ""
        packager = dockerfile_config.get("packager", "rpm")
        res = False 
        if packager == "deb":
            res, s_out = self.__generate_dockerfile_packages_deb(dockerfile_name, dockerfile_config, stage_name, stage_config, section_config)
        elif packager == "rpm":
            res, s_out = self.__generate_dockerfile_packages_rpm(dockerfile_name, dockerfile_config, stage_name, stage_config, section_config)
        else:
            logger.error("Unknown packager '{0}'".format(packager))
        return res, s_out

    def __generate_command_chain(self, first, command, lead):
        '''
        If first is True return 'command', else add lead
        The idea is to save some code lines and conditions
        '''    
        if first:
            return False, command
        else:
            return False, lead+command
        
    def __generate_dockerfile_run(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAML 'run' - add a RUN section to the Dockerfile
        '''
        s_out = ""
        commands = section_config.get("run", None)
        if not commands:
            return False, ""
        if dockerfile_config.get("build_trace_disable", False):
            commands_concatenated = "\nRUN "
        else:
            commands_concatenated = "\nRUN `# Execute commands` && set -x && "
        first = True        
        for command in commands:
            if command.startswith("comment "):
                command = command.split(" ", 1)[1]
                first, c = self.__generate_command_chain(first, " `# {0}`".format(command),  " && \\\n\t")
                commands_concatenated += c
                continue
                
            is_macro, words = match_macro(self.macros, command)
            if is_macro and not dockerfile_config.get("build_trace_disable", False):
                first, c = self.__generate_command_chain(first, " `# {0}`".format(command),  " && \\\n\t")
                commands_concatenated += c
            for w in words:
                first, c = self.__generate_command_chain(first, " {0}".format(w),  " && \\\n\t")
                commands_concatenated += c
        
        s_out += commands_concatenated 
        return True, s_out 
    
    
    def __generate_dockerfile_env(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAML 'env' - ENV command in the Dockerfile
        '''
        s_out = ""
        env_vars = section_config.get("env", None)
        if not env_vars:
            return False, ""
        env_dict = self.env_variables.get(dockerfile_name, {})
        for env_var in env_vars:
            _, words = match_macro(self.macros, env_var)
            for w in words:
                s_out += "\nENV {0}".format(w)
                name, value = split_env_definition(w)
                env_dict[name] = EnvironmentVariable(name, value, "", False)
        self.env_variables[dockerfile_name] = env_dict 
        return True, s_out

    def __generate_dockerfile_env_extended(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAML 'environment_variables' - ENV command in the Dockerfile
        '''
        s_out = ""
        environment_variables = section_config.get("env_ext", None)
        if not environment_variables:
            return False, ""
        env_dict = self.env_variables.get(dockerfile_name, {})
        for environment_variable in environment_variables:
            env_var_definition =  environment_variable["definition"]
            env_var_help = environment_variable.get("help", "")
            env_var_publish = environment_variable.get("publish", False)
            for env_var_help_line in convert_to_list(env_var_help):
                s_out += "\n# {0}".format(env_var_help_line)
            s_out += "\nENV {0}\n".format(env_var_definition)
            name, value = split_file_paths(env_var_definition)
            env_dict[name] = EnvironmentVariable(name, value, env_var_help, env_var_publish)
        self.env_variables[dockerfile_name] = env_dict 
            
        return True, s_out
    
    def __generate_file(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config, tags=("files", "file"), set_executable=False, collection=None):
        '''
        Handle YAMLs 'file' 
        '''
        s_out = ""
        root_tag = tags[0]
        node_tage = tags[1]
        shells = section_config.get(root_tag, None)
        if not shells:
            return False, ""
    
        if not dockerfile_config.get("build_trace_disable", False):
            commands_concatenated = "\nRUN `# Generate files` && set -x && "
        else:
            commands_concatenated = "\nRUN "
        first = True
        for shell in shells:
            filename = shell["filename"]
            help = shell.get("help", [])
            publish = shell.get("publish", False)
            env_dict = self.env_variables.get(dockerfile_name, {})
            filename_env = substitute_env_variables_deep(filename, env_dict)
            dirname = os.path.dirname(filename_env)
            #print("dirname", dirname, filename_env)
            
            if collection != None:
                collection.append(GeneratedFile(filename, help, publish))
            if not dockerfile_config.get("build_trace_disable", False):
                first, c = self.__generate_command_chain(first, "`# Generating {0}` mkdir -p \"{1}\"".format(filename, dirname),  " && \\\n\t")
            else:
                first, c = self.__generate_command_chain(first, "mkdir -p \"{0}\"".format(dirname),  " && \\\n\t")
            commands_concatenated += c
            for line in help:
                line = "# " + line + "\\n"
                first, c = self.__generate_command_chain(first, "echo -e \"{0}\" > {1}".format(line, filename),  " && \\\n\t")
                commands_concatenated += c
            for line in shell["lines"]:
                _, words = match_macro(self.macros, line)
                for w in words:
                    if w.startswith("comment "):
                        w = w.split(" ", 1)[1]
                        first, c = self.__generate_command_chain(first, "`# {0}`".format(w),  " && \\\n\t")
                        commands_concatenated += c
                    else:
                        first, c = self.__generate_command_chain(first, "echo \"{0}\" >> {1}".format(w, filename),  " && \\\n\t")
                        commands_concatenated += c
            if set_executable:
                first, c = self.__generate_command_chain(first, "chmod +x {0}".format(filename),  " && \\\n\t")
                commands_concatenated += c
        s_out += commands_concatenated
        return True, s_out

    def __generate_shell(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAMLs 'shell' 
        '''
        res, s_out = self.__generate_file(dockerfile_name, dockerfile_config, stage_name, stage_config, section_config, ("shells", "shell"), True, self.shells)
        return res, s_out
    
    def __generate_dockerfile_copy_f(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAML 'copy_f' - COPY command in the Dockerfile
        '''
        return self.__generate_dockerfile_copy_do(dockerfile_name, dockerfile_config, stage_name, stage_config, section_config, "copy_f", True)

    def __generate_dockerfile_copy(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config):
        '''
        Handle YAML 'copy' - COPY command in the Dockerfile
        '''
        return self.__generate_dockerfile_copy_do(dockerfile_name, dockerfile_config, stage_name, stage_config, section_config, "copy", False)
        
    def __generate_dockerfile_copy_do(self, dockerfile_name, dockerfile_config, stage_name, stage_config, section_config, key, skip_check):
        s_out = ""
        files = section_config.get(key, None)
        if not files:
            return False, ""
        for file in files:
            _, words = match_macro(self.macros, file)
            for w in words:
                src, dst = split_file_paths(w)
                if (src, dst) != (None, None):
                    s_out += '\nCOPY "{0}" "{1}"'.format(src, dst)
                    full_src_path1 = os.path.join(confile_file_folder, os.path.basename(src))
                    full_src_path2 = os.path.join(confile_file_folder, src)
                    if not glob.glob(full_src_path1) and not glob.glob(full_src_path2) and not self.warning_folder_does_not_exist and not skip_check:
                        self.warning_folder_does_not_exist = True
                        logger.warning("Path {0} does not exist in the folder {1}\
                         in the container {2}".format(src, confile_file_folder, self.dockerfile_name))
                else: 
                    logger.warning("Faled to parse COPY arguments {0}".format(w))
        return True, s_out

def get_dockerfile_path(dockerfile_name):
    return os.path.join(confile_file_folder, "Dockerfile.{0}.g2".format(dockerfile_name))

def get_user_help_env(root_generator, dockerfile_name):            
    env_vars_help = ""
    env_dict = root_generator.env_variables.get(dockerfile_name, {})
    
    for env_var_name, env_var in env_dict.iteritems():
        if env_var.publish:
            if env_var.value:
                env_vars_help += " -e \"{0}={1}\"".format(env_var_name, env_var.value)
            else:
                env_vars_help += " -e {0}".format(env_var_name)
    return env_vars_help

def save_dockerfile(dockerfile_content):
    res, f = open_file(get_dockerfile_path(dockerfile_content.name), "w")
    if not res:
        return 
    f.write(dockerfile_content.content)
    f.close()

def get_user_help_commands(data_map, root_generator, dockerfile_content):
    s_out = ""
    volumes_help = ""
    dockerfile_name = dockerfile_content.name
    dockerfile_path = get_dockerfile_path(dockerfile_name)
    s_out += "  # Build and run the container (try to add --rm). See https://docs.docker.com/engine/reference/commandline/run\n"    
    for stage in dockerfile_content.stages:
        stage_name, stage_config = stage.popitem()
        anonymous = False 
        if not stage_name:
            stage_name = dockerfile_name
            anonymous = True
         
        for (_, dst, src_abs_path) in stage_config.volumes:
            volumes_help += " \\\n  --volume {0}:{1} ".format(src_abs_path, dst)
        if volumes_help:
            volumes_help += " \\\n "
        ports_help = ""
        ports_list = root_generator.ports.get(dockerfile_name, [])
        for (port, protocol) in ports_list:
            ports_help += " -p {0}:{0}/{1}".format(port, protocol)
        if ports_help:
            ports_help += " \\\n "
        env_vars_help = get_user_help_env(root_generator, dockerfile_name)
        if not anonymous:
            tag = "{0}.{1}".format(dockerfile_name, stage_name)
            s_out += "  sudo docker build --target {0} --tag {1}:latest --file {2}  .\n".format(stage_name, tag, replace_home(dockerfile_path))
        else:
            tag = "{0}".format(dockerfile_name)
            s_out += "  sudo docker build --tag {0}:latest --file {1}  .\n".format(tag, replace_home(dockerfile_path))

        s_out += "  sudo docker run --rm --name {0} --network='host' --init --tty --interactive{1}{2}{3} {0}:latest\n".format(tag, volumes_help, ports_help, env_vars_help)
    
    return s_out 

def get_user_help(data_map, root_generator):
    '''
    Print help and examples for the container
    '''
    s_out = ""
    for content in root_generator.dockerfile_contents:
        s_out += "\nContainer '{0}' help:".format(content.name)
        s_out += "  {0}\n".format(dockerfile_content.help)
        s_out += get_user_help_commands(data_map, root_generator, content)
            #s_out += get_user_help_shells()
            #s_out += get_user_help_env_list() 
            #s_out += get_user_help_ports()
            #s_out += get_user_help_examples()
    
    return s_out        
            
def show_help(data_map, root_generator):
    for help in data_map.get("help", []):
        print("{0}".format(help))
    print get_user_help(data_map, root_generator)

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
        yaml=YAML(typ='rt') 
        data_map = yaml.load(f)
        root_generator = RootGenerator(data_map)
        res, content = root_generator.do()
        if not res:
            break
        for dockerfile_content in content:
            save_dockerfile(dockerfile_content)
            
        if not arguments["--disable_help"]:
            show_help(data_map, root_generator)

        break