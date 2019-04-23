#!/usr/bin/python3
import sys
import os
import subprocess
import re
import argparse
import logging
import fileinput

vyos_config_migrate_dir = r'/opt/vyatta/etc/config-migrate'
system_version_dir = os.path.join(vyos_config_migrate_dir, 'current')
migrate_util_dir = os.path.join(vyos_config_migrate_dir, 'migrate')
migrate_log = r'/var/log/vyatta/migrate.log'
vyos_version = r'/opt/vyatta/etc/version'

def get_config_file_versions(config_file_handle):
    """
    Get component versions from config file; return empty dictionary if
    config string is missing or raise error if string is malformed.
    """
    config_file_versions = {}

    for config_line in config_file_handle:
        if re.match(r'/\* === vyatta-config-version:.+=== \*/$', config_line):
            if not re.match(r'/\* === vyatta-config-version:\s+"([\w,-]+@\d+:)+([\w,-]+@\d+)"\s+=== \*/$', config_line):
                raise ValueError("malformed configuration string: {}".format(config_line))

            for pair in re.findall(r'([\w,-]+)@(\d+)', config_line):
                if pair[0] in config_file_versions.keys():
                    logging.info("duplicate unit name: {} in string: {}".format(pair[0],
                        config_line)) 
                config_file_versions[pair[0]] = int(pair[1])

    return config_file_versions

def get_system_versions():
    """
    Get component versions from running system; critical failure if
    unable to read migration directory.
    """
    system_versions = {}

    try:
        version_info = os.listdir(system_version_dir)
    except OSError as err: 
        logging.critical("Unable to read directory {}".format(system_version_dir))
        print("OS error: {}".format(err))
        sys.exit(1)

    for info in version_info:
        if re.match(r'[\w,-]+@\d+', info):
            pair = info.split('@')
            system_versions[pair[0]] = int(pair[1])

    return system_versions

def remove_config_file_version_string(config_file_name):
    """
    Remove old version string.
    """
    for line in fileinput.input(config_file_name, inplace=True):
        if re.match(r'/\* Warning:.+ \*/$', line):
            continue
        if re.match(r'/\* === vyatta-config-version:.+=== \*/$', line):
            continue
        if re.match(r'/\* Release version:.+ \*/$', line):
            continue
        sys.stdout.write(line)


def write_config_file_version_string(config_file_name, config_versions):
    """
    Write new version string.
    """
    separator = ":"
    component_versions = separator.join(config_versions)

    with open(vyos_version, 'r') as version:
        version_string = version.readline().lstrip('Version: ').rstrip()

    remove_config_file_version_string(config_file_name)

    with open(config_file_name, 'a') as config_file_handle:
        config_file_handle.write('/* Warning: Do not remove the following line. */\n')
        config_file_handle.write('/* === vyatta-config-version: "{}" === */\n'.format(component_versions)) 
        config_file_handle.write('/* Release version: {} */\n'.format(version_string))

def update_config_versions(config_file_name):
    """
    """
    with open(config_file_name, 'r') as config_file_handle: 
        conf_versions = get_config_file_versions(config_file_handle)

    sys_versions = get_system_versions()

    for key in conf_versions.keys() - sys_versions.keys():
        sys_versions[key] = 0

    # python dictionaries are not guaranteed to maintain insertion order
    # until 3.6; jessie has 3.4.2

    sys_keys = list(sys_versions.keys())
    sys_keys.sort()

    updated_config_versions = []

    for key in sys_keys:
        sys_ver = sys_versions[key]
        if key in conf_versions:
            conf_ver = conf_versions[key]
        else:
            conf_ver = 0

        migrate_script_dir = os.path.join(migrate_util_dir, key)

        while conf_ver != sys_ver:
            if conf_ver < sys_ver:
                next_ver = conf_ver + 1
            else:
                next_ver = conf_ver - 1

            #
            migrate_script = os.path.join(migrate_script_dir,
                    "{}-to-{}".format(conf_ver, next_ver))

            # subprocess.run() was introduced in python 3.5;
            # jessie has 3.4.2
            #
            try:
                subprocess.check_output([migrate_script,
                    config_file_name])
            except FileNotFoundError:
                logging.debug("Migration script {} does not exist; not fatal".format(migrate_script))
            except subprocess.CalledProcessError as err:
                logging.critical("Fatal error {}".format(err))
                print("Called process error: {}".format(err))
                sys.exit(1)

            conf_ver = next_ver

        updated_config_versions.append('{}@{}'.format(key, conf_ver))

    write_config_file_version_string(config_file_name, updated_config_versions)

def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument("config_file", type=str,
            help="configuration file to migrate")
    argparser.add_argument("--debug", help="Turn on debugging.",
            action="store_true")
    argparser.add_argument("--log-to-stdout", help="Show log messages on stdout.",
            action="store_true")
    args = argparser.parse_args()

    try:
        logging.basicConfig(filename=migrate_log, level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S')
    except PermissionError as err:
        print("Permissions error: {}".format(err))

    root_logger = logging.getLogger()

    if args.debug:
        root_logger.setLevel(logging.DEBUG)
    if args.log_to_stdout:
        root_logger.addHandler(logging.StreamHandler(sys.stdout))

    config_file_name = args.config_file

    if not os.access(config_file_name, os.R_OK):
        logging.critical("Unable to read config file {}".format(config_file_name))
        print("Read error: {}".format(config_file_name))
        sys.exit(1)

    if not os.access(config_file_name, os.W_OK):
        logging.critical("Unable to modify config file {}".format(config_file_name))
        print("Write error: {}".format(config_file_name))
        sys.exit(1)

    update_config_versions(config_file_name)

if __name__ == "__main__":
    main()

