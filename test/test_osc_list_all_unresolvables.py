"""
tests for osc-list-unresolvables
"""

#from argparse import Namespace
import importlib.machinery
import importlib.util
#import json
import os.path
#import re
#from unittest.mock import MagicMock, call, patch
#from urllib.parse import urlparse

#import pytest
#import requests

rootpath = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

loader = importlib.machinery.SourceFileLoader(
    "sut", rootpath + "/osc-list-all-unresolvables"
)
spec = importlib.util.spec_from_loader(loader.name, loader)
sut = importlib.util.module_from_spec(spec)
loader.exec_module(sut)


#def args_factory():
    #args = Namespace()
    #args.dry_run = False
    #args.verbose = 1
    #args.priority_add = 100
    #return args


def test_default_repo():
    assert sut.default_repo('home:okurz:try_openqa_leap16') == '16.0'

def test_basic():
    assert sut.list_unresolvables()
