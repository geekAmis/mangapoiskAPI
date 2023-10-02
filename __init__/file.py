import os,requests
from bs4 import BeautifulSoup as bs
from fake_headers import Headers as Hd
import json,random


from fastapi import FastAPI
from typing import Annotated
from fastapi import Query
from fastapi.responses import HTMLResponse

from uvicorn import run as start