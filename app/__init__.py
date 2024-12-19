from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from dotenv import load_dotenv
import os
import logging
from logging.handlers import RotatingFileHandler
from pythonjsonlogger import jsonlogger

# Load environment variables
load_dotenv()

# Initialize Flask extensions
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()

def create_app():
    app = Flask(__name__, 
                template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'))
    
    # Configure app
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///beira.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ECHO'] = os.getenv('FLASK_ENV') == 'development'  # Enable SQL query logging in development
    app.config['ALLOWED_EMAILS'] = os.getenv('ALLOWED_EMAILS', '').split(',')
    
    # Etsy configuration
    app.config['ETSY_API_KEY'] = os.getenv('ETSY_API_KEY')
    app.config['ETSY_SHARED_SECRET'] = os.getenv('ETSY_SHARED_SECRET')

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    migrate.init_app(app, db)

    # Setup logging
    log_level = logging.DEBUG if os.getenv('FLASK_ENV') == 'development' else logging.INFO
    
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Setup JSON logging to file
    file_handler = RotatingFileHandler(
        'logs/beira.log',
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    file_formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(log_level)
    
    # Setup console logging
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(log_level)
    
    # Add handlers to app logger
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(log_level)
    
    # Also setup logging for SQLAlchemy and other components
    loggers = [
        'sqlalchemy',
        'app.integrations.etsy',
        'app.integrations.square'
    ]
    
    for logger_name in loggers:
        logger = logging.getLogger(logger_name)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(log_level)

    # Add request logging
    @app.before_request
    def log_request_info():
        if os.getenv('FLASK_ENV') == 'development':
            app.logger.debug('Request Headers: %s', dict(request.headers))
            app.logger.debug('Request Body: %s', request.get_data())

    @app.after_request
    def log_response_info(response):
        if os.getenv('FLASK_ENV') == 'development':
            app.logger.debug('Response Status: %s', response.status)
            app.logger.debug('Response Headers: %s', dict(response.headers))
        return response

    # Register blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    return app

from app import models
