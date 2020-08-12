#!/bin/sh
#Must use an out of install path virtual env as this uses webbot and this needs to write to the 
#virtual env.
sudo pipenv2deb --venv_oip
