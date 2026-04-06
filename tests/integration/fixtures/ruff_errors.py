"""Sample file with deliberate ruff errors for integration testing."""
import os
import sys
import json

x=1
y =2
z= 3

def bad_func( a,b,c ):
    if a == True:
        return b
    elif a == False:
        return c
    else:
        return None
