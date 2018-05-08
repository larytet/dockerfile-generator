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

 build_essential_centos:
 - gcc 
 - gcc-c++ 
 - make

 get_release:
 - cat /etc/*release
 - gcc --version

 environment_vars:
 - SHARED_FOLDER /etc/docker

containers:

 centos7:
    base: centos:centos7
    packager: rpm
    install:
    - $build_essential_centos 
    - rpm-build
    run:
    - $get_release
    env:
     - $environment_vars
     
 centos6:
    base: centos:centos6
    packager: rpm
    sections:
      - section:    
        install:
          - $build_essential_centos 
          - rpm-build
      - section:    
        run:
          - $get_release
        env:
          - $environment_vars
     
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

def open_file(filename, flags):
    '''
    Open a text file 
    Returns handle to the open file and result code False/True
    '''
    try:
        file_handle = open(filename, flags) 
    except Exception:
        print sys.exc_info()
        logger.error('Failed to open file {0}'.format(filename))
        return (False, None)
    else:
        return (True, file_handle)    

def process_macro(token):
    '''
    If the token is a macro - starts form dollar sign - extend the macro
    otherwise return the token
    '''
    if len(token) > 2 and token[0] == '$' and token[1] != '{':
        macro_key = token[1:]
        macro = MACROS.get(macro_key, None)
        if macro:
            return macro
        else:
            logger.warning("Macro '{0}' not found. Skip macro substitution".format(token))
    return [token]

def substitute_evn_variables(s, env_variables):
    '''
    Replace simple cases of ${NAME}
    '''
    replaced = False
    for env_variable in env_variables:
        s_new = string.replace(s, "${{{0}}}".format(env_variable), env_variables[env_variable].value)
        replaced |= s != s_new
        s = s_new
    return replaced, s 

def substitute_evn_variables_deep(s, env_variables):
    '''
    Try to substitue variables until nothing changes
    '''
    while True:
        res, s = substitute_evn_variables(s, env_variables)
        if not res:
            break
    return s
    
def generate_section_separator():
    return "\n" 

def get_machine_ip():
    hostname = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
    except _:
        ip = socket.gethostbyname_ex(hostname)
    return hostname, ip 

def replace_home(s):
    home_folder = os.path.expanduser("~")
    if s.startswith(home_folder):
        s = s.replace(home_folder, "$HOME")
    return s

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

def get_docker_config():
    filenames = ["/etc/docker/daemon.json"]
    for filename in filenames:
        res, f = open_file(filename, "r")
        if res:
            lines = f.readlines()
            return True, filename, lines
    return False, None, None

VolumeDefinitions = collections.namedtuple('VolumeDefinitions', ['src', 'dst', 'abs_path'])
ExposedPort = collections.namedtuple('ExposedPort', ['port', 'protocol'])
GeneratedFile = collections.namedtuple('GeneratedFile', ['filename', 'help', 'publish'])
EnvironmentVariable = collections.namedtuple('EnvironmentVariable', ['name', 'value', 'help', 'publish'])
    
class RootGenerator(object):  
    def __init__(self, container_name, container_config):
        object.__init__(RootGenerator)
        self.container_name, self.container_config = container_name, container_config
        
        self.volumes = []
        self.shells = []
        self.ports = []
        self.env_variables = {}
        self.packager = container_config["packager"]
        self.examples = container_config.get("examples", [])
        self.warning_folder_does_not_exist = False

    def generate_dockerfile(self):
        '''
        Write a dockerfile for one of the containers in the YAML configuration file
        1. parse the YAML file
        2. build different parts of the Dockerfile 
        3. output the collected string to the Dockerfile  
        '''
        container_name, container_config = self.container_name, self.container_config

        # Create a new dockerfile with name like "Dockerfile.centos7"
        self.dockerfile_name = "Dockerfile.{0}".format(container_name)
        
        res, container_header = self.generate_header()
        res, container_entrypoint = self.generate_entrypoint()
        # A container contains one or more sections
        sections = container_config.get("sections", None)
    
        # "sections" is optional. I am forcing "sections" mode in all cases
        # and handling the YAML using the same function 
        if not sections:
            sections = [container_config]

        _, container_sections = self.generate_dockerfile_sections(sections)
        # I can generate help and README only after I parsed the sections and collected
        # all volumes etc
        _, container_help = self.generate_container_help()
        _, container_readme = self.generate_container_readme()

        res, f = open_file(self.dockerfile_name, "w")
        if not res:
            return False, None

        f.write(container_help)
        f.write("\n")
        f.write(container_header)
        f.write("\n")
        f.write("RUN set +x && `# Generate README file` && \
            echo -e '{0}' > README".format(container_readme))
        f.write(container_entrypoint)
        f.write(container_sections)

        f.close()
    
        _, container_help = self.get_user_help()

        return True, container_help


    def generate_dockerfile_packages_rpm(self, section_config):
        '''
        Use yum to install missing packages
        I force all packages in a single yum command to reduce the container image size
        '''
        s_out = ""
        packages = section_config.get("install", None)
        if not packages:
            return False, ""
        
        command = "\nRUN `# Install packages` && set -x"
        command += " && \\\n\tyum -y -v install"
        for package in packages:
            words = process_macro(package)
            for w in words:
                command += " {0}".format(w)
        
        command += " && \\\n\tyum clean all && yum -y clean packages"
        
        s_out += command 
        return True, s_out
            
    def generate_dockerfile_packages_deb(self, section_config):
        '''
        Use apt-get to install missing packages
        I force all packages in a single apt command to reduce the container image size
        '''
        s_out = ""
        packages = section_config.get("install", None)
        if not packages:
            return False, ""
        
        command = "\nRUN `# Install packages` && set -x"
        command += " && \\\n\tapt-get update && \\\n\tapt-get -y install"
        for package in packages:
            words = process_macro(package)
            for w in words:
                command += " {0}".format(w)
            
        command += " && \\\n\tapt-get -y clean"
        
        s_out += command 
        return True, s_out
        
    def generate_dockerfile_packages(self, section_config):
        '''
        Depending on 'packager' call apt-get or yum
        '''
        s_out = ""
        packager = self.packager
        res = False 
        if packager == "deb":
            res, s_out = self.generate_dockerfile_packages_deb(section_config)
        elif packager == "rpm":
            res, s_out = self.generate_dockerfile_packages_rpm(section_config)
        else:
            logger.error("Unknown packager '{0}'".format(packager))
        return res, s_out
    
    def generate_dockerfile_run(self, section_config):
        '''
        Handle YAML 'run' - add a RUN section to the Dockerfile
        '''
        s_out = ""
        commands = section_config.get("run", None)
        if not commands:
            return False, ""
        commands_concatenated = "\nRUN `# Execute commands` && set -x"
        for command in commands:
            if not ' ' in command:
                commands_concatenated += "  && \\\n`# {0}`".format(command)
            words = process_macro(command)
            for w in words:
                commands_concatenated += " && \\\n\t{0}".format(w)
        
        s_out += commands_concatenated 
        return True, s_out 
    
    
    def generate_dockerfile_env(self, section_config):
        '''
        Handle YAML 'env' - ENV command in the Dockerfile
        '''
        s_out = ""
        env_vars = section_config.get("env", None)
        if not env_vars:
            return False, ""
        for env_var in env_vars:
            words = process_macro(env_var)
            for w in words:
                s_out += "\nENV {0}".format(w)
                name, value = split_env_definition(w)
                self.env_variables[name] = EnvironmentVariable(name, value, "", False)
        return True, s_out

    def generate_dockerfile_env_extended(self, section_config):
        '''
        Handle YAML 'environment_variables' - ENV command in the Dockerfile
        '''
        s_out = ""
        environment_variables = section_config.get("env_ext", None)
        if not environment_variables:
            return False, ""
        for environment_variable in environment_variables:
            env_var_definition =  environment_variable["definition"]
            env_var_help = environment_variable.get("help", "")
            env_var_publish = environment_variable.get("publish", False)
            if env_var_help:
                s_out += "\n# {0}".format(env_var_help)
            s_out += "\nENV {0}".format(env_var_definition)
            name, value = split_file_paths(env_var_definition)
            self.env_variables[name] = EnvironmentVariable(name, value, env_var_help, env_var_publish)
            
        return True, s_out
    
    def generate_dockerfile_copy(self, section_config):
        '''
        Handle YAML 'add' - COPY command in the Dockerfile
        '''
        s_out = ""
        files = section_config.get("copy", None)
        if not files:
            return False, ""
        for file in files:
            words = process_macro(file)
            for w in words:
                src, dst = split_file_paths(w)
                if (src, dst) != (None, None):
                    s_out += '\nCOPY "{0}" "{1}"'.format(src, dst)
                    full_src_path1 = os.path.join(confile_file_folder, os.path.basename(src))
                    full_src_path2 = os.path.join(confile_file_folder, src)
                    if not glob.glob(full_src_path1) and not glob.glob(full_src_path2) and not self.warning_folder_does_not_exist:
                        self.warning_folder_does_not_exist = True
                        logger.warning("Path {0} does not exist in the folder {1}\
                         in the container {2}".format(src, confile_file_folder, self.container_name))
                else: 
                    logger.warning("Faled to parse COPY arguments {0}".format(w))
        return True, s_out
    
    def generate_header(self):
        s_out = ""
        s_out += "\nFROM {0}".format(self.container_config["base"])
        s_out += "\nMAINTAINER automatically generated from {0}".format(os.path.abspath(config_file))
        s_out += "\n"
        return True, s_out
    
    def generate_entrypoint(self):
        '''
        Add CMD 
        '''
        s_out = ""
        entrypoint = self.container_config.get("entrypoint", None)
        if not entrypoint:
            return False, s_out
        
        command = "\nENTRYPOINT"
        command += " {0}".format(entrypoint) 
        s_out += command
        return True, s_out
        
    def generate_dockerfile_sections(self, sections):
        '''
        Process the "sections" and add the sections data to the Dockerfile
        '''
    
        # This is the order of commands in the Dockerfile ections
        generators = [self.generate_dockerfile_expose, 
                      self.generate_dockerfile_env,           
                      self.generate_dockerfile_env_extended,           
                      self.generate_dockerfile_volume, 
                      self.generate_dockerfile_copy, 
                      self.generate_shell,
                      self.generate_dockerfile_packages,          
                      self.generate_file,
                      self.generate_dockerfile_run]
    
        s_out = ""
        section_idx = 0
        for section_config in sections:
            # do not add Section index if there is only one section
            if len(sections) > 1: s_out += "\n# Section {0}".format(section_idx) 
            section_idx += 1
            for generator in generators:
                res, s_tmp = generator(section_config)
                 # print a separator after non-empty blocks
                if res: 
                    s_out += s_tmp
                    s_out += generate_section_separator()

        return True, s_out
                    
    def get_user_help_shells(self):
        s_out = ""
        shells = self.shells
        if shells:
            s_out += "  Custom shell scripts:\n"
        for shell in shells:
            shell_help = ""
            if not shell.publish:
                continue
            padding = " " * (len(shell.filename) + 9)
            first_line = True 
            for help_line in shell.help:
                if not first_line:
                    help_line = padding + help_line
                first_line = False 
                shell_help += help_line + "\n"
            if len(shell_help):
                shell_help = shell_help[:-1]
            s_out += "    * {0} - {1}\n".format(shell.filename, shell_help)
        return s_out
    
    def get_user_help_ports(self):
        s_out = ""
        ports = self.ports
        if ports:
            s_out += "  Exposed ports:"
        for port in ports:
            s_out += " {0}/{1}".format(port.port, port.protocol)
        s_out += "\n"
        return s_out
    
    def get_user_help_examples(self):
        s_out = ""
        exmaples = self.container_config.get("examples", [])
        if exmaples:
            s_out += "  Examples:\n"
        for example in exmaples:
            s_out += "  {0}\n".format(example)
        return s_out

    def get_user_help_env(self):            
        env_vars_help = ""
        for env_var_name, env_var in self.env_variables.iteritems():
            if env_var.publish:
                if env_var.value:
                    env_vars_help += " -e \"{0}={1}\"".format(env_var_name, env_var.value)
                else:
                    env_vars_help += " -e {0}".format(env_var_name)
        return env_vars_help

    def get_user_help_env_list(self):            
        env_vars_help = ""
        for env_var_name, env_var in self.env_variables.iteritems():
            if env_var.publish:
                if env_var.value:
                    env_vars_definition = "    * {0}={1} - ".format(env_var_name, env_var.value)
                else:
                    env_vars_definition = "    * {0} - ".format(env_var_name)
                padding = " " * len(env_vars_definition)
                env_vars_help += env_vars_definition
                first_line = True
                env_help = "" 
                for help_line in env_var.help:
                    if not first_line:
                        help_line = padding + help_line
                    first_line = False 
                    env_help += help_line + "\n"
                if len(env_help):
                    env_help = env_help[:-1]
                env_vars_help += env_help
                
        if env_vars_help:
            env_vars_help = "  Flagged ENV vars:\n" + env_vars_help + "\n"
        return env_vars_help
    
    def get_user_help_commands(self):
        s_out = ""
        volumes_help = ""
        for (_, dst, src_abs_path) in self.volumes:
            volumes_help += " \\\n  --volume {0}:{1} ".format(src_abs_path, dst)
        if volumes_help:
            volumes_help += " \\\n "

        ports_help = ""
        for (port, protocol) in self.ports:
            ports_help += " -p {0}:{0}/{1}".format(port, protocol)
        if ports_help:
            ports_help += " \\\n "
            
        env_vars_help = self.get_user_help_env()

        dockerfile_path = os.path.join(confile_file_folder, "Dockerfile.{0}".format(self.container_name))
        s_out += "  # Build the container. See https://docs.docker.com/engine/reference/commandline/build\n"
        s_out += "  sudo docker build --tag {0}:latest --file {1}  .\n".format(self.container_name, replace_home(dockerfile_path))
        s_out += "  # Run the previously built container. See https://docs.docker.com/engine/reference/commandline/run\n"
        s_out += "  sudo docker run --name {0} --network='host' --tty --interactive{1}{2}{3} {0}:latest\n".format(self.container_name, volumes_help, ports_help, env_vars_help)
        s_out += "  # Start the previously run container\n"
        s_out += "  sudo docker start --interactive {0}\n".format(self.container_name)
        s_out += "  # Connect to a running container\n"
        s_out += "  sudo docker exec --interactive --tty {0} /bin/bash\n".format(self.container_name)
        s_out += "  # Save the container for the deployment to another machine. Use 'docker load' to load saved containers\n"
        s_out += "  sudo docker save {0} -o {0}.tar\n".format(self.container_name)
        s_out += "  # Remove container to 'run' it again\n"
        s_out += "  sudo docker rm {0}\n".format(self.container_name)
        
        return s_out
    
    def get_user_help(self):
        '''
        Print help and examples for the container
        '''
        s_out = ""
        s_out += "Container '{0}' help:\n".format(self.container_name)
        for help in self.container_config.get("help", []):
            s_out += "  {0}\n".format(help)
        s_out += self.get_user_help_commands()
        s_out += self.get_user_help_shells()
        s_out += self.get_user_help_env_list() 
        s_out += self.get_user_help_ports()
        s_out += self.get_user_help_examples()
        
        return True, s_out        
    
    def generate_container_help(self):
        hostname, IP = get_machine_ip()
        s_out = ""
        s_out += "\n# Generated by https://github.com/larytet/dockerfile-generator on {0} {1}".format(hostname, IP)
        s_out += "\n"

        for help in self.container_config.get("help", []):
            s_out += "\n# {0}".format(help)

        volumes_help = ""
        for volume in self.volumes:
            volumes_help += " --volume {0}:{1}".format(volume.src, volume.dst)
        env_vars_help = self.get_user_help_env()

        dockerfile_path = os.path.join(confile_file_folder, "Dockerfile.{0}".format(self.container_name))
        s_out += "\n# sudo docker build --tag {0}:latest --file {1}  .".format(self.container_name, dockerfile_path)
        s_out += "\n# sudo docker run --name {0} --tty --interactive  {1}{2} {0}:latest".format(self.container_name, volumes_help, env_vars_help)
        s_out += "\n# sudo docker start --interactive {0}".format(self.container_name)
        exmaples = container_config.get("examples", [])
        if exmaples:
            s_out += "\n# Examples:"
        for example in exmaples:
            s_out += "\n# {0}".format(example)
        res, filename, docker_config = get_docker_config()
        if res:
            s_out += "\n# Docker configuration:{0}".format(docker_config)
        s_out += "\n"
        
        return True, s_out
    
    def generate_container_readme(self):
        s_out = ""
        hostname, IP = get_machine_ip()
        s_out += "Generated by https://github.com/larytet/dockerfile-generator on {0} {1}\n".format(hostname, IP)
        for help in self.container_config.get("help", []):
            s_out += "{0}\n".format(help)
        s_out += self.get_user_help_commands()
        s_out += self.get_user_help_shells() 
        s_out += self.get_user_help_examples()
        s_out = s_out.replace("# ", "")
        s_out = s_out.replace("\n", "\\n\\\n")
        return True, s_out

    def generate_dockerfile_expose(self, section_config):
        '''
        Handle YAML 'expose' - EXPOSE command in the Dockerfile
        '''
        s_out = ""
        ports = section_config.get("expose", None)
        if not ports:
            return False, ""
        command = "\nEXPOSE"
        for port in ports:
            words = port.split("/")
            if len(words) == 1:
                self.ports.append(ExposedPort(words[0], "TCP"))
            else:
                self.ports.append(ExposedPort(words[0], words[1]))
            command += " {0}".format(port) 
        s_out += command
    
        return True, s_out
    
    
    def generate_dockerfile_volume(self, section_config):
        '''
        Handle YAML 'volume' - VOLUME command in the Dockerfile
        '''
        s_out = ""
        volumes = section_config.get("volumes", None)
        if not volumes:
            return False, ""
        command = "\nVOLUME ["
        for volume in volumes:
            src, dst = split_file_paths(volume)
            dst = substitute_evn_variables_deep(dst, self.env_variables)
            command += ' "{0}",'.format(dst)
            src_abs_path = find_folder(src, src)
            if src_abs_path == src:
                logger.warning("I did not find folder {0} in your home directory".format(src))
            self.volumes.append(VolumeDefinitions(src, dst, src_abs_path))
        command = command[:-1]
        command += ' ]' 
        s_out += command
        return True, s_out
    
    
    def generate_file(self, section_config, tags=("files", "file"), set_executable=False, collection=None):
        '''
        Handle YAMLs 'file' 
        '''
        s_out = ""
        root_tag = tags[0]
        node_tage = tags[1]
        shells = section_config.get(root_tag, None)
        if not shells:
            return False, ""
    
        commands_concatenated = "\nRUN `# Generate files` && set -x"
        for shell in shells:
            filename = shell["filename"]
            help = shell.get("help", [])
            publish = shell.get("publish", False)
            filename_env = substitute_evn_variables_deep(filename, self.env_variables)
            dirname = os.path.dirname(filename_env)
            #print("dirname", dirname, filename_env)
            
            if collection != None:
                collection.append(GeneratedFile(filename, help, publish))
            help_lines = ""
            for line in help:
                help_lines += "# " + line + "\\n"
            commands_concatenated += " && \\\n\t`# {1}` && \\\n\tmkdir -p {2} && \\\n\techo -e \"{0}\" > {1}".format(help_lines, filename, dirname)
            for line in shell["lines"]:
                words = process_macro(line)
                for w in words:
                    commands_concatenated += " && \\\n\techo \"{0}\" >> {1}".format(w, filename)
            if set_executable:
                commands_concatenated += " && \\\n\tchmod +x {0}".format(filename)
        s_out += commands_concatenated
        return True, s_out
    
    def generate_shell(self, section_config):
        '''
        Handle YAMLs 'shell' 
        '''
        res, s_out = self.generate_file(section_config, ("shells", "shell"), True, self.shells)
        return res, s_out

def show_help(data_map):
    for help in data_map.get("help", []):
        print("{0}".format(help))

if __name__ == '__main__':
    '''
    This is an emulation of staprun logic minus insmod, stapio, access rights
    '''
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
        
        macros = data_map["macros"]
        MACROS = {}
        if macros:
            for macro in macros:
                MACROS[macro] = macros[macro]

        containers = data_map.get("containers", None)
        if not containers:
            logger.info("No containers specified in the {0}".format(config_file))
            break
        if not arguments["--disable_help"]:
            show_help(data_map)

        # Generate the containers required by the YAML configuration file
        for container_name, container_config  in containers.items():
            root_generator = RootGenerator(container_name, container_config)
            res, container_help = root_generator.generate_dockerfile()
            if res and not arguments["--disable_help"]:
                print(container_help)

        res, filename, docker_config = get_docker_config()
        if res:
            logger.info("{0}:{1}".format(filename, docker_config))

        break
