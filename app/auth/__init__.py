from flask import Blueprint
import os

bp = Blueprint('auth', __name__,
               template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates'))

from app.auth import routes
