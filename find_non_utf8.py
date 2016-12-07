#!/usr/bin/env python

"""
reference:
http://stackoverflow.com/questions/623764/find-non-utf8-filenames-on-linux-file-system
"""


import shutil
import os
import os.path
def walk(dir):
    for child in os.listdir(dir):
        child= os.path.join(dir, child)
        if os.path.isdir(child):
            for descendant in walk(child):
                yield descendant
        yield child

l = []
for path in walk('.'):
    try:
        u= unicode(path, 'utf-8')
    except UnicodeError:
        l.append(path)

# TODO to delete use something like:
# print path, or attempt to rename file
#print(path)
#for i in l:
#    try:
#        os.remove(os.path.abspath(i))
#    except OSError:
#        try:
#            shutil.rmtree(os.path.abspath(i))
#        except OSError:
#            pass
#    del i
