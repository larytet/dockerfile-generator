# Why I need this

A Dockerfile is a list of commands to do in the container. 
What if I want to create many dockerfiles which have significant overlap between them. I introduce a YAML configuration file and a Python script which parses the configuration file. 
The main goals:

* Keep dockerfiles configuration in a single place
* All dockerfiles have consistent structure
* Switch to a different OS/OS release/different version of a package is trivial thanks to macros
   

# HowTo

Install missing Python packages
```sh
pip install -r requirements.txt
```

Install [DockerCE](https://docs.docker.com/engine/installation/linux/ubuntu/). For example, something like this shall work:

```sh 
# Run as root:

wget https://get.docker.com -O - | sh
systemctl stop docker

# Use overlayFS (because it is cool and recommended)

CONFIGURATION_FILE=$(systemctl show --property=FragmentPath docker | cut -f2 -d=)
cp $CONFIGURATION_FILE /etc/systemd/system/docker.service
perl -pi -e 's/^(ExecStart=.+)$/$1 -s overlay/' /etc/systemd/system/docker.service
systemctl daemon-reload
systemctl start docker
```

Generate dockerfiles (modify file ./containers.yml if necessary)

```sh 
rm -f Dockerfile.* ;./dockerfile-generator.py --config=./containers.yml   
```

Build Docker images. This operation should be done every time ./containers.yml is modified

```sh
for f in ./Dockerfile.*; do filename=`echo $f | sed -E 's/\..Dockerfile.(\S+)/\1/'`;echo Processing $filename;sudo docker build -t $filename -f $f  .;sudo docker save $filename -o $filename.tar;done
```

Check that the artefacts are created
```sh
ls -al Dockerfile* *.tar
```


Stop and remove:
```sh
#docker stop $(docker ps -a -q)
#docker rm $(docker ps -a -q)
#docker rmi $(docker images -q)
./remove-all.sh
```
