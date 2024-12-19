from flask import jsonify
from app.api import bp

@bp.route('/health')
def health_check():
    return jsonify({"status": "healthy"})
