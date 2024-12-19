from flask import Blueprint
import os

bp = Blueprint('main', __name__,
               template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates'))

from app.main import routes
